"""The statistics Gate E is decided on.

These are the only functions in the project whose output *is* the verdict, so they
are checked against an independently-derived oracle rather than against themselves:
for tie-free data Spearman has the closed form `1 - 6*sum(d^2)/(n(n^2-1))`, which
shares no code path with the rank-then-Pearson implementation. Where a closed form
does not exist the expected value is a hand-computed literal.
"""

from __future__ import annotations

import math

import pytest

from nh.backtest.stats import (
    Aggregate,
    evaluate,
    independent_windows,
    partial_spearman,
    pearson,
    ranks,
    spearman,
    thin,
)


def closed_form(xs: list[float], ys: list[float]) -> float:
    """Spearman for tie-free data, derived independently of the implementation."""
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry, strict=True))
    return 1 - 6 * d2 / (n * (n * n - 1))


# --------------------------------------------------------------------------
# Ranks
# --------------------------------------------------------------------------


def test_ties_share_an_averaged_rank():
    """Slice 3 measured 3 of 5 niches gapping at exactly 0. Giving tied niches an
    arbitrary order would let the correlation read that order as signal."""
    assert ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]
    assert ranks([5, 5, 5]) == [2.0, 2.0, 2.0]


def test_ranks_are_positional_not_value_scaled():
    assert ranks([1, 2, 1000]) == [1.0, 2.0, 3.0]


# --------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------


def test_spearman_matches_the_closed_form():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    ys = [2.0, 1.0, 4.0, 3.0, 7.0, 5.0, 6.0]

    assert spearman(xs, ys) == pytest.approx(closed_form(xs, ys))


def test_a_perfect_monotone_relationship_is_one():
    assert spearman([1, 2, 3, 4], [10, 200, 3000, 40000]) == pytest.approx(1.0)


def test_a_perfect_inversion_is_minus_one():
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_a_constant_series_is_none_not_zero():
    """Undefined, not "measured no relationship". Every niche sharing a score on a
    date is a real case, and 0.0 there would be averaged into the aggregate as
    evidence of no effect."""
    assert spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None
    assert pearson([1, 1, 1], [1, 2, 3]) is None


def test_too_few_points_is_none():
    assert spearman([1, 2], [2, 1]) is None


# --------------------------------------------------------------------------
# The size control
# --------------------------------------------------------------------------


def test_a_correlation_driven_entirely_by_size_vanishes_when_size_is_controlled():
    """The pre-registered control. A scorecard that ranks niches by how big they are
    needs no pipeline to reproduce, so this is the difference between a gate that
    passes and one that only looks like it."""
    size = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    score = list(size)
    outcome = list(size)

    assert spearman(score, outcome) == pytest.approx(1.0)
    assert partial_spearman(score, outcome, size) is None  # nothing left to explain


def test_a_genuine_relationship_survives_the_size_control():
    score = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    outcome = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    size = [3.0, 1.0, 6.0, 2.0, 5.0, 4.0]  # unrelated to either

    partial = partial_spearman(score, outcome, size)

    assert partial is not None
    assert partial > 0.9


# --------------------------------------------------------------------------
# Independent windows
# --------------------------------------------------------------------------


def test_overlapping_weekly_dates_are_not_independent_observations():
    """195 weekly dates cover roughly 8 non-overlapping 180-day windows. Quoting 195
    would shrink every interval by about a factor of five."""
    assert independent_windows(195, spacing_days=7, horizon_days=180) == 8
    assert independent_windows(1, spacing_days=7, horizon_days=180) == 1
    assert independent_windows(0, spacing_days=7, horizon_days=180) == 0


def test_independent_windows_is_always_at_most_the_date_count():
    for dates in (1, 5, 26, 195, 500):
        assert independent_windows(dates, 7, 180) <= dates


# --------------------------------------------------------------------------
# evaluate()
# --------------------------------------------------------------------------


def _dates(n: int, scores: list[float], outcomes: list[float]):
    """`n` decision dates. Callers pass `spacing_days=200` so every date exceeds the
    180-day horizon and is therefore an independent observation — otherwise thinning
    would silently reduce the sample and the test would not say what it means."""
    return [(f"date-{i:03d}", list(scores), list(outcomes)) for i in range(n)]


def test_a_real_signal_beats_the_permutation_null():
    aggregate, per_date = evaluate(_dates(4, [1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6]), draws=500)

    assert aggregate.rho == pytest.approx(1.0)
    assert aggregate.p_value is not None and aggregate.p_value < 0.01
    assert len(per_date) == 4


def test_noise_does_not():
    """Six niches whose outcome ranks are unrelated to their scores."""
    aggregate, _ = evaluate(
        _dates(4, [1, 2, 3, 4, 5, 6], [4, 6, 1, 5, 2, 3]), draws=500, spacing_days=200
    )

    assert aggregate.p_value > 0.05


def test_overlapping_dates_do_not_each_count_as_an_observation():
    """The defect this thinning exists for. Four weekly copies of one date carry one
    date's worth of evidence; without thinning the permutation null treats them as
    four draws and a rho of 0.486 comes back at p=0.034 -- a significant result
    derived from a single observation."""
    weekly = [
        (f"2018-01-{i * 7 + 1:02d}", [1, 2, 3, 4, 5, 6], [3, 1, 5, 2, 6, 4]) for i in range(4)
    ]

    aggregate, _ = evaluate(weekly, spacing_days=7, horizon_days=180, draws=500)

    assert aggregate.independent_windows == 1
    assert aggregate.dates == 4
    assert aggregate.p_value > 0.05


def test_thinning_keeps_one_date_per_outcome_window():
    weekly = [(f"d{i}", [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) for i in range(60)]

    kept = thin(weekly, spacing_days=7, horizon_days=180)

    assert [day for day, _, _ in kept] == ["d0", "d26", "d52"]
    assert len(kept) == independent_windows(60, 7, 180)


def test_the_p_value_never_reports_zero():
    """A p-value of exactly 0 claims more resolution than the draw count supports.
    With `draws` samples the floor is 1/(draws+1)."""
    aggregate, _ = evaluate(
        _dates(4, [1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6]), draws=200, spacing_days=200
    )

    assert aggregate.p_value >= 1 / 201


def test_the_same_input_gives_the_same_p_value_twice():
    """A verdict that changes between runs cannot be cited in a report."""
    data = _dates(3, [1, 2, 3, 4, 5], [2, 1, 4, 3, 5])

    first, _ = evaluate(data, draws=300, spacing_days=200)
    second, _ = evaluate(data, draws=300, spacing_days=200)

    assert first.p_value == second.p_value
    assert (first.ci_low, first.ci_high) == (second.ci_low, second.ci_high)


def test_a_date_whose_correlation_is_undefined_is_skipped_not_zeroed():
    data = [
        ("2018-01-01", [1, 2, 3, 4], [1, 2, 3, 4]),
        ("2018-01-08", [5, 5, 5, 5], [1, 2, 3, 4]),  # constant scores
    ]

    aggregate, per_date = evaluate(data, draws=200, spacing_days=200)

    assert per_date[1].rho is None
    assert aggregate.rho == pytest.approx(1.0)  # not 0.5
    assert aggregate.dates == 2


def test_the_confidence_interval_brackets_the_estimate():
    aggregate, _ = evaluate(
        _dates(3, [1, 2, 3, 4, 5, 6], [1, 3, 2, 5, 4, 6]), draws=500, spacing_days=200
    )

    assert aggregate.ci_low <= aggregate.rho <= aggregate.ci_high


def test_detectable_rho_reports_the_power_at_this_n():
    """A null at low N is underpowered, not evidence of no effect — the distinction
    the pre-registration turns on."""
    assert Aggregate(None, None, None, None, 0, 0, 6).detectable_rho == pytest.approx(
        2 / math.sqrt(5)
    )
    assert Aggregate(None, None, None, None, 0, 0, 30).detectable_rho == pytest.approx(
        0.371, abs=1e-3
    )
    assert Aggregate(None, None, None, None, 0, 0, 1).detectable_rho is None


def test_an_empty_run_returns_no_verdict():
    aggregate, per_date = evaluate([], draws=100)

    assert aggregate.rho is None
    assert aggregate.p_value is None
    assert per_date == []
