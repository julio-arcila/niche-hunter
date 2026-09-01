"""The eight production criteria, and the proof that each can FAIL.

Every test here is the same shape: remove or spoil the evidence, assert the criterion goes
red. That is the whole point of the file. A command that grades the repo against its own
definition of done is trivially written so it always passes, and the result is worse than no
command — it converts an unexamined belief into an artefact that looks examined.

The failure it guards against is not hypothetical. `c7_lawful`'s first version counted every
`reviewed <date>` anywhere in SOURCES.md, found one, and reported MET — on a repo where one
of six sources had a dated review. It was green because the evidence it happened to find was
recent, which is exactly how a self-grader lies.

Tests take an explicit engine and a seeded fixture, never the live database. `test_deferrals`
has a known defect where `fires()` reads live rows and the verdict moves with the corpus;
this file does not repeat it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from nh.db.models import JobRun
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.jobs import criteria


def _night(engine, days_ago: int, *, status: str = "ok", source: str = "youtube_api"):
    with session_scope(engine) as s:
        s.add(
            JobRun(
                run_id=f"r{days_ago}-{source}",
                job="nightly",
                source=source,
                status=status,
                started_at=utcnow() - timedelta(days=days_ago),
                quota_used=100,
            )
        )


# --- C1: the clock ------------------------------------------------------------------


def test_c1_counts_consecutive_all_ok_nights(engine):
    for d in range(criteria.UNATTENDED_NIGHTS):
        _night(engine, d)
    assert criteria.c1_unattended(engine).met is True


def test_c1_is_not_met_one_night_short(engine):
    for d in range(criteria.UNATTENDED_NIGHTS - 1):
        _night(engine, d)
    result = criteria.c1_unattended(engine)
    assert result.met is False
    assert f"{criteria.UNATTENDED_NIGHTS - 1}/{criteria.UNATTENDED_NIGHTS}" in result.detail


def test_c1_a_gap_restarts_the_clock(engine):
    """2026-08-30 is a permanent hole. A criterion that counted *total* good nights rather
    than consecutive ones would have read green through it, which is the opposite of what
    'unattended for 30 nights' claims."""
    for d in list(range(5)) + list(range(6, 40)):  # a hole at day 5
        _night(engine, d)
    result = criteria.c1_unattended(engine)
    assert result.met is False
    assert result.detail.startswith("5/30")


def test_c1_a_failed_source_disqualifies_the_night(engine):
    """A night someone had to look at is not an unattended night."""
    for d in range(criteria.UNATTENDED_NIGHTS):
        _night(engine, d)
    _night(engine, 3, status="failed", source="youtube_rss")
    assert criteria.c1_unattended(engine).met is False


# --- C2 / C3 / C4: evidence read from files -----------------------------------------


def test_c2_distinguishes_routing_from_timing(monkeypatch, tmp_path):
    """Two different claims. A ping that reaches a phone does not show that a MISSING ping
    is noticed, and only the first was ever run — so the criterion must not read green off
    the half that was."""
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(criteria, "ROOT", tmp_path)

    (docs / "RUNBOOK.md").write_text("alert routing verified 2026-08-27\n")
    half = criteria.c2_alarmed()
    assert half.met is False and "MISSING ping" in half.detail

    (docs / "RUNBOOK.md").write_text(
        "alert routing verified 2026-08-27\nmissed-ping detection verified 2026-09-05\n"
    )
    assert criteria.c2_alarmed().met is True


def _drill_log(tmp_path, *ages_in_days, offsite=True):
    """A restore log with passes N days old.

    **Relative to today, never literal dates.** The first version wrote 2026-09-01 and
    2026-09-02, which passed on the day it was written and would have started failing 46
    days later when `DRILL_STALE_DAYS` caught up with them — a test that rots into a
    false alarm is worse than no test, and this file's whole subject is graders that lie.
    """
    (tmp_path / "logs").mkdir(exist_ok=True)
    today = datetime.now(tz=UTC).date()
    lines = []
    for i, age in enumerate(ages_in_days):
        tag = " [offsite b2://]" if offsite and i == 0 else ""
        lines.append(f"{today - timedelta(days=age)} restore drill passed for x.db.gz{tag}")
    (tmp_path / "logs" / "restore.log").write_text("\n".join(lines) + "\n")


def test_c3_needs_logged_passes_not_a_script(monkeypatch, tmp_path):
    """'A drill, performed, twice.' A restore script that has never been run is a plan."""
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr(criteria, "ROOT", tmp_path)

    assert criteria.c3_recoverable().met is False

    _drill_log(tmp_path, 1)
    assert criteria.c3_recoverable().met is False, "one drill is not twice"

    _drill_log(tmp_path, 1, 30)
    result = criteria.c3_recoverable()
    assert result.met is True and "offsite arm exercised" in result.detail


def test_c3_goes_stale_when_the_schedule_dies(monkeypatch, tmp_path):
    """The clause that makes the monthly agent load-bearing.

    Without it, two drills in 2026 kept this green in 2027 — so a scheduled drill would
    have had a success and a failure that were equally invisible to the grader. A job
    whose death nobody notices is the auto-helpdesk pattern the RUNBOOK has a scar from.
    """
    monkeypatch.setattr(criteria, "ROOT", tmp_path)

    _drill_log(tmp_path, criteria.DRILL_STALE_DAYS - 1, criteria.DRILL_STALE_DAYS + 40)
    assert criteria.c3_recoverable().met is True, "inside the window, two passes: met"

    _drill_log(tmp_path, criteria.DRILL_STALE_DAYS + 1, criteria.DRILL_STALE_DAYS + 40)
    stale = criteria.c3_recoverable()
    assert stale.met is False
    assert "ago" in stale.detail, "and it says how old the newest pass is"


def test_c3_says_when_only_the_local_arm_was_tested(monkeypatch, tmp_path):
    """A local restore tests gzip and SQLite. It says nothing about whether the offsite
    object is readable with the key we hold."""
    monkeypatch.setattr(criteria, "ROOT", tmp_path)
    _drill_log(tmp_path, 1, 2, offsite=False)
    assert "LOCAL ONLY" in criteria.c3_recoverable().detail


def test_c4_requires_the_null_not_just_a_number(monkeypatch, tmp_path):
    """ADR-0055 reads C4 as asking for a CHARACTERISED correlation. A report with a rho and
    no null distribution is the uncharacterised kind, and must not pass."""
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(criteria, "ROOT", tmp_path)
    report = reports / "backtest_2026-08-28.md"

    report.write_text("rho 0.091 and nothing else\n")
    result = criteria.c4_calibrated()
    assert result.met is False and "null" in result.detail and "universe" in result.detail

    report.write_text("rho 0.091, permutation null, survivorship is the limitation\n")
    assert criteria.c4_calibrated().met is True


def test_c4_is_not_met_without_the_report(monkeypatch, tmp_path):
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(criteria, "ROOT", tmp_path)
    assert criteria.c4_calibrated().met is False


# --- C5 / C7 / C8 -------------------------------------------------------------------


def test_c5_fails_when_a_metric_has_no_drilldown(monkeypatch):
    from nh.api import drilldown

    assert criteria.c5_traceable().met is True
    monkeypatch.setattr(drilldown, "REGISTRY", {})
    assert criteria.c5_traceable().met is False


def test_c7_needs_a_review_per_source_not_one_anywhere(monkeypatch, tmp_path):
    """The bug this file exists for. The first version counted every `reviewed <date>` in
    the file, found one, and reported MET on a repo where five of six sources had none."""
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(criteria, "ROOT", tmp_path)
    from nh.collectors.registry import REGISTRY

    (docs / "SOURCES.md").write_text("## trends\nCollector reviewed 2026-08-27.\n")
    one = criteria.c7_lawful()
    assert one.met is False
    assert f"1/{len(REGISTRY)}" in one.detail
    assert "reddit" in one.detail, "and it names what is missing"

    today = datetime.now(tz=UTC).date()
    (docs / "SOURCES.md").write_text(
        "".join(f"## {s.source}\nreviewed {today}\n" for s in REGISTRY)
    )
    assert criteria.c7_lawful().met is True


def test_c7_goes_stale(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(criteria, "ROOT", tmp_path)
    from nh.collectors.registry import REGISTRY

    old = datetime.now(tz=UTC).date() - timedelta(days=criteria.REVIEW_STALE_DAYS + 1)
    (docs / "SOURCES.md").write_text("".join(f"## {s.source}\nreviewed {old}\n" for s in REGISTRY))
    assert criteria.c7_lawful().met is False


def test_c8_fails_on_stale_fixtures(monkeypatch, tmp_path):
    import os

    fixtures = tmp_path / "tests" / "fixtures"
    fixtures.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run_nightly.sh").touch()
    monkeypatch.setattr(criteria, "ROOT", tmp_path)

    recorded = fixtures / "a.json"
    recorded.write_text("{}")
    assert criteria.c8_maintainable().met is True

    stale = (datetime.now(tz=UTC) - timedelta(days=criteria.FIXTURE_STALE_DAYS + 5)).timestamp()
    os.utime(recorded, (stale, stale))
    assert criteria.c8_maintainable().met is False


# --- the whole set ------------------------------------------------------------------


def test_every_criterion_is_evaluated(engine):
    results = criteria.evaluate(engine)
    assert [r.n for r in results] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert all(r.evidence for r in results), "a verdict without a pointer is a claim"


@pytest.mark.parametrize("n", range(1, 9))
def test_no_criterion_is_hardcoded_met(engine, n):
    """The load-bearing assertion of this file, swept over all eight.

    Each criterion must be capable of returning something other than True. One that cannot
    is decoration, and the eight of them together would be a definition of done that grades
    itself green forever.
    """
    import inspect

    fn = [
        criteria.c1_unattended,
        criteria.c2_alarmed,
        criteria.c3_recoverable,
        criteria.c4_calibrated,
        criteria.c5_traceable,
        criteria.c6_bounded,
        criteria.c7_lawful,
        criteria.c8_maintainable,
    ][n - 1]
    source = inspect.getsource(fn)
    assert "Result(" in source
    # A criterion that never mentions False, and never computes a comparison, cannot fail.
    assert "False" in source or any(op in source for op in ("<=", ">=", "==", "not ")), (
        f"c{n} has no path to a negative verdict"
    )
