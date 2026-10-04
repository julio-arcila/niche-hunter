"""The nightly's own orchestration: what runs, in what order, and what stops it.

These were in `tests/test_registry.py` because the sweep's tests are, and review was
right that it is the wrong home — that file is about the collector catalogue. The ones
about `run_nightly`'s control flow live here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from nh.collectors.base import deadline_for
from nh.collectors.registry import CollectorSpec
from nh.db.models import JobRun
from nh.db.session import session_scope
from nh.jobs.nightly import SWEEP_STATUS_KEY, PlannedRun, run_nightly
from nh.jobs.phases import PHASES
from nh.jobs.status import SWEEP_JOB

#: A run that started inside its day. The boundary is 00:00 UTC on the 28th.
STARTED = datetime(2026, 8, 27, 14, 10, tzinfo=UTC)
BOUNDARY = deadline_for(STARTED.date())


class _StubCollector:
    """Runs nothing and writes nothing, reporting `ok`.

    Whether it ran is read from `statuses`, not from a counter on the class: pytest may
    import this module as both `test_nightly` and `tests.test_nightly`, and `spec.load()`
    goes through `import_module`, so a class attribute can be set on one copy and read
    from the other. A status of `ok` for a source can only come from the loop having run
    it, which is the evidence the tests actually need.
    """

    source = "stub"

    def __init__(self, run_id, *, settings=None, engine=None, observed_at=None, **kw):
        self.run_id = run_id

    def run(self, job="nightly"):
        return JobRun(run_id=self.run_id, job=job, source="stub", status="ok")


def _spec(source: str) -> CollectorSpec:
    """`dotted` points at the stub in this module, so `spec.load()` resolves it for real.
    `CollectorSpec` is a frozen dataclass, so patching `load` on an instance raises."""
    return CollectorSpec(
        source=source,
        dotted="tests.test_nightly:_StubCollector",
        cadence="nightly",
        prototype="",
        ported=True,
        notes="",
    )


@pytest.fixture
def world(engine, monkeypatch, settings):
    """A nightly of two stub collectors, with the sweep and the phases spied on."""
    import nh.jobs.nightly as nightly

    calls: dict[str, int] = {"sweep": 0, "phases": 0}
    planned = [
        PlannedRun(spec=_spec("alpha"), will_run=True, reason="ready"),
        PlannedRun(spec=_spec("beta"), will_run=True, reason="ready"),
    ]
    monkeypatch.setattr(nightly, "plan", lambda only, s: planned)
    monkeypatch.setattr(nightly, "session_scope", lambda *a, **k: session_scope(engine))

    def _sweep(*a, **k):
        calls["sweep"] += 1
        return {SWEEP_STATUS_KEY: "ok"}

    def _phases(*a, **k):
        calls["phases"] += 1
        return {name: "ok" for name, _ in PHASES}

    monkeypatch.setattr(nightly, "_sweep_enrichment", _sweep)
    monkeypatch.setattr(nightly, "run_phases", _phases)
    monkeypatch.setattr(nightly, "utcnow", lambda: STARTED)
    return calls


def _clock(monkeypatch, instant):
    from nh.collectors import base

    monkeypatch.setattr(base, "utcnow", lambda: instant)


def test_an_ordinary_night_runs_the_collectors_the_sweep_and_the_phases(
    world, engine, monkeypatch, settings
):
    """The guard must not fire on a normal night: a run finishes 10:17-10:50 local against
    a boundary at 19:00, nine hours away."""
    _clock(monkeypatch, STARTED + timedelta(minutes=20))

    result = run_nightly(settings=settings, run_id="inside")

    assert result.ok, result.statuses
    assert result.statuses["alpha"] == "ok" and result.statuses["beta"] == "ok"
    assert world == {"sweep": 1, "phases": 1}


def test_a_run_already_past_its_boundary_runs_no_collector_at_all(
    world, engine, monkeypatch, settings
):
    """2026-09-21's shape: the Mac woke at 08:42 with the run frozen since the previous
    morning. `wikipedia` and `trends` wrote snapshots stamped the previous day for four
    and a half minutes past the boundary, which is why the check sits before each
    collector and not only after the loop."""
    _clock(monkeypatch, BOUNDARY + timedelta(hours=8, minutes=42))

    result = run_nightly(settings=settings, run_id="past")

    assert not result.ok
    assert world == {"sweep": 0, "phases": 0}, "the sweep and the phases were not started"
    assert result.statuses["alpha"] == "aborted"
    assert result.statuses["beta"] == "aborted"
    assert result.statuses[SWEEP_STATUS_KEY] == "aborted"
    assert all(result.statuses[name] == "aborted" for name, _ in PHASES)


def test_the_aborted_rows_are_filed_where_the_checks_look(world, engine, monkeypatch, settings):
    """Each row goes where the check that covers it reads: the sweep under
    `job=nightly:sweep, source=youtube_api`, as `_sweep_enrichment` files its own. The
    first version wrote the statuses KEY as the source under `job=nightly`, landing where
    neither `_check_sweep` nor `_check_sources` looks — and tripping the latter's
    "writes job_runs but no check covers it" warning."""
    import nh.jobs.nightly as nightly

    _clock(monkeypatch, BOUNDARY + timedelta(hours=1))
    # The nightly's own `utcnow` gives the run its `started`, and must then move PAST the
    # boundary — otherwise a version that stamped the rows with `utcnow()` would be
    # indistinguishable from one that stamps them with the run's day, and the stamp
    # assertion below would pass either way. It did, until this.
    instants = iter([STARTED])
    monkeypatch.setattr(
        nightly, "utcnow", lambda: next(instants, BOUNDARY + timedelta(hours=1))
    )

    run_nightly(settings=settings, run_id="filed")

    with session_scope(engine) as s:
        rows = s.scalars(sa.select(JobRun).where(JobRun.run_id == "filed")).all()
        filed = {(r.job, r.source) for r in rows}
        assert (SWEEP_JOB, "youtube_api") in filed
        assert ("nightly", "youtube_api:sweep") not in filed
        assert ("nightly", "alpha") in filed and ("nightly", "beta") in filed
        assert all(("nightly", name) in filed for name, _ in PHASES)
        assert all(r.status == "aborted" for r in rows)
        # Stamped with the RUN's day, never `utcnow()`: the stages did not run, so no
        # later instant belongs to them, and a post-midnight stamp would file them under
        # D+1 where `criteria._nightly_days` groups by `started_at.date()` — marking a
        # clean next day not-ok. Review's finding.
        assert all(r.started_at.date() == STARTED.date() for r in rows)
        assert all("nh compute --day 2026-08-27" in r.error for r in rows)


def test_a_run_that_crosses_the_boundary_mid_flight_stops_before_the_sweep(
    world, engine, monkeypatch, settings
):
    """The collectors began inside the day and the clock crossed while they ran — the
    2026-09-20 shape, as opposed to the 09-21 one."""
    from nh.collectors import base

    instants = iter([STARTED + timedelta(minutes=5), STARTED + timedelta(minutes=6)])
    monkeypatch.setattr(base, "utcnow", lambda: next(instants, BOUNDARY + timedelta(hours=2)))

    result = run_nightly(settings=settings, run_id="crossed")

    assert result.statuses["alpha"] == "ok" and result.statuses["beta"] == "ok", (
        "both collectors got to run"
    )
    assert world == {"sweep": 0, "phases": 0}, "the sweep and phases did not"
    assert not result.ok
    assert result.statuses[SWEEP_STATUS_KEY] == "aborted"


def test_an_only_run_never_aborts(world, engine, monkeypatch, settings):
    """A `--only` run is a debugging aid: it writes no sweep and no phases anyway, and
    aborting it would make a hand re-run of one collector look like a lost night."""
    _clock(monkeypatch, BOUNDARY + timedelta(hours=8))

    result = run_nightly(only=["alpha"], settings=settings, run_id="only")

    assert result.statuses["alpha"] == "ok"
    assert SWEEP_STATUS_KEY not in result.statuses
    assert not any(v == "aborted" for v in result.statuses.values())
