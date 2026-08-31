"""The citation gate, and the test that derives its classification (ADR-0052).

The important test here is `test_the_scorer_dependent_set_is_what_actually_moves`. It does
not check that the set is spelled correctly; it recomputes it, by running every registered
metric twice against a synthetic corpus — once at the real relevance threshold and once at
a threshold nothing can clear — and asserting the set that moved is exactly the set the
gate declares.

That is the method rather than reading the queries, because reading them produced a wrong
answer once already: `openness.*` was placed on the safe side on the strength of ADR-0047
establishing that openness is unaffected by ballast. It is. `winner_age_years` still joins
`on_niche_join` and reads the threshold directly.
"""

from __future__ import annotations

import pytest

import nh.features.inputs as inputs
from nh.api import gates
from nh.features.run import METRICS
from tests.conftest_features import (
    CLUSTER,
    DAY,
    rich_corpus,
)

IMPOSSIBLE = 1.01  # above the maximum a geometric mean of two saturating axes can reach


@pytest.fixture
def corpus(engine):
    """The shared rich corpus — see `conftest_features.rich_corpus` for why each part."""
    return rich_corpus(engine)


def _moves_with_the_threshold(session, metric) -> bool:
    """Does this metric's value or confidence depend on a relevance decision?"""
    before = metric(session, CLUSTER, DAY)
    original = inputs.RELEVANCE_HIGH
    try:
        inputs.RELEVANCE_HIGH = IMPOSSIBLE
        after = metric(session, CLUSTER, DAY)
    finally:
        inputs.RELEVANCE_HIGH = original
    return (before.value != after.value) or (before.confidence != after.confidence)


def test_the_scorer_dependent_set_is_what_actually_moves(corpus):
    """Recompute the gate's classification and compare. This is the gate's real spec."""
    measured = {m.__name__ for m in METRICS if _moves_with_the_threshold(corpus, m)}
    declared = gates.SCORER_DEPENDENT - {"pressure_index"}  # cross-cluster, not in METRICS

    assert measured == declared, (
        f"gate is wrong: reads relevance but ungated {sorted(measured - declared)}; "
        f"gated but does not read relevance {sorted(declared - measured)}"
    )


@pytest.mark.parametrize("name", sorted(gates.SCORER_DEPENDENT - {"pressure_index"}))
def test_every_gated_metric_is_computable_here(corpus, name):
    """The fixture must compute a real value for every gated metric.

    This is the guard on the guard, and it is not redundant with the derivation test — it
    is what stops that test from being satisfied by silence. A metric returning `empty()`
    at both thresholds "does not move", so a fixture that starves one classifies it
    citable, and the number then reaches a reader. Four of the eight started out starved
    here, each for a reason having nothing to do with relevance.

    Named per metric rather than asserted in a loop so a failure says WHICH one went quiet.
    """
    metric = next(m for m in METRICS if m.__name__ == name)
    result = metric(corpus, CLUSTER, DAY)
    assert result.value is not None, (
        f"{name} is empty on the gate fixture — "
        f"{(result.detail or {}).get('reason', 'no reason given')}"
    )


def test_the_fixture_can_actually_detect_movement(corpus):
    """Guards the guard. If the corpus were too thin every metric would sit at `empty()`
    on both sides, `measured` would be empty, and the test above would only pass when the
    gate declared nothing. Assert the fixture moves a known-dependent metric."""
    on_niche_share = next(m for m in METRICS if m.__name__ == "on_niche_share")
    assert _moves_with_the_threshold(corpus, on_niche_share)


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.__name__)
def test_every_registered_metric_is_classified(metric):
    """A metric added later must not reach a reader ungated by omission.

    `citable()` answers for any string, so this cannot fail on a lookup — what it pins is
    that the name is *considered*: present in `SCORER_DEPENDENT`, or deliberately absent
    and therefore claimed to be scorer-independent, which the derivation test then checks.
    """
    verdict = gates.citable(metric.__name__, "history-of-ideas")
    assert isinstance(verdict, gates.Verdict)
    assert verdict.citable is (metric.__name__ not in gates.SCORER_DEPENDENT)


def test_a_validated_axis_is_citable(monkeypatch):
    """Both directions, because only one of them is the state we are in today."""
    assert gates.citable("on_niche_share", "history-of-ideas").citable is False
    monkeypatch.setattr(gates, "EXPOSITION_VALIDATED", True)
    assert gates.citable("on_niche_share", "history-of-ideas").citable is True


def test_a_failing_verdict_does_not_unlock_anything(monkeypatch):
    """`False` is a recorded failure, not an absence. It must not read as validated."""
    monkeypatch.setattr(gates, "EXPOSITION_VALIDATED", False)
    assert gates.citable("on_niche_share", "history-of-ideas").citable is False
    assert gates.scorecard_citable("history-of-ideas").citable is False


def test_the_event_axis_is_not_gated():
    """ADR-0041's objection is specific: 107 machine labels on the exposition axis. EVENT
    rests on 298 human labels at held-out precision 0.781, so gating it would be applying a
    standard to the one family that already met it."""
    assert gates.citable("on_niche_share", "aviation-disasters").citable is True
    assert gates.scorecard_citable("aviation-disasters").citable is True


def test_a_cluster_with_no_lexicon_is_not_gated():
    """A cluster nothing scores has no scorer to distrust — and `AXES` is keyed on
    `LEXICONS`, so a retired niche without one must not fall into a KeyError."""
    assert gates.axis_of("landmark-court-cases") is None
    assert gates.citable("on_niche_share", "landmark-court-cases").citable is True


def test_the_whole_scorecard_is_withheld_together():
    """`gap` is demand minus supply. Serving `demand` from a row whose `supply` is withheld
    invites the reader to reconstruct the difference, which is the citation being
    prevented."""
    assert gates.scorecard_citable("history-of-ideas").citable is False
    assert "gap" in gates.SCORECARD_FIELDS and "demand" in gates.SCORECARD_FIELDS


def test_the_withheld_reason_names_the_command_that_lifts_it():
    """A gate that does not say how to open it is a wall. The register's own text is what
    is shown in place of the number."""
    reason = gates.citable("on_niche_share", "history-of-ideas").reason
    assert "label_exposition.py" in reason
    assert "exposition" in reason
