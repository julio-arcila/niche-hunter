"""Nightly orchestration: run every configured collector, then features, then scoring.

One `run_id` covers the whole night, so `job_runs`, `raw_records` and every
normalized row written between dusk and dawn join back to a single execution.

A failing source degrades the night, it does not end it: each collector's
outcome is recorded in `job_runs` and the loop continues. Phases 3-4 will hang
feature and scoring passes off the end of this function.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy.engine import Engine

from nh.collectors.base import Collector, deadline_for, past_deadline_for
from nh.collectors.registry import CollectorSpec, iter_specs
from nh.collectors.youtube_api import YouTubeApiCollector
from nh.config import Settings, get_settings
from nh.db.models import JobRun
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.jobs.phases import PHASES, run_phases
from nh.jobs.status import SWEEP_JOB

#: The key `_sweep_enrichment` reports under in `NightlyResult.statuses`. Distinct from
#: every collector source so a sweep failure is visible without clobbering the primary
#: `youtube_api` status — and excluded from `NightlyResult.ok`, see there.
SWEEP_STATUS_KEY = "youtube_api:sweep"

log = logging.getLogger(__name__)


@dataclass(slots=True)
class PlannedRun:
    spec: CollectorSpec
    will_run: bool
    reason: str


@dataclass(slots=True)
class NightlyResult:
    run_id: str
    started_at: datetime
    planned: list[PlannedRun]
    statuses: dict[str, str]

    @property
    def ok(self) -> bool:
        """Every collector and phase finished, the enrichment sweep excepted.

        A failed sweep is not a failed night (ADR-0057): tonight's RSS wave keeps
        `is_short` NULL until tomorrow, which is the behaviour that existed before the
        sweep did. `status._check_sweep` warns on it. Until 2026-09-15 this counted it —
        so on 2026-09-10 a sweep 403 exited 1, pushed an alert and pinged /fail while
        `nh status --check` correctly passed the night. The exit code and the gate now
        agree.
        """
        return all(
            s in {"ok", "skipped"} for k, s in self.statuses.items() if k != SWEEP_STATUS_KEY
        )


def plan(only: list[str] | None = None, settings: Settings | None = None) -> list[PlannedRun]:
    """What tonight would do. Backs `nh nightly --dry-run`."""
    settings = settings or get_settings()
    out: list[PlannedRun] = []
    for spec in iter_specs(only):
        if not spec.ported:
            out.append(PlannedRun(spec, False, f"not ported from {spec.prototype}"))
        elif spec.manual:
            out.append(PlannedRun(spec, False, f"manual import — {spec.manual_cmd}"))
        elif not settings.configured(spec.source):
            out.append(PlannedRun(spec, False, "credentials not configured"))
        else:
            out.append(PlannedRun(spec, True, "ready"))
    return out


def _sweep_enrichment(
    run_id: str,
    started: datetime,
    settings: Settings,
    planned: list[PlannedRun],
) -> dict[str, str]:
    """Enrich what RSS discovered tonight, before the phases read it.

    The collector order is deliberate — `youtube_api` runs BEFORE `youtube_rss` so a
    channel discovered tonight gets its first feed poll the same night (ADR-0007). The
    cost of that order is that the API collector's own backfill has already finished by
    the time RSS lands its wave, and a feed supplies no duration, so `is_short` stays
    NULL until tomorrow. `eligible_videos` requires `is_short IS FALSE`, so every
    format-sensitive supply metric admitted each wave a night late and in a lump.

    A second, discovery-free pass closes it. Three things are load-bearing:

    * `JobRun.source` stays `"youtube_api"`. `_spent_today()` sums by source, so a
      distinct name would silently exempt the sweep from the per-day quota ledger, and
      `status.check`'s known-sources sweep would report a source no check covers.
    * It runs only on a full nightly. A `--only` debugging run must not spend quota it
      was not asked to spend.
    * It is skipped when `youtube_rss` did not run, because then there is no new wave to
      close and the primary run's own backfill already drained the backlog.

    A failure here is not a failed night: the wave simply lands tomorrow, which is the
    behaviour that existed before this. It reports its own status key so that is visible.
    """
    if not any(i.spec.source == "youtube_rss" and i.will_run for i in planned):
        return {}
    collector = YouTubeApiCollector(
        run_id, settings=settings, observed_at=started, backfill_only=True
    )
    record = collector.run(job=SWEEP_JOB)
    log.info(
        "%-8s %-16s quota=%s raw=%s upserts=%s",
        record.status,
        SWEEP_STATUS_KEY,
        record.quota_used,
        record.raw_written,
        record.rows_upserted,
    )
    return {SWEEP_STATUS_KEY: record.status}


def run_nightly(
    only: list[str] | None = None,
    since: date | None = None,
    *,
    settings: Settings | None = None,
    run_id: str | None = None,
) -> NightlyResult:
    settings = settings or get_settings()
    run_id = run_id or str(uuid4())
    started = utcnow()
    planned = plan(only, settings)
    statuses: dict[str, str] = {}

    # A --only run is a debugging aid, not a night's collection. Labelling it
    # separately keeps `nh status --check` judging complete runs: otherwise
    # re-running one collector by hand leaves the gate red until the next
    # scheduled fire, for no reason anyone would guess from the message.
    job = "nightly" if not only else "partial"
    log.info("%s run_id=%s since=%s", job, run_id, since)
    if _run_collectors(planned, statuses, run_id, started, settings, job, only):
        return NightlyResult(run_id=run_id, started_at=started, planned=planned, statuses=statuses)

    # And again after the collectors: a pass that began inside its day can cross the
    # boundary while it runs, which is 2026-09-20's shape exactly.
    if only is None and past_deadline_for(started.date()):
        statuses.update(_abort_past_boundary(run_id, started, job, []))
        return NightlyResult(run_id=run_id, started_at=started, planned=planned, statuses=statuses)

    if only is None:
        statuses.update(_sweep_enrichment(run_id, started, settings, planned))

    # Phases run even when a collector failed: features compute over what is real
    # and confidence says how much that was, so a dead source must not also cost
    # the night's feature history. A --only run skips them, because debugging one
    # collector should never silently rewrite today's features — `nh compute` is
    # the deliberate path for that (ADR-0014).
    if only is None:
        statuses.update(run_phases(run_id, started.date(), job=job))
    return NightlyResult(run_id=run_id, started_at=started, planned=planned, statuses=statuses)


def _run_collectors(
    planned: list[PlannedRun],
    statuses: dict[str, str],
    run_id: str,
    started: datetime,
    settings: Settings,
    job: str,
    only: list[str] | None,
) -> bool:
    """Run each planned collector in order. Returns True if the run aborted.

    The boundary is checked BEFORE each collector, not only after the loop (ADR-0066):
    `wikipedia` and `trends` write snapshots stamped `observed_date` exactly as the others
    do — on 2026-09-21 they ran 08:58:31 to 09:03:10, four and a half minutes past the
    boundary — so a check that only guarded the sweep would leave two more post-boundary
    snapshot writers, and "the run stops at its boundary" would be false. Review caught
    that; the first version of this change checked only after this loop.
    """
    for n, item in enumerate(planned):
        if not item.will_run:
            statuses[item.spec.source] = "skipped"
            log.info("skip %-16s %s", item.spec.source, item.reason)
            continue
        if only is None and past_deadline_for(started.date()):
            remaining = [i.spec.source for i in planned[n:] if i.will_run]
            statuses.update(_abort_past_boundary(run_id, started, job, remaining))
            return True
        collector_cls: type[Collector] = item.spec.load()
        collector = collector_cls(run_id, settings=settings, observed_at=started)
        record = collector.run(job=job)
        statuses[item.spec.source] = record.status
        log.info(
            "%-8s %-16s quota=%s raw=%s upserts=%s snapshots=%s",
            record.status,
            item.spec.source,
            record.quota_used,
            record.raw_written,
            record.rows_upserted,
            record.snapshots_written,
        )
    return False

def _abort_past_boundary(
    run_id: str,
    started: datetime,
    job: str,
    collectors: list[str],
    engine: Engine | None = None,
) -> dict[str, str]:
    """Record `collectors`, the sweep and every phase as `aborted`, with how to recover.

    A row per skipped stage rather than one summary line, because `status.check` reads
    `job_runs` per source and per phase: a night that silently wrote no phase rows would
    read as "the phase did not run", which is the same message a crashed phase gives.
    `aborted` is distinct from `failed` on purpose — nothing went wrong, the night simply
    ran out of its own day — and from `skipped`, which means "not configured" and is
    counted as fine.

    Each row is filed where the check that covers it will look: the sweep under
    `job=SWEEP_JOB, source="youtube_api"`, as `_sweep_enrichment` files its own, so
    `status._check_sweep` sees it and `_check_sources`' unknown-source sweep does not warn
    about a source nothing covers. The first version wrote it as `source="youtube_api:sweep"`
    under `job="nightly"` — the statuses KEY, which is not a source — and review found it
    landing where neither check looks.

    `started_at` is the run's own start, not `utcnow()`. The stages did not run, so there
    is no later instant that belongs to them, and a post-midnight `utcnow()` would file
    them under D+1 — where `criteria._nightly_days` groups by `started_at.date()` and
    would mark a clean D+1 not-ok. Also review's.

    What this does NOT do is recompute. The features for the day are a hand step, and the
    operator is reading the page anyway because the night is already not `ok`.
    """
    day = started.date()
    reason = (
        f"past this run's day boundary ({deadline_for(day).isoformat()}): "
        f"a reading taken now is not a reading of {day}. "
        f"Recover the phases with: nh compute --day {day}"
    )
    log.warning("aborting at the day boundary: %s", reason)
    rows = [(source, job, source) for source in collectors]
    rows.append((SWEEP_STATUS_KEY, SWEEP_JOB, "youtube_api"))
    rows.extend((name, job, name) for name, _ in PHASES)
    with session_scope(engine) as session:
        for _, row_job, source in rows:
            session.add(
                JobRun(
                    run_id=run_id,
                    job=row_job,
                    source=source,
                    status="aborted",
                    started_at=started,
                    finished_at=started,
                    error=reason[:4000],
                )
            )
    return {key: "aborted" for key, _, _ in rows}
