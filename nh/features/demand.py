"""Demand metrics: does anyone actually want this content?

Level and momentum come from Wikipedia in absolute units; shape corroboration
comes from Trends. See ADR-0015 for why that split, and docs/METRICS.md for what
each number does and does not mean — in particular, pageviews measure
encyclopedic curiosity, not intent to watch a video.
"""

from __future__ import annotations

from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.collectors.trends import window_ratio
from nh.db.models import DemandSeries, DemandSnapshot
from nh.features.inputs import demand_terms
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


def wiki_weekly_views(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Absolute audience attention, as a weekly rate."""
    terms = demand_terms(session, cluster_id, "wikipedia")
    if not terms:
        return FeatureResult.empty(
            GROUP, "wiki_weekly_views", "no wikipedia article mapped to this cluster"
        )
    hi = day - timedelta(days=LAG_DAYS)
    lo = hi - timedelta(days=WINDOW_DAYS)
    points, views = _window(session, terms, lo, hi)
    if not points:
        return FeatureResult.empty(
            GROUP,
            "wiki_weekly_views",
            "no pageview points in window — has the wikipedia collector run?",
            window=[lo.isoformat(), hi.isoformat()],
        )
    return FeatureResult(
        group=GROUP,
        name="wiki_weekly_views",
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
