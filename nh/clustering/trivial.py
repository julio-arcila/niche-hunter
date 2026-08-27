"""Channel identity: which niche does a channel belong to?

One cluster per seed, and each channel resolved to exactly one of them from its
discovery lineage (ADR-0013). Slice 4 kept this unchanged and added a *second*
question beside it — is a given video about that niche — in
`nh/clustering/relevance.py`. The two are genuinely different: a channel that
covers plane crashes still uploads plenty that is not about plane crashes, and
before Slice 4 the pipeline conflated them by letting videos inherit their
channel's cluster with no further question asked.

The docstring here used to say materialising video rows "would add nothing".
That was true while the only question was identity and false once topicality was
asked: measured 2026-08-27, only 20% of the videos inheriting a cluster this way
were about its niche. `nh/clustering/phase.py` writes those rows now.

Slice 4 did NOT bring embeddings or HDBSCAN — see ADR-0018 for why the roadmap's
plan for this slice was overtaken by what Slice 3 found.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import Cluster, ClusterMember, Discovery, NicheSeed, Video
from nh.db.provenance import Stamp
from nh.db.upsert import upsert

#: (channel_id, seed_id, distinct videos found under order=date, distinct videos total)
Lineage = Sequence[tuple[str, int, int, int]]


def dominant_seed(lineage: Lineage) -> dict[str, tuple[int, float]]:
    """Resolve each channel to exactly one seed (ADR-0013).

    Ranked by distinct videos discovered under `order=date`, then distinct videos
    overall, then lowest `seed_id`. `order=date` leads because `order=viewCount`
    selects on success and should not decide what a channel *is about*; the final
    tie-break is arbitrary but deterministic, so re-running never reshuffles.

    Returns `channel_id -> (seed_id, confidence)`, where confidence is the winning
    seed's share of the channel's discovered videos — 1.0 for an unambiguous
    channel, lower where two niches genuinely overlap.
    """
    by_channel: dict[str, list[tuple[int, int, int]]] = {}
    for channel_id, seed_id, dated, total in lineage:
        by_channel.setdefault(channel_id, []).append((seed_id, dated, total))

    resolved: dict[str, tuple[int, float]] = {}
    for channel_id, candidates in by_channel.items():
        best = max(candidates, key=lambda c: (c[1], c[2], -c[0]))
        all_videos = sum(c[2] for c in candidates)
        resolved[channel_id] = (best[0], best[2] / all_videos if all_videos else 0.0)
    return resolved


def assign_channels(session: Session, day: date, mark: Stamp) -> int:
    """Write one cluster per active seed, and one membership row per channel."""
    seeds = session.execute(
        sa.select(NicheSeed.id, NicheSeed.slug, NicheSeed.label).where(NicheSeed.active)
    ).all()
    if not seeds:
        return 0
    written = upsert(
        session,
        Cluster,
        [
            mark(Cluster, {"cluster_id": slug, "seed_id": seed_id, "label": label})
            for seed_id, slug, label in seeds
        ],
    )

    # Distinct videos, not raw discovery rows: `discoveries` appends nightly, so
    # counting rows would drift dominance toward whichever seed's queries
    # re-surface the same videos most often.
    lineage = session.execute(
        sa.select(
            Video.channel_id,
            Discovery.seed_id,
            sa.func.count(sa.distinct(sa.case((Discovery.order_by == "date", Discovery.video_id)))),
            sa.func.count(sa.distinct(Discovery.video_id)),
        )
        .join(Video, Video.video_id == Discovery.video_id)
        .where(Discovery.seed_id.is_not(None))
        .group_by(Video.channel_id, Discovery.seed_id)
    ).all()

    slug_of = {seed_id: slug for seed_id, slug, _ in seeds}
    members = [
        mark(
            ClusterMember,
            {
                "cluster_id": slug_of[seed_id],
                "item_type": "channel",
                "item_id": channel_id,
                "confidence": confidence,
                "is_noise": False,
            },
        )
        for channel_id, (seed_id, confidence) in dominant_seed(lineage).items()
        if seed_id in slug_of
    ]
    if members:
        written += upsert(session, ClusterMember, members, conflict_on=("item_type", "item_id"))
    return written
