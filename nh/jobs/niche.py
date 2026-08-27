"""Read queries behind `nh niche show`.

Kept out of `nh/cli.py` so that module stays presentation-only, the same split
`nh/jobs/status.py` already uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.db.models import Cluster, ClusterMember, FeatureDaily, NicheSeed, Scorecard
from nh.db.session import session_scope


class UnknownCluster(KeyError):
    pass


@dataclass(slots=True)
class MetricLine:
    group: str
    name: str
    value: float | None
    confidence: float | None
    inputs_n: int | None
    detail: dict[str, Any] | None


@dataclass(slots=True)
class NicheView:
    cluster_id: str
    label: str | None
    day: date
    run_id: str | None
    member_channels: int
    metrics: list[MetricLine]
    scorecard: dict[str, float | None]


def known_clusters(engine: Engine | None = None) -> list[str]:
    with session_scope(engine) as session:
        return list(session.scalars(sa.select(Cluster.cluster_id).order_by(Cluster.cluster_id)))


def load(cluster_id: str, day: date | None = None, engine: Engine | None = None) -> NicheView:
    """Everything `nh niche show` prints, for one cluster on one day.

    `day` defaults to the latest day that actually has features for this cluster,
    not to today — so the command is useful the morning after a failed run rather
    than reporting an empty day.
    """
    with session_scope(engine) as session:
        cluster = session.get(Cluster, cluster_id)
        if cluster is None:
            raise UnknownCluster(cluster_id)
        label = session.scalar(sa.select(NicheSeed.label).where(NicheSeed.id == cluster.seed_id))
        if day is None:
            day = session.scalar(
                sa.select(sa.func.max(FeatureDaily.day)).where(
                    FeatureDaily.cluster_id == cluster_id
                )
            )
        members = (
            session.scalar(
                sa.select(sa.func.count()).where(
                    ClusterMember.cluster_id == cluster_id,
                    ClusterMember.item_type == "channel",
                )
            )
            or 0
        )
        if day is None:
            return NicheView(cluster_id, label, date.min, None, members, [], {})

        rows = session.execute(
            sa.select(
                FeatureDaily.metric_group,
                FeatureDaily.name,
                FeatureDaily.value,
                FeatureDaily.confidence,
                FeatureDaily.inputs_n,
                FeatureDaily.detail,
                FeatureDaily.run_id,
            ).where(FeatureDaily.cluster_id == cluster_id, FeatureDaily.day == day)
        ).all()
        card = session.scalar(
            sa.select(Scorecard).where(Scorecard.cluster_id == cluster_id, Scorecard.day == day)
        )

    # Present in the order metrics are computed, so groups stay together and the
    # layout does not reshuffle when a value goes NULL.
    from nh.features.run import METRICS

    order = {fn.__name__: i for i, fn in enumerate(METRICS)}
    metrics = sorted(
        (MetricLine(*row[:6]) for row in rows),
        key=lambda m: order.get(m.name, len(order)),
    )
    return NicheView(
        cluster_id=cluster_id,
        label=label,
        day=day,
        run_id=rows[0][6] if rows else None,
        member_channels=members,
        metrics=metrics,
        scorecard={
            field: getattr(card, field, None)
            for field in ("openness", "supply", "gap", "value", "opportunity")
        }
        if card
        else {},
    )
