"""Replay the production feature layer at historical decision dates.

The one rule that makes the gate mean anything: **this module computes nothing.**
It calls `nh.features.run.compute` and `nh.scoring.scorecard.build` — the same
functions the nightly calls — and its own job is only to choose the dates, bind the
provenance, and pair each score with what actually happened (ADR-0026). Backtesting
code that is not the product tells you nothing about the product.

**It must never call `nh.jobs.run_phases`.** The clustering phase mutates and
commits: `assign_videos` rescores every video and overwrites `relevance` and `at`,
and `retire_empty` writes `retired_on = day` — so replaying 2019 through the job
runner would stamp `retired_on = 2019-01-01` onto live clusters. A test asserts this
module does not import it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.backtest.load import RefusingLiveDatabase, refuse_live
from nh.backtest.outcome import growth
from nh.db.models import Scorecard
from nh.db.provenance import stamp
from nh.db.session import session_scope
from nh.features import demand, openness, supply
from nh.features.inputs import member_channels, pinned_ballast
from nh.features.run import Metric, compute
from nh.scoring.scorecard import build

log = logging.getLogger(__name__)

SOURCE = "backtest"
#: Weekly, because YouNiverse's series is weekly and a denser grid would only
#: interpolate. `stats.thin` reduces this to non-overlapping windows for inference.
SPACING_DAYS = 7
#: The supply proxy the backtest ranks on. `median_views` is NULL at every
#: historical date — YouNiverse holds per-video views only at its 2019 crawl — so
#: the live default would take supply, gap and stage down with it.
SUPPLY_FROM = "views_per_new_video"

#: The metrics with historical inputs. A reduced set, not a reimplementation: every
#: entry is the production function, and `compute` takes it as a parameter so the
#: loop is not forked.
#:
#: Left out, with the reason each would produce a column of NULLs:
#:   trends_momentum_13w  — no historical Trends series exists to replay.
#:   geo_concentration    — YouNiverse has no country column (see load.py).
#:   breakthrough_rate_cohort / views_per_sub — the cohort needs order=date
#:                          discovery lineage, which YouNiverse has no analogue of.
#:   midroll_eligible_share — duration is not loaded; it is a 2026 backfill fact.
#: `winner_age_years` is kept: it needs only channel creation dates and video views
#: on niche, and it is the openness signal that survives an empty cohort.
BACKTEST_METRICS: tuple[Metric, ...] = (
    demand.wiki_weekly_views,
    demand.wiki_momentum_28d,
    demand.wiki_yoy,
    demand.wiki_volatility_365d,
    supply.uploads_per_week,
    supply.views_per_new_video,
    supply.on_niche_share,
    supply.top10_concentration,
    openness.winner_age_years,
)


@dataclass(slots=True)
class Pairing:
    """One decision date's aligned scores and outcomes, ready for `stats.evaluate`."""

    day: date
    clusters: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    outcomes: list[float] = field(default_factory=list)
    #: Member-channel count per cluster, for the partial correlation that controls
    #: for niche size. Without it a pass cannot be distinguished from "big niches
    #: grow", which needs no pipeline.
    sizes: list[int] = field(default_factory=list)


def decision_dates(start: date, end: date, *, spacing_days: int = SPACING_DAYS) -> list[date]:
    """Every `spacing_days`-th day in `[start, end]`."""
    if start > end:
        return []
    count = (end - start).days // spacing_days
    return [start + timedelta(days=spacing_days * i) for i in range(count + 1)]


def replay_day(
    engine: Engine,
    day: date,
    *,
    run_id: str,
    at: datetime,
    metrics: tuple[Metric, ...] = BACKTEST_METRICS,
    supply_from: str = SUPPLY_FROM,
) -> tuple[int, int]:
    """Compute features and scorecards as of `day`. Returns (feature rows, cards).

    `at` is the wall-clock time of the replay run, not `day`. Provenance records when
    a row was written; `day` records what it describes. Conflating them is the same
    confusion ADR-0015 untangled for `observed_date`, and here it would additionally
    make the replay's own output indistinguishable from a night of real collection.
    """
    mark = partial(stamp, source=SOURCE, run_id=run_id, at=at)
    with session_scope(engine) as session:
        rows = compute(session, day, mark, metrics=metrics)
        cards = build(session, day, mark, supply_from=supply_from)
    return rows, cards


def replay(
    engine: Engine,
    dates: list[date],
    *,
    run_id: str,
    at: datetime | None = None,
    metrics: tuple[Metric, ...] = BACKTEST_METRICS,
    supply_from: str = SUPPLY_FROM,
    ballast: bool | None = None,
) -> tuple[int, int]:
    """Replay every date. Idempotent — `compute` and `build` both upsert on the day.

    `ballast` pins ADR-0047's exclusion for the whole replay (ADR-0050). Left `None` it
    resolves once from `ballast_active()` and holds, so a long replay cannot cross the
    sunset mid-run and compute its early dates under one definition and its late ones
    under another. Pass it explicitly to replay history under a chosen definition — the
    honest way to compare the two, since three of nine `BACKTEST_METRICS` route through
    the predicate and the difference is a definition change, not noise.
    """
    refuse_live(engine)
    at = at or datetime.now(UTC)
    rows = cards = 0
    with pinned_ballast(ballast) as active:
        log.info("replay ballast exclusion %s", "ON (v3)" if active else "OFF (v2)")
        for i, day in enumerate(dates, start=1):
            r, c = replay_day(
                engine, day, run_id=run_id, at=at, metrics=metrics, supply_from=supply_from
            )
            rows += r
            cards += c
            if i % 25 == 0 or i == len(dates):
                log.info("replayed %s/%s dates (%s rows, %s cards)", i, len(dates), rows, cards)
    return rows, cards


def pair(
    engine: Engine,
    dates: list[date],
    *,
    score: str = "gap",
    horizon_days: int = 180,
) -> list[Pairing]:
    """Join each date's scores to the outcome that followed, dropping incomplete pairs.

    A cluster appears only when **both** its score and its outcome are non-NULL. The
    alternative — treating a NULL as a zero on either side — would rank a niche that
    could not be scored against one that scored badly, and the correlation would then
    partly measure which niches had enough data, not which ones grew.
    """
    column = getattr(Scorecard, score)
    pairings = []
    # One session per date, not per cluster: the real run is ~195 dates x ~30
    # clusters, and a session apiece is 6,000 connections to answer 195 questions.
    for day in dates:
        with session_scope(engine) as session:
            scores = dict(
                session.execute(
                    sa.select(Scorecard.cluster_id, column).where(
                        Scorecard.day == day, column.is_not(None)
                    )
                ).all()
            )
            if not scores:
                continue
            pairing = Pairing(day=day)
            for cluster_id in sorted(scores):
                result = growth(session, cluster_id, day, horizon_days)
                if result.value is None:
                    continue
                pairing.clusters.append(cluster_id)
                pairing.scores.append(float(scores[cluster_id]))
                pairing.outcomes.append(result.value)
                pairing.sizes.append(len(list(member_channels(session, cluster_id, day))))
        # Fewer than three points has no rank correlation, so the date carries no
        # information and is dropped rather than contributing a None to the mean.
        if len(pairing.clusters) >= 3:
            pairings.append(pairing)
    return pairings


def as_series(
    pairings: list[Pairing],
) -> list[tuple[str, list[str], list[float], list[float]]]:
    """The shape `stats.evaluate` takes.

    The cluster ids travel with the numbers because the permutation null relabels
    niches *globally* — one permutation per replication, applied at every date — and
    that is only expressible if each date knows which niche each number belongs to.
    """
    return [(p.day.isoformat(), p.clusters, p.scores, p.outcomes) for p in pairings]


__all__ = [
    "BACKTEST_METRICS",
    "Pairing",
    "RefusingLiveDatabase",
    "as_series",
    "decision_dates",
    "pair",
    "replay",
    "replay_day",
]
