"""The demand-trajectory classifier.

The most important test here is `test_classify_takes_no_session`. Slice 6 replays
this function at historical dates, and leakage — a feature reading a snapshot from
after the decision date — is the failure mode that makes a backtest look excellent
and mean nothing. A pure function cannot leak, so purity is the guarantee and it is
worth asserting rather than assuming.
"""

from __future__ import annotations

import inspect

import pytest

from nh.scoring.lifecycle import DEFAULT, Stage, Thresholds, classify


@pytest.mark.parametrize(
    ("momentum", "gap", "expected"),
    [
        (0.2, 0.5, Stage.EMERGING),  # demand rising, under-served
        (0.2, -0.5, Stage.CONTESTED),  # demand rising, supply keeps up
        (-0.2, 0.5, Stage.COOLING),  # demand falling, still under-served
        (-0.2, -0.5, Stage.SATURATED),  # demand falling, well served
    ],
)
def test_the_four_quadrants_come_from_the_two_signs(momentum, gap, expected):
    stage, _ = classify({"momentum": momentum, "gap": gap})
    assert stage is expected


@pytest.mark.parametrize("axis", ["momentum", "gap"])
def test_a_missing_axis_is_unknown_not_a_fifth_kind_of_niche(axis):
    """Defaulting an absent axis to 0 would silently classify every un-measured
    cluster as cooling or saturated (data rule 7)."""
    vector = {"momentum": 0.2, "gap": 0.5} | {axis: None}
    stage, evidence = classify(vector)
    assert stage is Stage.UNKNOWN
    assert axis in evidence["reason"]
    assert axis not in evidence["basis"]


def test_exactly_zero_is_not_growing():
    """Zero is the boundary, and the boundary has to fall somewhere. Flat demand is
    not rising demand."""
    stage, _ = classify({"momentum": 0.0, "gap": 0.5})
    assert stage is Stage.COOLING


def test_the_evidence_records_which_axes_were_available():
    _, evidence = classify({"momentum": -0.2, "gap": 0.1})
    assert evidence["basis"] == ["gap", "momentum"]
    assert evidence["axes"] == {"momentum": -0.2, "gap": 0.1}


def test_the_evidence_records_the_threshold_version():
    """Slice 6 will move these cutoffs, and every stored stage has to stay
    attributable to the ones that produced it."""
    _, evidence = classify({"momentum": 0.1, "gap": 0.1})
    assert evidence["thresholds"] == DEFAULT.version


def test_extra_vector_keys_are_carried_into_the_evidence_untouched():
    """So a caller can attach what it wants traceable without this function growing
    an opinion about it."""
    _, evidence = classify({"momentum": 0.1, "gap": 0.1, "wiki_momentum_28d": -0.31})
    assert evidence["wiki_momentum_28d"] == -0.31


def test_a_threshold_sweep_changes_the_stage():
    """If it did not, the thresholds would be decoration and Slice 6 would have
    nothing to tune."""
    vector = {"momentum": 0.05, "gap": 0.5}
    assert classify(vector, Thresholds(version="t", momentum=0.0))[0] is Stage.EMERGING
    assert classify(vector, Thresholds(version="t", momentum=0.10))[0] is Stage.COOLING


def test_the_default_thresholds_are_all_zero():
    """Zero IS the definition of growing and of a positive gap. A non-zero default
    would be a number chosen because the output looked right — the trap METRICS.md
    warns about three separate times."""
    assert DEFAULT.momentum == 0.0
    assert DEFAULT.gap == 0.0


def test_classify_takes_no_session():
    """Purity is the anti-leakage guarantee, so it is asserted rather than assumed.
    A function that cannot read anything cannot read a snapshot from after the
    decision date."""
    parameters = inspect.signature(classify).parameters
    assert list(parameters) == ["vector", "thresholds"]
    source = inspect.getsource(classify)
    for forbidden in ("session", "Session", "select(", "utcnow", "date.today"):
        assert forbidden not in source


def test_the_module_does_not_import_the_database_layer():
    """The stronger form: nothing in here can reach a query even indirectly."""
    import nh.scoring.lifecycle as module

    source = inspect.getsource(module)
    assert "nh.db" not in source
    assert "sqlalchemy" not in source
