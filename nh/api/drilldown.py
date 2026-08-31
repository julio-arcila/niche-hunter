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
    RawRecord,
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
    `file_sha256` is the link on to `raw_records`, i.e. to the bytes Google returned — but
    **it is a 12-character PREFIX join, not an equality one**: the collector keys the raw
    row `f"{digest[:12]}:{self.path.name}"` (`keyword_planner.py:236`). An earlier version
    of this docstring said "the link on to `raw_records`" flatly, and the first person to
    try it — the person writing this — matched the full sha and got zero rows. Use
    `raw_source()` below rather than reconstructing the join.
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
    from nh.api.gates import citable
    from nh.features.run import PRESSURE_FROM

    rows = session.execute(
        sa.select(
            FeatureDaily.cluster_id, FeatureDaily.name, FeatureDaily.value, FeatureDaily.confidence
        )
        .where(FeatureDaily.day == day, FeatureDaily.name.in_(PRESSURE_FROM))
        .order_by(FeatureDaily.name, FeatureDaily.value.desc())
        .limit(LIMIT)
    ).all()
    # **Masked per row, and this was a real leak.** `PRESSURE_FROM` is `median_views` and
    # `uploads_per_week` — both gated — so this drilldown served, for all ten unvalidated
    # clusters, the exact values withheld two expanders above it. Found by an independent
    # review 2026-08-31, and it defeats the gate rather than bending it: the inputs to a
    # RANK are other scorer-decided aggregates, so the "observations, not claims" argument
    # that licenses every other drilldown does not reach here.
    #
    # Masked by the ROW's cluster, not the page's: a `philosophy-of-science` page listing
    # `history-of-ideas` values would leak just as well.
    return (
        ["cluster", "component", "value", "confidence"],
        [
            (cluster, name, value, confidence)
            if citable(name, cluster)
            else (cluster, name, "withheld", "withheld")
            for cluster, name, value, confidence in rows
        ],
    )


def raw_source(session: Session, sha: str) -> tuple[str, str] | None:
    """The stored payload a Keyword Planner reading came from: `(key, source)`.

    The last click of the three. `keyword_metrics.file_sha256` is the full digest while
    `raw_records.key` carries only its first twelve characters plus the filename, so this
    exists to stop every caller re-deriving a prefix join and getting it subtly wrong.

    Twelve characters of hex is 48 bits. Collision is not a practical concern at five
    stored exports, and this returns the first match rather than pretending to resolve one
    — a caller that needs certainty has the full digest on the metric row.
    """
    row = session.execute(
        sa.select(RawRecord.key, RawRecord.source)
        .where(RawRecord.kind == "keyword_csv", RawRecord.key.startswith(sha[:12]))
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


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


#: Columns dropped from a gated metric's drilldown. `relevance` is the scorer's per-row
#: judgement, and serving (video, score) pairs for the whole frame is a contamination
#: surface for anyone about to label a validation sample — the repo defends that blinding
#: with three independent guards in `api/reports.py` and then handed it out here, one click
#: from the withheld number, behind a caption asking the reader not to look. Narrowed after
#: the 2026-08-31 review. The rows still answer "what is in this population"; they stop
#: answering "what did the scorer think of each one".
GATED_COLUMNS = ("relevance",)


def rows_behind(
    session: Session, name: str, cluster_id: str, day: date, *, gated: bool | None = None
) -> Rows:
    """The input rows for one metric, or empty headers if it has no drilldown.

    `gated` defaults to asking the gate, so a caller cannot get the wide version by
    forgetting to ask — the same fail-safe direction as `jobs.niche.load`.
    """
    fn = REGISTRY.get(name)
    if fn is None:
        return [], []
    headers, rows = fn(session, cluster_id, day)
    if gated is None:
        from nh.api.gates import citable

        gated = not citable(name, cluster_id)
    if not gated:
        return headers, rows
    keep = [i for i, h in enumerate(headers) if h not in GATED_COLUMNS]
    return [headers[i] for i in keep], [tuple(row[i] for i in keep) for row in rows]
