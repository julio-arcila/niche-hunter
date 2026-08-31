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
        # Active seeds only. Dominance used to be computed over EVERY seed's lineage
        # and the winner discarded afterwards if it was inactive — so a channel whose
        # majority lineage came from a deactivated seed was dropped from the loop
        # entirely and kept its stale membership row indefinitely, no matter how much
        # lineage an active seed accumulated. Measured 2026-08-28: 110 channels sat
        # frozen in the retired `court-cases` cluster while both its successors were
        # collecting. Filtering here rather than after the ranking also makes
        # `confidence` a share among the niches actually tracked, which is what it
        # claims to be.
        .join(NicheSeed, NicheSeed.id == Discovery.seed_id)
        .where(NicheSeed.active)
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
        # `is_noise` is in the INSERT payload (a new member starts non-noise) but
        # deliberately OUT of the update set, because `upsert`'s `update` defaults to
        # every supplied column. Nothing derives channel `is_noise` today — ADR-0047
        # computes ballast at read time rather than storing it — but the column is a
        # hand switch `member_join` honours, and a nightly that silently reset it
        # would be indistinguishable from one that worked. Same shape as `apply_seeds`
        # keeping `active` outside its update set.
        written += upsert(
            session,
            ClusterMember,
            members,
            conflict_on=("item_type", "item_id"),
            update=["cluster_id", "confidence", "source", "run_id", "at"],
        )
    return written
