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


def test_the_event_axis_is_not_gated_on_metrics():
    """ADR-0041's objection is specific: 107 machine labels on the exposition axis. EVENT
    rests on 298 human labels at held-out precision 0.781, so gating its METRICS would be
    applying a standard to the one family that already met it."""
    assert gates.citable("on_niche_share", "aviation-disasters").citable is True


def test_the_scorecard_is_withheld_on_every_axis_including_the_validated_one():
    """The two gates are keyed to different things and only one of them is the scorer.

    Found by review 2026-08-31: `scorecard_citable` keyed on axis validation alone, so the
    five retired EVENT clusters rendered `gap=-0.467` while ROADMAP and CLAUDE.md both said
    the slice ships "no rendering of `scorecards`". `gap`'s problem is Gate E's null, which
    human labelling cannot repair — the corpus contains no channel that failed. A validated
    scorer feeding a nulled composite is a well-measured input to a claim that failed.
    """
    for cluster in ("aviation-disasters", "history-of-ideas", "landmark-court-cases"):
        verdict = gates.scorecard_citable(cluster)
        assert verdict.citable is False
        assert "Gate E" in verdict.reason and "rho 0.091" in verdict.reason


def test_the_scorecard_stays_withheld_even_when_the_axis_is_validated(monkeypatch):
    """The load-bearing half: labelling the sample must not unlock the composite."""
    monkeypatch.setattr(gates, "EXPOSITION_VALIDATED", True)
    assert gates.citable("on_niche_share", "history-of-ideas").citable is True
    assert gates.scorecard_citable("history-of-ideas").citable is False


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


def test_the_withheld_reason_states_a_settled_position_not_a_queue():
    """It used to name the command that lifts the gate. The operator has since declined to
    label (ADR-0054), so advertising the task on every withheld metric forever would be
    nagging about work that is not going to happen — and would misdescribe the state as
    pending when it is decided."""
    reason = gates.citable("on_niche_share", "history-of-ideas").reason
    assert "exposition" in reason and "ADR-0054" in reason
    assert "label_exposition.py" not in reason


def test_the_disclosure_register_is_complete_and_argued():
    """`DISCLOSURES` is the answer to the review's structural finding.

    ADR-0052 states an absolute — "may not display a number the scorer decided" — and the
    slice then opened seven separately-argued doors through it, each locally plausible,
    each argued in a different file, and no artifact enumerating the union. One of the
    doors turned out to be nobody's decision at all. This asserts the register exists, that
    every entry carries a reason rather than a label, and that it names the paths that
    actually exist in the code — the same shape as `reports.FORBIDDEN_STEMS`.
    """
    assert len(gates.DISCLOSURES) >= 5
    for path, reason in gates.DISCLOSURES:
        assert path and len(reason) > 80, f"{path} is listed without an argument"

    listed = " ".join(path for path, _ in gates.DISCLOSURES)
    for expected in ("drilldown", "ALERT", "--unvalidated", "reports"):
        assert expected in listed, f"{expected} is a door and is not in the register"


def test_the_pressure_index_drilldown_does_not_serve_gated_values(engine):
    """The leak the register exists because of.

    `PRESSURE_FROM` is `median_views` and `uploads_per_week` — both gated — so this
    drilldown served, for every unvalidated cluster, the exact values withheld elsewhere on
    the same page. The "observations, not claims" argument that licenses other drilldowns
    does not reach here: the inputs to a RANK are other scorer-decided aggregates.
    """
    from datetime import date

    from nh.api import drilldown
    from nh.db.models import Cluster, FeatureDaily, NicheSeed
    from nh.db.session import session_scope
    from tests.conftest_features import session_for

    day = date(2026, 8, 31)
    with session_scope(engine) as s:
        s.add(NicheSeed(id=1, slug="history-of-ideas", label="H", keywords=[], active=True))
        s.flush()
        s.add(Cluster(cluster_id="history-of-ideas", seed_id=1, source="c", run_id="r"))
        s.add(
            FeatureDaily(
                cluster_id="history-of-ideas",
                day=day,
                metric_group="supply",
                name="median_views",
                value=8_214.0,
                confidence=0.87,
                inputs_n=10,
                detail={},
                source="features",
                run_id="r",
            )
        )
    _, rows = drilldown.rows_behind(session_for(engine), "pressure_index", "history-of-ideas", day)

    assert rows, "the fixture must produce rows, or this passes for free"
    assert all(row[2] == "withheld" for row in rows)
    assert "8214" not in str(rows) and "8,214" not in str(rows)


def test_a_gated_drilldown_drops_the_scorers_per_row_judgement(engine):
    """`relevance` is the score itself. Serving (video, score) pairs for the whole frame is
    a contamination surface for anyone about to label a sample — the repo defends that
    blinding with three guards in `api/reports.py` and handed it out here behind a caption
    asking the reader not to look."""

    from nh.api import drilldown
    from nh.db.models import Cluster, NicheSeed
    from nh.db.session import session_scope
    from tests.conftest_features import DAY, add_channel, session_for

    with session_scope(engine) as s:
        s.add(NicheSeed(id=1, slug="history-of-ideas", label="H", keywords=[], active=True))
        s.flush()
        s.add(Cluster(cluster_id="history-of-ideas", seed_id=1, source="c", run_id="r"))
    add_channel(engine, "a", videos=3, cluster_id="history-of-ideas", relevant=True)
    session = session_for(engine)

    gated_headers, _ = drilldown.rows_behind(session, "on_niche_share", "history-of-ideas", DAY)
    assert "relevance" not in gated_headers

    with session_scope(engine) as s:
        s.add(NicheSeed(id=2, slug="aviation-disasters", label="A", keywords=[], active=True))
        s.flush()
        s.add(Cluster(cluster_id="aviation-disasters", seed_id=2, source="c", run_id="r"))
    add_channel(engine, "b", videos=3, cluster_id="aviation-disasters", relevant=True)
    open_headers, _ = drilldown.rows_behind(
        session_for(engine), "on_niche_share", "aviation-disasters", DAY
    )
    assert "relevance" in open_headers, "and it is still there where nothing is gated"


def test_asking_for_the_wide_version_requires_saying_so(engine):
    """`gated` defaults to asking the gate, so a caller cannot widen the rows by forgetting
    — the same fail-safe direction as `jobs.niche.load`."""
    import inspect

    from nh.api import drilldown

    assert inspect.signature(drilldown.rows_behind).parameters["gated"].default is None
