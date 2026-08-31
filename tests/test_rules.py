"""The insight rules — one test that fires each, one that does not.

That pairing is INSIGHT_RULES.md's standing requirement, and it is not ceremony: a rule
with only a firing test is a rule nobody has checked for false positives, and a rule that
fires constantly is one the reader learns to skip.

Each rule's DOCUMENTED false positive gets its own test, because that is the failure the
rule's author already anticipated and the one most likely to be regressed.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import sqlalchemy as sa

from nh.db.models import Alert, Cluster, FeatureDaily, NicheSeed
from nh.db.provenance import stamp
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.scoring import rules
from tests.conftest_features import CLUSTER, session_for

DAY = date(2026, 8, 27)
RUN = "rules-run"


def _mark(model, values):
    return stamp(model, values, source="rules", run_id=RUN, at=utcnow())


def _feature(engine, name, *, day, value=1.0, inputs_n=100, detail=None, cluster_id=CLUSTER):
    with session_scope(engine) as s:
        s.add(
            FeatureDaily(
                cluster_id=cluster_id,
                day=day,
                metric_group="supply",
                name=name,
                value=value,
                confidence=0.5,
                inputs_n=inputs_n,
                detail=detail or {},
                source="features",
                run_id=RUN,
            )
        )


@pytest.fixture
def seeded(engine):
    """An ACTIVE seed, because Rule 3 checks that before firing."""
    with session_scope(engine) as s:
        s.add(NicheSeed(id=1, slug=CLUSTER, label="Aviation", keywords=[], geo="US", active=True))
        s.flush()
        s.add(Cluster(cluster_id=CLUSTER, seed_id=1, label="Aviation", source="c", run_id=RUN))
    return engine


# --- Rule 1: demand breakout -------------------------------------------------------


def _demand_history(engine, *, spike: bool) -> None:
    """A year of flat dailies, optionally with the most recent 28-day window lifted.

    Flat-plus-noise rather than flat: a zero standard deviation makes every z infinite,
    and a rule that fires on a constant series would fire on every fixture forever.
    """
    from nh.db.models import DemandSnapshot, SeedTerm

    with session_scope(engine) as s:
        s.add(
            SeedTerm(
                seed_id=1, source="wikipedia", term="Test_Article", lang="en", geo="", active=True
            )
        )
        for offset in range(420):
            day = DAY - timedelta(days=offset)
            base = 1_000.0 + (offset % 5) * 20
            recent = offset < rules.WINDOW_DAYS + 2
            s.add(
                DemandSnapshot(
                    term="Test_Article",
                    source="wikipedia",
                    geo="",
                    observed_date=day,
                    value=base * (6.0 if (spike and recent) else 1.0),
                    run_id=RUN,
                )
            )


def test_rule_1_fires_on_a_demand_breakout(seeded):
    _demand_history(seeded, spike=True)
    finding = rules.demand_breakout(session_for(seeded), CLUSTER, DAY)

    assert finding is not None
    assert finding.severity == "info"
    assert finding.evidence["z"] >= rules.BREAKOUT_Z
    assert finding.evidence["baseline_windows"] >= rules.BREAKOUT_MIN_WINDOWS


def test_rule_1_does_not_fire_on_a_flat_series(seeded):
    _demand_history(seeded, spike=False)
    assert rules.demand_breakout(session_for(seeded), CLUSTER, DAY) is None


def test_rule_1_does_not_fire_without_enough_history(seeded):
    """The sd of four windows is not a baseline. Below the floor the rule stays silent
    rather than reporting a z it cannot support."""
    from nh.db.models import DemandSnapshot, SeedTerm

    with session_scope(seeded) as s:
        s.add(
            SeedTerm(
                seed_id=1, source="wikipedia", term="Test_Article", lang="en", geo="", active=True
            )
        )
        for offset in range(60):  # ~2 baseline windows
            s.add(
                DemandSnapshot(
                    term="Test_Article",
                    source="wikipedia",
                    geo="",
                    observed_date=DAY - timedelta(days=offset),
                    value=1_000.0 * (8 if offset < 30 else 1),
                    run_id=RUN,
                )
            )
    assert rules.demand_breakout(session_for(seeded), CLUSTER, DAY) is None


# --- Rule 2: definition step -------------------------------------------------------


def test_rule_2_fires_when_a_definition_changes(seeded):
    """The event that actually happened and that nothing detected: ADR-0047 moved
    `on_niche_share` 0.076 -> 0.227 on an identical numerator of 230."""
    yesterday = DAY - timedelta(days=1)
    _feature(
        seeded, "on_niche_share", day=yesterday, value=0.076, detail={"definition": "v2-on-niche"}
    )
    _feature(
        seeded,
        "on_niche_share",
        day=DAY,
        value=0.227,
        detail={"definition": "v3-non-ballast-members"},
    )
    finding = rules.definition_step(session_for(seeded), CLUSTER, DAY)

    assert finding is not None and finding.severity == "watch"
    assert finding.evidence["definitions"] == [
        {"metric": "on_niche_share", "from": "v2-on-niche", "to": "v3-non-ballast-members"}
    ]


def test_rule_2_does_not_fire_when_the_definition_holds(seeded):
    """A value moving is not news of the kind this rule reports — only the definition is."""
    yesterday = DAY - timedelta(days=1)
    for day, value in ((yesterday, 0.076), (DAY, 0.400)):
        _feature(
            seeded, "on_niche_share", day=day, value=value, detail={"definition": "v2-on-niche"}
        )
    assert rules.definition_step(session_for(seeded), CLUSTER, DAY) is None


def test_rule_2_compares_stored_days_not_calendar_days(seeded):
    """2026-08-30 is a permanent hole — the nightly a sleeping Mac ate. A rule reaching for
    "yesterday" would find nothing there and fire, or fail to fire, on every gap forever."""
    old = DAY - timedelta(days=9)
    _feature(seeded, "on_niche_share", day=old, value=0.076, detail={"definition": "v2-on-niche"})
    _feature(
        seeded,
        "on_niche_share",
        day=DAY,
        value=0.227,
        detail={"definition": "v3-non-ballast-members"},
    )
    finding = rules.definition_step(session_for(seeded), CLUSTER, DAY)

    assert finding is not None, "a nine-day gap must not hide a definition change"
    assert finding.evidence["from_day"] == old.isoformat()


def test_rule_2_ignores_an_absent_ballast_stamp(seeded):
    """The first night after a stamp lands, the previous day has none. Absent is not a
    change — the same tolerance `nh status --check` gives."""
    yesterday = DAY - timedelta(days=1)
    _feature(
        seeded, "on_niche_share", day=yesterday, detail={"definition": "v3-non-ballast-members"}
    )
    _feature(
        seeded,
        "on_niche_share",
        day=DAY,
        detail={"definition": "v3-non-ballast-members", "ballast": {"channels": 90}},
    )
    assert rules.definition_step(session_for(seeded), CLUSTER, DAY) is None


# --- Rule 3: evidence collapse -----------------------------------------------------


def test_rule_3_fires_when_a_metric_goes_null(seeded):
    yesterday = DAY - timedelta(days=1)
    _feature(seeded, "wiki_yoy", day=yesterday, value=0.3)
    _feature(seeded, "wiki_yoy", day=DAY, value=None, detail={"reason": "no article mapped"})
    finding = rules.evidence_collapse(session_for(seeded), CLUSTER, DAY)

    assert finding is not None and finding.severity == "watch"
    assert finding.evidence["went_null"] == [{"metric": "wiki_yoy", "reason": "no article mapped"}]


def test_rule_3_fires_when_inputs_halve(seeded):
    yesterday = DAY - timedelta(days=1)
    _feature(seeded, "wiki_yoy", day=yesterday, value=0.3, inputs_n=500)
    _feature(seeded, "wiki_yoy", day=DAY, value=0.3, inputs_n=100)
    finding = rules.evidence_collapse(session_for(seeded), CLUSTER, DAY)

    assert finding is not None
    assert finding.evidence["lost_inputs"] == [{"metric": "wiki_yoy", "from": 500, "to": 100}]


def test_rule_3_does_not_fire_on_a_steady_day(seeded):
    yesterday = DAY - timedelta(days=1)
    for day in (yesterday, DAY):
        _feature(seeded, "wiki_yoy", day=day, value=0.3, inputs_n=500)
    assert rules.evidence_collapse(session_for(seeded), CLUSTER, DAY) is None


def test_rule_3_does_not_fire_on_a_retired_cluster(seeded):
    """Its documented false positive. Retiring a niche makes every metric go NULL at once,
    which is a decision — firing there would make the rule loudest when least useful."""
    yesterday = DAY - timedelta(days=1)
    _feature(seeded, "wiki_yoy", day=yesterday, value=0.3)
    _feature(seeded, "wiki_yoy", day=DAY, value=None)
    with session_scope(seeded) as s:
        s.get(NicheSeed, 1).active = False

    assert rules.evidence_collapse(session_for(seeded), CLUSTER, DAY) is None


def test_rule_3_reports_counts_for_a_gated_metric_too(seeded):
    """Counts ARE reported in an alert, and the reversal is deliberate.

    This asserted the opposite until 2026-08-31, when a review pointed out that Rule 3
    masked `inputs_n` while Rule 2 published ballast CHANNEL counts — the same class of
    number — so the module held both positions at once. Resolved toward reporting, with the
    reason recorded in `gates.DISCLOSURES`: a count of rows the scorer decided about is a
    fact about the PIPELINE, and an alert's whole subject is the pipeline. The metric TABLE
    still blanks a count beside a withheld value, for a presentation reason rather than an
    epistemic one. `inputs_n` for `on_niche_share` is its DENOMINATOR; the numerator is
    never emitted, so no withheld value is reconstructible from an alert.
    """
    yesterday = DAY - timedelta(days=1)
    with session_scope(seeded) as s:
        s.get(NicheSeed, 1).slug = "history-of-ideas"
        s.add(Cluster(cluster_id="history-of-ideas", seed_id=1, source="c", run_id=RUN))
    for day, n in ((yesterday, 500), (DAY, 10)):
        _feature(seeded, "on_niche_share", day=day, inputs_n=n, cluster_id="history-of-ideas")
    finding = rules.evidence_collapse(session_for(seeded), "history-of-ideas", DAY)

    assert finding is not None
    assert finding.evidence["lost_inputs"] == [{"metric": "on_niche_share", "from": 500, "to": 10}]


# --- the phase ---------------------------------------------------------------------


def test_no_rule_quotes_a_number_from_a_gated_metric(seeded):
    """Swept over every rule's evidence rather than asserted per rule, because the rule
    that breaks this will be the fourth one somebody adds."""
    from nh.api.gates import SCORER_DEPENDENT

    yesterday = DAY - timedelta(days=1)
    _demand_history(seeded, spike=True)
    _feature(
        seeded,
        "on_niche_share",
        day=yesterday,
        value=0.076,
        inputs_n=500,
        detail={"definition": "v2-on-niche"},
    )
    _feature(
        seeded,
        "on_niche_share",
        day=DAY,
        value=0.227,
        inputs_n=10,
        detail={"definition": "v3-non-ballast-members"},
    )
    session = session_for(seeded)

    for rule in rules.RULES:
        finding = rule(session, CLUSTER, DAY)
        if finding is None:
            continue
        blob = str(finding.evidence)
        for gated in SCORER_DEPENDENT:
            if gated in blob:
                # Naming a gated metric is allowed; quoting its value is not.
                assert "0.227" not in blob and "0.076" not in blob, (
                    f"{finding.rule} quotes a gated metric's value"
                )


def test_the_phase_writes_one_alert_per_rule_per_cluster_per_day(seeded):
    yesterday = DAY - timedelta(days=1)
    _feature(seeded, "on_niche_share", day=yesterday, detail={"definition": "v2-on-niche"})
    _feature(seeded, "on_niche_share", day=DAY, detail={"definition": "v3-non-ballast-members"})

    with session_scope(seeded) as s:
        written = rules.evaluate(s, DAY, _mark)
    assert written == 1

    with session_scope(seeded) as s:
        alert = s.scalars(sa.select(Alert)).one()
        assert alert.rule == "definition_step"
        assert alert.severity == "watch"
        assert alert.fired_on == DAY


def test_re_running_a_day_writes_nothing_new(seeded):
    """`insert_ignore` on `(cluster_id, rule, fired_on)` — the same append-only discipline
    a snapshot gets, and for the same reason: the first firing of the day is the record."""
    yesterday = DAY - timedelta(days=1)
    _feature(seeded, "on_niche_share", day=yesterday, detail={"definition": "v2-on-niche"})
    _feature(seeded, "on_niche_share", day=DAY, detail={"definition": "v3-non-ballast-members"})

    with session_scope(seeded) as s:
        rules.evaluate(s, DAY, _mark)
    with session_scope(seeded) as s:
        again = rules.evaluate(s, DAY, _mark)
    assert again == 0

    with session_scope(seeded) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Alert)) == 1


def test_the_phase_skips_retired_clusters(seeded):
    yesterday = DAY - timedelta(days=1)
    _feature(seeded, "on_niche_share", day=yesterday, detail={"definition": "v2-on-niche"})
    _feature(seeded, "on_niche_share", day=DAY, detail={"definition": "v3-non-ballast-members"})
    with session_scope(seeded) as s:
        s.get(NicheSeed, 1).active = False

    with session_scope(seeded) as s:
        assert rules.evaluate(s, DAY, _mark) == 0


def test_rules_is_the_last_phase(seeded):
    """It reads what every earlier phase wrote; an alert from a half-computed day would be
    worse than no alert."""
    from nh.jobs.phases import PHASES

    assert PHASES[-1][0] == "rules"
    assert [name for name, _ in PHASES] == ["clustering", "features", "scoring", "rules"]
