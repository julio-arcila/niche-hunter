"""Money metrics: what the niche's inventory is worth to advertisers.

Slice 2 ships one, and it is display-only — the money composite arrives in
Slice 5. It is here because the roadmap asks for features spanning three groups
and because, once durations exist, it costs one query.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import ClusterMember, Video
from nh.features.inputs import member_join
from nh.features.types import FeatureResult

GROUP = "money"
WINDOW_DAYS = 90
#: Per-video and exactly measured, so videos are the honest sample unit. 100
#: because the window is video-rich and 30 videos can be two channels' output.
CONFIDENCE_N = 100


def midroll_eligible_share(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Share of the niche's recent long-form videos that can carry mid-roll ads.

    Unknown durations are excluded from numerator *and* denominator. Counting them
    as ineligible would be the NULL-as-False trap: before the enrichment backfill
    runs, 91% of videos have no duration, and treating those as "no mid-roll" would
    report a confident near-zero for every niche.
    """
    since = datetime.combine(day - timedelta(days=WINDOW_DAYS), time.min, tzinfo=UTC)
    until = datetime.combine(day, time.max, tzinfo=UTC)
    known, eligible = session.execute(
        sa.select(
            sa.func.count(Video.video_id),
            sa.func.sum(sa.case((Video.midroll_eligible.is_(True), 1), else_=0)),
        )
        .join(ClusterMember, member_join(Video.channel_id, cluster_id))
        .where(
            Video.midroll_eligible.is_not(None),
            Video.published_at.is_not(None),
            Video.published_at > since,
            Video.published_at <= until,
        )
    ).one()

    if not known:
        return FeatureResult.empty(
            GROUP,
            "midroll_eligible_share",
            "no member video in the window has a known duration "
            "(the enrichment backfill has not reached this cluster yet)",
            window_days=WINDOW_DAYS,
        )
    return FeatureResult(
        group=GROUP,
        name="midroll_eligible_share",
        value=(eligible or 0) / known,
        confidence=min(known / CONFIDENCE_N, 1.0),
        inputs_n=known,
        detail={
            "videos_with_known_duration": known,
            "midroll_eligible": eligible or 0,
            "window": [since.date().isoformat(), day.isoformat()],
            "note": "unknown durations excluded from both sides, never counted ineligible",
            "inputs": {"tables": ["videos", "cluster_members"]},
        },
    )
