"""Supply metrics: how much competing content the niche already carries."""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.clustering.lexicon import LEXICON_VERSION
from nh.db.models import Channel, Cluster, ClusterMember, NicheSeed, Video
from nh.features.inputs import (
    AGE_FLOOR_DAYS,
    FEED_DEPTH,
    RELEVANCE_HIGH,
    eligible_niche_videos,
    member_channels,
    member_join,
    on_niche_join,
    relevance_coverage,
)
from nh.features.types import FeatureResult

GROUP = "supply"
#: Four weeks. Long enough to smooth a lumpy publishing schedule, short enough to
#: track a niche that is heating up.
WINDOW_DAYS = 28
CONFIDENCE_N = 30


#: Stamped into `detail` on every metric that moved to the on-niche pool in Slice
#: 4, so a step change in a stored series is attributable rather than mysterious.
DEFINITION = "v2-on-niche"


def _confidence(
    sample_n: int, contributing: int, universe: int, relevance: tuple[int, int] | None = None
) -> float:
    """Sample adequacy times coverage, times relevance coverage where it applies.

    Two different ways a supply metric lies, and it needs both. `min(n/30, 1)`
    alone saturates: 74 contributing channels out of 197 scores 1.00 while the
    metric is computed from 38% of the niche — and those 74 are the enriched,
    discovery-biased ones. Coverage alone would under-report a small but fully
    observed cluster. The product says "enough rows, and enough of the niche".

    Relevance coverage is the third leg, new in Slice 4: a metric computed over
    on-niche videos depends on a judgement about each one, and the share of the
    cluster we could actually judge is a distinct way the number lies. Held-out
    precision on that judgement is 0.781, not 1.0 — see
    reports/relevance_2026-08-27.md — so these metrics are not clean and their
    confidence must not read as though they were.
    """
    adequacy = min(sample_n / CONFIDENCE_N, 1.0)
    # Clamped, but the clamp should never bind: `universe` comes from
    # `member_channels` and `contributing` from a `member_join` query, so both
    # exclude noise. Coverage above 1.0 means those two populations have drifted
    # apart again — a bug in the query, not a value. `confidence` is the column
    # that bounds trust in every other number, so it must not be the one that
    # silently exceeds its own range.
    coverage = min(contributing / universe, 1.0) if universe else 0.0
    decided = 1.0
    if relevance is not None:
        judged, total = relevance
        decided = min(judged / total, 1.0) if total else 0.0
    return adequacy * coverage * decided


def uploads_per_week(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Long-form on-niche uploads entering the niche per week.

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
            # EXISTS rather than a second join: `cluster_members` is already joined
            # once for channel membership, and an alias here would read as though
            # the two memberships were the same thing. They are not — one says the
            # channel belongs to the niche, the other says this video is about it.
            sa.exists(sa.select(1).where(on_niche_join(cluster_id)).correlate(Video)),
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
        confidence=_confidence(
            known, known, len(channels), relevance_coverage(session, cluster_id)
        ),
        inputs_n=uploads,
        detail={
            "window": [since.date().isoformat(), day.isoformat()],
            "member_channels": len(channels),
            "channels_with_any_video": known,
            "channels_publishing_in_window": covered,
            "definition": DEFINITION,
            "note": (
                "long-form, on-niche only; unknown-format videos excluded until enrichment lands"
            ),
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
    by_channel = eligible_niche_videos(session, cluster_id, day)
    pooled = [views for rows in by_channel.values() for _, views in rows]
    if not pooled:
        return FeatureResult.empty(
            GROUP,
            "median_views",
            "no eligible on-niche videos: none long-form, aged past the floor, "
            "observed, and judged on-niche",
            age_floor_days=AGE_FLOOR_DAYS,
        )
    pooled.sort()
    return FeatureResult(
        group=GROUP,
        name="median_views",
        value=float(statistics.median(pooled)),
        confidence=_confidence(
            len(by_channel),
            len(by_channel),
            len(member_channels(session, cluster_id)),
            relevance_coverage(session, cluster_id),
        ),
        inputs_n=len(pooled),
        detail={
            "definition": DEFINITION,
            "contributing_channels": len(by_channel),
            "p90_views": float(pooled[int(0.9 * (len(pooled) - 1))]),
            "as_of": day.isoformat(),
            "filters": {
                "long_form_only": True,
                "age_floor_days": AGE_FLOOR_DAYS,
                "per_channel_cap": FEED_DEPTH,
                "on_niche_only": True,
            },
            "inputs": {"tables": ["videos", "video_snapshots", "cluster_members"]},
        },
    )


def on_niche_share(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Share of the cluster's videos that are actually about its niche.

    The headline finding of Slice 4, and the number that says how much to trust
    every other supply figure. Measured 2026-08-27 it is ~20% across all five
    clusters, because `cluster_members` assigns *channels* to seeds and videos
    inherited their channel's cluster with no further question asked.

    Denominator is decided videos only — on-niche plus decided-noise. Undecided and
    unscorable are excluded from both sides rather than counted against, which is
    the same treatment `money.midroll_eligible_share` gives an unknown duration.
    """
    judged, total = relevance_coverage(session, cluster_id)
    if not judged:
        return FeatureResult.empty(GROUP, "on_niche_share", "no video has a relevance decision yet")
    on_niche = (
        session.scalar(
            sa.select(sa.func.count()).where(
                ClusterMember.item_type == "video",
                ClusterMember.cluster_id == cluster_id,
                ClusterMember.relevance >= RELEVANCE_HIGH,
            )
        )
        or 0
    )
    return FeatureResult(
        group=GROUP,
        name="on_niche_share",
        value=on_niche / judged,
        # Coverage only: there is no sample-adequacy leg because the metric is a
        # census of the cluster, not a sample of it.
        confidence=min(judged / total, 1.0) if total else 0.0,
        inputs_n=judged,
        detail={
            "definition": DEFINITION,
            "on_niche": on_niche,
            "decided": judged,
            "videos": total,
            "undecided_or_unscorable": total - judged,
            "lexicon": LEXICON_VERSION,
            "threshold": RELEVANCE_HIGH,
            "note": (
                "measures the lexicon as much as the corpus; held-out precision "
                "0.781, recall 0.694 against a 28.6% base rate — "
                "reports/relevance_2026-08-27.md"
            ),
            "inputs": {"tables": ["cluster_members"]},
        },
    )


def geo_concentration(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Share of member channels based in the market the seed says it is about.

    The demand side is read off English Wikipedia, which is global and US-leaning;
    the supply side is whatever `relevanceLanguage=en` discovery returns, which
    measured 2026-08-27 is 234 Indian channels against 290 US. `gap` subtracts one
    rank from the other and cannot see that, so this metric makes the divergence a
    number instead of letting the gap absorb it.

    NOT a quality score, and it must not be read as one. A low value can mean the
    seed's stated geo is wrong, or that the niche is genuinely global; both are
    findings and neither is a defect. It exists so that a `gap` computed across
    mismatched populations is visibly that, rather than quietly plausible.

    Unknown country excludes a channel from both sides — 719 of 955 have one — and
    lowers confidence, rather than counting as "not local" (data rule 7).
    """
    seed_geo = session.scalar(
        sa.select(NicheSeed.geo)
        .join(Cluster, Cluster.seed_id == NicheSeed.id)
        .where(Cluster.cluster_id == cluster_id)
    )
    if not seed_geo:
        return FeatureResult.empty(
            GROUP, "geo_concentration", "seed states no geo, so there is nothing to diverge from"
        )
    members = member_channels(session, cluster_id)
    if not members:
        return FeatureResult.empty(GROUP, "geo_concentration", "cluster has no member channel")

    counts = dict(
        session.execute(
            sa.select(Channel.country, sa.func.count())
            .where(Channel.channel_id.in_(members), Channel.country.is_not(None))
            .group_by(Channel.country)
        ).all()
    )
    known = sum(counts.values())
    if not known:
        return FeatureResult.empty(
            GROUP, "geo_concentration", "no member channel reports a country"
        )
    return FeatureResult(
        group=GROUP,
        name="geo_concentration",
        value=counts.get(seed_geo, 0) / known,
        confidence=known / len(members),
        inputs_n=known,
        detail={
            "seed_geo": seed_geo,
            "member_channels": len(members),
            "with_known_country": known,
            "top_countries": sorted(counts.items(), key=lambda kv: -kv[1])[:5],
            "as_of": day.isoformat(),
            "note": "not a quality score; a low value may mean the niche is global",
            "inputs": {"tables": ["cluster_members", "channels", "clusters", "niche_seeds"]},
        },
    )
