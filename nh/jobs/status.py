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
from nh.db.models import (
    ClusterMember,
    FeatureDaily,
    JobRun,
    KeywordMetric,
    Scorecard,
    VideoSnapshot,
)
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.jobs.phases import PHASES

#: `observed_date` is a PERIOD END, so it already lags the export by up to a month
#: (ADR-0027). 70 days is that lag, plus a monthly refresh cadence, plus slack — the
#: point at which a hand-refreshed source has plainly been forgotten rather than merely
#: not refreshed yet.
KP_STALE_DAYS = 70

#: Night-over-night movement in a cluster's ballast channel count, as a share of its
#: member channels, above which the gate speaks up. ADR-0047 deferred this check and
#: ADR-0050 makes it due: ballast removes over half the video rows from some
#: denominators, and until the recall sample is labelled the only thing standing between
#: a lexicon regression and a silently 3x-better number is that somebody notices the cut
#: changed size.
#:
#: **On the DELTA, never on the level.** history-of-ideas sits at 126 ballast channels of
#: 205 members by construction, and a check that fires on that fires every night forever,
#: which is how a check stops being read. 5% of members is roughly ten channels there —
#: above ordinary nightly drift, below a definition change.
BALLAST_DRIFT_SHARE = 0.05

#: Metrics that carry `detail.ballast` (`supply._ballast_detail`). Named rather than
#: scanned, so adding the stamp somewhere new is a deliberate act.
BALLAST_STAMPED = ("on_niche_share", "median_views")

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

    _check_one_run_per_day(engine, result)
    _check_ballast_drift(engine, result)
    return result


def _feature_days(session, n: int = 2) -> list[date]:
    """The `n` most recent days that have feature rows, newest first."""
    return list(
        session.scalars(
            sa.select(FeatureDaily.day)
            .group_by(FeatureDaily.day)
            .order_by(FeatureDaily.day.desc())
            .limit(n)
        )
    )


def _check_one_run_per_day(engine: Engine | None, result: CheckResult) -> None:
    """One day of features must come from one run, and its scorecards from that run.

    The defect this catches happened: `philosophy-of-science` was retired between two
    feature passes on 2026-08-31, so ten clusters carried run `5f8c2fd7` under
    `v3-non-ballast-members` while one carried `a6d35aee` under `v2-on-niche` — and its
    SCORECARD carried the converged run id over features from the older one. Provenance
    that is merely stale is a nuisance; provenance that names the wrong run is a lie, and
    data rule 1 exists to make that impossible. Nothing detected it; an independent
    reviewer did, two days later.

    A **problem**, not a warning. It means a published row does not describe how it was
    computed, which is the one thing every row is required to do, and the fix is to
    recompute or delete the day — same-day work, not a backlog item.

    Newest day only. Older days may legitimately hold a run per definition step, and
    re-litigating history on every ping would make the gate unreadable.
    """
    with session_scope(engine) as session:
        days = _feature_days(session, 1)
        if not days:
            return
        day = days[0]
        runs = sorted(
            r
            for r in session.scalars(
                sa.select(FeatureDaily.run_id).where(FeatureDaily.day == day).distinct()
            )
            if r
        )
        if len(runs) > 1:
            result.problems.append(
                f"features for {day} come from {len(runs)} runs ({', '.join(r[:8] for r in runs)}) — "
                f"a definition or seed change landed mid-day; recompute or delete the day"
            )
        cards = session.execute(
            sa.select(Scorecard.cluster_id, Scorecard.run_id).where(Scorecard.day == day)
        ).all()
        feature_run = dict(
            session.execute(
                sa.select(FeatureDaily.cluster_id, sa.func.min(FeatureDaily.run_id))
                .where(FeatureDaily.day == day)
                .group_by(FeatureDaily.cluster_id)
            ).all()
        )
        for cluster_id, card_run in cards:
            own = feature_run.get(cluster_id)
            if own is not None and card_run is not None and card_run != own:
                result.problems.append(
                    f"{cluster_id} scorecard for {day} claims run {card_run[:8]} but its "
                    f"features come from {own[:8]}"
                )


def _check_ballast_drift(engine: Engine | None, result: CheckResult) -> None:
    """Warn when a cluster's ballast cut changes size overnight (ADR-0047, ADR-0050).

    Two things it deliberately does not do. It does not fire on the LEVEL — see
    `BALLAST_DRIFT_SHARE`. And it tolerates a missing `detail.ballast` on a day where NO
    row carries one: the stamp landed on 2026-08-31 and the first nightly after it is the
    first day any row has it, so a check that demanded it would fail every run until then
    and be silenced rather than fixed. A day where SOME rows carry it and others do not is
    a different thing — that means the stamp was dropped, and it warns.
    """
    with session_scope(engine) as session:
        days = _feature_days(session, 2)
        if not days:
            return
        rows = session.execute(
            sa.select(
                FeatureDaily.day, FeatureDaily.cluster_id, FeatureDaily.name, FeatureDaily.detail
            ).where(FeatureDaily.day.in_(days), FeatureDaily.name.in_(BALLAST_STAMPED))
        ).all()
        members = dict(
            session.execute(
                sa.select(ClusterMember.cluster_id, sa.func.count())
                .where(ClusterMember.item_type == "channel")
                .group_by(ClusterMember.cluster_id)
            ).all()
        )

    stamped: dict[tuple[date, str], int] = {}
    seen: set[tuple[date, str]] = set()
    for day, cluster_id, _name, detail in rows:
        seen.add((day, cluster_id))
        ballast = (detail or {}).get("ballast")
        if isinstance(ballast, dict) and ballast.get("channels") is not None:
            stamped[(day, cluster_id)] = int(ballast["channels"])

    today = days[0]
    if stamped:  # the first-night tolerance: silent until ANY row carries the stamp
        for day, cluster_id in sorted(seen):
            if day == today and (day, cluster_id) not in stamped:
                result.warnings.append(
                    f"{cluster_id} has no detail.ballast on {day} while other rows do — "
                    f"the size of the ADR-0047 cut is unrecorded for it"
                )

    if len(days) < 2:
        return
    previous = days[1]
    for cluster_id in sorted({c for _, c in seen}):
        now = stamped.get((today, cluster_id))
        before = stamped.get((previous, cluster_id))
        if now is None or before is None:
            continue
        floor = max(members.get(cluster_id, 0), 1)
        drift = abs(now - before) / floor
        if drift > BALLAST_DRIFT_SHARE:
            result.warnings.append(
                f"{cluster_id} ballast channels moved {before} -> {now} "
                f"({drift:.1%} of {floor} members) between {previous} and {today}"
            )
    return
