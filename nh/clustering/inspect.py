"""What the relevance rule decided for one cluster, and why.

Production criterion 5 is that every displayed number reaches its input rows. For
`supply.*` that path now runs through a relevance decision, so the decision has to
be readable.

The two lists worth reading are the weakest video kept and the strongest dropped.
Those sit either side of the threshold, they are where the rule is doing its least
confident work, and reading twenty of them tells you the lexicon is wrong long
before a metric moves enough to notice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.clustering.relevance import RELEVANCE_HIGH
from nh.db.models import Cluster, ClusterMember, Video


@dataclass(slots=True)
class Decision:
    relevance: float
    title: str | None
    detail: dict[str, Any] | None


@dataclass(slots=True)
class ClusterView:
    cluster_id: str
    active: bool
    total: int
    threshold: float
    bands: list[tuple[str, int]]
    weakest_kept: list[Decision]
    strongest_dropped: list[Decision]


def _edge(session: Session, cluster_id: str, *, kept: bool, n: int) -> list[Decision]:
    """Rows nearest the threshold from one side."""
    condition = (
        ClusterMember.relevance >= RELEVANCE_HIGH
        if kept
        else sa.and_(ClusterMember.relevance > 0, ClusterMember.relevance < RELEVANCE_HIGH)
    )
    rows = session.execute(
        sa.select(ClusterMember.relevance, Video.title, ClusterMember.detail)
        .join(Video, Video.video_id == ClusterMember.item_id)
        .where(
            ClusterMember.item_type == "video",
            ClusterMember.cluster_id == cluster_id,
            condition,
        )
        .order_by(ClusterMember.relevance.asc() if kept else ClusterMember.relevance.desc())
        .limit(n)
    ).all()
    return [Decision(r[0], r[1], r[2]) for r in rows]


def inspect_cluster(session: Session, cluster_id: str, n: int = 8) -> ClusterView | None:
    """None when the cluster does not exist."""
    cluster = session.get(Cluster, cluster_id)
    if cluster is None:
        return None
    counts = session.execute(
        sa.select(
            sa.func.count(),
            sa.func.count(sa.case((ClusterMember.relevance >= RELEVANCE_HIGH, 1))),
            sa.func.count(
                sa.case(
                    (
                        sa.and_(
                            ClusterMember.relevance > 0, ClusterMember.relevance < RELEVANCE_HIGH
                        ),
                        1,
                    )
                )
            ),
            sa.func.count(sa.case((ClusterMember.is_noise.is_(True), 1))),
            sa.func.count(sa.case((ClusterMember.relevance.is_(None), 1))),
        ).where(ClusterMember.item_type == "video", ClusterMember.cluster_id == cluster_id)
    ).one()
    total, on_niche, undecided, noise, unscorable = counts
    return ClusterView(
        cluster_id=cluster_id,
        active=bool(cluster.active),
        total=total or 0,
        threshold=RELEVANCE_HIGH,
        bands=[
            ("on-niche", on_niche or 0),
            ("undecided", undecided or 0),
            ("noise", noise or 0),
            ("unscorable", unscorable or 0),
        ],
        weakest_kept=_edge(session, cluster_id, kept=True, n=n),
        strongest_dropped=_edge(session, cluster_id, kept=False, n=n),
    )
