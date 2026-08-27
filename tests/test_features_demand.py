"""Demand metrics.

Wikipedia carries level and momentum in absolute units; Trends carries shape.
The tests that matter most here are the ones about *time*: a feature must read
only what was knowable on `day`, or Slice 6's backtest is unsound in a way
nothing downstream could detect.
"""

from __future__ import annotations

from datetime import date, timedelta

from nh.db.models import Cluster, DemandSeries, DemandSnapshot, NicheSeed, SeedTerm
from nh.db.session import session_scope
from nh.features.demand import (
    ADEQUATE_VIEWS,
    LAG_DAYS,
    trends_momentum_13w,
    wiki_momentum_28d,
    wiki_weekly_views,
)
from tests.conftest_features import session_for

DAY = date(2026, 8, 27)
CLUSTER = "aviation-disasters"


def _cluster(engine, terms=(("wikipedia", "Article_A"),)):
    with session_scope(engine) as s:
        s.add(NicheSeed(id=1, slug=CLUSTER, label="Aviation", keywords=[]))
        s.flush()  # the seed must exist before rows that reference it
        s.add(Cluster(cluster_id=CLUSTER, seed_id=1, source="clustering", run_id="t"))
        for source, term in terms:
            s.add(SeedTerm(seed_id=1, source=source, term=term, geo="", active=True))


def _views(engine, term, start_days_ago, n, per_day):
    """`n` consecutive days of `per_day` views, ending `start_days_ago` before DAY."""
    with session_scope(engine) as s:
        for i in range(n):
            s.add(
                DemandSnapshot(
                    term=term,
                    geo="",
                    observed_date=DAY - timedelta(days=start_days_ago + i),
                    value=float(per_day),
                    source="wikipedia",
                    run_id="t",
                )
            )


def _series(engine, term, points, observed=DAY):
    with session_scope(engine) as s:
        s.add(
            DemandSeries(
                term=term,
                geo="",
                timeframe="today 5-y",
                observed_date=observed,
                points=points,
                source="trends",
                run_id="t",
            )
        )


# -- level -------------------------------------------------------------------


def test_weekly_views_is_the_window_total_as_a_weekly_rate(engine):
    _cluster(engine)
    _views(engine, "Article_A", LAG_DAYS, 28, 100)  # 2,800 over 28 days
    assert wiki_weekly_views(session_for(engine), CLUSTER, DAY).value == 700.0


def test_articles_are_summed_not_averaged(engine):
    """A niche's attention is the total across its topics, not the mean."""
    _cluster(engine, [("wikipedia", "A"), ("wikipedia", "B")])
    _views(engine, "A", LAG_DAYS, 28, 100)
    _views(engine, "B", LAG_DAYS, 28, 100)
    assert wiki_weekly_views(session_for(engine), CLUSTER, DAY).value == 1400.0


def test_a_cluster_with_no_mapped_article_is_null_not_zero(engine):
    _cluster(engine, terms=())
    result = wiki_weekly_views(session_for(engine), CLUSTER, DAY)
    assert result.value is None
    assert "no wikipedia article mapped" in result.detail["reason"]


def test_days_inside_the_maturation_lag_are_excluded(engine):
    """Counts younger than two days are still maturing at the API, and snapshots
    are first-write-wins — reading them would freeze an undercount forever."""
    _cluster(engine)
    _views(engine, "Article_A", 0, 2, 1_000_000)  # today and yesterday only
    assert wiki_weekly_views(session_for(engine), CLUSTER, DAY).value is None


def test_a_feature_never_reads_days_after_the_day_it_is_asked_about(engine):
    """The anti-leakage property Slice 6's replay depends on."""
    _cluster(engine)
    _views(engine, "Article_A", LAG_DAYS, 28, 100)
    past = wiki_weekly_views(session_for(engine), CLUSTER, DAY - timedelta(days=60))
    assert past.value is None


# -- confidence --------------------------------------------------------------


def test_confidence_falls_when_counts_are_too_small_to_be_stable(engine):
    """Corporate_scandal draws ~3 views a day, where sampling noise is ~10% and
    any momentum built on it is noise. Coverage alone would report 1.00."""
    _cluster(engine)
    _views(engine, "Article_A", LAG_DAYS, 28, 3)
    result = wiki_weekly_views(session_for(engine), CLUSTER, DAY)
    assert result.confidence < 0.02


def test_a_high_volume_niche_reaches_full_confidence(engine):
    _cluster(engine)
    _views(engine, "Article_A", LAG_DAYS, 28, ADEQUATE_VIEWS)
    assert wiki_weekly_views(session_for(engine), CLUSTER, DAY).confidence == 1.0


def test_missing_days_lower_confidence(engine):
    _cluster(engine)
    _views(engine, "Article_A", LAG_DAYS, 14, ADEQUATE_VIEWS)  # half the window
    assert wiki_weekly_views(session_for(engine), CLUSTER, DAY).confidence == 0.5


# -- momentum ----------------------------------------------------------------


def test_momentum_compares_adjacent_windows(engine):
    _cluster(engine)
    _views(engine, "Article_A", LAG_DAYS, 28, 200)  # recent
    _views(engine, "Article_A", LAG_DAYS + 28, 28, 100)  # prior
    assert wiki_momentum_28d(session_for(engine), CLUSTER, DAY).value == 1.0


def test_momentum_is_scale_free(engine):
    """The 590x level spread must not leak into the trend."""
    _cluster(engine)
    _views(engine, "Article_A", LAG_DAYS, 28, 2_000_000)
    _views(engine, "Article_A", LAG_DAYS + 28, 28, 1_000_000)
    assert wiki_momentum_28d(session_for(engine), CLUSTER, DAY).value == 1.0


def test_an_empty_prior_window_is_null_not_an_infinity(engine):
    _cluster(engine)
    _views(engine, "Article_A", LAG_DAYS, 28, 100)
    result = wiki_momentum_28d(session_for(engine), CLUSTER, DAY)
    assert result.value is None
    assert "infinity" in result.detail["reason"]


def test_momentum_confidence_is_bounded_by_the_worse_window(engine):
    _cluster(engine)
    _views(engine, "Article_A", LAG_DAYS, 28, ADEQUATE_VIEWS)  # strong
    _views(engine, "Article_A", LAG_DAYS + 28, 28, 10)  # weak
    assert wiki_momentum_28d(session_for(engine), CLUSTER, DAY).confidence < 0.05


# -- trends shape ------------------------------------------------------------


def _flat_then_double(n=13):
    days = [(date(2026, 1, 1) + timedelta(weeks=i)).isoformat() for i in range(n * 2)]
    return [[d, 10.0] for d in days[:n]] + [[d, 20.0] for d in days[n:]]


def test_trends_momentum_reads_shape_from_one_series(engine):
    _cluster(engine, [("trends", "plane crash")])
    _series(engine, "plane crash", _flat_then_double())
    assert trends_momentum_13w(session_for(engine), CLUSTER, DAY).value == 1.0


def test_trends_momentum_is_scale_invariant(engine):
    """Per-request normalisation makes Trends LEVELS incomparable, which is
    harmless here: this never compares two requests, only two windows in one."""
    _cluster(engine, [("trends", "plane crash")])
    scaled = [[d, v * 7] for d, v in _flat_then_double()]
    _series(engine, "plane crash", scaled)
    assert trends_momentum_13w(session_for(engine), CLUSTER, DAY).value == 1.0


def test_a_mostly_zero_series_reports_near_zero_confidence(engine):
    """A term at Trends' integer quantisation floor produces a ratio that is
    noise, however many points it has."""
    _cluster(engine, [("trends", "bridge collapse")])
    points = _flat_then_double()
    points = [[d, 0.0] for d, _ in points[:20]] + points[20:]
    _series(engine, "bridge collapse", points)
    assert trends_momentum_13w(session_for(engine), CLUSTER, DAY).confidence < 0.35


def test_a_series_observed_after_the_day_is_invisible(engine):
    """A replay of a historical date must not see an observation made later."""
    _cluster(engine, [("trends", "plane crash")])
    _series(engine, "plane crash", _flat_then_double(), observed=DAY + timedelta(days=5))
    assert trends_momentum_13w(session_for(engine), CLUSTER, DAY).value is None


def test_points_after_the_day_are_dropped_even_inside_a_stored_row(engine):
    """The stored curve may extend past `day`; the metric must truncate it."""
    _cluster(engine, [("trends", "plane crash")])
    points = _flat_then_double()
    points.append([(DAY + timedelta(days=7)).isoformat(), 999.0])
    _series(engine, "plane crash", points, observed=DAY)
    assert trends_momentum_13w(session_for(engine), CLUSTER, DAY).value == 1.0
