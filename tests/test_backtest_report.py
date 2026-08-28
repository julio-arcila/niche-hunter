"""The report renderer, and the verdict rule it applies.

The renderer is where the pre-registration stops being a promise: a secondary that
outscores the primary is still labelled secondary, and a null at low N is reported
as inconclusive rather than as a failure. Both are easy to lose to a writer's
judgement on the day, which is why they are tested rather than trusted.
"""

from __future__ import annotations

from datetime import date

from nh.backtest.report import CAVEATS, Findings, Variant, render, verdict
from nh.backtest.stats import Aggregate

DAY = date(2026, 8, 27)


def _aggregate(rho, p, *, n_median=30, dates=195, windows=8):
    return Aggregate(
        rho=rho,
        p_value=p,
        ci_low=None if rho is None else rho - 0.1,
        ci_high=None if rho is None else rho + 0.1,
        dates=dates,
        independent_windows=windows,
        n_median=n_median,
        draws=10_000,
    )


def _variant(rho, p, *, label="gap", n_median=30):
    return Variant(
        label=label,
        stratum="topic",
        supply_from="views_per_new_video",
        threshold=0.55,
        horizon_days=180,
        aggregate=_aggregate(rho, p, n_median=n_median),
    )


def _findings(rho, p, *, selected=30, size_controlled=0.3, **kw):
    return Findings(
        day=DAY,
        primary=_variant(rho, p, n_median=selected),
        niches_selected=selected,
        niches_committed=36,
        size_rho=0.1,
        size_controlled_rho=size_controlled,
        **kw,
    )


# --------------------------------------------------------------------------
# The verdict rule
# --------------------------------------------------------------------------


def test_a_real_positive_result_that_survives_the_size_control_passes():
    label, reason = verdict(_findings(0.42, 0.002))

    assert label == "PASS"
    assert "0.42" in reason


def test_a_null_fails():
    label, _ = verdict(_findings(0.05, 0.61))

    assert label == "FAIL"


def test_a_correlation_that_vanishes_under_the_size_control_fails():
    """A scorecard that ranks niches by how big they are needs no pipeline."""
    label, reason = verdict(_findings(0.42, 0.002, size_controlled=0.0))

    assert label == "FAIL"
    assert "size" in reason


def test_a_negative_correlation_is_a_failure_not_a_pass():
    label, _ = verdict(_findings(-0.42, 0.002))

    assert label == "FAIL"


def test_underpowered_is_not_the_same_verdict_as_null():
    """With too few niches the smallest detectable rho exceeds any effect worth
    having, so reporting "no relationship" would retire the thesis on a test that
    could not have detected one. Only a null licenses that."""
    label, reason = verdict(_findings(0.10, 0.40, selected=12))

    assert label == "INCONCLUSIVE — UNDERPOWERED"
    assert "12 niches" in reason
    assert "not evidence of no effect" in reason


def test_an_uncomputable_primary_is_inconclusive():
    label, _ = verdict(_findings(None, None))

    assert label == "INCONCLUSIVE"


def test_a_low_n_pass_is_still_reported_as_underpowered():
    """The N check comes before the p-value check on purpose: a significant result
    from 12 niches is as untrustworthy as a null from 12 niches."""
    label, _ = verdict(_findings(0.9, 0.001, selected=12))

    assert label.startswith("INCONCLUSIVE")


# --------------------------------------------------------------------------
# The rendered document
# --------------------------------------------------------------------------


def test_the_three_caveats_precede_every_number():
    body = render(_findings(0.42, 0.002))
    first_number = body.index("0.42")

    for heading, _ in CAVEATS:
        assert body.index(heading) < first_number


def test_survivorship_is_the_first_caveat():
    assert "Survivorship" in CAVEATS[0][0]


def test_a_secondary_that_beats_the_primary_is_still_labelled_secondary():
    """The only defence against the garden of forking paths, and the one most
    likely to be lost to judgement on the day."""
    findings = _findings(0.20, 0.03)
    findings.secondary = [_variant(0.85, 0.0001, label="opportunity")]

    body = render(findings)
    row = next(line for line in body.splitlines() if "opportunity" in line)

    assert row.startswith("| secondary |")
    assert "**primary**" not in row


def test_the_date_count_is_never_presented_as_a_sample_size():
    body = render(_findings(0.42, 0.002))

    assert "quasi-independent windows" in body
    assert "never a sample size" in body


def test_dropped_niches_are_named_not_silently_absent():
    findings = _findings(0.42, 0.002, dropped=[("chemical-spills", 4)])

    body = render(findings)

    assert "chemical-spills" in body
    assert "4 member channels" in body


def test_an_uncomputed_quantity_renders_as_na_not_zero():
    """`0.000` reads as a measurement. `n/a` reads as what it is."""
    body = render(_findings(None, None))

    assert "n/a" in body
    assert "rho = **0.000**" not in body


def test_the_report_cites_the_preregistration():
    body = render(_findings(0.42, 0.002))

    assert "backtest_preregistration" in body


def test_the_size_baseline_appears_beside_the_primary():
    body = render(_findings(0.42, 0.002))

    assert "size baseline" in body
    assert "controlling for size" in body
