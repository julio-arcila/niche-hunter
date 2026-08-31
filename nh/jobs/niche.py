"""Read queries behind `nh niche show`.

Kept out of `nh/cli.py` so that module stays presentation-only, the same split
`nh/jobs/status.py` already uses.

**Gated by default (ADR-0052).** This is a citation surface — it prints `gap`, `supply`
and every scorer-dependent metric for clusters whose relevance rule rests on machine
labels — and it was the *only* one when ADR-0045 wrote a trigger that watches columns Gate
E holds NULL. The gate lives here rather than in `cli.py` because the web layer reads the
same functions, and a rule enforced in one presenter is a rule the next presenter forgets.

`load()` withholds by default. Forgetting the argument is therefore safe, which is the
only direction a default may fail in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.api import gates
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
    #: Empty when the number may be shown. Otherwise the reason it is not, and the command
    #: that lifts it — a withheld number is replaced by the register's own text, never
    #: shown under a caveat. A caveat beside a number is read as a number.
    withheld: str = ""

    @property
    def shown(self) -> bool:
        return not self.withheld


@dataclass(slots=True)
class NicheView:
    cluster_id: str
    label: str | None
    day: date
    run_id: str | None
    member_channels: int
    metrics: list[MetricLine]
    scorecard: dict[str, float | None]
    #: Empty when the scorecard may be shown. `scorecard` is `{}` when it is not — all or
    #: nothing, because `gap` is demand minus supply and serving one side invites the
    #: reader to reconstruct the other.
    scorecard_withheld: str = ""


def known_clusters(engine: Engine | None = None) -> list[str]:
    with session_scope(engine) as session:
        return list(session.scalars(sa.select(Cluster.cluster_id).order_by(Cluster.cluster_id)))


def load(
    cluster_id: str,
    day: date | None = None,
    engine: Engine | None = None,
    *,
    include_unvalidated: bool = False,
) -> NicheView:
    """Everything `nh niche show` prints, for one cluster on one day.

    `day` defaults to the latest day that actually has features for this cluster,
    not to today — so the command is useful the morning after a failed run rather
    than reporting an empty day.

    `include_unvalidated` bypasses the ADR-0052 gate. **It is not an escape hatch of the
    kind ADR-0050 forbids**, and the difference is worth stating because it looks like
    one: what ADR-0050 refuses is a *stored setting* — an env var, a file — standing in
    for a human's verdict about a bar, because that is a verdict nobody made being read
    off disk forever. This is a human asking, once, at the moment of asking, and it
    records nothing. The operator debugging their own pipeline is not the reader the
    deferral protects. The web layer never passes it.
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

    card_fields = (
        {
            field: getattr(card, field, None)
            for field in ("demand", "supply", "gap", "gap_confidence", "openness", "value")
        }
        if card
        else {}
    )
    scorecard_withheld = ""
    if not include_unvalidated:
        for metric in metrics:
            verdict = gates.citable(metric.name, cluster_id)
            if not verdict:
                metric.withheld = verdict.reason
        card_verdict = gates.scorecard_citable(cluster_id)
        if card_fields and not card_verdict:
            card_fields, scorecard_withheld = {}, card_verdict.reason

    return NicheView(
        cluster_id=cluster_id,
        label=label,
        day=day,
        run_id=rows[0][6] if rows else None,
        member_channels=members,
        metrics=metrics,
        scorecard=card_fields,
        scorecard_withheld=scorecard_withheld,
    )
