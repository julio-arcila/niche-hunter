"""`nh niche show` — the operator's view of one niche.

The rendering contract is that a reader can tell three states apart at a glance:
a measured number, a measured zero, and "we could not compute this". Conflating
the last two is how a pipeline gap gets read as a finding about the niche.
"""

from __future__ import annotations

from datetime import date

import pytest
from typer.testing import CliRunner

from nh.cli import app
from nh.db.models import Cluster, FeatureDaily
from nh.db.session import session_scope

runner = CliRunner()
DAY = date(2026, 8, 27)


@pytest.fixture
def niche(engine, monkeypatch):
    """A cluster with one real metric, one measured zero and one uncomputable."""
    monkeypatch.setattr("nh.db.session.get_engine", lambda: engine)
    monkeypatch.setattr("nh.jobs.niche.session_scope", lambda _=None: session_scope(engine))
    with session_scope(engine) as s:
        s.add(Cluster(cluster_id="aviation", label=None, source="clustering", run_id="r"))
        s.add_all(
            [
                FeatureDaily(
                    cluster_id="aviation",
                    day=DAY,
                    metric_group="supply",
                    name="median_views",
                    value=8_214.0,
                    confidence=0.87,
                    inputs_n=1_893,
                    detail={"contributing_channels": 174, "inputs": {"tables": ["videos"]}},
                    source="features",
                    run_id="r",
                ),
                FeatureDaily(
                    cluster_id="aviation",
                    day=DAY,
                    metric_group="supply",
                    name="uploads_per_week",
                    value=0.0,
                    confidence=0.9,
                    inputs_n=0,
                    detail={"window": ["2026-07-30", "2026-08-27"]},
                    source="features",
                    run_id="r",
                ),
                FeatureDaily(
                    cluster_id="aviation",
                    day=DAY,
                    metric_group="money",
                    name="vw_cpc",
                    value=17_057.88,
                    confidence=0.07,
                    inputs_n=2,
                    detail={
                        "geo": "US",
                        "currency": "COP",
                        "window": ["2025-08-01", "2026-07-31"],
                        "inputs": {"tables": ["keyword_metrics", "seed_terms"]},
                    },
                    source="features",
                    run_id="r",
                ),
                FeatureDaily(
                    cluster_id="aviation",
                    day=DAY,
                    metric_group="openness",
                    name="views_per_sub",
                    value=None,
                    confidence=0.0,
                    inputs_n=0,
                    detail={"reason": "cohort empty"},
                    source="features",
                    run_id="r",
                ),
            ]
        )
    return engine


def test_every_metric_shows_value_confidence_and_inputs(niche):
    out = runner.invoke(app, ["niche", "show", "aviation"]).stdout
    assert "median_views" in out and "8,214" in out
    assert "0.87" in out and "1,893" in out


def test_a_measured_zero_prints_as_a_number(niche):
    """0.00 is a finding: we looked, and the niche published nothing."""
    out = runner.invoke(app, ["niche", "show", "aviation"]).stdout
    assert "uploads_per_week" in out
    assert "0.00" in out


def test_an_uncomputable_metric_prints_a_dash_and_its_reason(niche):
    out = runner.invoke(app, ["niche", "show", "aviation"]).stdout
    assert "—" in out
    assert "cohort empty" in out


def test_the_legend_states_the_convention(niche):
    """Printed every time, because the distinction is only obvious once you know it."""
    out = runner.invoke(app, ["niche", "show", "aviation"]).stdout
    assert "not computable" in out


def test_provenance_names_the_tables_a_number_came_from(niche):
    out = runner.invoke(app, ["niche", "show", "aviation"]).stdout
    assert "174 channels contributed" in out
    assert "from videos" in out


def test_an_unknown_slug_is_an_error_not_a_traceback(niche):
    result = runner.invoke(app, ["niche", "show", "nonsense"])
    assert result.exit_code == 2
    assert "unknown niche: nonsense" in result.output
    assert "known: aviation" in result.output
    assert "Traceback" not in result.output


def test_it_defaults_to_the_latest_computed_day(niche):
    """Useful the morning after a failed run, rather than reporting an empty today."""
    out = runner.invoke(app, ["niche", "show", "aviation"]).stdout
    assert str(DAY) in out


def test_provenance_names_the_currency_and_market_of_a_price(niche):
    """`17,058` is a plausible-looking CPC and a wrong one: the account exports in COP,
    so the number is ~US$4, and a reader who assumes dollars is off by four orders of
    magnitude (ADR-0031 forbids converting it, which makes saying so the whole defence).
    `geo` is the same class of fact — the figure describes the US market, not the
    niche's worldwide demand, and nothing else on the line says which market."""
    out = runner.invoke(app, ["niche", "show", "aviation"]).output

    assert "bids in COP" in out
    assert "geo US" in out
    # On one line, under the value it qualifies — not stranded in another metric's block.
    line = next(ln for ln in out.splitlines() if "bids in COP" in ln)
    assert "geo US" in line and "2025-08-01..2026-07-31" in line


# --- the citation gate (ADR-0052) --------------------------------------------------
#
# `nh niche show` was the repo's only citation surface when ADR-0045 wrote a trigger that
# watches `scorecards.value` — a column Gate E holds NULL permanently. So the register read
# green while this command printed `gap`, `supply` and every scorer-dependent metric for
# ten clusters whose relevance rule rests on 107 machine labels. These pin the fix.


@pytest.fixture
def exposition(engine, monkeypatch):
    """The same shape as `niche`, on a cluster the exposition lexicon scores.

    `history-of-ideas` rather than an invented slug: `gates.axis_of` reads
    `clustering.lexicon.AXES`, so a made-up cluster would have no axis, would not be gated,
    and the test would pass while testing nothing.
    """
    from nh.db.models import Scorecard

    monkeypatch.setattr("nh.db.session.get_engine", lambda: engine)
    monkeypatch.setattr("nh.jobs.niche.session_scope", lambda _=None: session_scope(engine))
    with session_scope(engine) as s:
        s.add(Cluster(cluster_id="history-of-ideas", label=None, source="clustering", run_id="r"))
        s.add_all(
            [
                FeatureDaily(  # gated: reads a relevance decision
                    cluster_id="history-of-ideas",
                    day=DAY,
                    metric_group="supply",
                    name="on_niche_share",
                    value=0.227,
                    confidence=0.61,
                    inputs_n=1_012,
                    detail={"inputs": {"tables": ["cluster_members"]}},
                    source="features",
                    run_id="r",
                ),
                FeatureDaily(  # ungated: the scorer never touches it
                    cluster_id="history-of-ideas",
                    day=DAY,
                    metric_group="demand",
                    name="wiki_yoy",
                    value=-0.18,
                    confidence=1.0,
                    inputs_n=504,
                    detail={"inputs": {"tables": ["demand_snapshots"]}},
                    source="features",
                    run_id="r",
                ),
            ]
        )
        s.add(
            Scorecard(
                cluster_id="history-of-ideas",
                day=DAY,
                demand=0.80,
                supply=0.30,
                gap=0.50,
                source="features",
                run_id="r",
            )
        )
    return engine


def test_a_scorer_dependent_metric_is_withheld_not_printed(exposition):
    out = runner.invoke(app, ["niche", "show", "history-of-ideas"]).stdout
    assert "on_niche_share" in out, "the metric is named — it is withheld, not hidden"
    assert "0.23" not in out and "0.227" not in out
    assert "1,012" not in out, "inputs_n goes with the value; a half-blank row reads as a bug"


def test_a_scorer_independent_metric_is_untouched(exposition):
    """The gate is about the scorer, not about the cluster. Demand is measured the same way
    whatever the lexicon does, so gating it would be superstition."""
    out = runner.invoke(app, ["niche", "show", "history-of-ideas"]).stdout
    assert "wiki_yoy" in out and "-0.18" in out and "504" in out


def test_the_whole_scorecard_is_withheld(exposition):
    """`gap` is demand minus supply — printing either side invites reconstruction."""
    out = runner.invoke(app, ["niche", "show", "history-of-ideas"]).stdout
    assert "gap=0.50" not in out and "supply=0.30" not in out and "demand=0.80" not in out
    assert "Gate E" in out, "and the reason quoted is the null, not the scorer"


def test_a_withheld_number_says_how_to_unwithhold_it(exposition):
    """A gate that does not say how to open it is a wall. What replaces the number is the
    deferral register's own text, which is serving the register rather than citing."""
    out = runner.invoke(app, ["niche", "show", "history-of-ideas"]).stdout
    assert "unvalidated" in out and "label_exposition.py" in out
    assert "ADR-0041" in out


def test_the_flag_shows_them_again(exposition):
    """A human asking once, at the moment of asking — not a stored setting standing in for
    a verdict, which is what ADR-0050 forbids and what this deliberately is not."""
    out = runner.invoke(app, ["niche", "show", "history-of-ideas", "--unvalidated"]).stdout
    assert "0.23" in out and "gap=0.50" in out


def test_the_legend_appears_only_when_something_was_withheld(niche, exposition):
    """`aviation` has no lexicon and so no unvalidated scorer. A legend explaining a symbol
    that is not on screen trains the reader to skip legends."""
    gated = runner.invoke(app, ["niche", "show", "history-of-ideas"]).stdout
    ungated = runner.invoke(app, ["niche", "show", "aviation"]).stdout
    assert "means withheld, not missing" in gated
    assert "means withheld, not missing" not in ungated


def test_a_validated_axis_prints_its_metrics_but_still_no_scorecard(exposition, monkeypatch):
    """The metric gate is a state that labelling lifts. The SCORECARD gate is not.

    Two gates, keyed to different things: the metrics wait on the scorer, the scorecard
    waits on Gate E — and Gate E returned a null that no labelling repairs. This asserted
    `gap=0.50` reappearing until the 2026-08-31 review pointed out that ROADMAP and
    CLAUDE.md both promised no scorecard rendering at all.
    """
    monkeypatch.setattr("nh.api.gates.EXPOSITION_VALIDATED", True)
    out = runner.invoke(app, ["niche", "show", "history-of-ideas"]).stdout
    assert "0.23" in out
    assert "gap=0.50" not in out and "Gate E" in out


# --- `nh niche trace` — the exit criterion from a terminal ---------------------------


def test_trace_prints_the_rows_behind_a_number(exposition, monkeypatch):
    from tests.conftest_features import add_demand, make_cluster

    monkeypatch.setattr("nh.api.queries.demand_terms", lambda s, c, src: ["Test_Article"])
    make_cluster(exposition, "traced")
    add_demand(exposition, cluster_id="traced")
    out = runner.invoke(app, ["niche", "trace", "history-of-ideas", "wiki_yoy"]).stdout

    assert "population:" in out
    assert "English readers globally" in out, "ADR-0035: a number must name who it counts"


def test_trace_on_a_gated_metric_shows_rows_and_names_the_cost(exposition):
    """The asymmetry is deliberate: `gates` withholds the scorer's aggregate CLAIM, while
    these rows are what a person needs to judge whether the claim is any good. Withholding
    the audit trail would make the thing unvalidatable, which is backwards. The real cost —
    a video row carries `relevance`, so a would-be labeller must not browse it first — is
    named rather than assumed away."""
    out = runner.invoke(app, ["niche", "trace", "history-of-ideas", "on_niche_share"]).stdout
    assert "withheld" in out and "before labelling" in out


def test_trace_on_an_unknown_metric_lists_what_it_knows(exposition):
    result = runner.invoke(app, ["niche", "trace", "history-of-ideas", "invented"])
    assert result.exit_code == 2
    assert "no drilldown registered" in result.output
    assert "wiki_yoy" in result.output, "a dead end must say what the live ends are"
    assert "Traceback" not in result.output
