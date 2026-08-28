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
    evaluate_partial,
    independent_windows,
    partial_spearman,
    pearson,
    ranks,
    spearman,
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
    """`n` decision dates over the same niche set."""
    clusters = [f"niche-{i}" for i in range(len(scores))]
    return [(f"date-{i:03d}", list(clusters), list(scores), list(outcomes)) for i in range(n)]


def test_a_real_signal_beats_the_permutation_null():
    aggregate, per_date = evaluate(_dates(4, [1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6]), draws=500)

    assert aggregate.rho == pytest.approx(1.0)
    assert aggregate.p_value is not None and aggregate.p_value < 0.01
    assert len(per_date) == 4


def test_noise_does_not():
    """Six niches whose outcome ranks are unrelated to their scores."""
    aggregate, _ = evaluate(_dates(4, [1, 2, 3, 4, 5, 6], [4, 6, 1, 5, 2, 3]), draws=500)

    assert aggregate.p_value > 0.05


def test_repeating_one_date_does_not_multiply_the_evidence():
    """The defect the global permutation exists for. Four weekly copies of a single
    date carry one date's worth of evidence, but a within-date null treats them as
    four independent draws: rho=0.486 comes back at p=0.034, a significant result
    derived from one observation. Permuting niche labels globally preserves each
    niche's trajectory on both sides, so repetition adds no significance."""
    clusters = [f"n{i}" for i in range(6)]
    weekly = [
        (f"2018-01-{i * 7 + 1:02d}", list(clusters), [1, 2, 3, 4, 5, 6], [3, 1, 5, 2, 6, 4])
        for i in range(4)
    ]

    aggregate, _ = evaluate(weekly, spacing_days=7, horizon_days=180, draws=500)

    assert aggregate.dates == 4
    assert aggregate.independent_windows == 1
    assert aggregate.p_value > 0.05


def test_the_null_permutes_the_same_labels_at_every_date():
    """One permutation per replication, not one per date. If each date were permuted
    independently the null would assert the dates are independent replicates and
    shrink the standard error by sqrt(D)."""
    clusters = ["a", "b", "c", "d", "e", "f"]
    scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    # Two dates whose outcomes invert each other: any single global relabelling helps
    # one date exactly as much as it hurts the other, so the aggregate sits at zero
    # and neither date can lend the other significance.
    data = [
        ("d0", list(clusters), list(scores), [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
        ("d1", list(clusters), list(scores), [6.0, 5.0, 4.0, 3.0, 2.0, 1.0]),
    ]

    aggregate, per_date = evaluate(data, draws=300)

    assert per_date[0].rho == pytest.approx(1.0)
    assert per_date[1].rho == pytest.approx(-1.0)
    assert aggregate.rho == pytest.approx(0.0)


def test_the_p_value_never_reports_zero():
    """A p-value of exactly 0 claims more resolution than the draw count supports.
    With `draws` samples the floor is 1/(draws+1)."""
    aggregate, _ = evaluate(_dates(4, [1, 2, 3, 4, 5, 6], [1, 2, 3, 4, 5, 6]), draws=200)

    assert aggregate.p_value >= 1 / 201


def test_the_same_input_gives_the_same_p_value_twice():
    """A verdict that changes between runs cannot be cited in a report."""
    data = _dates(3, [1, 2, 3, 4, 5], [2, 1, 4, 3, 5])

    first, _ = evaluate(data, draws=300)
    second, _ = evaluate(data, draws=300)

    assert first.p_value == second.p_value
    assert (first.ci_low, first.ci_high) == (second.ci_low, second.ci_high)


def test_a_date_whose_correlation_is_undefined_is_skipped_not_zeroed():
    clusters = ["a", "b", "c", "d"]
    data = [
        ("2018-01-01", clusters, [1, 2, 3, 4], [1, 2, 3, 4]),
        ("2018-01-08", clusters, [5, 5, 5, 5], [1, 2, 3, 4]),  # constant scores
    ]

    aggregate, per_date = evaluate(data, draws=200)

    assert per_date[1].rho is None
    assert aggregate.rho == pytest.approx(1.0)  # not 0.5
    assert aggregate.dates == 2


def test_the_confidence_interval_brackets_the_estimate():
    aggregate, _ = evaluate(_dates(3, [1, 2, 3, 4, 5, 6], [1, 3, 2, 5, 4, 6]), draws=500)

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


# --------------------------------------------------------------------------
# The size control (amended 2026-08-28, pre-data)
# --------------------------------------------------------------------------


def _panel(scores, outcomes, sizes, dates=4):
    clusters = [f"n{i}" for i in range(len(scores))]
    return [
        (f"d{d}", list(clusters), list(scores), list(outcomes), list(sizes)) for d in range(dates)
    ]


def test_a_ranking_that_is_really_size_fails_the_control():
    """The falsification this amendment exists for.

    Score is very nearly size, and the outcome is driven by size — so the primary
    correlates beautifully and carries no information of its own. Under the old rule
    the leftover residual was positive and that counted as survival; the amended rule
    asks whether the residual survives the permutation null, and it does not.

    The confound is deliberately imperfect (two ranks swapped). Making score *exactly*
    size is the easier test and the less useful one: the partial is then undefined and
    caught by the NULL branch, which never exercises the p-value at all."""
    sizes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    scores = [1.0, 3.0, 2.0, 4.0, 6.0, 5.0, 7.0, 8.0]
    outcomes = [1.0, 3.0, 2.0, 5.0, 4.0, 6.0, 7.0, 8.0]

    primary, _ = evaluate(
        [(d, c, sc, o) for d, c, sc, o, _ in _panel(scores, outcomes, sizes)], draws=300
    )
    controlled, _ = evaluate_partial(_panel(scores, outcomes, sizes), draws=300)

    assert primary.rho > 0.9  # the ranking looks excellent
    # The residual is POSITIVE (~0.23) and would have passed the old `> 0` check.
    assert controlled.rho > 0
    assert controlled.p_value >= 0.05  # ...and does not survive the control


def test_a_score_that_is_exactly_size_leaves_nothing_to_partial():
    """Perfect collinearity makes the partial undefined, not zero — and `verdict`
    already reads an uncomputable control as FAIL."""
    sizes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

    controlled, _ = evaluate_partial(_panel(sizes, sizes, sizes), draws=100)

    assert controlled.rho is None


def test_a_genuine_ranking_survives_the_control():
    """The other side: a score unrelated to size that still predicts the outcome
    keeps both its residual and its significance."""
    sizes = [5.0, 1.0, 8.0, 3.0, 7.0, 2.0, 6.0, 4.0]
    scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    outcomes = list(scores)

    controlled, _ = evaluate_partial(_panel(scores, outcomes, sizes), draws=300)

    assert controlled.rho > 0.9
    assert controlled.p_value < 0.05


def test_the_control_permutes_outcomes_and_keeps_score_with_size():
    """Size is a property of the niche whose score is on trial, so it stays on the
    score side of the permutation. Determinism is asserted too: a verdict that moves
    between runs cannot be cited."""
    panel = _panel([1.0, 2, 3, 4, 5, 6], [2.0, 1, 4, 3, 6, 5], [3.0, 1, 6, 2, 5, 4])

    first, per_date = evaluate_partial(panel, draws=200)
    second, _ = evaluate_partial(panel, draws=200)

    assert first.p_value == second.p_value
    assert all(r.n == 6 for r in per_date)


def test_an_uncomputable_control_yields_no_verdict():
    panel = _panel([1.0, 1.0, 1.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0])

    controlled, _ = evaluate_partial(panel, draws=100)

    assert controlled.rho is None
    assert controlled.p_value is None
