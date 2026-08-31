"""Is the pipeline actually working?

A dead-man switch guards the *process*: it fires when a run does not happen. It
cannot tell you the run happened and collected nothing. `NightlyResult.ok` counts
`skipped` as success — correct for an unported source, but once a source is ported
a vanished API key turns into days of silent non-collection behind a green ping.

`check()` is the product-level gate the cron script pings on, so "the job ran" and
"the job worked" are not confused for each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.collectors.registry import REGISTRY
from nh.config import Settings, get_settings
from nh.db.models import JobRun, KeywordMetric, VideoSnapshot
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.jobs.phases import PHASES

#: `observed_date` is a PERIOD END, so it already lags the export by up to a month
#: (ADR-0027). 70 days is that lag, plus a monthly refresh cadence, plus slack — the
#: point at which a hand-refreshed source has plainly been forgotten rather than merely
#: not refreshed yet.
KP_STALE_DAYS = 70

JOB = "nightly"


@dataclass(slots=True)
class RunLine:
    day: date
    source: str
    status: str
    quota_used: int | None
    quota_budget: int | None
    snapshots: int | None


@dataclass(slots=True)
class CheckResult:
    run_id: str | None
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def recent_runs(engine: Engine | None = None, days: int = 7) -> list[RunLine]:
    since = utcnow() - timedelta(days=days)
    with session_scope(engine) as session:
        rows = session.execute(
            sa.select(
                JobRun.started_at,
                JobRun.source,
                JobRun.status,
                JobRun.quota_used,
                JobRun.quota_budget,
                JobRun.snapshots_written,
            )
            .where(JobRun.job == JOB, JobRun.started_at >= since)
            .order_by(JobRun.started_at.desc(), JobRun.source)
        ).all()
    return [RunLine(r[0].date(), *r[1:]) for r in rows]


def snapshots_by_day(engine: Engine | None = None, days: int = 8) -> list[tuple[date, str, int]]:
    since = (utcnow() - timedelta(days=days)).date()
    with session_scope(engine) as session:
        return [
            tuple(row)
            for row in session.execute(
                sa.select(
                    VideoSnapshot.observed_date,
                    VideoSnapshot.source,
                    sa.func.count(),
                )
                .where(VideoSnapshot.observed_date >= since)
                .group_by(VideoSnapshot.observed_date, VideoSnapshot.source)
                .order_by(VideoSnapshot.observed_date.desc())
            ).all()
        ]


def check(engine: Engine | None = None, settings: Settings | None = None) -> CheckResult:
    """Green only if the latest nightly actually collected something.

    Every source that is both ported and configured must have finished `ok`, and
    the run as a whole must have written at least one snapshot. A ported source
    left unconfigured is a problem, not a legitimate skip — that is the failure
    mode this exists to catch.
    """
    settings = settings or get_settings()
    with session_scope(engine) as session:
        run_id = session.scalar(
            sa.select(JobRun.run_id)
            .where(JobRun.job == JOB)
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
        if run_id is None:
            return CheckResult(None, ["no nightly run has ever been recorded"])
        rows = session.execute(
            sa.select(
                JobRun.source,
                JobRun.status,
                JobRun.quota_used,
                JobRun.quota_budget,
                JobRun.snapshots_written,
            ).where(JobRun.run_id == run_id, JobRun.job == JOB)
        ).all()

    result = CheckResult(run_id)
    by_source = {row[0]: row for row in rows}

    # `s.manual` excluded deliberately: a manual source has no network fetch the
    # nightly could run, so its absence from a nightly run says nothing about the
    # night's health. Its freshness is the operator's job and is visible in
    # `job_runs` under its own job name (ADR-0030).
    for spec in (s for s in REGISTRY if s.ported and not s.manual):
        row = by_source.get(spec.source)
        if not settings.configured(spec.source):
            result.problems.append(
                f"{spec.source} is ported but not configured — it collected nothing"
            )
        elif row is None:
            result.problems.append(f"{spec.source} did not run")
        elif row[1] != "ok":
            result.problems.append(f"{spec.source} finished {row[1]}")
        elif row[3] and row[2] and row[2] >= row[3]:
            result.warnings.append(f"{spec.source} spent its whole quota ({row[2]}/{row[3]})")

    if sum(row[4] or 0 for row in rows) == 0:
        result.problems.append("the run wrote no snapshots")

    # Phases are not in REGISTRY, so the loop above cannot see them. Without
    # this the features phase could fail every night behind a green healthcheck
    # — the same hole this gate exists to close for collectors (ADR-0014).
    for phase, _ in PHASES:
        row = by_source.get(phase)
        if row is None:
            result.problems.append(f"{phase} phase did not run")
        elif row[1] != "ok":
            result.problems.append(f"{phase} phase finished {row[1]}")

    # Anything writing job_runs that is neither a collector nor a phase is
    # invisible to both checks above. Warn, so the next person to add one finds
    # out from the gate rather than from archaeology.
    known = {s.source for s in REGISTRY} | {p for p, _ in PHASES}
    for source in sorted(set(by_source) - known):
        result.warnings.append(f"{source} writes job_runs but no check covers it")

    # A manual source cannot fail a nightly it never joins, so staleness is the only
    # way it degrades — and it degrades silently, because every KP metric keeps
    # returning the last export's numbers with full confidence.
    #
    # A WARNING, never a problem: the export is refreshed by hand and ADR-0030 already
    # excludes manual sources from the ported-source gate above. Paging someone at 03:00
    # because a human has not opened a browser in ten weeks would train them to ignore
    # the gate.
    #
    # No rows at all produces no warning. Absence is already carried by the metrics
    # (they return NULL with a reason) and by the deferral register; warning here as
    # well would fire on every fresh database and on every fixture.
    with session_scope(engine) as session:
        newest = session.scalar(sa.select(sa.func.max(KeywordMetric.observed_date)))
    if newest is not None:
        age = (utcnow().date() - newest).days
        if age > KP_STALE_DAYS:
            result.warnings.append(
                f"keyword_planner is {age} days stale (newest period ends {newest}); "
                f"`nh kp ingest` a fresh export"
            )
    return result
