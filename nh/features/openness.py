"""Openness metrics: can a newcomer get reach here?

Both metrics run over the same cohort — small, date-discovered channels with
enough eligible videos to have a stable median. The cohort definition *is* the
metric: measured on live data, the same breakthrough formula computed over all
channels is flat across five niches (2 percentage points), and over the cohort it
spreads 40. See docs/METRICS.md and the correction in ADR-0013's neighbourhood.
"""

from __future__ import annotations

import statistics
from datetime import date

from sqlalchemy.orm import Session

from nh.features.inputs import (
    COHORT_MAX_SUBS,
    COHORT_MIN_VIDEOS,
    cohort,
    latest_subs,
)
from nh.features.types import FeatureResult

GROUP = "openness"
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
