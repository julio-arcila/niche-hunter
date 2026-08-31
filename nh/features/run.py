"""Compute every metric for every cluster on one day."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import Cluster, FeatureDaily
from nh.db.provenance import Stamp
from nh.db.upsert import upsert
from nh.features import demand, money, openness, supply
from nh.features.supply import definition
from nh.features.types import FeatureResult

log = logging.getLogger(__name__)

Metric = Callable[[Session, str, date], FeatureResult]


#: Order is display order in `nh niche show`, so keep groups together.
def _stratum(fn: Metric, stratum: str) -> Metric:
    """Bind a stratum, keeping a `__name__` that matches the metric it emits.

    A closure rather than `functools.partial`, because a partial has no `__name__`
    and `nh/jobs/niche.py` orders its output by exactly that. It failed loudly, but
    only in the CLI tests — the features layer itself was perfectly happy — which is
    the sort of coupling worth naming rather than working around.
    """

    def metric(session: Session, cluster_id: str, day: date) -> FeatureResult:
        return fn(session, cluster_id, day, stratum=stratum)

    metric.__name__ = f"{fn.__name__}_{stratum}"
    return metric


def _geo(fn: Metric, geo: str, *, suffix: str = "") -> Metric:
    """Bind a market, the same way `_stratum` binds a stratum and for the same reason.

    The market is chosen HERE, at the registration site, rather than defaulted inside the
    loader — ADR-0038's point is that a seed term is geo-independent curation while the
    market is a property of the observation, so something has to state it out loud and
    this is the honest place. It also lands in `detail["geo"]` and renders, so a reader
    of `nh niche show` sees which population the number describes.

    The default market keeps the BARE name (`vw_cpc`, not `vw_cpc_us`), following
    `demand._named`: a stored series must stay continuous across the day a second market
    is added, and renaming it would silently start a new one. A second market registers
    with a suffix.
    """

    def metric(session: Session, cluster_id: str, day: date) -> FeatureResult:
        return fn(session, cluster_id, day, geo=geo)

    metric.__name__ = f"{fn.__name__}{suffix}"
    return metric


METRICS: tuple[Metric, ...] = (
    demand.wiki_weekly_views,
    # The event stratum, carried in parallel rather than replacing the topic one.
    # Measured, the two invert the demand ranking end to end; which is right is a
    # question for Gate E, not for an argument (ADR-0022).
    _stratum(demand.wiki_weekly_views, "event"),
    demand.wiki_momentum_28d,
    demand.wiki_yoy,
    demand.wiki_volatility_365d,
    demand.wiki_seasonality,
    demand.trends_momentum_13w,
    # Keyword Planner, bound to US (ADR-0035 rule 3: one stated basis until the first
    # market validates). The 66 GB rows stay ingested and loader-readable; the deferral
    # register carries why they are not registered yet.
    _geo(demand.total_monthly_searches, "US"),
    supply.uploads_per_week,
    supply.median_views,
    supply.on_niche_share,
    supply.geo_concentration,
    supply.format_mix,
    supply.top10_concentration,
    openness.breakthrough_rate_cohort,
    openness.views_per_sub,
    openness.winner_age_years,
    money.midroll_eligible_share,
    _geo(money.priced_share, "US"),
    _geo(money.competition_index_mean, "US"),
    _geo(money.vw_cpc, "US"),
    _geo(money.median_bid_high, "US"),
)


def compute(
    session: Session, day: date, mark: Stamp, *, metrics: tuple[Metric, ...] = METRICS
) -> int:
    """One `features_daily` row per cluster per metric, for every active cluster.

    Every metric runs for every cluster even when it cannot be computed: the row
    is written with `value=NULL, confidence=0, inputs_n=0` and a reason in
    `detail`. A missing row and a NULL row mean different things — the first says
    the pipeline did not run, the second says it ran and found nothing — and only
    the second is a fact about the niche.

    `metrics` is a parameter so the backtest can run a reduced set — several
    production metrics have no historical inputs — without forking this loop. The
    alternative is backtesting code that is not the product (ADR-0026).
    """
    # Active only. A retired cluster keeps its `features_daily` history — that is
    # the point of retiring rather than deleting — but stops accruing new rows,
    # and stops appearing in the day's percentile-rank population.
    cluster_ids = list(
        session.scalars(
            sa.select(Cluster.cluster_id).where(Cluster.active).order_by(Cluster.cluster_id)
        )
    )
    if not cluster_ids:
        log.warning("no clusters — run the clustering phase first")
        return 0

    rows = []
    for cluster_id in cluster_ids:
        for metric in metrics:
            result = metric(session, cluster_id, day)
            rows.append(
                mark(
                    FeatureDaily,
                    {
                        "cluster_id": cluster_id,
                        "day": day,
                        "metric_group": result.group,
                        "name": result.name,
                        "value": result.value,
                        "confidence": result.confidence,
                        "inputs_n": result.inputs_n,
                        "detail": result.detail,
                    },
                )
            )
    rows.extend(_cross_cluster(rows, day, mark))
    return upsert(session, FeatureDaily, rows, conflict_on=("cluster_id", "day", "name"))


#: The two supply metrics a newcomer actually feels: how well incumbent content
#: performs, and how much of it arrives.
PRESSURE_FROM = ("median_views", "uploads_per_week")


def _cross_cluster(rows: list[dict], day: date, mark: Stamp) -> list[dict]:
    """Metrics that need every cluster's value, computed once the per-cluster pass is done.

    `supply.pressure_index` is the mean of the within-day percentile ranks of
    `median_views` and `uploads_per_week`. docs/METRICS.md names this as the fix for
    gap compression: `scorecards.supply` currently ranks `median_views` alone, which
    correlates with niche size — and so does demand — so `gap` is a mismatch of two
    ranks that share a driver and comes out narrower than either input.

    A MEAN OF RANKS, which is the point: it invents no weights. Any coefficient on
    "how big are the winners" versus "how much arrives" would be a fabricated
    constant, and there is nothing to calibrate it against until Gate E.

    It ships as a `features_daily` metric and `scorecards.supply` is left alone, so
    the stored series survives and Slice 6 backtests both — the same treatment the
    two demand strata get.
    """
    from nh.scoring.scorecard import percentile_rank

    values = {
        name: {
            r["cluster_id"]: r["value"]
            for r in rows
            if r["name"] == name and r["value"] is not None
        }
        for name in PRESSURE_FROM
    }
    ranks = {name: percentile_rank(v) for name, v in values.items()}
    clusters = set.intersection(*(set(r) for r in ranks.values())) if ranks else set()
    out = []
    for cluster_id in sorted(clusters):
        parts = [ranks[name][cluster_id] for name in PRESSURE_FROM]
        out.append(
            mark(
                FeatureDaily,
                {
                    "cluster_id": cluster_id,
                    "day": day,
                    "metric_group": "supply",
                    "name": "pressure_index",
                    "value": sum(parts) / len(parts),
                    # Ranks carry no confidence of their own; the weaker input bounds it.
                    "confidence": min(
                        (r["confidence"] or 0.0)
                        for r in rows
                        if r["cluster_id"] == cluster_id and r["name"] in PRESSURE_FROM
                    ),
                    "inputs_n": len(clusters),
                    "detail": {
                        "definition": definition(),
                        "components": dict(zip(PRESSURE_FROM, parts, strict=True)),
                        "ranked_over": sorted(clusters),
                        "note": (
                            "mean of within-day percentile ranks; NOT comparable "
                            "across days on which the cluster set changed"
                        ),
                        "inputs": {"tables": ["features_daily"]},
                    },
                },
            )
        )
    return out
