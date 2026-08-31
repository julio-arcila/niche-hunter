"""Every displayed number, back to the rows it came from.

This is Slice 7's exit criterion in executable form. The criterion — "every displayed
number reaches its input rows" — is the kind of promise a UI can appear to keep while
linking to a plausible-looking query nobody checked, so it is a registry with a test
rather than a convention.

**Grouped by input SHAPE, not one function per metric.** Twenty-odd bespoke queries would
drift from the twenty-odd feature queries they mirror, and a drilldown that returns the
wrong rows is worse than none: it is a wrong answer wearing an audit trail. Six shapes
cover every registered metric, and each reuses the same `features.inputs` helpers the
metric itself used — `demand_terms`, `keyword_planner_rows`, `member_channels`,
`on_niche_join` — so the two cannot disagree about what the population was.

What comes back is rows, not a rendering: `(headers, rows)`, so the caller decides.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import (
    Channel,
    ChannelSnapshot,
    ClusterMember,
    DemandSeries,
    DemandSnapshot,
    FeatureDaily,
    KeywordMetric,
    Video,
    VideoSnapshot,
)
from nh.features.inputs import (
    demand_terms,
    member_channels,
    on_niche_join,
)

#: How many rows a drilldown returns. A drilldown is for checking a number, not for
#: exporting a corpus — 200 rows is enough to see the shape and the outliers, and the
#: metric's own `inputs_n` is what states the true count.
LIMIT = 200

Rows = tuple[list[str], list[tuple]]


def _wikipedia(session: Session, cluster_id: str, day: date) -> Rows:
    """The article-day readings behind every `wiki_*` metric."""
    articles = demand_terms(session, cluster_id, "wikipedia")
    if not articles:
        return ["article", "date", "views"], []
    rows = session.execute(
        sa.select(DemandSnapshot.term, DemandSnapshot.observed_date, DemandSnapshot.value)
        .where(
            DemandSnapshot.source == "wikipedia",
            DemandSnapshot.term.in_(articles),
            DemandSnapshot.observed_date <= day,
        )
        .order_by(DemandSnapshot.observed_date.desc(), DemandSnapshot.term)
        .limit(LIMIT)
    ).all()
    return ["article", "date", "views"], [tuple(r) for r in rows]


def _trends(session: Session, cluster_id: str, day: date) -> Rows:
    """One row per fetched CURVE, not per point.

    That is the shape of the table and the shape of the truth: Trends renormalises every
    response to its own peak, so points cannot be appended across fetches and the honest
    unit of observation is the whole curve as seen on a date (ADR-0015). A drilldown that
    flattened `points` into rows would present a series that was never observed as one.
    """
    terms = demand_terms(session, cluster_id, "trends")
    if not terms:
        return ["term", "geo", "timeframe", "observed", "points", "latest"], []
    rows = session.execute(
        sa.select(
            DemandSeries.term,
            DemandSeries.geo,
            DemandSeries.timeframe,
            DemandSeries.observed_date,
            DemandSeries.points,
        )
        .where(DemandSeries.term.in_(terms), DemandSeries.observed_date <= day)
        .order_by(DemandSeries.observed_date.desc(), DemandSeries.term)
        .limit(LIMIT)
    ).all()
    return (
        ["term", "geo", "timeframe", "observed", "points", "latest"],
        [
            (term, geo, timeframe, observed, len(points or []), (points or [[None, None]])[-1][1])
            for term, geo, timeframe, observed, points in rows
        ],
    )


def _keyword_planner(session: Session, cluster_id: str, day: date) -> Rows:
    """Every KP reading the cluster's curated terms have, in any market.

    Deliberately not filtered to one geo, unlike the metric. The metric must name a market
    (ADR-0038); a reader checking the metric benefits from seeing that a second market
    exists and differs — `reports/geo_value_2026-08-28.md` measured the value ranking
    reordering between US and GB, which is invisible from a single-market view.
    `file_sha256` is included because it is the link on to `raw_records`, i.e. to the bytes
    Google returned.
    """
    # Two steps rather than one join: "this cluster's curated terms" resolves through
    # `clusters.seed_id`, which `demand_terms` already owns. A third join path here could
    # disagree with the feature layer's about which terms belong to the niche, and a
    # drilldown that disagrees with its metric is worse than no drilldown — it is a wrong
    # answer wearing an audit trail.
    terms = [t.lower() for t in demand_terms(session, cluster_id, "keyword_planner")]
    if not terms:
        return ["keyword", "geo", "period end", "searches", "competition", "bid", "sha"], []
    rows = session.execute(
        sa.select(
            KeywordMetric.keyword,
            KeywordMetric.geo,
            KeywordMetric.observed_date,
            KeywordMetric.avg_monthly_searches,
            KeywordMetric.competition_index,
            KeywordMetric.bid_high,
            KeywordMetric.currency,
            KeywordMetric.file_sha256,
        )
        .where(
            sa.func.lower(KeywordMetric.keyword).in_(terms),
            KeywordMetric.observed_date <= day,
        )
        .order_by(KeywordMetric.observed_date.desc(), KeywordMetric.keyword)
        .limit(LIMIT)
    ).all()
    return (
        ["keyword", "geo", "period end", "searches", "competition", "bid high", "cur", "sha"],
        [tuple(r) for r in rows],
    )


def _on_niche_videos(session: Session, cluster_id: str, day: date) -> Rows:
    """The videos every supply and `money.midroll_eligible_share` number is computed over."""
    latest = (
        sa.select(VideoSnapshot.video_id, sa.func.max(VideoSnapshot.views).label("views"))
        .where(VideoSnapshot.observed_date <= day)
        .group_by(VideoSnapshot.video_id)
        .subquery()
    )
    rows = session.execute(
        sa.select(
            Video.video_id,
            Video.channel_id,
            Video.title,
            Video.published_at,
            Video.is_short,
            latest.c.views,
            ClusterMember.relevance,
        )
        .join(ClusterMember, on_niche_join(cluster_id, day))
        .outerjoin(latest, latest.c.video_id == Video.video_id)
        .order_by(Video.published_at.desc())
        .limit(LIMIT)
    ).all()
    return (
        ["video", "channel", "title", "published", "short", "views", "relevance"],
        [tuple(r) for r in rows],
    )


def _member_channels(session: Session, cluster_id: str, day: date) -> Rows:
    """The channel population behind `openness.*` and `supply.geo_concentration`.

    Through `member_channels`, so a channel this view shows is a channel the metric
    counted — including ADR-0047's ballast exclusion, and including its reversal on the
    sunset. A second membership query here would be a second answer to the question
    `supply._confidence`'s clamp comment already calls a bug when the two disagree.
    """
    members = member_channels(session, cluster_id, day)
    if not members:
        return ["channel", "title", "country", "created", "subs"], []
    latest = (
        sa.select(ChannelSnapshot.channel_id, sa.func.max(ChannelSnapshot.subs).label("subs"))
        .where(ChannelSnapshot.observed_date <= day)
        .group_by(ChannelSnapshot.channel_id)
        .subquery()
    )
    rows = session.execute(
        sa.select(
            Channel.channel_id, Channel.title, Channel.country, Channel.created_at, latest.c.subs
        )
        .outerjoin(latest, latest.c.channel_id == Channel.channel_id)
        .where(Channel.channel_id.in_(members))
        .order_by(latest.c.subs.desc().nullslast())
        .limit(LIMIT)
    ).all()
    return ["channel", "title", "country", "created", "subs"], [tuple(r) for r in rows]


def _ranked_metrics(session: Session, cluster_id: str, day: date) -> Rows:
    """`pressure_index` is a rank across the day's clusters, so its inputs are other rows.

    Every cluster's value for each component, because a rank is not checkable from one
    cluster's row — which is also why `detail.ranked_over` exists and why the metric warns
    it is not comparable across days whose cluster set changed.
    """
    from nh.features.run import PRESSURE_FROM

    rows = session.execute(
        sa.select(
            FeatureDaily.cluster_id, FeatureDaily.name, FeatureDaily.value, FeatureDaily.confidence
        )
        .where(FeatureDaily.day == day, FeatureDaily.name.in_(PRESSURE_FROM))
        .order_by(FeatureDaily.name, FeatureDaily.value.desc())
        .limit(LIMIT)
    ).all()
    return ["cluster", "component", "value", "confidence"], [tuple(r) for r in rows]


Drilldown = Callable[[Session, str, date], Rows]

#: Metric → the query returning its inputs. Exhaustive over `features.run.METRICS` by
#: test: an unregistered metric would render in the UI with no way to check it, which is
#: the one thing this slice promises cannot happen.
REGISTRY: dict[str, Drilldown] = {
    "wiki_weekly_views": _wikipedia,
    "wiki_weekly_views_event": _wikipedia,
    "wiki_momentum_28d": _wikipedia,
    "wiki_yoy": _wikipedia,
    "wiki_volatility_365d": _wikipedia,
    "wiki_seasonality": _wikipedia,
    "trends_momentum_13w": _trends,
    "total_monthly_searches": _keyword_planner,
    "priced_share": _keyword_planner,
    "competition_index_mean": _keyword_planner,
    "vw_cpc": _keyword_planner,
    "median_bid_high": _keyword_planner,
    "uploads_per_week": _on_niche_videos,
    "median_views": _on_niche_videos,
    "on_niche_share": _on_niche_videos,
    "format_mix": _on_niche_videos,
    "top10_concentration": _on_niche_videos,
    "median_top_video_age": _on_niche_videos,
    "midroll_eligible_share": _on_niche_videos,
    "geo_concentration": _member_channels,
    "breakthrough_rate_cohort": _member_channels,
    "views_per_sub": _member_channels,
    "winner_age_years": _member_channels,
    "pressure_index": _ranked_metrics,
}


def rows_behind(session: Session, name: str, cluster_id: str, day: date) -> Rows:
    """The input rows for one metric, or empty headers if it has no drilldown."""
    fn = REGISTRY.get(name)
    if fn is None:
        return [], []
    return fn(session, cluster_id, day)
