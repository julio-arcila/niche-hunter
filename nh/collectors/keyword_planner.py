"""Google Ads Keyword Planner — demand scale and advertiser value, via the UI export.

**A manual collector.** Nothing here reaches the network: a human exports the
"Historical metrics" CSV from the Keyword Planner UI and runs `nh kp ingest <path>`.
It stays a `Collector` rather than becoming a loader because `Collector.run()` is
exactly the machinery data rules 1-3 demand — raw-before-normalized, provenance on
every row, `job_runs` bookkeeping, commit-as-you-go — and a loader would either
re-implement all of it or quietly skip it. The contract's "network lives in `fetch()`
and nowhere else" generalises to acquisition I/O: `fetch()` opens the file, and
`normalize()` stays pure, so an eventual Google Ads API path can share it unchanged
(ADR-0016 records that the prototype already proved API and CSV rows normalise alike).

**The two access paths, and why this is the one that shipped.** The API needs a
developer token and Basic access approval; nobody ever applied, and the four-week
clock ADR-0016 started expired unused. The UI export needs *no API, no token and no
application at all* — which ADR-0016 recorded as the fallback and ADR-0029 acted on.

**What the export actually gives, measured 2026-08-28 on the first US export** (30
keywords, the five active niches):

- `Avg. monthly searches` on 22/30 — and **quantised to power-of-ten bucket
  midpoints**: only 50, 500, 5000 and 50000 occur. A bucket centre, never a count.
- `Competition (indexed value)` on 20/30, 0-10.
- Top-of-page bids on 7/30, in the exporting **account's currency** (COP here).
- The twelve `Searches: <month>` columns on **0/360** — entirely empty. So ADR-0016's
  "monthly volumes to `demand_snapshots` as month-start rows" cannot be fulfilled from
  this path, and this collector writes no `demand_snapshots` at all (ADR-0030).

The on-screen table shows ranges (`10 mil - 100 mil`) where the CSV holds `50000.0`;
the export is strictly better than the UI, contrary to the legacy prototype's header.

**Caveats that travel with every number this produces**, and belong in any page that
shows one: this is Google *search* data, not YouTube — a bid is advertiser value, not
an RPM; close variants collapse plurals and misspellings; long-tail terms carry no bid
data, so aggregate at niche level and never per keyword.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from nh.collectors.base import Batch, Collector, Raw, Snapshot
from nh.collectors.parse import as_float, as_int
from nh.db.models import KeywordMetric

#: The export is UTF-16 with a BOM. Sniffed rather than assumed, because a future
#: locale or Google change could ship UTF-8 and a hard-coded codec would fail loudly
#: on the wrong line.
_BOMS = {b"\xff\xfe": "utf-16", b"\xfe\xff": "utf-16"}

#: Spanish and English month names, because the export follows the account's locale
#: and this account is Colombian. Only the period line needs them.
_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_PERIOD = re.compile(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})|(\w+)\s+(\d{1,2}),\s*(\d{4})", re.I)


class KeywordPlannerError(RuntimeError):
    """The export could not be read as a Keyword Planner historical-metrics file."""


@dataclass(frozen=True, slots=True)
class Period:
    """The window the numbers describe, from the export's own second line."""

    start: date
    end: date


def decode(path: Path) -> str:
    """Read the export, sniffing the BOM rather than assuming a codec."""
    raw = path.read_bytes()
    return raw.decode(_BOMS.get(raw[:2], "utf-8-sig"), errors="replace")


def parse_period(line: str) -> Period | None:
    """`1 de agosto de 2025 - 31 de julio de 2026` -> the window it names.

    Returns None rather than guessing when the locale is one this does not read; the
    caller must then be given `--period-end` explicitly. A wrong `observed_date` would
    silently misfile a whole export against the wrong twelve months.
    """
    found = _PERIOD.findall(line or "")
    days = []
    for es_d, es_m, es_y, en_m, en_d, en_y in found:
        d, m, y = (es_d, es_m, es_y) if es_d else (en_d, en_m, en_y)
        month = _MONTHS.get(m.strip().lower())
        if month:
            days.append(date(int(y), month, int(d)))
    return Period(days[0], days[1]) if len(days) == 2 else None


def _number(cell: str | None) -> float | None:
    """A cell to a float, or None. Never 0 for an absent value.

    Handles the export's two number shapes: plain (`50000.0`) and quoted
    decimal-comma (`"4043,23"`). The legacy prototype's `int(num(x) or 0)` turned
    every absent cell into a zero, which data rule 7 forbids — a keyword with no
    measured volume is unknown, not a keyword nobody searches for.
    """
    # \u00a0 is a non-breaking space, used as a thousands separator in some
    # locales; the three dashes are what the export uses for "no value".
    text = (cell or "").strip().strip('"').replace("\u00a0", "").replace(" ", "")
    if not text or text in {"-", "\u2014", "\u2013"}:
        return None
    if "," in text and "." not in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    return as_float(text)


def _percent(cell: str | None) -> float | None:
    """`-90%` -> -0.90. None when absent, and None for the export's `+∞` sentinel."""
    text = (cell or "").strip().replace("%", "")
    if "∞" in text or not text.strip():
        return None
    value = _number(text)
    return None if value is None else value / 100.0


def rows(text: str) -> Iterator[dict[str, str]]:
    """Yield one dict per keyword row, header located by content.

    The header is found by looking for a line whose first cell is `Keyword`, not by
    skipping a fixed number of lines. The prototype tried to skip two preamble lines
    with `skiprows=lambda i: i < 2 and False`, which is always False and therefore
    never skipped anything — locating by content makes the count irrelevant.

    Rows whose `Keyword` cell is blank are the export's own aggregate rows (`Todo`,
    and one per location) and are excluded here; `fetch()` keeps them in the
    file-level raw payload, where they serve as a free end-to-end check: measured
    2026-08-28, they equal the sum of the keyword rows exactly (179,300).
    """
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.split("\t")[0].strip() == "Keyword"), None
    )
    if start is None:
        raise KeywordPlannerError(
            "no header row found: expected a line whose first tab-separated cell is "
            "'Keyword'. Is this the 'Historical metrics' export rather than the "
            "forecast one?"
        )
    reader = csv.DictReader(lines[start:], delimiter="\t")
    for row in reader:
        if (row.get("Keyword") or "").strip():
            yield row


def _pick(row: dict[str, str], *needles: str) -> str | None:
    """Match a column by content, since headers are locale-dependent."""
    for key in row:
        low = (key or "").lower()
        if any(n in low for n in needles):
            return row[key]
    return None


class KeywordPlannerCollector(Collector):
    source = "keyword_planner"
    description = "Google Ads Keyword Planner — demand scale and advertiser value (manual CSV)."
    quota_budget = None

    def __init__(
        self,
        *args: Any,
        path: Path | str | None = None,
        geo: str = "",
        lang: str = "en",
        period_end: date | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.path = Path(path) if path else None
        self.geo = geo
        self.lang = lang
        self.period_end = period_end

    def is_configured(self) -> bool:
        """A file, not a credential. `Settings.configured` returns True for this
        source because its only requirement is a human with a browser; what this
        actually needs is a path, and the CLI supplies one."""
        return self.path is not None and self.path.exists()

    def fetch(self) -> Iterable[Raw]:
        if self.path is None:
            raise KeywordPlannerError("no export path given; run `nh kp ingest <csv>`")
        text = decode(self.path)
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        lines = text.splitlines()

        period = parse_period(lines[1] if len(lines) > 1 else "")
        if period is None and self.period_end is None:
            raise KeywordPlannerError(
                f"could not read the period from {lines[1]!r}. Pass --period-end "
                "YYYY-MM-DD rather than letting the export be filed against a guessed "
                "twelve months."
            )

        # The whole file first, verbatim: rule 2, and it carries the aggregate rows
        # that check the keyword rows sum correctly.
        yield Raw(
            kind="keyword_csv",
            key=f"{digest[:12]}:{self.path.name}",
            payload={
                "filename": self.path.name,
                "sha256": digest,
                "title": lines[0] if lines else "",
                "period_line": lines[1] if len(lines) > 1 else "",
                "aggregates": [
                    line for line in lines[2:] if line.split("\t")[0].strip() == "" and line.strip()
                ],
                "geo": self.geo,
                "lang": self.lang,
            },
        )
        for row in rows(text):
            keyword = row["Keyword"].strip()
            yield Raw(
                kind="keyword",
                key=f"{keyword}|{self.geo}|{self.lang}",
                payload={
                    **{k: v for k, v in row.items() if k},
                    "_file_sha256": digest,
                    "_geo": self.geo,
                    "_lang": self.lang,
                    "_period_start": (period.start.isoformat() if period else None),
                    "_period_end": (
                        period.end.isoformat()
                        if period
                        else (self.period_end.isoformat() if self.period_end else None)
                    ),
                },
            )

    def normalize(self, raw: Raw) -> Batch:
        """One `KeywordMetric` per keyword row. Pure — no clock, no I/O.

        The file-level raw yields no rows: it exists so the export's own header and
        aggregate lines survive verbatim, not to be interpreted.
        """
        if raw.kind != "keyword":
            return Batch()
        payload = raw.payload
        end = payload.get("_period_end")
        if not end:
            return Batch()
        return Batch(
            # A Snapshot, not an Upsert, and the difference is load-bearing.
            # `KeywordMetric` is AppendOnly, and `_flush` routes snapshots through
            # `insert_ignore` after checking that the model really is append-only,
            # so re-ingesting an export is a no-op and the first reading of a period
            # survives. An Upsert would reach the table by ON CONFLICT DO UPDATE — a
            # Core statement, which slips past the ORM append-only guard entirely
            # (a known defect, docs/RUNBOOK.md) and would silently overwrite a
            # period's bids with a later export's revision of them.
            snapshots=[
                Snapshot(
                    KeywordMetric,
                    self._stamp(
                        KeywordMetric,
                        {
                            "keyword": payload["Keyword"].strip(),
                            "geo": payload.get("_geo") or "",
                            "lang": payload.get("_lang"),
                            "observed_date": date.fromisoformat(end),
                            "period_start": (
                                date.fromisoformat(payload["_period_start"])
                                if payload.get("_period_start")
                                else None
                            ),
                            "avg_monthly_searches": _number(_pick(payload, "monthly searches")),
                            "three_month_change": _percent(_pick(payload, "three month")),
                            "yoy_change": _percent(_pick(payload, "yoy")),
                            "competition": (_pick(payload, "competition") or "").strip() or None,
                            # No `or None` here. `_number("0")` is 0.0, which is
                            # falsy, so `or None` would turn a *measured* competition
                            # index of zero into "not measured" — the prototype's
                            # absent-as-zero defect running backwards, and caught by
                            # test_coverage_matches_the_measured_export at 11/30
                            # instead of 20/30. Nine keywords score a real 0 here.
                            "competition_index": as_int(_number(_pick(payload, "indexed value"))),
                            "bid_low": _number(_pick(payload, "low range")),
                            "bid_high": _number(_pick(payload, "high range")),
                            "currency": (payload.get("Currency") or "").strip() or None,
                            "method": "ui_csv",
                            "file_sha256": payload.get("_file_sha256"),
                        },
                    ),
                )
            ]
        )
