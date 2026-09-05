"""The five Keyword Planner metrics.

The house pattern per metric is normal / sparse / empty, and the empty case asserts the
`reason` string as well as the NULL — a metric that returns None for the wrong reason is
still broken.

Two properties get more attention than the rest because they are the ones that would be
wrong silently: the sentinel-bid exclusion is per CELL, and `priced_share`'s zero is a
measurement rather than an absence.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from nh.features import demand, money
from nh.features.inputs import keyword_planner_rows
from nh.features.money import SENTINEL_BIDS
from tests.conftest_features import (
    CLUSTER,
    DAY,
    add_channel,
    add_keyword_metrics,
    make_cluster,
    session_for,
)

BEFORE_ANY_EXPORT = DAY - timedelta(days=3650)


def _world(engine, **kw):
    make_cluster(engine)
    add_keyword_metrics(engine, **kw)
    return session_for(engine)


# --------------------------------------------------------------------------
# The sentinel rule — the property a per-row implementation would get wrong
# --------------------------------------------------------------------------


def test_the_sentinel_set_is_two_exact_literals():
    """Measured values, not a heuristic. A roundness rule would silently discard real
    bids that happen to land on a round number, and nobody would see it happen."""
    assert {64_083.40, 6_408.34} == SENTINEL_BIDS


def test_a_sentinel_low_does_not_discard_its_real_high(engine):
    """The `humanism` GB shape, and the whole reason exclusion is per cell.

    That row carries an imputed 6,408.34 low beside a real 47,045.50 high. Dropping the
    row would throw away a genuine measurement; dropping the cell keeps it.
    """
    s = _world(engine)
    result = money.median_bid_high(s, CLUSTER, DAY, geo="US")

    # 1,100 · 4,043.23 · 27,968.37 · 47,045.50 → median of the middle pair.
    assert result.value == (4_043.23 + 27_968.37) / 2
    assert result.inputs_n == 4, "the real high of a sentinel-low row must be counted"


def test_a_fully_degenerate_row_contributes_nothing(engine):
    """Both cells sentinel: it drops out of both sides on its own, no special case."""
    basket = (
        ("plane crash investigation", 50_000.0, 41, 1_200.0, 27_968.37),
        ("scientific method", 500_000.0, 20, 6_408.34, 6_408.34),
    )
    s = _world(engine, basket=basket)

    priced = money.priced_share(s, CLUSTER, DAY, geo="US")
    median = money.median_bid_high(s, CLUSTER, DAY, geo="US")

    assert priced.value == 0.5, "the degenerate row is observed but not priced"
    assert median.value == 27_968.37 and median.inputs_n == 1


# --------------------------------------------------------------------------
# priced_share — the metric whose zero is a finding
# --------------------------------------------------------------------------


def test_no_advertiser_bids_is_zero_not_null(engine):
    """Keywords observed, none bid on. That is a measurement about the niche, and it is
    only honest because the denominator is day-bounded — before any export the metric
    returns NULL instead (the test below)."""
    basket = (("aviation safety", 500.0, 8, None, None),)
    s = _world(engine, basket=basket)
    result = money.priced_share(s, CLUSTER, DAY, geo="US")

    assert result.value == 0.0
    assert result.confidence > 0.0, "a measured zero carries real confidence"


def test_before_any_export_priced_share_is_null_not_zero(engine):
    """The pair to the test above: the same code path must not report a confident 0.0
    for a day on which no export existed."""
    s = _world(engine)
    result = money.priced_share(s, CLUSTER, BEFORE_ANY_EXPORT, geo="US")

    assert result.value is None and result.confidence == 0.0
    assert "on or before this day" in result.detail["reason"]


# --------------------------------------------------------------------------
# The remaining three, and their empty cases
# --------------------------------------------------------------------------


def test_total_monthly_searches_sums_only_measured_volumes(engine):
    """A keyword the export carried no volume for is absent, never zero — treating it as
    zero would understate a niche for the crime of being unmeasured (data rule 7)."""
    s = _world(engine)
    result = demand.total_monthly_searches(s, CLUSTER, DAY, geo="US")

    assert result.value == 50_000 + 5_000 + 500 + 50_000
    assert result.inputs_n == 4, "the volume-less keyword is excluded, not counted as 0"


def test_volumes_present_but_all_null_is_empty(engine):
    basket = (("air crash analysis", None, 3, 300.0, 1_100.0),)
    s = _world(engine, basket=basket)
    result = demand.total_monthly_searches(s, CLUSTER, DAY, geo="US")

    assert result.value is None
    assert "no volume" in result.detail["reason"]


def test_competition_index_mean_averages_the_raw_index(engine):
    s = _world(engine)
    result = money.competition_index_mean(s, CLUSTER, DAY, geo="US")

    assert result.value == (41 + 12 + 8 + 3 + 55) / 5


def test_vw_cpc_weights_by_volume_and_skips_unusable_keywords(engine):
    """A keyword needs both a real price and a volume; missing either excludes it from
    both sides of the ratio rather than contributing a zero."""
    s = _world(engine)
    result = money.vw_cpc(s, CLUSTER, DAY, geo="US")

    # plane crash (50k, mid 14,584.185) · air traffic (5k, mid 2,471.615) ·
    # humanism (50k, real high alone 47,045.50). Two keywords are unusable.
    expected = (
        50_000 * (1_200.0 + 27_968.37) / 2 + 5_000 * (900.0 + 4_043.23) / 2 + 50_000 * 47_045.50
    ) / 105_000
    assert result.value == expected
    assert result.inputs_n == 3


# --------------------------------------------------------------------------
# Loader properties the metrics all inherit
# --------------------------------------------------------------------------


def test_a_second_export_supersedes_the_first_per_term(engine):
    """`keyword_metrics` is append-only, so a re-export sits beside the old row rather
    than replacing it. The loader must take the newest reading on or before `day`."""
    make_cluster(engine)
    add_keyword_metrics(engine, observed_offset_days=90)
    add_keyword_metrics(
        engine,
        observed_offset_days=10,
        basket=(("plane crash investigation", 500_000.0, 41, 1_200.0, 27_968.37),),
    )
    s = session_for(engine)
    kp = keyword_planner_rows(s, CLUSTER, DAY, "US")

    newest = {r.keyword: r.avg_monthly_searches for r in kp.rows}
    assert newest["plane crash investigation"] == 500_000.0
    assert len(kp.rows) == 5, "one row per keyword, not one per export"


def test_a_market_cannot_see_another_markets_rows(engine):
    """The geo argument resolves the market on the observation (ADR-0038)."""
    make_cluster(engine)
    add_keyword_metrics(engine, geo="GB")
    s = session_for(engine)

    assert keyword_planner_rows(s, CLUSTER, DAY, "US").rows == []
    assert len(keyword_planner_rows(s, CLUSTER, DAY, "GB").rows) == 5


def test_mixed_currencies_refuse_to_average(engine):
    """ADR-0031 forbids inventing an exchange rate, so the honest answer is no answer."""
    make_cluster(engine)
    add_keyword_metrics(engine, basket=(("plane crash investigation", 50_000.0, 41, 1.0, 2.0),))
    add_keyword_metrics(
        engine,
        basket=(("air traffic control", 5_000.0, 12, 3.0, 4.0),),
        currency="USD",
    )
    s = session_for(engine)
    result = money.vw_cpc(s, CLUSTER, DAY, geo="US")

    assert result.value is None
    assert "more than one currency" in result.detail["reason"]
    assert result.detail["currencies"] == ["COP", "USD"]


def test_a_cluster_with_no_keyword_terms_says_so(engine):
    make_cluster(engine)
    s = session_for(engine)
    result = money.vw_cpc(s, CLUSTER, DAY, geo="US")

    assert result.value is None
    assert "no keyword_planner term mapped" in result.detail["reason"]


def test_money_metrics_carry_their_currency_and_market(engine):
    """ADR-0031: a bid figure without its currency is a four-orders-of-magnitude
    misreading waiting to happen, so `detail` must carry both."""
    s = _world(engine)
    for result in (
        money.vw_cpc(s, CLUSTER, DAY, geo="US"),
        money.median_bid_high(s, CLUSTER, DAY, geo="US"),
    ):
        assert result.detail["currency"] == "COP"
        assert result.detail["geo"] == "US"


# --- ADR-0058: confidence decays with the reading's age, values do not move -----------


def test_confidence_is_full_inside_one_refresh_cycle(engine):
    """KP volumes are twelve-month monthly averages, so a reading younger than the
    source's own cadence is not stale in any meaningful sense."""
    from nh.features.inputs import KP_REFRESH_DAYS

    make_cluster(engine)
    add_keyword_metrics(engine, observed_offset_days=KP_REFRESH_DAYS)
    session = session_for(engine)

    at_cycle = money.priced_share(session, CLUSTER, DAY, geo="US").confidence
    fresher = money.priced_share(session, CLUSTER, DAY - timedelta(days=20), geo="US").confidence
    assert at_cycle == pytest.approx(fresher), "no decay inside one cycle"


def test_confidence_decays_linearly_as_the_same_reading_ages(engine):
    """The reading does not change; the day advances. Three times the cadence, one third
    the confidence — unbounded, which is the property that was missing. Without it these
    metrics were exactly as confident on day 400 as on day 1: keyword_metrics held ONE
    observed_date for 35 days and counting, so a frozen input read as a flawless metric
    with a within-cluster variance of exactly 0.0."""
    from nh.features.inputs import KP_REFRESH_DAYS

    make_cluster(engine)
    add_keyword_metrics(engine, observed_offset_days=KP_REFRESH_DAYS)
    session = session_for(engine)

    fresh = money.priced_share(session, CLUSTER, DAY, geo="US")
    stale = money.priced_share(session, CLUSTER, DAY + timedelta(days=60), geo="US")

    assert stale.confidence == pytest.approx(fresh.confidence / 3)


def test_staleness_moves_confidence_and_never_the_value(engine):
    """The whole contract of ADR-0058, across all five KP-sourced metrics. A confidence
    change is honest about what we know; a value change would be a different number
    reported for the same input, which this is emphatically not."""
    from nh.features.demand import total_monthly_searches
    from nh.features.inputs import KP_REFRESH_DAYS

    metrics = (
        money.priced_share,
        money.competition_index_mean,
        money.vw_cpc,
        money.median_bid_high,
        total_monthly_searches,
    )
    make_cluster(engine)
    add_keyword_metrics(engine, observed_offset_days=KP_REFRESH_DAYS)
    session = session_for(engine)
    later = DAY + timedelta(days=KP_REFRESH_DAYS * 5)

    for metric in metrics:
        fresh = metric(session, CLUSTER, DAY, geo="US")
        stale = metric(session, CLUSTER, later, geo="US")
        assert stale.value == fresh.value, f"{fresh.name} changed value on staleness alone"
        assert stale.confidence == pytest.approx(fresh.confidence / 6), fresh.name


def test_midroll_eligible_share_is_not_touched_by_kp_staleness(engine):
    """It lives in money.* but is computed from VIDEOS, not from the export, so it was
    never frozen and must not be discounted for the export's age. The scoping caveat is
    the easy thing to get wrong when the fix is described as 'the money metrics'."""
    from nh.features.inputs import KP_REFRESH_DAYS

    make_cluster(engine)
    add_channel(engine, "long", videos=3, age_days=1, is_short=False)
    add_keyword_metrics(engine, observed_offset_days=KP_REFRESH_DAYS * 10)

    assert money.midroll_eligible_share(session_for(engine), CLUSTER, DAY).confidence > 0
