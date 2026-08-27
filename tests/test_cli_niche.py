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
