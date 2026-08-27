"""Provenance stamping, shared by collectors and computation phases.

Data rule 1 says every write carries `source`, `run_id` and `at`. Collectors got
that for free from `Collector._stamp`, but features and scorecards are not
collectors — they have no fetch, no normalize, no quota, no raw payloads — and
bolting them onto the Collector contract to borrow one method would be the wrong
shape entirely.

So the stamping is a plain function that both call. It is the whole abstraction:
a phase binds it with `functools.partial(stamp, source=..., run_id=..., at=...)`
and hands the result to `nh.db.upsert`, exactly as a collector does.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

from nh.db.models import Base


class Stamp(Protocol):
    """A provenance stamper bound to one run. What `partial(stamp, ...)` returns."""

    def __call__(self, model: type[Base], values: dict[str, Any]) -> dict[str, Any]: ...


def stamp(
    model: type[Base],
    values: dict[str, Any],
    *,
    source: str,
    run_id: str,
    at: datetime,
    observed_date: date | None = None,
) -> dict[str, Any]:
    """Fill in whichever provenance columns the model declares.

    `setdefault`, not assignment: a caller that supplies its own value keeps it,
    which is what lets a backfill write rows stamped with the run that originally
    produced them rather than the run that moved them.
    """
    columns = model.__table__.c
    row = dict(values)
    if "source" in columns:
        row.setdefault("source", source)
    if "run_id" in columns:
        row.setdefault("run_id", run_id)
    if "at" in columns:
        row.setdefault("at", at)
    if observed_date is not None and "observed_date" in columns:
        row.setdefault("observed_date", observed_date)
    return row
