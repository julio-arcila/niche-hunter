from __future__ import annotations

from typer.testing import CliRunner

from nh.cli import app

runner = CliRunner()


def test_dry_run_lists_every_collector_with_a_reason():
    result = runner.invoke(app, ["nightly", "--dry-run"])
    assert result.exit_code == 0
    for source in ("youtube_rss", "youtube_api", "trends", "reddit", "keyword_planner"):
        assert source in result.stdout
    assert "not ported" in result.stdout


def test_unknown_collector_is_an_error_message_not_a_traceback():
    result = runner.invoke(app, ["nightly", "--dry-run", "--only", "nope"])
    assert result.exit_code == 2
    assert "unknown collector(s): nope" in result.output
    assert "known:" in result.output
    assert "youtube_rss" in result.output
    assert "Traceback" not in result.output
    assert "COLLECTOR" not in result.output  # no header before the failure


def test_only_filters_the_plan():
    result = runner.invoke(app, ["nightly", "--dry-run", "--only", "trends"])
    assert result.exit_code == 0
    assert "trends" in result.stdout
    assert "reddit" not in result.stdout
