"""Supply metrics: how much competing content the niche already carries."""

from __future__ import annotations

import statistics
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.clustering.lexicon import LEXICON_VERSION
from nh.db.models import (
    Channel,
    ChannelSnapshot,
    Cluster,
    ClusterMember,
    NicheSeed,
    Video,
    VideoSnapshot,
)
from nh.features.inputs import (
    AGE_FLOOR_DAYS,
    FEED_DEPTH,
    RELEVANCE_HIGH,
    _until,
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
    channels = member_channels(session, cluster_id, day)
    if not channels:
        return FeatureResult.empty(GROUP, "uploads_per_week", "cluster has no member channels")

    since = datetime.combine(day - timedelta(days=WINDOW_DAYS), time.min, tzinfo=UTC)
    until = datetime.combine(day, time.max, tzinfo=UTC)
    uploads, covered = session.execute(
        sa.select(
            sa.func.count(Video.video_id),
            sa.func.count(sa.distinct(Video.channel_id)),
        )
        .join(Channel, Channel.channel_id == Video.channel_id)
        .join(ClusterMember, member_join(Video.channel_id, cluster_id, day=day))
        .where(
            Video.is_short.is_(False),
            Video.published_at.is_not(None),
            Video.published_at > since,
            Video.published_at <= until,
            # EXISTS rather than a second join: `cluster_members` is already joined
            # once for channel membership, and an alias here would read as though
            # the two memberships were the same thing. They are not — one says the
            # channel belongs to the niche, the other says this video is about it.
            sa.exists(sa.select(1).where(on_niche_join(cluster_id, day)).correlate(Video)),
        )
    ).one()

    known = (
        session.scalar(
            sa.select(sa.func.count(sa.distinct(Video.channel_id)))
            .join(Channel, Channel.channel_id == Video.channel_id)
            .join(ClusterMember, member_join(Video.channel_id, cluster_id, day=day))
            # Bounded: unbounded, this counted every present-day channel and
            # produced a CONFIDENT ZERO at any historical date — measured, 0.0 at
            # confidence 0.871 for 2019 against 197 channels that did not exist.
            .where(Video.published_at < _until(day))
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
            known, known, len(channels), relevance_coverage(session, cluster_id, day)
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
            len(member_channels(session, cluster_id, day)),
            relevance_coverage(session, cluster_id, day),
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
    judged, total = relevance_coverage(session, cluster_id, day)
    if not judged:
        return FeatureResult.empty(GROUP, "on_niche_share", "no video has a relevance decision yet")
    on_niche = (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(ClusterMember)
            .join(Video, Video.video_id == ClusterMember.item_id)
            .where(on_niche_join(cluster_id, day))
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
    members = member_channels(session, cluster_id, day)
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


#: Videos that define "the top" of a niche. Same N as `winner_age_years`, so the
#: two describe the same slice of content from different angles.
TOP_N = 100
DAYS_PER_YEAR = 365.25


def _top_videos(session: Session, cluster_id: str, day: date) -> list[tuple[str, int, date]]:
    """`(video_id, views, published)` for the niche's biggest on-niche videos."""
    latest = (
        sa.select(VideoSnapshot.video_id, sa.func.max(VideoSnapshot.views).label("views"))
        .where(VideoSnapshot.observed_date <= day, VideoSnapshot.views.is_not(None))
        .group_by(VideoSnapshot.video_id)
        .subquery()
    )
    rows = session.execute(
        sa.select(Video.video_id, latest.c.views, Video.published_at)
        .join(latest, latest.c.video_id == Video.video_id)
        .join(ClusterMember, on_niche_join(cluster_id, day))
        .where(Video.published_at.is_not(None), Video.published_at < _until(day))
        .order_by(latest.c.views.desc())
        .limit(TOP_N)
    ).all()
    return [(vid, views, published) for vid, views, published in rows]


def top10_concentration(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Share of the top-100's views held by its top 10. HIGHER IS MORE CONCENTRATED.

    A newcomer competes against the shape of a niche's attention, not only its
    volume. Ten videos holding most of it means the niche has settled winners; a
    flat distribution means attention is still spread and there is room.

    A ratio within the top 100 rather than a share of all cluster views, because
    the denominator would then move with how many videos we happen to have
    collected — a coverage artefact would read as a change in concentration.
    """
    top = _top_videos(session, cluster_id, day)
    if len(top) < 20:
        return FeatureResult.empty(
            GROUP,
            "top10_concentration",
            f"only {len(top)} on-niche videos with views; a top-10 share needs a top",
        )
    views = [v for _, v, _ in top]
    total = sum(views)
    if not total:
        return FeatureResult.empty(GROUP, "top10_concentration", "the top videos have no views")
    return FeatureResult(
        group=GROUP,
        name="top10_concentration",
        value=sum(views[:10]) / total,
        # Confidence is how close we got to a full top-100; a top drawn from 25
        # videos is a weaker description of a niche's shape than one drawn from 100.
        confidence=min(len(top) / TOP_N, 1.0),
        inputs_n=len(top),
        detail={
            "definition": DEFINITION,
            "top_n": TOP_N,
            "videos_ranked": len(top),
            "top10_views": sum(views[:10]),
            "total_views": total,
            "as_of": day.isoformat(),
            "note": "lifetime views, so older videos rank higher; on-niche only",
            "inputs": {"tables": ["cluster_members", "videos", "video_snapshots"]},
        },
    )


def median_top_video_age(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Median age of the niche's biggest videos, in years. HIGHER IS MORE EVERGREEN.

    **NOT REGISTERED. Implemented, measured, and deliberately not shipped** — it is
    structurally censored by how the corpus is collected, and the censoring is
    invisible in the output.

    Measured 2026-08-27: 2,859 of 2,977 on-niche videos are under 90 days old,
    because an RSS feed returns a channel's newest 15 entries and the corpus is one
    day of collection. The metric returned 29-61 days for every niche against a
    corpus whose mean age is 27 days — it was reporting the collection window and
    would have read as "every niche is a news treadmill".

    This is data rule 9 in a new place: "a metric that normalises away the dimension
    you are comparing on comes out flat, and flat reads as a finding rather than as
    a bug". `uploads_per_week` was redefined as a rate over an observed span for
    exactly this reason.

    Register it when the corpus has real age spread — the deferral register carries
    the trigger.

    The evergreen-versus-news proxy, and the closest thing available to the
    `cost_risk` evergreen score without a collector that does not exist. A niche
    whose top videos are years old rewards content that keeps earning; one whose
    top videos are weeks old is a news treadmill.

    Distinct from `openness.winner_age_years`, which is the age of the CHANNELS
    behind those videos. A young channel can hold an old video and an old channel
    can hold a fresh one; the two answer different questions and are kept apart
    deliberately.
    """
    top = _top_videos(session, cluster_id, day)
    if not top:
        return FeatureResult.empty(
            GROUP, "median_top_video_age", "no on-niche video with views and a publish date"
        )
    ages = [(day - published.date()).days / DAYS_PER_YEAR for _, _, published in top]
    return FeatureResult(
        group=GROUP,
        name="median_top_video_age",
        value=float(statistics.median(ages)),
        confidence=min(len(top) / TOP_N, 1.0),
        inputs_n=len(top),
        detail={
            "definition": DEFINITION,
            "top_n": TOP_N,
            "videos_ranked": len(top),
            "youngest_years": round(min(ages), 2),
            "oldest_years": round(max(ages), 2),
            "as_of": day.isoformat(),
            "note": (
                "ranking on LIFETIME views favours older videos, so this "
                "over-states evergreen-ness; it is a floor, not an estimate"
            ),
            "inputs": {"tables": ["cluster_members", "videos", "video_snapshots"]},
        },
    )


#: Weekly snapshots differenced over this many observations. Four weeks matches
#: `WINDOW_DAYS`, so the two supply definitions describe the same span.
FLOW_SNAPSHOTS = 5


def views_per_new_video(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Views accruing per newly published video. The replayable analogue of median_views.

    `median_views` cannot be replayed: YouNiverse holds per-video view counts only
    as of its 2019-10-27 crawl, which is after every decision date, so
    `eligible_videos` correctly excludes all of it and the metric is NULL for every
    historical date — taking `scorecards.supply`, `gap` and `stage` with it. This is
    what lets the backtest compute a supply rank at all.

    Flows are differenced from consecutive **stock** snapshots rather than stored:
    `total_views` and `video_count` are stocks measured when we looked, which is
    ADR-0015's existing reading, so no third meaning of `observed_date` is created.

    A channel-week with no new video is excluded, not counted as zero — a week
    without an upload says nothing about reach per upload (data rule 7).
    """
    members = member_channels(session, cluster_id, day)
    if not members:
        return FeatureResult.empty(GROUP, "views_per_new_video", "cluster has no member channel")

    rows = session.execute(
        sa.select(
            ChannelSnapshot.channel_id,
            ChannelSnapshot.observed_date,
            ChannelSnapshot.total_views,
            ChannelSnapshot.video_count,
        )
        .where(
            ChannelSnapshot.channel_id.in_(members),
            ChannelSnapshot.observed_date <= day,
            ChannelSnapshot.total_views.is_not(None),
            ChannelSnapshot.video_count.is_not(None),
        )
        .order_by(ChannelSnapshot.channel_id, ChannelSnapshot.observed_date)
    ).all()

    series: dict[str, list[tuple[int, int]]] = {}
    for channel_id, _, total_views, video_count in rows:
        series.setdefault(channel_id, []).append((total_views, video_count))

    ratios = []
    for points in series.values():
        window = points[-FLOW_SNAPSHOTS:]
        if len(window) < 2:
            continue
        new_views = window[-1][0] - window[0][0]
        new_videos = window[-1][1] - window[0][1]
        if new_videos > 0 and new_views >= 0:
            ratios.append(new_views / new_videos)
    if not ratios:
        return FeatureResult.empty(
            GROUP,
            "views_per_new_video",
            "no member channel published between two snapshots in the window",
        )
    return FeatureResult(
        group=GROUP,
        name="views_per_new_video",
        value=float(statistics.median(ratios)),
        confidence=min(len(ratios) / len(members), 1.0),
        inputs_n=len(ratios),
        detail={
            "definition": DEFINITION,
            "member_channels": len(members),
            "contributing_channels": len(ratios),
            "snapshots_differenced": FLOW_SNAPSHOTS,
            "as_of": day.isoformat(),
            "note": (
                "delta_views includes back-catalogue traffic, so this OVERSTATES "
                "new-video reach for channels with large catalogues; the backtested "
                "gap built on it is not the live gap"
            ),
            "inputs": {"tables": ["cluster_members", "channel_snapshots"]},
        },
    )
