"""Money metrics: what the niche's inventory is worth to advertisers.

Slice 2 ships one, and it is display-only — the money composite arrives in
Slice 5. It is here because the roadmap asks for features spanning three groups
and because, once durations exist, it costs one query.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import Channel, ClusterMember, Video
from nh.features.inputs import (
    _day_end,
    member_join,
    on_niche_join,
    relevance_coverage,
    window_start,
)
from nh.features.types import FeatureResult

GROUP = "money"
WINDOW_DAYS = 90
#: Per-video and exactly measured, so videos are the honest sample unit. 100
#: because the window is video-rich and 30 videos can be two channels' output.
CONFIDENCE_N = 100


def _decided(session: Session, cluster_id: str, day) -> float:
    """Share of the cluster's videos we could decide on-niche or not."""
    judged, total = relevance_coverage(session, cluster_id, day)
    return min(judged / total, 1.0) if total else 0.0


def midroll_eligible_share(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Share of the niche's recent long-form videos that can carry mid-roll ads.

    Unknown durations are excluded from numerator *and* denominator. Counting them
    as ineligible would be the NULL-as-False trap: before the enrichment backfill
    runs, 91% of videos have no duration, and treating those as "no mid-roll" would
    report a confident near-zero for every niche.
    """
    since = window_start(day, WINDOW_DAYS)
    until = _day_end(day)
    known, eligible = session.execute(
        sa.select(
            sa.func.count(Video.video_id),
            sa.func.sum(sa.case((Video.midroll_eligible.is_(True), 1), else_=0)),
        )
        .join(Channel, Channel.channel_id == Video.channel_id)
        .join(ClusterMember, member_join(Video.channel_id, cluster_id, day=day))
        .where(
            Video.midroll_eligible.is_not(None),
            Video.published_at.is_not(None),
            Video.published_at >= since,
            Video.published_at <= until,
            # Both numerator and denominator restrict to on-niche: the question is
            # what share of THIS NICHE's supply can carry a midroll, and a channel's
            # off-niche uploads answer a different question.
            sa.exists(sa.select(1).where(on_niche_join(cluster_id, day)).correlate(Video)),
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
        # Times relevance coverage, like the supply metrics: this is now computed
        # over videos we judged, and how much of the cluster we could judge is a
        # distinct way it lies. Held-out precision on that judgement is 0.781.
        confidence=min(known / CONFIDENCE_N, 1.0) * _decided(session, cluster_id, day),
        inputs_n=known,
        detail={
            "definition": "v2-on-niche",
            "videos_with_known_duration": known,
            "midroll_eligible": eligible or 0,
            "window": [since.date().isoformat(), day.isoformat()],
            "note": "unknown durations excluded from both sides, never counted ineligible",
            "inputs": {"tables": ["videos", "cluster_members"]},
        },
    )
