"""The computation phases and their job_runs bookkeeping.

The gate integration is the point. `check()` iterates REGISTRY sources, so phase
rows are invisible to it unless it is told about them — which would mean a
features phase failing every night behind a green healthcheck (ADR-0014).
"""

from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from nh.db.models import JobRun
from nh.db.session import session_scope
from nh.jobs.phases import PHASES, run_phases
from nh.seeds import apply_seeds

DAY = date(2026, 8, 27)
RUN = "77777777-7777-7777-7777-777777777777"


def test_all_three_phases_run_in_dependency_order(engine):
    """Features need clusters, scoring needs features."""
    assert [name for name, _ in PHASES] == ["clustering", "features", "scoring"]
    apply_seeds(engine)
    assert set(run_phases(RUN, DAY, engine=engine).values()) == {"ok"}


def test_each_phase_writes_a_job_run_under_the_nights_run_id(engine):
    apply_seeds(engine)
    run_phases(RUN, DAY, engine=engine)
    with session_scope(engine) as s:
        rows = dict(
            s.execute(sa.select(JobRun.source, JobRun.status).where(JobRun.run_id == RUN)).all()
        )
    assert rows == {"clustering": "ok", "features": "ok", "scoring": "ok"}


def test_phase_rows_carry_no_quota(engine):
    """Phases consume no external budget; a number there would be fiction."""
    apply_seeds(engine)
    run_phases(RUN, DAY, engine=engine)
    with session_scope(engine) as s:
        used = s.scalars(sa.select(JobRun.quota_used).where(JobRun.source == "features")).one()
    assert used is None


def test_a_failing_phase_is_recorded_and_the_next_one_still_runs(engine, monkeypatch):
    """Same posture as a failing collector: features computed from partial inputs
    are worth having, and confidence says how partial."""
    import nh.jobs.phases as phases

    def boom(session, day, mark):
        raise RuntimeError("clustering exploded")

    monkeypatch.setattr(phases, "PHASES", (("clustering", boom), *PHASES[1:]))
    apply_seeds(engine)
    statuses = phases.run_phases(RUN, DAY, engine=engine)
    assert statuses["clustering"] == "failed"
    assert statuses["features"] == "ok"  # ran anyway
    with session_scope(engine) as s:
        error = s.scalar(sa.select(JobRun.error).where(JobRun.source == "clustering"))
    assert "clustering exploded" in error


def test_rerunning_a_day_leaves_the_values_unchanged(engine):
    """The exit criterion: re-running the day changes nothing."""
    from nh.db.models import FeatureDaily

    apply_seeds(engine)
    run_phases(RUN, DAY, engine=engine)

    def snapshot():
        with session_scope(engine) as s:
            return sorted(
                s.execute(
                    sa.select(
                        FeatureDaily.cluster_id,
                        FeatureDaily.name,
                        FeatureDaily.value,
                        FeatureDaily.confidence,
                        FeatureDaily.inputs_n,
                    )
                ).all()
            )

    before = snapshot()
    run_phases("a-different-run", DAY, engine=engine)
    assert snapshot() == before


# -- the gate ---------------------------------------------------------------


def _collectors_ok(engine, run_id=RUN):
    from nh.db.types import utcnow

    with session_scope(engine) as s:
        for source in ("youtube_api", "youtube_rss"):
            s.add(
                JobRun(
                    run_id=run_id,
                    job="nightly",
                    source=source,
                    status="ok",
                    started_at=utcnow(),
                    snapshots_written=10,
                )
            )


@pytest.mark.parametrize("missing", ["clustering", "features", "scoring"])
def test_a_missing_phase_fails_the_gate(engine, settings, missing):
    """Without this the pipeline could stop computing for a week behind a green
    healthcheck — the collectors would still be writing snapshots."""
    from nh.db.types import utcnow
    from nh.jobs.status import check

    _collectors_ok(engine)
    with session_scope(engine) as s:
        for name, _ in PHASES:
            if name == missing:
                continue
            s.add(
                JobRun(
                    run_id=RUN,
                    job="nightly",
                    source=name,
                    status="ok",
                    started_at=utcnow(),
                )
            )
    result = check(engine, settings)
    assert not result.ok
    assert any(f"{missing} phase did not run" in p for p in result.problems)


def test_a_failed_phase_fails_the_gate(engine, settings):
    from nh.db.types import utcnow
    from nh.jobs.status import check

    _collectors_ok(engine)
    with session_scope(engine) as s:
        for name, _ in PHASES:
            s.add(
                JobRun(
                    run_id=RUN,
                    job="nightly",
                    source=name,
                    status="failed" if name == "scoring" else "ok",
                    started_at=utcnow(),
                )
            )
    result = check(engine, settings)
    assert not result.ok
    assert any("scoring phase finished failed" in p for p in result.problems)


def test_an_unrecognised_job_runs_source_warns_rather_than_hiding(engine, settings):
    """The next person to add a source learns from the gate, not from archaeology."""
    from nh.db.types import utcnow
    from nh.jobs.status import check

    _collectors_ok(engine)
    with session_scope(engine) as s:
        for name, _ in PHASES:
            s.add(JobRun(run_id=RUN, job="nightly", source=name, status="ok", started_at=utcnow()))
        s.add(JobRun(run_id=RUN, job="nightly", source="mystery", status="ok", started_at=utcnow()))
    result = check(engine, settings)
    assert any("mystery" in w for w in result.warnings)
