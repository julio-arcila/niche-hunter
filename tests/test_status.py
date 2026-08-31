"""The product-level gate.

`nh nightly` exiting 0 means the process finished. It does not mean anything was
collected: a ported source whose credentials vanished is recorded as `skipped`,
and `NightlyResult.ok` counts that as success. Left alone, that is seven silent
days of no collection behind seven green healthchecks pings.
"""

from __future__ import annotations

from datetime import timedelta

from nh.collectors.registry import REGISTRY
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


def test_sources_that_cannot_run_tonight_are_not_expected_to(settings, engine):
    """Two different reasons, and the gate must honour both.

    `reddit` is **unported** — no code exists. `keyword_planner` is **ported but
    manual** (ADR-0030): its data arrives as a CSV a human downloads, so it has no
    network fetch the nightly could run and its absence from a nightly says nothing
    about the night's health. Before manual sources existed this test passed for one
    reason; it now passes for two, and conflating them would let a real regression —
    a ported, schedulable source silently collecting nothing — hide behind the same
    green.
    """
    _healthy(engine)
    result = check(engine, settings)
    assert not any("reddit" in p for p in result.problems)
    assert not any("keyword_planner" in p for p in result.problems)

    by_source = {s.source: s for s in REGISTRY}
    assert not by_source["reddit"].ported
    assert by_source["keyword_planner"].ported and by_source["keyword_planner"].manual


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


def test_a_stale_keyword_planner_export_warns_but_does_not_fail(settings, engine):
    """A manual source cannot fail a nightly it never joins, so staleness is the only
    way it degrades — and it degrades silently, because every KP metric goes on
    returning the last export's numbers at full confidence.

    A warning rather than a problem: ADR-0030 already excludes manual sources from the
    ported-source gate, and paging someone because a human has not opened a browser in
    ten weeks would train them to ignore the gate.
    """
    from datetime import date

    from nh.db.models import KeywordMetric
    from nh.jobs.status import KP_STALE_DAYS

    _healthy(engine)
    stale = (utcnow().date() - timedelta(days=KP_STALE_DAYS + 5)).replace(day=1)
    with session_scope(engine) as s:
        s.add(
            KeywordMetric(
                keyword="inflation",
                geo="US",
                lang="en",
                observed_date=stale,
                source="keyword_planner",
                run_id=RUN_ID,
                at=utcnow(),
            )
        )
    result = check(engine, settings)

    assert result.ok, "a stale manual export is not a failed night"
    assert any("keyword_planner is" in w and "stale" in w for w in result.warnings)
    assert not any("keyword_planner" in p for p in result.problems)
    assert isinstance(stale, date)


def test_no_keyword_planner_rows_at_all_is_silent(settings, engine):
    """Absence is already carried by the metrics, which return NULL with a reason, and
    by the deferral register. Warning here as well would fire on every fresh database
    and on every fixture that does not happen to seed an export."""
    _healthy(engine)
    result = check(engine, settings)

    assert result.ok
    assert not any("keyword_planner" in w for w in result.warnings)


# --- provenance and the ballast cut ------------------------------------------------
#
# Both of these guard defects that HAPPENED and that nothing detected: a retirement
# landing between two feature passes left one cluster's scorecard naming a run its
# features did not come from (ADR-0044 addendum), and ADR-0047 removed over half the
# video rows from some denominators with no stored record of how big the cut was.


def _feature(engine, cluster_id, day, name="on_niche_share", run_id=RUN_ID, ballast=None):
    from nh.db.models import FeatureDaily

    detail = {"definition": "v3-non-ballast-members"}
    if ballast is not None:
        detail["ballast"] = {"active": True, "n": 10, "channels": ballast, "rows": ballast * 12}
    with session_scope(engine) as s:
        s.add(
            FeatureDaily(
                cluster_id=cluster_id,
                day=day,
                metric_group="supply",
                name=name,
                value=0.2,
                confidence=0.5,
                inputs_n=10,
                detail=detail,
                source="features",
                run_id=run_id,
                at=utcnow(),
            )
        )


def _members(engine, cluster_id, n):
    from nh.db.models import ClusterMember

    with session_scope(engine) as s:
        for i in range(n):
            s.add(
                ClusterMember(
                    cluster_id=cluster_id,
                    item_type="channel",
                    item_id=f"{cluster_id}-ch{i}",
                    confidence=1.0,
                    is_noise=False,
                    source="clustering",
                    run_id=RUN_ID,
                    at=utcnow(),
                )
            )


def test_two_runs_on_one_feature_day_is_a_problem(settings, engine):
    """The 2026-08-31 defect, reproduced: a retirement between two passes.

    A problem and not a warning, because a row that does not describe how it was
    computed breaks data rule 1, and the fix is same-day — recompute or delete.
    """
    from datetime import date

    _healthy(engine)
    day = date(2026, 8, 31)
    _feature(engine, "kept", day, run_id=RUN_ID)
    _feature(engine, "retired", day, run_id="aaaaaaaa-0000-0000-0000-000000000000")
    result = check(engine, settings)

    assert not result.ok
    assert any("come from 2 runs" in p for p in result.problems)


def test_a_scorecard_naming_a_run_its_features_did_not_come_from_is_a_problem(settings, engine):
    """The sharper half of the same defect: not a stale row, an untrue one.

    `philosophy-of-science`'s 2026-08-31 scorecard carried the CONVERGED run id over
    features computed by an earlier run under an earlier definition. Stale provenance is
    a nuisance; provenance that names the wrong run is a lie.
    """
    from datetime import date

    from nh.db.models import Scorecard

    _healthy(engine)
    day = date(2026, 8, 31)
    _feature(engine, "retired", day, run_id="aaaaaaaa-0000-0000-0000-000000000000")
    with session_scope(engine) as s:
        s.add(
            Scorecard(
                cluster_id="retired",
                day=day,
                source="features",
                run_id=RUN_ID,  # the converged run — not the one that wrote the features
                at=utcnow(),
            )
        )
    result = check(engine, settings)

    assert not result.ok
    assert any("scorecard for" in p and "claims run" in p for p in result.problems)


def test_a_single_run_over_one_day_is_silent(settings, engine):
    from datetime import date

    _healthy(engine)
    day = date(2026, 8, 31)
    for cluster in ("a", "b", "c"):
        _feature(engine, cluster, day)
    assert check(engine, settings).ok


def test_a_jump_in_the_ballast_cut_warns(settings, engine):
    """A lexicon regression shows up here first: channels tip into ballast in a batch,
    and the denominators they leave make every share metric look better overnight."""
    from datetime import date

    _healthy(engine)
    _members(engine, "shifting", 200)
    _feature(engine, "shifting", date(2026, 8, 30), ballast=100)
    _feature(engine, "shifting", date(2026, 8, 31), ballast=130)  # +30 of 200 = 15%
    result = check(engine, settings)

    assert result.ok, "drift is a warning, not a failed night"
    assert any("ballast channels moved 100 -> 130" in w for w in result.warnings)


def test_a_high_but_steady_ballast_level_is_silent(settings, engine):
    """The property that keeps this check readable. history-of-ideas sits at 126 ballast
    channels of 205 members by construction; a check that fires on the level fires every
    night forever, and a check nobody reads is worse than no check."""
    from datetime import date

    _healthy(engine)
    _members(engine, "history-of-ideas", 205)
    _feature(engine, "history-of-ideas", date(2026, 8, 30), ballast=126)
    _feature(engine, "history-of-ideas", date(2026, 8, 31), ballast=128)  # +2 of 205 = 1%
    result = check(engine, settings)

    assert result.ok
    assert not any("ballast" in w for w in result.warnings)


def test_no_ballast_stamp_anywhere_is_tolerated(settings, engine):
    """The first-night rule. The stamp landed 2026-08-31 and no stored row carries one
    until the next nightly writes it; a check that demanded it immediately would fail
    every run until then, and would be silenced rather than fixed."""
    from datetime import date

    _healthy(engine)
    _feature(engine, "unstamped", date(2026, 8, 30))
    _feature(engine, "unstamped", date(2026, 8, 31))
    result = check(engine, settings)

    assert result.ok
    assert not any("ballast" in w for w in result.warnings)


def test_a_stamp_dropped_on_only_some_clusters_warns(settings, engine):
    """Distinct from the case above and must not collapse into it: if some rows carry
    the stamp and others do not, the stamp was lost rather than not yet arrived."""
    from datetime import date

    _healthy(engine)
    day = date(2026, 8, 31)
    _feature(engine, "stamped", day, ballast=10)
    _feature(engine, "dropped", day)
    result = check(engine, settings)

    assert result.ok
    assert any("dropped" in w and "no detail.ballast" in w for w in result.warnings)
