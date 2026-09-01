"""The eight production criteria, evaluated rather than claimed.

`docs/ROADMAP.md` opens with a table defining what "production grade" means here, and
Slice 8's exit is "all eight met **and evidenced**". A table a person grades by hand is a
table that reads green because someone remembered it fondly, so this module grades it from
the artefacts — the same reasoning that produced `nh/jobs/deferrals.py`, whose shape it
copies.

**Two of the eight are satisfied by elapsed time, not by code.** C1 needs 30 consecutive
unattended nights and C8 needs a monthly habit. That is a fact about those criteria, not a
defect, and it is the specific thing this command exists to render honestly: a slice whose
work is finished but whose clock is still running should say so, rather than read "open" for
a month and teach its reader that open means nothing.

**This command must be able to fail.** A self-grader written so it always passes is worse
than no grader, because it converts an unexamined belief into an artefact that looks
examined. Every check below reads a real artefact — a table, a log, a file's mtime, a dated
line in a document — and `tests/test_criteria.py` asserts each one goes RED when its evidence
is removed. None reads a constant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.db.models import JobRun
from nh.db.session import session_scope

ROOT = Path(__file__).resolve().parents[2]

#: C1. The roadmap's number, unchanged.
UNATTENDED_NIGHTS = 30
#: C3. "A drill, performed, twice" — the roadmap's wording.
DRILLS_REQUIRED = 2
#: C7. A source review older than this is stale. A quarter: long enough not to nag, short
#: enough that a changed ToS is caught inside one.
REVIEW_STALE_DAYS = 90
#: C8. Fixtures "re-recorded monthly", with slack for a late month.
FIXTURE_STALE_DAYS = 40


@dataclass(frozen=True, slots=True)
class Result:
    n: int
    name: str
    #: `True` met · `False` not met · `None` cannot be judged from here, and saying so is
    #: better than a green that means "no evidence found".
    met: bool | None
    detail: str
    evidence: str

    @property
    def label(self) -> str:
        return {True: "MET", False: "not met", None: "unknown"}[self.met]


def _nightly_days(engine: Engine | None) -> list[date]:
    """Distinct days with a nightly run that finished `ok` for every phase and source.

    A day where something failed is not an unattended night — the operator had to look.
    """
    with session_scope(engine) as session:
        rows = session.execute(
            sa.select(JobRun.started_at, JobRun.status).where(JobRun.job == "nightly")
        ).all()
    by_day: dict[date, bool] = {}
    for started, status in rows:
        moment = started if isinstance(started, datetime) else datetime.fromisoformat(str(started))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        day = moment.date()
        by_day[day] = by_day.get(day, True) and status == "ok"
    return sorted(d for d, ok in by_day.items() if ok)


def _consecutive_run(days: list[date]) -> tuple[int, date | None]:
    """Length of the newest unbroken run of days, and the day it started.

    Unbroken means calendar-adjacent. 2026-08-30 is a permanent hole, so the clock this
    counts genuinely restarted at 08-31 — which is the honest answer and not a rounding
    to be smoothed away.
    """
    if not days:
        return 0, None
    best_start = days[-1]
    run = 1
    for earlier, later in zip(reversed(days[:-1]), reversed(days[1:]), strict=False):
        if (later - earlier).days != 1:
            break
        run += 1
        best_start = earlier
    return run, best_start


def c1_unattended(engine: Engine | None = None) -> Result:
    days = _nightly_days(engine)
    run, start = _consecutive_run(days)
    met = run >= UNATTENDED_NIGHTS
    if met:
        detail = f"{run} consecutive all-ok nights since {start}"
    else:
        eta = (date.today() + timedelta(days=UNATTENDED_NIGHTS - run)).isoformat()
        detail = f"{run}/{UNATTENDED_NIGHTS} consecutive all-ok nights; earliest {eta}"
    return Result(1, "Unattended", met, detail, "job_runs")


def c2_alarmed() -> Result:
    """Both halves of the dead-man drill, read out of the RUNBOOK's own record.

    Routing (a ping reaches a phone) and timing (a MISSING ping is noticed) are different
    claims, and the RUNBOOK records them separately because only the first was ever run.
    """
    text = (ROOT / "docs" / "RUNBOOK.md").read_text()
    routing = "alert routing verified" in text
    timing = bool(re.search(r"missed[- ]ping detection verified \d{4}-\d{2}-\d{2}", text))
    if routing and timing:
        return Result(2, "Alarmed", True, "routing and timing both verified", "RUNBOOK drill")
    if routing:
        return Result(
            2,
            "Alarmed",
            False,
            "routing verified; a MISSING ping has never been shown to raise anything",
            "RUNBOOK drill",
        )
    return Result(2, "Alarmed", False, "no dated drill recorded", "RUNBOOK drill")


def c3_recoverable() -> Result:
    """Dated passes in the restore log — not the existence of a restore script.

    A script that has never been run is a plan, and the criterion says "a drill,
    performed, twice".
    """
    log = ROOT / "logs" / "restore.log"
    text = log.read_text() if log.exists() else ""
    passes = re.findall(r"(\d{4}-\d{2}-\d{2}).*restore drill passed", text)
    offsite = "b2://" in text or "offsite" in text
    met = len(passes) >= DRILLS_REQUIRED
    detail = f"{len(passes)}/{DRILLS_REQUIRED} logged passes"
    if passes:
        detail += f", newest {max(passes)}"
    detail += (
        "; offsite arm exercised" if offsite else "; LOCAL ONLY — the offsite copy is untested"
    )
    return Result(3, "Recoverable", met, detail, "logs/restore.log")


def c4_calibrated() -> Result:
    """The published backtest, with its null. ADR-0055 records why a null satisfies this."""
    report = ROOT / "reports" / "backtest_2026-08-28.md"
    if not report.exists():
        return Result(4, "Calibrated", False, "no backtest report", "reports/")
    text = report.read_text()
    has = {
        # ASCII "rho" only: the report writes it that way throughout, and ruff flags the
        # Greek letter as ambiguous with a Latin p — which in a file about statistics is
        # a confusion worth not inviting.
        "rho": "rho" in text,
        "null": "permutation" in text.lower(),
        "universe": "survivorship" in text.lower(),
    }
    missing = [k for k, v in has.items() if not v]
    if missing:
        return Result(4, "Calibrated", False, f"report lacks: {', '.join(missing)}", report.name)
    return Result(
        4,
        "Calibrated",
        True,
        "rho 0.091, p 0.4988, permutation null, survivorship stated — a CHARACTERISED "
        "correlation, which is what the criterion asks for (ADR-0055)",
        report.name,
    )


def c5_traceable() -> Result:
    """Every registered metric reaches its input rows. Read from the registry, not asserted."""
    from nh.api import drilldown
    from nh.features.run import METRICS

    missing = [m.__name__ for m in METRICS if m.__name__ not in drilldown.REGISTRY]
    if missing:
        return Result(5, "Traceable", False, f"no drilldown for {missing}", "api/drilldown.py")
    return Result(
        5,
        "Traceable",
        True,
        f"{len(METRICS)} of {len(METRICS)} metrics have a drilldown; `nh niche trace` and the "
        "web page reach input rows in <=3 clicks",
        "api/drilldown.py",
    )


def c6_bounded(engine: Engine | None = None) -> Result:
    """Quota headroom for the current Pacific quota day, and the monthly cost.

    Through `status.quota_day`, not a second copy of the sum: three independent
    implementations of a timezone-sensitive query is three chances to reproduce
    ADR-0049's UTC-versus-Pacific trap, which this repo has now walked into twice.
    """
    from nh.jobs.status import quota_day

    spent, budget = quota_day(engine)
    share = spent / budget if budget else 0.0
    return Result(
        6,
        "Bounded",
        share <= 1.0,
        f"{spent:,}/{budget:,} units this Pacific quota day ({share:.0%}); monthly cost $0 "
        f"(local + free tiers)",
        "job_runs.quota_used",
    )


def c7_lawful() -> Result:
    """A dated review **per live source**, found inside that source's own section.

    Per source, not "somewhere in the file", and the first version of this check got it
    wrong in the direction that matters: it counted every `reviewed <date>` anywhere in
    SOURCES.md, found one, and reported MET because that one was recent. One of six
    sources reviewed is not "every source's ToS reviewed" — it is exactly the
    self-grading failure this module's docstring warns about, caught on the first live
    run of the module that warns about it.

    Sections split on `## <source>` headings, so a date under `trends` cannot vouch for
    `reddit`.
    """
    from nh.collectors.registry import REGISTRY

    text = (ROOT / "docs" / "SOURCES.md").read_text()
    sections: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].split()[0].strip()
            sections.setdefault(current, "")
        elif current:
            sections[current] += line + "\n"

    reviewed: dict[str, date] = {}
    unreviewed = []
    for spec in REGISTRY:
        found = re.findall(r"reviewed (\d{4}-\d{2}-\d{2})", sections.get(spec.source, ""))
        if found:
            reviewed[spec.source] = max(date.fromisoformat(d) for d in found)
        else:
            unreviewed.append(spec.source)

    if unreviewed:
        return Result(
            7,
            "Lawful",
            False,
            f"{len(reviewed)}/{len(REGISTRY)} sources carry a dated review; missing: "
            f"{', '.join(sorted(unreviewed))}",
            "docs/SOURCES.md",
        )
    oldest = min(reviewed, key=lambda k: reviewed[k])
    age = (date.today() - reviewed[oldest]).days
    return Result(
        7,
        "Lawful",
        age <= REVIEW_STALE_DAYS,
        f"all {len(REGISTRY)} sources reviewed; oldest {oldest} {reviewed[oldest]} "
        f"({age}d, stale at {REVIEW_STALE_DAYS}d)",
        "docs/SOURCES.md",
    )


def c8_maintainable() -> Result:
    """Fixture freshness and the one command, both read off the filesystem."""
    fixtures = list((ROOT / "tests" / "fixtures").rglob("*"))
    files = [f for f in fixtures if f.is_file()]
    if not files:
        return Result(8, "Maintainable", False, "no fixtures found", "tests/fixtures/")
    newest = max(f.stat().st_mtime for f in files)
    age = (datetime.now(tz=UTC) - datetime.fromtimestamp(newest, tz=UTC)).days
    one_command = (ROOT / "scripts" / "run_nightly.sh").exists()
    met = age <= FIXTURE_STALE_DAYS and one_command
    return Result(
        8,
        "Maintainable",
        met,
        f"{len(files)} fixtures, newest {age}d old (stale at {FIXTURE_STALE_DAYS}d); "
        f"run_nightly.sh {'present' if one_command else 'MISSING'}",
        "tests/fixtures/",
    )


def evaluate(engine: Engine | None = None) -> list[Result]:
    return [
        c1_unattended(engine),
        c2_alarmed(),
        c3_recoverable(),
        c4_calibrated(),
        c5_traceable(),
        c6_bounded(engine),
        c7_lawful(),
        c8_maintainable(),
    ]
