"""The computation phases that run after the collectors.

Phases are not collectors: no fetch, no normalize, no quota, no raw payloads.
They share exactly two things with them, both extracted rather than inherited —
provenance stamping (`nh.db.provenance.stamp`) and the write layer
(`nh.db.upsert`). See ADR-0014.

Each phase gets its own `job_runs` row under the night's `run_id`, which is what
lets `nh status --check` see a broken scoring phase instead of reporting green
while the product quietly stops being computed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from functools import partial

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from nh.clustering import phase as clustering
from nh.db.models import JobRun
from nh.db.provenance import Stamp, stamp
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.features import run as features_run
from nh.features.inputs import pinned_ballast
from nh.scoring import rules, scorecard

log = logging.getLogger(__name__)

Phase = Callable[[Session, date, Stamp], int]

#: Order is dependency order: features need clusters, scoring needs features.
#: `nh.jobs.status.check` reads this, so adding one here extends the gate.
PHASES: tuple[tuple[str, Phase], ...] = (
    ("clustering", clustering.assign),
    ("features", features_run.compute),
    ("scoring", scorecard.build),
    # Last: every rule reads what the earlier phases wrote, and an alert derived from a
    # half-computed day would be worse than no alert. A failing phase does not stop the
    # next, so a broken rule cannot cost a night's features.
    ("rules", rules.evaluate),
)


def run_phases(
    run_id: str,
    day: date,
    *,
    job: str = "nightly",
    engine: Engine | None = None,
) -> dict[str, str]:
    """Run every phase in order, recording each in `job_runs`.

    A failing phase is recorded and the next one still runs — same posture as a
    failing collector. Features computed from partial inputs are worth having, and
    `confidence` is what says how partial they were.

    Wrapped in `pinned_ballast` so the whole run computes under one definition. A run
    started at 23:58 on 2026-09-13 would otherwise cross ADR-0050's sunset mid-way and
    write two definitions under one `run_id` — the mixed-day defect ADR-0044's addendum
    repairs, arriving on a schedule nobody chose rather than from an operator's edit.
    """
    at = utcnow()
    with pinned_ballast():
        return {
            name: _run_phase(name, fn, run_id, day, job, at, engine).status for name, fn in PHASES
        }


def _run_phase(
    name: str,
    fn: Phase,
    run_id: str,
    day: date,
    job: str,
    at,
    engine: Engine | None,
) -> JobRun:
    record = JobRun(run_id=run_id, job=job, source=name, status="running", started_at=utcnow())
    mark = partial(stamp, source=name, run_id=run_id, at=at)
    with session_scope(engine) as session:
        session.add(record)
        session.commit()
        try:
            record.rows_upserted = fn(session, day, mark)
            session.commit()
            record.status = "ok"
            log.info("ok       %-16s rows=%s", name, record.rows_upserted)
        except Exception as exc:
            session.rollback()
            record.status = "failed"
            record.error = f"{type(exc).__name__}: {exc}"[:4000]
            log.exception("%s phase failed", name)
        finally:
            record.finished_at = utcnow()
    return record
