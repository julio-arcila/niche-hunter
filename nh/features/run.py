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
    supply.uploads_per_week,
    supply.median_views,
    supply.on_niche_share,
    supply.geo_concentration,
    openness.breakthrough_rate_cohort,
    openness.views_per_sub,
    openness.winner_age_years,
    money.midroll_eligible_share,
)


def compute(session: Session, day: date, mark: Stamp) -> int:
    """One `features_daily` row per cluster per metric.

    Every metric runs for every cluster even when it cannot be computed: the row
    is written with `value=NULL, confidence=0, inputs_n=0` and a reason in
    `detail`. A missing row and a NULL row mean different things — the first says
    the pipeline did not run, the second says it ran and found nothing — and only
    the second is a fact about the niche.
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
        for metric in METRICS:
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
    return upsert(session, FeatureDaily, rows, conflict_on=("cluster_id", "day", "name"))
