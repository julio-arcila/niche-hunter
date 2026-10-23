#!/usr/bin/env python
"""Profile the features phase without writing anything.

Stage 1 of the plan in `reports/features_profile_*.md`. It answers one question with
numbers: how much of the features phase is the whole-table `max(views)` aggregate, and how
much of THAT is repetition rather than work.

Three deliberate constraints, each of which cost something to learn:

* **It never calls `features.run.compute`.** That function upserts into `features_daily`
  (`nh/features/run.py:143`), so profiling through it would write to whatever database it
  is pointed at. This calls the metric callables directly and throws the results away.
* **It builds its own engine with `sa.create_engine`, not `nh.db.session.make_engine`.**
  The latter installs a connect hook that runs `PRAGMA journal_mode=WAL`, which fails on a
  read-only connection, and its path handling mangles a `file:...?mode=ro&uri=true` URL.
* **Run it outside 09:10-12:30 local, and not on restore-drill day.** It reads ~700MB
  repeatedly and will evict the nightly's page cache — contaminating the `job_runs` series
  the whole investigation rests on.

Usage:
    uv run python scripts/profile_features.py --day 2026-10-04 --reps 3
    /usr/bin/time -lp uv run python scripts/profile_features.py 2>&1 | tee -a report.txt
"""

from __future__ import annotations

import argparse
import hashlib
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from nh.db.models import Cluster
from nh.features import inputs, supply
from nh.features.run import METRICS

#: The live database, opened read-only. `mode=ro` is enforced by SQLite itself rather than
#: by this script's good intentions, which matters because the alternative is profiling a
#: 6.3GB production corpus with a connection that could write to it.
LIVE = Path(__file__).resolve().parent.parent / "data" / "niche_hunter.db"


def read_only_url(path: Path) -> str:
    return f"sqlite:///file:{path}?mode=ro&uri=true"


@dataclass
class Timing:
    """Wall and CPU for a set of calls. `cpu_share` is the I/O-bound detector."""

    calls: int = 0
    wall: float = 0.0
    cpu: float = 0.0
    args: set[tuple] = field(default_factory=set)

    @property
    def cpu_share(self) -> float:
        return self.cpu / self.wall if self.wall else 0.0

    @property
    def distinct(self) -> int:
        return len(self.args)

    @property
    def repetition(self) -> float:
        """Calls per distinct argument tuple — the CEILING on what memoisation can buy.

        Stated before any code changes, so the claim "a cache would help" is a number
        rather than a hope. 1.0 means a cache can buy nothing.
        """
        return self.calls / self.distinct if self.distinct else 0.0


def _normalise(sql: str) -> str:
    """Collapse a statement to something groupable: whitespace out, literals out."""
    sql = re.sub(r"\s+", " ", sql).strip()
    sql = re.sub(r"'[^']*'", "?", sql)
    sql = re.sub(r"\b\d+\b", "?", sql)
    return sql


@contextmanager
def statement_timer(engine: Engine) -> Iterator[dict[str, Timing]]:
    """Per-statement wall time, from the engine's own cursor events.

    This is what turns "the aggregate is probably the problem" into a percentage.
    """
    stats: dict[str, Timing] = defaultdict(Timing)
    started: dict[int, float] = {}

    def before(conn, cursor, statement, parameters, context, executemany):
        started[id(cursor)] = time.perf_counter()

    def after(conn, cursor, statement, parameters, context, executemany):
        elapsed = time.perf_counter() - started.pop(id(cursor), time.perf_counter())
        key = _normalise(statement)
        digest = hashlib.sha1(key.encode()).hexdigest()[:8]
        entry = stats[f"{digest} {key[:160]}"]
        entry.calls += 1
        entry.wall += elapsed

    sa.event.listen(engine, "before_cursor_execute", before)
    sa.event.listen(engine, "after_cursor_execute", after)
    try:
        yield stats
    finally:
        sa.event.remove(engine, "before_cursor_execute", before)
        sa.event.remove(engine, "after_cursor_execute", after)


#: The input functions worth attributing. Each is `(module, attribute)` so the wrapper can
#: be installed and removed without touching `nh/` itself — the profiler must not be able
#: to change what it measures.
WATCHED: tuple[tuple[Any, str], ...] = (
    (inputs, "eligible_videos"),
    (inputs, "eligible_niche_videos"),
    (inputs, "latest_subs"),
    (inputs, "cohort"),
    (inputs, "member_channels"),
    (inputs, "numerator_coverage"),
    (inputs, "relevance_coverage"),
    (inputs, "date_discovered_channels"),
    (supply, "_top_videos"),
)


@contextmanager
def input_timer() -> Iterator[dict[str, Timing]]:
    """Time the input layer by wrapping, then restore the originals.

    Monkeypatching in the harness rather than instrumenting `nh/features/inputs.py`:
    production code should not carry a profiler's scaffolding, and a wrapper that only
    exists for the duration of this context cannot be left switched on by accident.
    """
    stats: dict[str, Timing] = defaultdict(Timing)
    originals: list[tuple[Any, str, Callable]] = []

    def wrap(module: Any, name: str) -> None:
        original = getattr(module, name)
        originals.append((module, name, original))

        def timed(*args: Any, **kwargs: Any) -> Any:
            w0, c0 = time.perf_counter(), time.process_time()
            try:
                return original(*args, **kwargs)
            finally:
                entry = stats[f"{module.__name__.split('.')[-1]}.{name}"]
                entry.calls += 1
                entry.wall += time.perf_counter() - w0
                entry.cpu += time.process_time() - c0
                # args[0] is the Session; identity of the session matters for the cache
                # key question, so record it alongside the cluster and day.
                entry.args.add((id(args[0]), *(str(a) for a in args[1:])))

        setattr(module, name, timed)

    for module, name in WATCHED:
        wrap(module, name)
    try:
        yield stats
    finally:
        for module, name, original in reversed(originals):
            setattr(module, name, original)


def active_clusters(session: Session) -> list[str]:
    return list(session.scalars(sa.select(Cluster.cluster_id).where(Cluster.active.is_(True))))


def profile(
    engine: Engine, day: date, reps: int, cache_size: int | None
) -> tuple[dict[str, Timing], dict[str, Timing], dict[str, Timing]]:
    """Run every metric for every active cluster, `reps` times. Returns three views."""
    maker = sessionmaker(engine)
    per_metric: dict[str, Timing] = defaultdict(Timing)

    if cache_size is not None:
        # Defeat SQLite's own page cache so the OS cache is the only one, which is what
        # makes the cache-hostile condition meaningful rather than decorative.
        @sa.event.listens_for(engine, "connect")
        def _small_cache(dbapi_conn, record):  # pragma: no cover - profiling only
            dbapi_conn.execute(f"PRAGMA cache_size={cache_size}")

    with statement_timer(engine) as statements, input_timer() as per_input:
        for rep in range(reps):
            with maker() as session:
                clusters = active_clusters(session)
                print(f"  rep {rep + 1}/{reps}: {len(clusters)} clusters x {len(METRICS)} metrics")
                for cluster_id in clusters:
                    for metric in METRICS:
                        w0, c0 = time.perf_counter(), time.process_time()
                        metric(session, cluster_id, day)
                        entry = per_metric[metric.__name__]
                        entry.calls += 1
                        entry.wall += time.perf_counter() - w0
                        entry.cpu += time.process_time() - c0
    return per_metric, per_input, statements


def table(title: str, rows: list[tuple[str, Timing]], *, show_repetition: bool) -> None:
    print(f"\n{title}")
    header = f"  {'name':<52} {'calls':>6} {'wall s':>9} {'cpu%':>6}"
    if show_repetition:
        header += f" {'distinct':>9} {'calls/dist':>11}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, t in rows:
        line = f"  {name[:52]:<52} {t.calls:>6} {t.wall:>9.1f} {t.cpu_share * 100:>5.0f}%"
        if show_repetition:
            line += f" {t.distinct:>9} {t.repetition:>11.1f}"
        print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=read_only_url(LIVE), help="SQLAlchemy URL (read-only)")
    parser.add_argument("--day", default="2026-10-04", help="the day to compute for")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument(
        "--cache-size",
        type=int,
        default=None,
        help="PRAGMA cache_size (negative = KiB). -2000 is the cache-hostile condition.",
    )
    args = parser.parse_args()

    day = date.fromisoformat(args.day)
    engine = sa.create_engine(args.db, future=True)
    print(f"profiling {args.db}")
    print(f"day={day} reps={args.reps} cache_size={args.cache_size}")

    # Pinned explicitly: `ballast_active()` reads the operator's calendar, and a profile
    # that silently straddles the sunset is measuring two definitions at once.
    t0 = time.perf_counter()
    with inputs.pinned_ballast(False):
        per_metric, per_input, statements = profile(engine, day, args.reps, args.cache_size)
    total = time.perf_counter() - t0

    table(
        "PER METRIC (sorted by wall)",
        sorted(per_metric.items(), key=lambda kv: -kv[1].wall),
        show_repetition=False,
    )
    table(
        "PER INPUT FUNCTION (calls/dist is the ceiling on what a cache can buy)",
        sorted(per_input.items(), key=lambda kv: -kv[1].wall),
        show_repetition=True,
    )
    table(
        "PER STATEMENT (top 12 by wall)",
        sorted(statements.items(), key=lambda kv: -kv[1].wall)[:12],
        show_repetition=False,
    )

    hot = max(statements.items(), key=lambda kv: kv[1].wall, default=("none", Timing()))
    print("\nVERDICT")
    print(f"  total wall                {total:>9.1f} s  ({total / 60:.1f} min)")
    print(
        f"  hottest statement         {hot[1].wall:>9.1f} s  ({hot[1].wall / total * 100:.0f}% of total)"
    )
    print(f"  its executions            {hot[1].calls:>9}")
    print(f"  hottest statement sql     {hot[0][:140]}")
    for name in ("inputs.eligible_videos", "inputs.member_channels", "inputs.latest_subs"):
        if name in per_input:
            t = per_input[name]
            print(f"  {name:<25} {t.calls:>4} calls / {t.distinct} distinct = {t.repetition:.1f}x")


if __name__ == "__main__":
    main()
