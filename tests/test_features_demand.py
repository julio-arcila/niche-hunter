"""Demand metrics.

Wikipedia carries level and momentum in absolute units; Trends carries shape.
The tests that matter most here are the ones about *time*: a feature must read
only what was knowable on `day`, or Slice 6's backtest is unsound in a way
nothing downstream could detect.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import sqlalchemy as sa

from nh.db.models import Cluster, DemandSeries, DemandSnapshot, NicheSeed, SeedTerm
from nh.db.session import session_scope
from nh.features.demand import (
    ADEQUATE_VIEWS,
    LAG_DAYS,
    trends_momentum_13w,
    wiki_momentum_28d,
    wiki_seasonality,
    wiki_volatility_365d,
    wiki_weekly_views,
    wiki_yoy,
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


def test_demand_terms_is_per_seed_not_per_cluster(engine):
    """A named blocker for sub-niche discovery (ADR-0018), pinned as a test.

    `demand_terms` joins `clusters.seed_id -> seed_terms.seed_id`, so two clusters
    sharing a seed get an identical article list and therefore an identical
    `wiki_weekly_views`. Today one cluster maps to one seed and this is harmless.
    The moment a seed is split, every sub-cluster's demand becomes the same number
    and `gap` degenerates into a within-seed supply shuffle against a constant.

    This test exists so that lands as a red test rather than as five plausible
    scorecards nobody questions.
    """
    from nh.features.inputs import demand_terms

    _cluster(engine, terms=(("wikipedia", "Aviation_safety"),))
    with session_scope(engine) as s:
        s.add(Cluster(cluster_id="sub-2", seed_id=1, label="B", source="clustering", run_id="t"))
        s.commit()
        first = demand_terms(s, CLUSTER, "wikipedia")
        second = demand_terms(s, "sub-2", "wikipedia")

    assert first == second == ["Aviation_safety"]


# -- the history metrics `stage` needs (Slice 5) -----------------------------


def test_wiki_yoy_compares_the_same_window_a_year_apart(engine):
    """Doubling year on year must read +1.0, not +100 or +0.5."""
    _cluster(engine)
    _views(engine, "Article_A", start_days_ago=2, n=28, per_day=200)
    _views(engine, "Article_A", start_days_ago=367, n=28, per_day=100)

    with session_scope(engine) as s:
        result = wiki_yoy(s, CLUSTER, DAY)

    assert result.value == pytest.approx(1.0)


def test_wiki_yoy_is_null_without_a_prior_year(engine):
    """A year of history is the whole point of the metric; without it there is no
    number to report, and 0.0 would read as "flat"."""
    _cluster(engine)
    _views(engine, "Article_A", start_days_ago=2, n=28, per_day=200)

    with session_scope(engine) as s:
        result = wiki_yoy(s, CLUSTER, DAY)

    assert result.value is None
    assert "last year" in result.detail["reason"]


def test_wiki_yoy_ignores_a_month_over_month_seasonal_dip(engine):
    """The reason this is the stage's axis rather than wiki_momentum_28d. A series
    that is identical in both year-apart windows reads flat, however it moved in
    between."""
    _cluster(engine)
    _views(engine, "Article_A", start_days_ago=2, n=28, per_day=100)
    _views(engine, "Article_A", start_days_ago=40, n=28, per_day=900)  # a spike between
    _views(engine, "Article_A", start_days_ago=367, n=28, per_day=100)

    with session_scope(engine) as s:
        assert wiki_yoy(s, CLUSTER, DAY).value == pytest.approx(0.0)


def test_volatility_is_zero_for_a_perfectly_flat_series(engine):
    _cluster(engine)
    _views(engine, "Article_A", start_days_ago=2, n=364, per_day=100)

    with session_scope(engine) as s:
        result = wiki_volatility_365d(s, CLUSTER, DAY)

    assert result.value == pytest.approx(0.0)
    assert result.confidence == 1.0


def test_volatility_is_scale_free(engine):
    """A niche drawing 300 views a day and one drawing 30,000 must be comparable;
    raw variance would rank them by size."""
    _cluster(engine)
    for i in range(52):
        _views(engine, "Article_A", start_days_ago=2 + i * 7, n=7, per_day=100 * (1 + i % 2))
    with session_scope(engine) as s:
        small = wiki_volatility_365d(s, CLUSTER, DAY).value

    with session_scope(engine) as s:
        s.execute(sa.text("UPDATE demand_snapshots SET value = value * 1000"))
        s.commit()
        large = wiki_volatility_365d(s, CLUSTER, DAY).value

    assert small == pytest.approx(large)


def test_volatility_refuses_too_short_a_series(engine):
    _cluster(engine)
    _views(engine, "Article_A", start_days_ago=2, n=21, per_day=100)

    with session_scope(engine) as s:
        result = wiki_volatility_365d(s, CLUSTER, DAY)

    assert result.value is None
    assert "standard deviation needs more" in result.detail["reason"]


def test_seasonality_needs_all_twelve_months(engine):
    """An annual pattern computed from part of a year is not a weak measurement of
    seasonality, it is not a measurement of seasonality."""
    _cluster(engine)
    _views(engine, "Article_A", start_days_ago=2, n=120, per_day=100)

    with session_scope(engine) as s:
        result = wiki_seasonality(s, CLUSTER, DAY)

    assert result.value is None
    assert "calendar months observed" in result.detail["reason"]


def test_seasonality_confidence_counts_cycles_not_rows(engine):
    """One year of daily data is 365 rows and exactly one cycle. Row count would
    report full confidence in a number that cannot exist yet."""
    _cluster(engine)
    _views(engine, "Article_A", start_days_ago=2, n=364, per_day=100)

    with session_scope(engine) as s:
        result = wiki_seasonality(s, CLUSTER, DAY)

    assert result.inputs_n > 300
    assert result.confidence == pytest.approx(1 / 3, abs=0.02)


def test_seasonality_finds_the_peak_month(engine):
    _cluster(engine)
    _views(engine, "Article_A", start_days_ago=2, n=1095, per_day=100)
    with session_scope(engine) as s:
        s.execute(
            sa.text(
                "UPDATE demand_snapshots SET value = 500 "
                "WHERE CAST(strftime('%m', observed_date) AS INTEGER) = 7"
            )
        )
        s.commit()
        result = wiki_seasonality(s, CLUSTER, DAY)

    assert result.detail["peak_month"] == 7
    assert result.value > 0.1
