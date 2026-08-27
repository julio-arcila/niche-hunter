"""The product-level gate.

`nh nightly` exiting 0 means the process finished. It does not mean anything was
collected: a ported source whose credentials vanished is recorded as `skipped`,
and `NightlyResult.ok` counts that as success. Left alone, that is seven silent
days of no collection behind seven green healthchecks pings.
"""

from __future__ import annotations

from datetime import timedelta

from nh.db.models import JobRun
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.jobs.phases import PHASES
from nh.jobs.status import check, recent_runs

RUN_ID = "66666666-6666-6666-6666-666666666666"


def _run(engine, source, status="ok", snapshots=10, run_id=RUN_ID, ago_days=0, **kw):
    with session_scope(engine) as s:
        s.add(
            JobRun(
                run_id=run_id,
                job="nightly",
                source=source,
                status=status,
                started_at=utcnow() - timedelta(days=ago_days),
                snapshots_written=snapshots,
                **kw,
            )
        )


def _healthy(engine):
    """A complete good night: both collectors plus all three computation phases.

    The phases are part of what "healthy" means since ADR-0014 — a night that
    collected but never computed is not a working pipeline, it is a pipeline that
    stopped producing the product behind a green ping."""
    _run(engine, "youtube_api", snapshots=40, quota_used=3_000, quota_budget=9_500)
    _run(engine, "youtube_rss", snapshots=120)
    _run(engine, "wikipedia", snapshots=450)
    _run(engine, "trends", snapshots=5)
    for phase, _ in PHASES:
        _run(engine, phase, snapshots=None)


def test_a_healthy_night_passes(settings, engine):
    _healthy(engine)
    assert check(engine, settings).ok


def test_no_runs_at_all_is_a_failure(settings, engine):
    result = check(engine, settings)
    assert not result.ok
    assert "ever been recorded" in result.problems[0]


def test_a_ported_but_unconfigured_source_fails_the_check(settings, engine):
    """The exact hole the dead-man switch cannot see: the job ran fine, and
    collected nothing, because a key went missing."""
    _healthy(engine)
    settings.yt_api_key = None
    result = check(engine, settings)
    assert not result.ok
    assert any("not configured" in p for p in result.problems)


def test_a_failed_source_fails_the_check(settings, engine):
    _run(engine, "youtube_api", status="failed", snapshots=0)
    _run(engine, "youtube_rss", snapshots=120)
    _run(engine, "wikipedia", snapshots=450)
    _run(engine, "trends", snapshots=5)
    result = check(engine, settings)
    assert not result.ok
    assert any("finished failed" in p for p in result.problems)


def test_a_source_that_did_not_run_fails_the_check(settings, engine):
    _run(engine, "youtube_rss", snapshots=120)
    _run(engine, "wikipedia", snapshots=450)
    _run(engine, "trends", snapshots=5)
    result = check(engine, settings)
    assert not result.ok
    assert any("did not run" in p for p in result.problems)


def test_a_run_that_collected_nothing_fails_even_if_every_source_is_ok(settings, engine):
    _run(engine, "youtube_api", snapshots=0)
    _run(engine, "youtube_rss", snapshots=0)
    _run(engine, "wikipedia", snapshots=0)
    result = check(engine, settings)
    assert not result.ok
    assert "the run wrote no snapshots" in result.problems


def test_spending_the_whole_quota_warns_but_does_not_fail(settings, engine):
    """A degraded run still collected. Worth surfacing, not worth paging over."""
    _run(engine, "youtube_api", snapshots=40, quota_used=9_500, quota_budget=9_500)
    _run(engine, "youtube_rss", snapshots=120)
    _run(engine, "wikipedia", snapshots=450)
    _run(engine, "trends", snapshots=5)
    for phase, _ in PHASES:
        _run(engine, phase, snapshots=None)
    result = check(engine, settings)
    assert result.ok
    assert any("whole quota" in w for w in result.warnings)


def test_only_the_latest_run_is_judged(settings, engine):
    _run(engine, "youtube_api", status="failed", snapshots=0, run_id="older", ago_days=2)
    _run(engine, "youtube_rss", status="failed", snapshots=0, run_id="older", ago_days=2)
    _healthy(engine)
    result = check(engine, settings)
    assert result.ok
    assert result.run_id == RUN_ID


def test_unported_sources_are_not_expected_to_run(settings, engine):
    """reddit and keyword_planner are absent by design until ported."""
    _healthy(engine)
    result = check(engine, settings)
    assert not any("reddit" in p for p in result.problems)
    assert not any("keyword_planner" in p for p in result.problems)


def test_recent_runs_is_newest_first(settings, engine):
    _run(engine, "youtube_rss", run_id="older", ago_days=3)
    _healthy(engine)
    lines = recent_runs(engine, days=7)
    assert len(lines) == 4 + 1 + len(PHASES)
    assert lines[0].day >= lines[-1].day


def test_a_partial_run_does_not_poison_the_gate(settings, engine):
    """`nh nightly --only youtube_rss` is a debugging aid, not a night's
    collection. Judging it would leave the gate red until the next cron fire."""
    _healthy(engine)
    with session_scope(engine) as s:
        s.add(
            JobRun(
                run_id="debug-run",
                job="partial",
                source="youtube_rss",
                status="ok",
                started_at=utcnow(),
                snapshots_written=5,
            )
        )
    result = check(engine, settings)
    assert result.ok
    assert result.run_id == RUN_ID  # the last real nightly, not the partial
