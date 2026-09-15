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

from nh.collectors.base import Collector
from nh.collectors.registry import CollectorSpec, iter_specs
from nh.collectors.youtube_api import YouTubeApiCollector
from nh.config import Settings, get_settings
from nh.db.types import utcnow
from nh.jobs.phases import run_phases
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
    for item in planned:
        if not item.will_run:
            statuses[item.spec.source] = "skipped"
            log.info("skip %-16s %s", item.spec.source, item.reason)
            continue
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
