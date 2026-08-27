"""Shared input queries for the feature functions.

Every metric that needs "this cluster's channels" or "this channel's eligible
videos" comes here. One definition, so supply and openness cannot quietly drift
apart — two metrics disagreeing about which videos count is the kind of bug that
survives review because both numbers look reasonable in isolation.

Everything is parameterised by `day` and nothing reads the clock. That is
re-run determinism now (the same day recomputes to the same values) and the
anti-leakage property Slice 6's backtest will depend on: a feature must never see
a row that did not exist at the decision date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import (
    ChannelSnapshot,
    Cluster,
    ClusterMember,
    Discovery,
    SeedTerm,
    Video,
    VideoSnapshot,
)

#: Views on a very fresh upload have not settled, so comparing one against an
#: older video measures age rather than performance. A stopgap until the snapshot
#: series supports views-at-day-30 — see docs/METRICS.md supply.median_views.
AGE_FLOOR_DAYS = 14

#: An RSS feed returns at most 15 entries. Capping every channel at 15 keeps
#: API-discovered channels from getting a deeper window than RSS-only ones, which
#: would make their medians incomparable.
FEED_DEPTH = 15

#: Openness is about small entrants. Above this, views-per-sub measures audience
#: retention rather than whether a newcomer can get reach.
COHORT_MAX_SUBS = 10_000

#: Below this a channel has no stable median to compare a breakout against.
COHORT_MIN_VIDEOS = 5


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def member_join(column, cluster_id: str, item_type: str = "channel"):
    """The membership predicate, defined once.

    Every metric that resolves an item to a cluster joins on the same three
    conditions plus `is_noise IS FALSE`, and until Slice 4 four of the six join
    sites had hand-copied the first three and dropped the fourth. That was
    invisible while nothing wrote noise, and would have become a live corruption
    the moment something did: `supply._confidence` takes its universe from
    `member_channels` (noise-free) and its numerator from a leaky join, so
    coverage — and therefore confidence — could exceed 1.0.

    The module docstring already promised "one definition, so supply and openness
    cannot quietly drift apart". This is that promise made mechanical.
    """
    return sa.and_(
        ClusterMember.item_id == column,
        ClusterMember.item_type == item_type,
        ClusterMember.cluster_id == cluster_id,
        ClusterMember.is_noise.is_(False),
    )


def member_channels(session: Session, cluster_id: str) -> list[str]:
    return list(
        session.scalars(
            sa.select(ClusterMember.item_id).where(member_join(ClusterMember.item_id, cluster_id))
        )
    )


def eligible_videos(
    session: Session, cluster_id: str, day: date
) -> dict[str, list[tuple[str, int]]]:
    """`channel_id -> [(video_id, views), ...]`, newest first, capped at FEED_DEPTH.

    Eligible means: long-form (`is_short IS FALSE` — a NULL is unknown format and
    is excluded, never treated as long-form), published at least AGE_FLOOR_DAYS
    before `day`, and with at least one view observation on or before `day`.

    Views are the max over snapshots up to `day` rather than the value on the
    latest date. For a monotonically increasing counter these agree, and the max
    is robust to one source under-reporting on a given day.
    """
    latest = (
        sa.select(
            VideoSnapshot.video_id,
            sa.func.max(VideoSnapshot.views).label("views"),
        )
        .where(VideoSnapshot.observed_date <= day, VideoSnapshot.views.is_not(None))
        .group_by(VideoSnapshot.video_id)
        .subquery()
    )
    ranked = (
        sa.select(
            Video.channel_id.label("channel_id"),
            Video.video_id.label("video_id"),
            latest.c.views.label("views"),
            sa.func.row_number()
            .over(partition_by=Video.channel_id, order_by=Video.published_at.desc())
            .label("rn"),
        )
        .join(latest, latest.c.video_id == Video.video_id)
        .join(ClusterMember, member_join(Video.channel_id, cluster_id))
        .where(
            Video.is_short.is_(False),
            Video.published_at.is_not(None),
            Video.published_at <= _midnight(day - timedelta(days=AGE_FLOOR_DAYS)),
        )
        .subquery()
    )
    out: dict[str, list[tuple[str, int]]] = {}
    for channel_id, video_id, views in session.execute(
        sa.select(ranked.c.channel_id, ranked.c.video_id, ranked.c.views).where(
            ranked.c.rn <= FEED_DEPTH
        )
    ):
        out.setdefault(channel_id, []).append((video_id, views))
    return out


def latest_subs(session: Session, cluster_id: str, day: date) -> dict[str, int]:
    """`channel_id -> subs` for member channels whose count is visible on `day`.

    A hidden subscriber count is absent from this mapping rather than present as
    zero. Callers must treat "not in the dict" as unknown (data rule 7).
    """
    rows = session.execute(
        sa.select(
            ChannelSnapshot.channel_id,
            sa.func.max(ChannelSnapshot.subs),
        )
        .join(ClusterMember, member_join(ChannelSnapshot.channel_id, cluster_id))
        .where(ChannelSnapshot.observed_date <= day, ChannelSnapshot.subs.is_not(None))
        .group_by(ChannelSnapshot.channel_id)
    ).all()
    return {channel_id: subs for channel_id, subs in rows if subs is not None}


def date_discovered_channels(session: Session, cluster_id: str) -> set[str]:
    """Member channels with at least one video found under `order=date`.

    This is the unbiased-denominator filter, and it is the whole reason
    `Discovery.order_by` is a column. A channel that entered the sample only
    through `order=viewCount` is there *because* it had a winner; counting it in
    an openness denominator inflates the rate by construction. Measured: without
    this filter the breakthrough rate is flat across all five niches.
    """
    return set(
        session.scalars(
            sa.select(Video.channel_id)
            .join(Discovery, Discovery.video_id == Video.video_id)
            .join(ClusterMember, member_join(Video.channel_id, cluster_id))
            .where(Discovery.order_by == "date")
            .distinct()
        )
    )


def cohort(session: Session, cluster_id: str, day: date) -> dict[str, list[int]]:
    """The openness cohort: `channel_id -> [views, ...]` of its eligible videos.

    Membership requires all three of: subscriber count visible and at or below
    COHORT_MAX_SUBS, at least COHORT_MIN_VIDEOS eligible videos, and `order=date`
    discovery lineage. Each filter is load-bearing — see docs/METRICS.md.
    """
    videos = eligible_videos(session, cluster_id, day)
    subs = latest_subs(session, cluster_id, day)
    dated = date_discovered_channels(session, cluster_id)
    return {
        channel_id: [views for _, views in rows]
        for channel_id, rows in videos.items()
        if len(rows) >= COHORT_MIN_VIDEOS
        and channel_id in dated
        and 0 < subs.get(channel_id, 0) <= COHORT_MAX_SUBS
    }


def demand_terms(session: Session, cluster_id: str, source: str) -> list[str]:
    """Active demand terms for the cluster's seed.

    Joins through `clusters.seed_id`, which is the one place to touch when Slice 4
    changes what a `cluster_id` is. Deliberately does NOT fall back to
    `niche_seeds.keywords`: those are YouTube search phrases and are demand-dead
    elsewhere — most read literal zero on Trends — so reusing them would
    manufacture confident nonsense (ADR-0015).
    """
    return list(
        session.scalars(
            sa.select(SeedTerm.term)
            .join(Cluster, Cluster.seed_id == SeedTerm.seed_id)
            .where(
                Cluster.cluster_id == cluster_id,
                SeedTerm.source == source,
                SeedTerm.active.is_(True),
            )
            .order_by(SeedTerm.term)
        )
    )
