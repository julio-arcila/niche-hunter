"""Is the pipeline actually working?

A dead-man switch guards the *process*: it fires when a run does not happen. It
cannot tell you the run happened and collected nothing. `NightlyResult.ok` counts
`skipped` as success — correct for an unported source, but once a source is ported
a vanished API key turns into days of silent non-collection behind a green ping.

`check()` is the product-level gate the nightly script pings on (launchd since
2026-08-30, ADR — see RUNBOOK 'Scheduling'; the backup stays on cron for Full Disk Access), so "the job ran" and
"the job worked" are not confused for each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.collectors.registry import REGISTRY
from nh.collectors.youtube_api import read_on, watchlist_population
from nh.config import Settings, get_settings
from nh.db.models import (
    ClusterMember,
    FeatureDaily,
    JobRun,
    KeywordMetric,
    Scorecard,
    Video,
    VideoSnapshot,
)
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.features.inputs import BALLAST_DRIFT_SHARE, BALLAST_RAMP_DAYS, BALLAST_RAMP_SHARE
from nh.jobs.phases import PHASES

#: `observed_date` is a PERIOD END, so it already lags the export by up to a month
#: (ADR-0027). 70 days is that lag, plus a monthly refresh cadence, plus slack — the
#: point at which a hand-refreshed source has plainly been forgotten rather than merely
#: not refreshed yet.
KP_STALE_DAYS = 70

#: Imported, not restated: INSIGHT_RULES' Rule 2 fires on the same threshold, and a
#: gate and an alert disagreeing about what "a big move" is would be a defect nobody
#: could see from either file. See `features.inputs.BALLAST_DRIFT_SHARE` for why the
#: check is on the delta and never the level.

#: Metrics that carry `detail.ballast` (`supply._ballast_detail`). Named rather than
#: scanned, so adding the stamp somewhere new is a deliberate act.
BALLAST_STAMPED = ("on_niche_share", "median_views")

#: Share of the day's budget above which `check()` speaks up. The ROADMAP's number
#: (Slice 8's ships-list). A normal single nightly spends 68-76% — measured 6,447 to
#: 7,190 units across 2026-08-28..08-31 — so this is silent on an ordinary night and
#: fires when a same-day re-run has happened.
QUOTA_WARN_SHARE = 0.85

JOB = "nightly"

#: The ADR-0057 enrichment sweep's own job name. Distinct from JOB so it cannot be
#: mistaken for the night's youtube_api collection by anything reading `job_runs` by
#: source — its SOURCE deliberately stays "youtube_api" so `_spent_today()` keeps
#: charging its quota to the day. `_check_sweep` is what watches it.
SWEEP_JOB = "nightly:sweep"

#: Below this, the channel-reach outcome is being censored again (ADR-0059). Deleted and
#: private videos are the only legitimate misses, well under 1% of a window; 0.9 leaves
#: room for them and still catches a capped, budget-cut or skipped night.
WATCHLIST_MIN_COVERAGE = 0.9
#: A handful of videos is not a population to measure coverage on.
WATCHLIST_MIN_POPULATION = 50


def quota_day(engine: Engine | None = None, settings: Settings | None = None) -> tuple[int, int]:
    """`(spent, budget)` for the CURRENT Pacific quota day, across every run.

    One helper, three consumers — `check()`, `nh status`, and `criteria.c6_bounded` —
    because three copies of a timezone-sensitive sum is three chances to reproduce
    ADR-0049's UTC-versus-Pacific trap independently. This repo has walked into it twice.

    **Deliberately not shared with `YouTubeApiCollector._spent_today`.** That one anchors
    on the run's own `observed_at` rather than on now, which is correct for enforcement
    and is the path with tests since Slice 1. Two functions that look alike but answer
    "what may this run still spend" and "what has today spent" are not duplication.
    """
    from zoneinfo import ZoneInfo

    settings = settings or get_settings()
    start = datetime.now(ZoneInfo("America/Los_Angeles")).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    with session_scope(engine) as session:
        spent = (
            session.scalar(
                sa.select(sa.func.coalesce(sa.func.sum(JobRun.quota_used), 0)).where(
                    JobRun.source == "youtube_api",
                    JobRun.started_at >= start.astimezone(UTC),
                )
            )
            or 0
        )
    return int(spent), settings.yt_quota_budget


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
    by_source = _worst_per_source(rows)

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
            # `job_runs.quota_budget` records the run's REMAINING slice of the day, not
            # the day's budget — the collector seeds its ledger with `budget - spent
            # today`. So this now means "this run was cut short by the day cap", a
            # different signal from the day-headroom warning below.
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

    spent, budget = quota_day(engine, settings)
    if budget and spent >= budget * QUOTA_WARN_SHARE:
        result.warnings.append(
            f"quota day is {spent / budget:.0%} spent ({spent:,}/{budget:,}); "
            f"a re-run today has {max(budget - spent, 0):,} units of headroom"
        )

    _check_one_run_per_day(engine, result)
    _check_ballast_drift(engine, result)
    _check_sweep(engine, run_id, result)
    _check_watchlist(engine, run_id, result)
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


def _warn_on_a_dropped_stamp(
    result: CheckResult,
    today: date,
    seen: set[tuple[date, str]],
    stamped: dict[tuple[date, str], int],
) -> None:
    """The first-night tolerance, and the case it must not swallow.

    Silent while NO row carries `detail.ballast` — the stamp landed 2026-08-31 and the
    first nightly after it is the first day any row has one, so demanding it earlier
    would fail every run until then and be silenced rather than fixed. But once some
    rows carry it, a cluster missing it means the stamp was dropped, and that is a
    different thing from "not yet arrived".
    """
    if not stamped:
        return
    for day, cluster_id in sorted(seen):
        if day == today and (day, cluster_id) not in stamped:
            result.warnings.append(
                f"{cluster_id} has no detail.ballast on {day} while other rows do — "
                f"the size of the ADR-0047 cut is unrecorded for it"
            )


def _worst_per_source(rows: list) -> dict[str, tuple]:
    """One row per source, and a FAILURE always wins.

    This was `{row[0]: row for row in rows}` — a dict comprehension over an unordered
    query, so whichever row the driver returned last silently became the source's
    verdict. That was survivable only while every source wrote exactly one row per run.
    ADR-0057's enrichment sweep broke that assumption: it writes a second `youtube_api`
    row, deliberately, so `_spent_today()` keeps counting its quota — and being inserted
    last, its `ok` masked a FAILED primary collection. A dead API key would then page
    nobody, which is the precise failure `check` exists to close.

    The sweep now carries its own `job` and never reaches this query. This stays anyway:
    the trap is in the aggregation, not in the sweep, and the next source to write twice
    should not have to rediscover it.
    """
    worst: dict[str, tuple] = {}
    for row in rows:
        seen = worst.get(row[0])
        if seen is None or (seen[1] == "ok" and row[1] != "ok"):
            worst[row[0]] = row
    return worst


def _check_sweep(engine: Engine | None, run_id: str, result: CheckResult) -> None:
    """A failed enrichment sweep warns; it does not page.

    The night collected — the sweep only decides whether tonight's RSS wave gets its
    duration tonight or tomorrow, and tomorrow is the behaviour that existed before
    ADR-0057. But a pass that silently stops running is exactly how the enrichment lag
    would come back unnoticed, so it must be visible.
    """
    with session_scope(engine) as session:
        statuses = list(
            session.scalars(
                sa.select(JobRun.status).where(JobRun.run_id == run_id, JobRun.job == SWEEP_JOB)
            )
        )
    for status in statuses:
        if status != "ok":
            result.warnings.append(
                f"the enrichment sweep finished {status} — tonight's RSS wave keeps "
                f"is_short NULL until tomorrow's nightly (ADR-0057)"
            )


def _check_watchlist(engine: Engine | None, run_id: str, result: CheckResult) -> None:
    """Warn when the watched videos lack the reading the registered outcome needs.

    Measured from stored rows against the collector's own population, not from a flag the
    collector sets: of the long-form videos of small active-cluster members aged 14-17 on
    the night's observed date, how many carry a snapshot for that date from ANY source.
    A warning, never a page: the night collected, and the [14, 17] reading window absorbs
    three short nights before any single video's reading is lost.
    """
    with session_scope(engine) as session:
        started = session.scalar(
            sa.select(sa.func.min(JobRun.started_at)).where(JobRun.run_id == run_id)
        )
        if started is None:
            return
        day = started.date()
        ids = watchlist_population(day).subquery()
        total = session.scalar(sa.select(sa.func.count()).select_from(ids)) or 0
        if total < WATCHLIST_MIN_POPULATION:
            return
        read = (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(Video)
                .where(Video.video_id.in_(sa.select(ids.c.video_id)), read_on(day))
            )
            or 0
        )
    if read / total < WATCHLIST_MIN_COVERAGE:
        result.warnings.append(
            f"channel-reach watchlist: {read} of {total} videos aged 14-17 have a reading "
            f"on {day} ({read / total:.0%}) — the pre-registered 14-day outcome is being "
            f"censored (ADR-0059)"
        )


def _read_stamps(
    rows: list,
) -> tuple[set[tuple[date, str]], dict[tuple[date, str], int], dict[tuple[date, str], str | None]]:
    """Every (day, cluster) seen; the ballast channel count where stamped; the definition.

    `definition` is read the way Rule 2 reads it, `(detail or {}).get("definition")`, so
    the two checks agree on what a step is. A stamped row without a definition is
    unwritable — both `BALLAST_STAMPED` metrics write the two keys into one dict — so
    there is deliberately no guard for it.
    """
    seen: set[tuple[date, str]] = set()
    stamped: dict[tuple[date, str], int] = {}
    definition: dict[tuple[date, str], str | None] = {}
    for day, cluster_id, _name, detail in rows:
        seen.add((day, cluster_id))
        definition[(day, cluster_id)] = (detail or {}).get("definition")
        ballast = (detail or {}).get("ballast")
        if isinstance(ballast, dict) and ballast.get("channels") is not None:
            stamped[(day, cluster_id)] = int(ballast["channels"])
    return seen, stamped, definition


def _check_ballast_ramp(
    result: CheckResult,
    days: list[date],
    stamped: dict[tuple[date, str], int],
    definition: dict[tuple[date, str], str | None],
    members: dict[str, int],
) -> None:
    """Warn on cumulative ballast movement the per-night wire cannot see.

    `_check_ballast_drift` compares two adjacent days, so a cluster can ramp
    indefinitely while every single night stays under `BALLAST_DRIFT_SHARE`. That is
    not hypothetical — see `BALLAST_RAMP_SHARE` for the run that did it. This compares
    today against the OLDEST of the stored days in the window, on the delta and never
    the level, and says nothing when the window holds fewer than three days: two days
    is what the nightly wire already covers, and warning twice about one step teaches
    the operator to skim.

    The window is scoped to days sharing TODAY's `detail.definition`. Values either side
    of a definition step are not comparable — that is Rule 2's rule
    (`scoring.rules.definition_step`), and a ramp check that ignored it would re-report
    every planned step as a flood. The first version did exactly that: on 2026-09-14 the
    ballast cut reverted, `channels` went ~137 -> 0 on every cluster, and this anchored on
    a v3 day and warned on 8 of 10 clusters — and would have every night until the last
    v3 day scrolled out on 09-19. `definition` rather than `ballast.active`, because a
    future definition bump with no active change is reachable and would re-fire the same
    defect one step later.
    """
    if len(days) < 3:
        return
    today = days[0]
    for cluster_id in sorted({c for _, c in stamped}):
        now = stamped.get((today, cluster_id))
        if now is None:
            continue
        # The OLDEST STAMPED day, not the oldest day: the stamp landed on 2026-08-31 and
        # a window reaching past it holds days that carry no ballast at all. Anchoring on
        # days[-1] would make this check silently unfireable for its first week, which is
        # the failure mode where a check reads green because it never runs.
        today_def = definition.get((today, cluster_id))
        anchored = [
            (d, stamped[(d, cluster_id)])
            for d in reversed(days)
            if (d, cluster_id) in stamped and definition.get((d, cluster_id)) == today_def
        ]
        if len(anchored) < 3:
            continue
        oldest, before = anchored[0]
        floor = max(members.get(cluster_id, 0), 1)
        ramp = abs(now - before) / floor
        if ramp > BALLAST_RAMP_SHARE:
            result.warnings.append(
                f"{cluster_id} ballast channels ramped {before} -> {now} "
                f"({ramp:.1%} of {floor} members) across {len(anchored)} stored days, "
                f"{oldest} to {today} — cumulative, may not have tripped the nightly check"
            )


def _check_ballast_drift(engine: Engine | None, result: CheckResult) -> None:
    """Warn when a cluster's ballast cut changes size overnight (ADR-0047, ADR-0050).

    Two things it deliberately does not do. It does not fire on the LEVEL — see
    `BALLAST_DRIFT_SHARE`. And it tolerates a missing `detail.ballast` on a day where NO
    row carries one: the stamp landed on 2026-08-31 and the first nightly after it is the
    first day any row has it, so a check that demanded it would fail every run until then
    and be silenced rather than fixed. A day where SOME rows carry it and others do not is
    a different thing — that means the stamp was dropped, and it warns.

    Deliberately NOT scoped to a definition, unlike `_check_ballast_ramp`: a definition
    step moves the count once, this reports it once, and the next night compares two
    days on the same side. CLAUDE.md says to expect it on 2026-09-14, and it did.
    """
    with session_scope(engine) as session:
        days = _feature_days(session, BALLAST_RAMP_DAYS)
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

    seen, stamped, definition = _read_stamps(rows)

    today = days[0]
    _warn_on_a_dropped_stamp(result, today, seen, stamped)

    _check_ballast_ramp(result, days, stamped, definition, members)

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
