"""Demand metrics: does anyone actually want this content?

Level and momentum come from Wikipedia in absolute units; shape corroboration
comes from Trends. See ADR-0015 for why that split, and docs/METRICS.md for what
each number does and does not mean — in particular, pageviews measure
encyclopedic curiosity, not intent to watch a video.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise
from math import log
from statistics import stdev

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.collectors.trends import window_ratio
from nh.db.models import DemandSeries, DemandSnapshot
from nh.features.inputs import KP_ADEQUATE_KEYWORDS, demand_terms, keyword_planner_rows
from nh.features.types import FeatureResult

GROUP = "demand"
WINDOW_DAYS = 28
#: Must match the collector's wiki_lag_days: counts younger than this are still
#: maturing at the API, and a snapshot is first-write-wins.
LAG_DAYS = 2
#: Views at which relative sampling noise (~1/sqrt(N)) falls to about 1%.
#: Corporate_scandal draws ~3 views a day, where that noise is ~10% and any
#: momentum built on it is noise.
ADEQUATE_VIEWS = 10_000
TRENDS_WINDOW = 13


def _window(session: Session, terms: list[str], lo: date, hi: date) -> tuple[int, float]:
    points, total = session.execute(
        sa.select(
            sa.func.count(),
            sa.func.coalesce(sa.func.sum(DemandSnapshot.value), 0.0),
        ).where(
            DemandSnapshot.term.in_(terms),
            DemandSnapshot.source == "wikipedia",
            DemandSnapshot.value.is_not(None),
            DemandSnapshot.observed_date > lo,
            DemandSnapshot.observed_date <= hi,
        )
    ).one()
    return points, float(total)


def _adequacy(points: int, expected: int, views: float) -> float:
    """Coverage times volume adequacy.

    Coverage alone pins at 1.00 for every niche once the backfill completes and
    proves nothing. What makes this metric lie at the bottom of the range is count
    scarcity, so both have to be in the number.
    """
    coverage = min(points / expected, 1.0) if expected else 0.0
    return coverage * min(views / ADEQUATE_VIEWS, 1.0)


def wiki_weekly_views(
    session: Session, cluster_id: str, day: date, stratum: str = "topic"
) -> FeatureResult:
    """Absolute audience attention, as a weekly rate."""
    name = _named("wiki_weekly_views", stratum)
    terms = demand_terms(session, cluster_id, "wikipedia", stratum)
    if not terms:
        return FeatureResult.empty(GROUP, name, "no wikipedia article mapped to this cluster")
    hi = day - timedelta(days=LAG_DAYS)
    lo = hi - timedelta(days=WINDOW_DAYS)
    points, views = _window(session, terms, lo, hi)
    if not points:
        return FeatureResult.empty(
            GROUP,
            name,
            "no pageview points in window — has the wikipedia collector run?",
            window=[lo.isoformat(), hi.isoformat()],
        )
    return FeatureResult(
        group=GROUP,
        name=name,
        value=views / (WINDOW_DAYS / 7),
        confidence=_adequacy(points, WINDOW_DAYS * len(terms), views),
        inputs_n=points,
        detail={
            "articles": terms,
            "window": [lo.isoformat(), hi.isoformat()],
            "window_views": views,
            "lag_days": LAG_DAYS,
            "note": "agent=user pageviews; encyclopedic attention, not watch intent",
            "inputs": {"tables": ["demand_snapshots", "seed_terms"]},
        },
    )


def wiki_momentum_28d(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Adjacent 28-day windows, so the level spread does not leak into the trend."""
    terms = demand_terms(session, cluster_id, "wikipedia")
    if not terms:
        return FeatureResult.empty(
            GROUP, "wiki_momentum_28d", "no wikipedia article mapped to this cluster"
        )
    hi = day - timedelta(days=LAG_DAYS)
    mid = hi - timedelta(days=WINDOW_DAYS)
    lo = mid - timedelta(days=WINDOW_DAYS)
    recent_n, recent = _window(session, terms, mid, hi)
    prior_n, prior = _window(session, terms, lo, mid)
    if not prior:
        return FeatureResult.empty(
            GROUP,
            "wiki_momentum_28d",
            "prior window has no views — a ratio would be an infinity, not a number",
            window=[lo.isoformat(), hi.isoformat()],
        )
    expected = WINDOW_DAYS * len(terms)
    return FeatureResult(
        group=GROUP,
        name="wiki_momentum_28d",
        value=recent / prior - 1,
        # A momentum figure is only as good as its worse window.
        confidence=min(_adequacy(recent_n, expected, recent), _adequacy(prior_n, expected, prior)),
        inputs_n=recent_n + prior_n,
        detail={
            "articles": terms,
            "recent_window": [mid.isoformat(), hi.isoformat()],
            "prior_window": [lo.isoformat(), mid.isoformat()],
            "recent_views": recent,
            "prior_views": prior,
            "note": "a single news spike in either window swamps the ratio",
            "inputs": {"tables": ["demand_snapshots", "seed_terms"]},
        },
    )


def trends_momentum_13w(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Search-interest shape, from the newest series observed on or before `day`."""
    terms = demand_terms(session, cluster_id, "trends")
    if not terms:
        return FeatureResult.empty(
            GROUP, "trends_momentum_13w", "no trends term mapped to this cluster"
        )
    row = session.scalars(
        sa.select(DemandSeries)
        .where(
            DemandSeries.term.in_(terms),
            DemandSeries.source == "trends",
            DemandSeries.observed_date <= day,
        )
        .order_by(DemandSeries.observed_date.desc())
        .limit(1)
    ).first()
    if row is None:
        return FeatureResult.empty(
            GROUP, "trends_momentum_13w", "no trends series observed on or before this day"
        )
    value, non_zero = window_ratio(row.points, day, TRENDS_WINDOW)
    if value is None:
        return FeatureResult.empty(
            GROUP,
            "trends_momentum_13w",
            "series too short, or the prior window is all zero — at the quantisation floor",
            term=row.term,
            observed_date=row.observed_date.isoformat(),
        )
    return FeatureResult(
        group=GROUP,
        name="trends_momentum_13w",
        value=value,
        # A mostly-zero series sits at Trends' integer quantisation floor and its
        # ratio is noise, however many points it has.
        confidence=non_zero / (TRENDS_WINDOW * 2),
        inputs_n=TRENDS_WINDOW * 2,
        detail={
            "term": row.term,
            "series_observed": row.observed_date.isoformat(),
            "non_zero_points": non_zero,
            "note": "shape only — Trends levels are not comparable across requests",
            "inputs": {"tables": ["demand_series", "seed_terms"]},
        },
    )


def _named(base: str, stratum: str) -> str:
    """`wiki_weekly_views` for the topic stratum, `wiki_weekly_views_event` otherwise.

    The default stratum keeps the bare name so the series stored since Slice 3 stays
    one continuous, comparable thing. A renamed metric would look like a gap in the
    history rather than a second measurement beside it.
    """
    return base if stratum == "topic" else f"{base}_{stratum}"


def _daily_series(session: Session, terms: list[str], lo: date, hi: date) -> list[float]:
    """Cluster-total views per day over `(lo, hi]`, in date order.

    Summed across the niche's articles per day, not per article: a niche's demand
    is what its whole basket draws, and a per-article series would be dominated by
    whichever article is largest.
    """
    rows = session.execute(
        sa.select(DemandSnapshot.observed_date, sa.func.sum(DemandSnapshot.value))
        .where(
            DemandSnapshot.term.in_(terms),
            DemandSnapshot.source == "wikipedia",
            DemandSnapshot.value.is_not(None),
            DemandSnapshot.observed_date > lo,
            DemandSnapshot.observed_date <= hi,
        )
        .group_by(DemandSnapshot.observed_date)
        .order_by(DemandSnapshot.observed_date)
    ).all()
    return [float(total) for _, total in rows]


def wiki_yoy(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """This 28-day window against the same window a year ago. The stage's momentum axis.

    Year-over-year rather than month-over-month, and the reason is written into
    `wiki_momentum_28d`'s own entry: court-cases measured -31% month-over-month in
    late August, which is plausibly the school calendar rather than decay. A
    year-apart comparison is immune to annual seasonality by construction, which is
    what makes it safe to hand to a classifier. `wiki_momentum_28d` stays as
    evidence; it is not a decision input.
    """
    terms = demand_terms(session, cluster_id, "wikipedia")
    if not terms:
        return FeatureResult.empty(GROUP, "wiki_yoy", "no wikipedia terms mapped for this seed")
    end = day - timedelta(days=LAG_DAYS)
    now_points, now_views = _window(session, terms, end - timedelta(days=WINDOW_DAYS), end)
    then_end = end - timedelta(days=365)
    ago_points, ago_views = _window(
        session, terms, then_end - timedelta(days=WINDOW_DAYS), then_end
    )
    if not ago_views:
        return FeatureResult.empty(
            GROUP,
            "wiki_yoy",
            "no views in the same window last year — a year of history is the whole point",
            window_days=WINDOW_DAYS,
        )
    expected = WINDOW_DAYS * len(terms)
    return FeatureResult(
        group=GROUP,
        name="wiki_yoy",
        value=now_views / ago_views - 1,
        # The weaker of the two windows bounds the ratio, as in wiki_momentum_28d.
        confidence=min(
            _adequacy(now_points, expected, now_views), _adequacy(ago_points, expected, ago_views)
        ),
        inputs_n=now_points + ago_points,
        detail={
            "window_days": WINDOW_DAYS,
            "views_now": now_views,
            "views_year_ago": ago_views,
            "terms": len(terms),
            "as_of": end.isoformat(),
            "note": "immune to annual seasonality by construction; a news spike in either window still moves it",
            "inputs": {"tables": ["demand_snapshots", "seed_terms", "clusters"]},
        },
    )


def wiki_volatility_365d(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """How jumpy the demand series is — standard deviation of weekly log changes.

    Log changes rather than raw differences so the number is scale-free: a niche
    drawing 300 views a day and one drawing 30,000 are comparable, which raw
    variance would not be. Weekly rather than daily because Wikipedia traffic has a
    strong day-of-week cycle that would otherwise dominate and measure the calendar
    rather than the niche.

    This is the false-positive check INSIGHT_RULES Rule 7 asks for: a demand spike
    in a volatile series is a Tuesday, and in a quiet one it is news.
    """
    terms = demand_terms(session, cluster_id, "wikipedia")
    if not terms:
        return FeatureResult.empty(
            GROUP, "wiki_volatility_365d", "no wikipedia terms mapped for this seed"
        )
    end = day - timedelta(days=LAG_DAYS)
    daily = _daily_series(session, terms, end - timedelta(days=365), end)
    weeks = [sum(daily[i : i + 7]) for i in range(0, len(daily) - 6, 7)]
    changes = [
        log(later / earlier) for earlier, later in pairwise(weeks) if earlier > 0 and later > 0
    ]
    if len(changes) < 8:
        return FeatureResult.empty(
            GROUP,
            "wiki_volatility_365d",
            f"only {len(changes)} usable weekly changes; a standard deviation needs more",
        )
    return FeatureResult(
        group=GROUP,
        name="wiki_volatility_365d",
        value=float(stdev(changes)),
        # 52 weeks is the full year this metric claims to describe.
        confidence=min(len(changes) / 51, 1.0),
        inputs_n=len(changes),
        detail={
            "weeks_observed": len(weeks),
            "usable_changes": len(changes),
            "as_of": end.isoformat(),
            "note": "sd of week-over-week log change; scale-free, so comparable across niches",
            "inputs": {"tables": ["demand_snapshots", "seed_terms", "clusters"]},
        },
    )


#: Full annual cycles wanted before a seasonal index is worth reading. Three is the
#: bare minimum — one cycle cannot separate season from trend, two cannot tell a
#: repeating pattern from a coincidence — and three is what the backfill provides.
SEASON_CYCLES = 3


def wiki_seasonality(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """How much of a niche's demand is the calendar. Spread of the month-of-year index.

    Each calendar month gets an index: its mean daily views over all observed years
    divided by the overall mean. The metric is the standard deviation of those
    twelve, so it is scale-free and reads as "typical monthly deviation from the
    annual average".

    This is the false-positive check INSIGHT_RULES Rule 4 asks for — a September
    upload spike against a September demand peak is the school calendar, not a
    niche heating up — and it is the reason `wiki_momentum_28d` carries a warning
    not to be read as a trend.

    `confidence` keys on **cycles observed**, not on row count. A metric about an
    annual pattern computed from eight months of data would otherwise report full
    confidence in a number that cannot exist.
    """
    terms = demand_terms(session, cluster_id, "wikipedia")
    if not terms:
        return FeatureResult.empty(
            GROUP, "wiki_seasonality", "no wikipedia terms mapped for this seed"
        )
    end = day - timedelta(days=LAG_DAYS)
    rows = session.execute(
        sa.select(DemandSnapshot.observed_date, sa.func.sum(DemandSnapshot.value))
        .where(
            DemandSnapshot.term.in_(terms),
            DemandSnapshot.source == "wikipedia",
            DemandSnapshot.value.is_not(None),
            DemandSnapshot.observed_date <= end,
        )
        .group_by(DemandSnapshot.observed_date)
    ).all()
    if not rows:
        return FeatureResult.empty(GROUP, "wiki_seasonality", "no demand history for this seed")

    by_month: dict[int, list[float]] = {}
    for observed, total in rows:
        by_month.setdefault(observed.month, []).append(float(total))
    if len(by_month) < 12:
        return FeatureResult.empty(
            GROUP,
            "wiki_seasonality",
            f"only {len(by_month)} of 12 calendar months observed",
            months_observed=len(by_month),
        )
    overall = sum(total for _, total in rows) / len(rows)
    if not overall:
        return FeatureResult.empty(GROUP, "wiki_seasonality", "no views in the observed history")
    index = {month: (sum(v) / len(v)) / overall for month, v in by_month.items()}
    cycles = len(rows) / 365.25
    return FeatureResult(
        group=GROUP,
        name="wiki_seasonality",
        value=float(stdev(index.values())),
        confidence=min(cycles / SEASON_CYCLES, 1.0),
        inputs_n=len(rows),
        detail={
            "cycles_observed": round(cycles, 2),
            "cycles_wanted": SEASON_CYCLES,
            "peak_month": max(index, key=index.get),
            "trough_month": min(index, key=index.get),
            "month_index": {m: round(v, 3) for m, v in sorted(index.items())},
            "as_of": end.isoformat(),
            "inputs": {"tables": ["demand_snapshots", "seed_terms", "clusters"]},
        },
    )


def total_monthly_searches(
    session: Session, cluster_id: str, day: date, *, geo: str
) -> FeatureResult:
    """Absolute search volume across the niche's curated keywords, in one market.

    The first absolute demand figure this project has that is not Wikipedia pageviews —
    and the first that is scoped to a country rather than to a language (ADR-0035).

    Every value is a power-of-ten bucket MIDPOINT, not a count: measured 2026-08-28, a
    zero-spend export takes only six distinct values across 152 priced rows. So this is
    order-of-magnitude arithmetic and nothing downstream may de-bucket it. A keyword the
    export carried no volume for is absent, never zero — 10 of 162 live rows are NULL,
    and treating them as zero would understate a niche for the crime of being unmeasured.
    """
    kp = keyword_planner_rows(session, cluster_id, day, geo)
    if not kp.rows:
        reason = (
            "no keyword_planner term mapped to this cluster"
            if not kp.curated
            else f"no Keyword Planner reading for geo {geo!r} on or before this day"
        )
        return FeatureResult.empty(GROUP, "total_monthly_searches", reason, geo=geo)

    volumes = [r.avg_monthly_searches for r in kp.rows if r.avg_monthly_searches is not None]
    if not volumes:
        return FeatureResult.empty(
            GROUP,
            "total_monthly_searches",
            "keywords observed but the export carried no volume for any of them",
            geo=geo,
            keywords_observed=len(kp.rows),
        )
    coverage = min(len(kp.rows) / kp.curated, 1.0) if kp.curated else 0.0
    return FeatureResult(
        group=GROUP,
        name="total_monthly_searches",
        value=sum(volumes),
        confidence=coverage * min(len(volumes) / KP_ADEQUATE_KEYWORDS, 1.0),
        inputs_n=len(volumes),
        detail={
            "geo": geo,
            "keywords_with_volume": len(volumes),
            "curated": kp.curated,
            "window": (
                [kp.rows[0].period_start.isoformat(), kp.rows[0].observed_date.isoformat()]
                if kp.rows[0].period_start
                else None
            ),
            "note": "power-of-ten bucket midpoints; order-of-magnitude at best, never de-bucket",
            "inputs": {"tables": ["keyword_metrics", "seed_terms"]},
        },
    )
