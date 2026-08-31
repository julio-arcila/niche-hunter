"""Openness metrics: can a newcomer get reach here?

**Three metrics, and only two of them run over the cohort.** `breakthrough_rate_cohort`
and `views_per_sub` do — small, date-discovered channels with enough eligible videos to
have a stable median. The cohort definition *is* the metric there: measured on live
data, the same breakthrough formula computed over all channels is flat across five
niches (2 percentage points), and over the cohort it spreads 40. See docs/METRICS.md and
the correction in ADR-0013's neighbourhood.

**`winner_age_years` is the exception, and reading this docstring instead of the code
already caused one error.** It runs over the top-N videos by views and joins
`on_niche_join` (line 167), so it **reads the relevance threshold directly** — unlike
its two neighbours, which reach channel membership only. A Slice 7 plan classified all
of `openness.*` as scorer-independent by reasoning from this text, on the strength of
ADR-0047's true and different claim that openness is unaffected by *ballast*. It is
gated in `api/gates.py::SCORER_DEPENDENT`, and that set is derived by execution rather
than by reading — which is how the mistake was caught.
"""

from __future__ import annotations

import statistics
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import Channel, ClusterMember, Video, VideoSnapshot
from nh.features.inputs import (
    COHORT_MAX_SUBS,
    COHORT_MIN_VIDEOS,
    _until,
    cohort,
    latest_subs,
    on_niche_join,
)
from nh.features.types import FeatureResult

GROUP = "openness"
#: How many of the niche's biggest videos define "who wins here".
TOP_N = 100
DAYS_PER_YEAR = 365.25
#: A video at or above this multiple of its channel's median is a breakout.
BREAKOUT_X_MEDIAN = 5.0
#: ...or this multiple of the channel's subscriber count, which catches a channel
#: whose whole catalogue is small but which reached far beyond its audience.
BREAKOUT_X_SUBS = 10.0
CONFIDENCE_N = 30

_EMPTY_COHORT = (
    f"cohort empty: no member channel with visible subs <= {COHORT_MAX_SUBS:,}, "
    f">= {COHORT_MIN_VIDEOS} eligible videos, and order=date discovery lineage"
)


def _breakouts(views: list[int], subs: int | None) -> list[int]:
    median = statistics.median(views)
    return [
        v
        for v in views
        if (median and v >= BREAKOUT_X_MEDIAN * median) or (subs and v >= BREAKOUT_X_SUBS * subs)
    ]


def breakthrough_rate_cohort(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Share of cohort channels with at least one breakout video.

    A rate *of channels*, not of videos: the question is whether a typical small
    entrant can break through, and a per-video rate would be dominated by whichever
    channels publish most.
    """
    members = cohort(session, cluster_id, day)
    if not members:
        return FeatureResult.empty(GROUP, "breakthrough_rate_cohort", _EMPTY_COHORT)

    subs = latest_subs(session, cluster_id, day)
    broke = {
        channel_id: _breakouts(views, subs.get(channel_id)) for channel_id, views in members.items()
    }
    winners = {c: v for c, v in broke.items() if v}
    return FeatureResult(
        group=GROUP,
        name="breakthrough_rate_cohort",
        value=len(winners) / len(members),
        confidence=min(len(members) / CONFIDENCE_N, 1.0),
        inputs_n=len(members),
        detail={
            "cohort_channels": len(members),
            "channels_with_breakout": len(winners),
            "breakout_channel_ids": sorted(winners)[:20],
            "thresholds": {"x_median": BREAKOUT_X_MEDIAN, "x_subs": BREAKOUT_X_SUBS},
            "cohort_filters": {
                "max_subs": COHORT_MAX_SUBS,
                "min_eligible_videos": COHORT_MIN_VIDEOS,
                "requires_order_date_lineage": True,
            },
            "as_of": day.isoformat(),
            "inputs": {
                "tables": [
                    "cluster_members",
                    "channel_snapshots",
                    "videos",
                    "video_snapshots",
                    "discoveries",
                ]
            },
        },
    )


def views_per_sub(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Cohort reach relative to audience size — punching above weight.

    Unweighted median across cohort channels. A mean is destroyed by a 500-sub
    channel with one viral video, and weighting by subscribers answers a different
    question ("where do this niche's views go") dominated by its largest channels.
    """
    members = cohort(session, cluster_id, day)
    if not members:
        return FeatureResult.empty(GROUP, "views_per_sub", _EMPTY_COHORT)

    subs = latest_subs(session, cluster_id, day)
    ratios = [
        statistics.median(views) / subs[channel_id]
        for channel_id, views in members.items()
        if subs.get(channel_id)
    ]
    if not ratios:
        return FeatureResult.empty(
            GROUP, "views_per_sub", "no cohort channel has a visible subscriber count"
        )
    return FeatureResult(
        group=GROUP,
        name="views_per_sub",
        value=float(statistics.median(ratios)),
        confidence=min(len(ratios) / CONFIDENCE_N, 1.0),
        inputs_n=len(ratios),
        detail={
            "cohort_channels": len(members),
            "with_visible_subs": len(ratios),
            "note": "hidden subscriber counts exclude a channel; never read as zero",
            "as_of": day.isoformat(),
            "inputs": {
                "tables": ["cluster_members", "channel_snapshots", "videos", "video_snapshots"]
            },
        },
    )


def winner_age_years(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Median age of the channels behind the niche's biggest videos. LOWER IS MORE OPEN.

    A second openness signal that shares no machinery with the cohort metrics above:
    it asks who is *currently winning* rather than whether a small entrant can break
    out, and it needs no subscriber counts and no discovery lineage — so it survives
    the cohort being empty, which for four of five clusters it currently is.

    Deliberately threshold-free. An earlier draft used "share of top videos from
    channels younger than 3 years" and 3 was chosen because it maximised spread
    across five niches; docs/METRICS.md records that and says not to reintroduce a
    cutoff. A median needs no cutoff.

    No per-channel cap here, unlike `eligible_videos`. A cap would change what "top"
    means, and the real risk — a handful of prolific channels filling the top 100 —
    is what `confidence` measures rather than something to engineer away.
    """
    latest = (
        sa.select(VideoSnapshot.video_id, sa.func.max(VideoSnapshot.views).label("views"))
        .where(VideoSnapshot.observed_date <= day, VideoSnapshot.views.is_not(None))
        .group_by(VideoSnapshot.video_id)
        .subquery()
    )
    rows = session.execute(
        sa.select(Video.channel_id, Channel.created_at, latest.c.views)
        .join(latest, latest.c.video_id == Video.video_id)
        .join(Channel, Channel.channel_id == Video.channel_id)
        .join(ClusterMember, on_niche_join(cluster_id, day))
        .where(Channel.created_at.is_not(None), Channel.created_at < _until(day))
        .order_by(latest.c.views.desc())
        .limit(TOP_N)
    ).all()
    if not rows:
        return FeatureResult.empty(
            GROUP, "winner_age_years", "no on-niche video with views and a dated channel"
        )

    ages = [(day - created.date()).days / DAYS_PER_YEAR for _, created, _ in rows]
    channels = {channel_id for channel_id, _, _ in rows}
    return FeatureResult(
        group=GROUP,
        name="winner_age_years",
        value=float(statistics.median(ages)),
        # Distinct channels, not videos: if the top-N comes from few prolific
        # channels the median describes those channels rather than the niche.
        confidence=min(len(channels) / TOP_N, 1.0),
        inputs_n=len(rows),
        detail={
            "top_n": TOP_N,
            "videos_ranked": len(rows),
            "distinct_channels": len(channels),
            "youngest_years": round(min(ages), 2),
            "oldest_years": round(max(ages), 2),
            "as_of": day.isoformat(),
            "note": (
                "ranked on lifetime views, which favours older videos and so "
                "UNDER-states openness; on-niche videos only"
            ),
            "inputs": {"tables": ["cluster_members", "videos", "video_snapshots", "channels"]},
        },
    )
