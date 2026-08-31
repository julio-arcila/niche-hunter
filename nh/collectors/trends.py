"""Google Trends — demand *shape* only, one term per request, no anchor.

Ported from `legacy/niche_hunter_trends.py`, but deliberately a partial port
(ADR-0015). What the prototype was built around does not survive contact with
the live endpoint:

  * `related_queries` and `related_topics` are reachable after all, via the
    library's documented referer header — a per-endpoint rate limit, not a wall
    (ADR-0032 supersedes ADR-0015 on this). They are still not called here:
    they give sub-niche *vocabulary*, which this collector does not produce,
    and no level, which is what the normalisation below denies them.
  * Our niche phrases mostly read literal zero: Trends normalises 0-100 per
    request against the batch maximum, so a small term beside a large one rounds
    away. Measured, `aviation disasters documentary` is NaN even queried alone.

**No anchor, and no anchor chain.** The anchor existed for exactly one purpose —
carrying *level* across batches — and Wikipedia now supplies level in absolute
units. What per-request normalisation does not destroy is within-series shape:
momentum, slope and seasonality are scale-invariant. So each term is queried
alone and only shape is read off it.

The whole curve is one row, not one row per point. Each fetch renormalises to its
own peak, so appending points across fetches would let a new all-time peak
silently rescale later points against frozen earlier ones — corrupting the series
in a way nothing downstream could detect.
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa

from nh.collectors.base import Batch, Collector, Raw, Snapshot
from nh.collectors.parse import as_float
from nh.db.models import DemandSeries, SeedTerm
from nh.db.session import session_scope

TIMEFRAME = "today 5-y"
MAX_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class _Term:
    term: str
    geo: str


class TrendsCollector(Collector):
    source = "trends"
    description = "Google Trends — demand shape only; one term per request, no anchor."
    quota_budget = None  # unofficial endpoint; politeness is the limit, not a budget

    def fetch(self) -> Iterable[Raw]:
        from trendspy import Trends  # optional extra; imported here so the module loads without it

        terms = self._terms()
        if not terms:
            self.log.warning("no trends terms mapped — run `nh seed` first")
            return
        # `request_delay` is the library's OWN pacing between the several HTTP
        # requests it makes inside one `interest_over_time` call, and it defaults
        # to 1.0s — under the 2.5s minimum gap .claude/rules/sources.md sets for
        # this endpoint. The `time.sleep` in `_call` paces only the calls WE make,
        # so without this the rule was honoured between terms and broken within
        # them. Observed 2026-08-31: repeated 429s on the live run, and trendspy's
        # own "Too many rate limit errors (429). Consider increasing
        # request_delay" warning. One knob, one source of truth for the gap.
        kwargs = {"request_delay": self.settings.trends_min_gap_s}
        if self.settings.trends_proxy:
            kwargs["proxy"] = self.settings.trends_proxy
        client = Trends(**kwargs)
        for term in terms:
            if self._already_observed(term):
                # The snapshot unique key IS the cache key: one observation per
                # term per day, so a same-day re-run costs nothing and needs no
                # separate cache table.
                self.log.info("%s already observed today", term.term)
                continue
            payload = self._call(client, term)
            if payload is None:
                continue  # one throttled term degrades the run, never fails it
            yield Raw(
                kind="interest_over_time",
                key=f"{term.term}|{term.geo}|{TIMEFRAME}",
                payload=payload,
            )

    def normalize(self, raw: Raw) -> Batch:
        """The whole curve as one row.

        Operates on the split dict rather than a DataFrame, so features and tests
        need no pandas and no optional extra installed.
        """
        term, geo, timeframe = raw.key.rsplit("|", 2)
        columns = raw.payload["columns"]
        if term not in columns:
            return Batch()
        column = columns.index(term)
        points = [
            [str(stamp)[:10], as_float(row[column])]
            for stamp, row in zip(raw.payload["index"], raw.payload["data"], strict=False)
        ]
        return Batch(
            snapshots=[
                Snapshot(
                    DemandSeries,
                    {"term": term, "geo": geo, "timeframe": timeframe, "points": points},
                )
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

    def _already_observed(self, term: _Term) -> bool:
        with session_scope(self.engine) as session:
            return (
                session.scalar(
                    sa.select(sa.func.count())
                    .select_from(DemandSeries)
                    .where(
                        DemandSeries.term == term.term,
                        DemandSeries.geo == term.geo,
                        DemandSeries.timeframe == TIMEFRAME,
                        DemandSeries.observed_date == self.observed_date,
                        DemandSeries.source == self.source,
                    )
                )
                > 0
            )

    def _call(self, client, term: _Term) -> dict | None:
        """One term, paced and backed off. Never raises."""
        for attempt in range(MAX_ATTEMPTS):
            time.sleep(self.settings.trends_min_gap_s + random.uniform(0, 0.8))
            try:
                frame = client.interest_over_time(
                    [term.term], timeframe=TIMEFRAME, geo=term.geo or ""
                )
                return frame.to_dict(orient="split")
            except Exception as exc:
                message = str(exc).splitlines()[0][:120]
                if attempt == MAX_ATTEMPTS - 1:
                    self.log.warning(
                        "%s gave up after %d attempts: %s", term.term, attempt + 1, message
                    )
                    return None
                self.log.info(
                    "%s attempt %d failed, backing off: %s", term.term, attempt + 1, message
                )
                time.sleep(min(60, 5 * 2**attempt))
        return None


def window_ratio(points: list[list], day: date, window: int = 13) -> tuple[float | None, int]:
    """Ratio of the last `window` values to the previous `window`, minus 1.

    Pure, and the leakage guard lives here: points dated after `day` are dropped
    even when the stored row contains them, so a Slice 6 replay of a historical
    date can never see the future. Returns (value, non_zero_count).
    """
    cutoff = day.isoformat()
    values = [v for stamp, v in points if stamp <= cutoff and v is not None]
    if len(values) < window * 2:
        return None, 0
    recent, prior = values[-window:], values[-window * 2 : -window]
    non_zero = sum(1 for v in recent + prior if v)
    mean_prior = sum(prior) / window
    if not mean_prior:
        return None, non_zero
    return (sum(recent) / window) / mean_prior - 1, non_zero
