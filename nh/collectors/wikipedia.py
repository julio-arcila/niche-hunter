"""Wikimedia pageviews — absolute demand level, backfillable to 2015.

The primary demand signal (ADR-0015). Google Trends returns literal zero for most
of these niches, and its topic-mid workaround is quota-blocked; Wikipedia returns
data for all five in **absolute** units from an official, quota-free API.

Two properties make it worth leading with:

  * **Absolute counts.** No anchor, no per-request normalisation, no rescaling.
    A niche's number means the same thing tomorrow and beside every other niche.
  * **History.** The endpoint serves daily data back to 2015-07-01 for any range,
    so momentum is computable on the first night rather than after months of
    collecting. Nothing else in this pipeline has ever produced history.

Two constraints the design has to respect:

  * **`agent=user`, always.** Bot and spider traffic is 19-54% of raw counts and
    is *not* uniform across articles — measured, Corporate_scandal is 54% bots
    against Aviation's 19% — so `all-agents` systematically inflates small niches
    relative to large ones.
  * **Counts mature over 24-48 hours.** Snapshots are first-write-wins, so
    fetching yesterday would freeze an undercount permanently. Nothing closer
    than `wiki_lag_days` is ever requested.
"""

from __future__ import annotations

import time
import urllib.parse
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import requests
import sqlalchemy as sa

from nh.collectors.base import Batch, Collector, Raw, Snapshot
from nh.collectors.parse import as_float
from nh.db.models import DemandSnapshot, SeedTerm
from nh.db.session import session_scope

API = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
    "{project}/all-access/user/{article}/daily/{start}/{end}"
)
PROJECT = "en.wikipedia"
#: Wikimedia's UA policy asks for a descriptive agent with contact details.
PACE_S = 0.5
#: The endpoint rejects very long ranges; a year per request keeps them bounded.
CHUNK_DAYS = 365


@dataclass(frozen=True, slots=True)
class _Term:
    term: str
    geo: str


class WikipediaCollector(Collector):
    source = "wikipedia"
    description = "Wikimedia pageviews — absolute demand level, backfillable to 2015."
    quota_budget = None  # official API, nothing countable to spend

    def fetch(self) -> Iterable[Raw]:
        end = self.observed_date - timedelta(days=self.settings.wiki_lag_days)
        terms = self._terms()
        if not terms:
            self.log.warning("no wikipedia terms mapped — run `nh seed` first")
            return
        self.log.info("fetching %d articles up to %s", len(terms), end)
        for term in terms:
            start = self._resume_from(term.term) or end - timedelta(
                days=self.settings.wiki_backfill_days
            )
            if start > end:
                continue
            for lo, hi in _chunks(start, end):
                payload = self._get(term.term, lo, hi)
                if payload is None:
                    break  # this article failed; the next one still runs
                yield Raw(
                    kind="pageviews",
                    key=f"{term.term}|{lo:%Y%m%d}|{hi:%Y%m%d}",
                    payload=payload,
                )

    def normalize(self, raw: Raw) -> Batch:
        """One snapshot per described day.

        `observed_date` is the day the count describes, not the day we fetched —
        `stamp()` uses `setdefault`, so the value supplied here survives (ADR-0015).
        """
        return Batch(
            snapshots=[
                Snapshot(
                    DemandSnapshot,
                    {
                        "term": item["article"],
                        "geo": "",
                        "observed_date": _described_day(item["timestamp"]),
                        "value": as_float(item.get("views")),
                    },
                )
                for item in raw.payload.get("items", [])
            ]
        )

    # -- internals ----------------------------------------------------------

    def _terms(self) -> list[_Term]:
        with session_scope(self.engine) as session:
            # Deliberately NOT joined through `clusters`: clustering is a phase
            # that runs *after* the collectors, so on a fresh database no cluster
            # exists yet and joining would collect nothing on night one. Terms
            # belong to seeds; only features need the cluster mapping.
            rows = session.execute(
                sa.select(SeedTerm.term, SeedTerm.geo)
                .where(SeedTerm.source == self.source, SeedTerm.active.is_(True))
                .distinct()
                .order_by(SeedTerm.term)
            ).all()
        return [_Term(*row) for row in rows]

    def _resume_from(self, term: str) -> date | None:
        """The day after the newest reading we hold, so a nightly run costs one call."""
        with session_scope(self.engine) as session:
            newest = session.scalar(
                sa.select(sa.func.max(DemandSnapshot.observed_date)).where(
                    DemandSnapshot.term == term, DemandSnapshot.source == self.source
                )
            )
        return newest + timedelta(days=1) if newest else None

    def _get(self, article: str, lo: date, hi: date) -> dict[str, Any] | None:
        """One range for one article. Never raises: a dead article costs one article."""
        url = API.format(
            project=PROJECT,
            article=urllib.parse.quote(article, safe=""),
            start=f"{lo:%Y%m%d}00",
            end=f"{hi:%Y%m%d}00",
        )
        time.sleep(PACE_S)
        try:
            response = requests.get(
                url, headers={"User-Agent": self.settings.wiki_user_agent}, timeout=30
            )
            if response.status_code == 404:
                # No data for this article in this range. Genuinely absent rather
                # than an error — it writes no rows, which says more than a zero.
                self.log.info("no data for %s in %s..%s", article, lo, hi)
                return {"items": []}
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            self.log.warning("%s failed: %s", article, exc)
            return None


def _chunks(start: date, end: date) -> Iterator[tuple[date, date]]:
    while start <= end:
        stop = min(start + timedelta(days=CHUNK_DAYS - 1), end)
        yield start, stop
        start = stop + timedelta(days=1)


def _described_day(timestamp: str) -> date:
    """'2026082700' -> date(2026, 8, 27). The API pads an hour field it never uses."""
    return datetime.strptime(timestamp[:8], "%Y%m%d").date()
