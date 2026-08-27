"""Supply metrics: how much competing content the niche already carries."""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import ClusterMember, Video
from nh.features.inputs import (
    AGE_FLOOR_DAYS,
    FEED_DEPTH,
    eligible_videos,
    member_channels,
    member_join,
)
from nh.features.types import FeatureResult

GROUP = "supply"
#: Four weeks. Long enough to smooth a lumpy publishing schedule, short enough to
#: track a niche that is heating up.
WINDOW_DAYS = 28
CONFIDENCE_N = 30


def _confidence(sample_n: int, contributing: int, universe: int) -> float:
    """Sample adequacy times coverage.

    Two different ways a supply metric lies, and it needs both. `min(n/30, 1)`
    alone saturates: 74 contributing channels out of 197 scores 1.00 while the
    metric is computed from 38% of the niche — and those 74 are the enriched,
    discovery-biased ones. Coverage alone would under-report a small but fully
    observed cluster. The product says "enough rows, and enough of the niche".
    """
    adequacy = min(sample_n / CONFIDENCE_N, 1.0)
    # Clamped, but the clamp should never bind: `universe` comes from
    # `member_channels` and `contributing` from a `member_join` query, so both
    # exclude noise. Coverage above 1.0 means those two populations have drifted
    # apart again — a bug in the query, not a value. `confidence` is the column
    # that bounds trust in every other number, so it must not be the one that
    # silently exceeds its own range.
    coverage = min(contributing / universe, 1.0) if universe else 0.0
    return adequacy * coverage


def uploads_per_week(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Long-form uploads entering the niche per week.

    A cluster total, not a per-channel average: supply is the volume of content a
    newcomer competes against. Confidence keys on *coverage* — member channels we
    know anything about — rather than on contributing channels, so that a niche
    which genuinely published nothing this window reports a confident zero rather
    than a doubtful one.
    """
    channels = member_channels(session, cluster_id)
    if not channels:
        return FeatureResult.empty(GROUP, "uploads_per_week", "cluster has no member channels")

    since = datetime.combine(day - timedelta(days=WINDOW_DAYS), time.min, tzinfo=UTC)
    until = datetime.combine(day, time.max, tzinfo=UTC)
    uploads, covered = session.execute(
        sa.select(
            sa.func.count(Video.video_id),
            sa.func.count(sa.distinct(Video.channel_id)),
        )
        .join(ClusterMember, member_join(Video.channel_id, cluster_id))
        .where(
            Video.is_short.is_(False),
            Video.published_at.is_not(None),
            Video.published_at > since,
            Video.published_at <= until,
        )
    ).one()

    known = (
        session.scalar(
            sa.select(sa.func.count(sa.distinct(Video.channel_id))).join(
                ClusterMember, member_join(Video.channel_id, cluster_id)
            )
        )
        or 0
    )
    if not known:
        return FeatureResult.empty(
            GROUP, "uploads_per_week", "no member channel has any known video"
        )
    return FeatureResult(
        group=GROUP,
        name="uploads_per_week",
        value=uploads / (WINDOW_DAYS / 7),
        # Coverage is channels we can SEE, not channels that published: a niche
        # that genuinely published nothing is a confident zero, and using
        # `covered` here would drive its confidence to 0 and call the finding
        # missing data.
        confidence=_confidence(known, known, len(channels)),
        inputs_n=uploads,
        detail={
            "window": [since.date().isoformat(), day.isoformat()],
            "member_channels": len(channels),
            "channels_with_any_video": known,
            "channels_publishing_in_window": covered,
            "note": "long-form only; unknown-format videos excluded until enrichment lands",
            "inputs": {"tables": ["videos", "cluster_members"]},
        },
    )


def median_views(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Typical reach of a video in this niche.

    Pooled across every member channel's eligible videos rather than a median of
    channel medians: supply is the field you compete against, and a 500-subscriber
    channel should not weigh as much as one with 30 million. The per-channel
    FEED_DEPTH cap is what stops a prolific channel from dominating the pool.
    """
    by_channel = eligible_videos(session, cluster_id, day)
    pooled = [views for rows in by_channel.values() for _, views in rows]
    if not pooled:
        return FeatureResult.empty(
            GROUP,
            "median_views",
            "no eligible videos: none long-form, aged past the floor, and observed",
            age_floor_days=AGE_FLOOR_DAYS,
        )
    pooled.sort()
    return FeatureResult(
        group=GROUP,
        name="median_views",
        value=float(statistics.median(pooled)),
        confidence=_confidence(
            len(by_channel), len(by_channel), len(member_channels(session, cluster_id))
        ),
        inputs_n=len(pooled),
        detail={
            "contributing_channels": len(by_channel),
            "p90_views": float(pooled[int(0.9 * (len(pooled) - 1))]),
            "as_of": day.isoformat(),
            "filters": {
                "long_form_only": True,
                "age_floor_days": AGE_FLOOR_DAYS,
                "per_channel_cap": FEED_DEPTH,
            },
            "inputs": {"tables": ["videos", "video_snapshots", "cluster_members"]},
        },
    )
