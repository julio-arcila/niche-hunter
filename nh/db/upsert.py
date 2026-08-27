"""Dialect-agnostic idempotent writes.

The prototypes used ``INSERT OR REPLACE``, which is destructive: it deletes the
existing row and inserts a new one, so any column the new payload omits is
silently reset to NULL and any row-level history is lost. Every helper here
targets the real conflict key and touches only the columns supplied.

All three take a *homogeneous* batch: every dict must carry the same keys. A
multi-row ``VALUES`` requires it, and :func:`upsert` derives its SET clause from
the first row. ``Collector._flush`` guarantees homogeneity by bucketing on the
column set before calling in — see ``nh.collectors.base._group``.

Every statement is chunked to stay under the backend's bind-parameter ceiling.
That ceiling is per *parameter*, not per row, so the safe row count depends on
how wide the rows are — and a collector cannot know it. Chunking here rather than
capping the caller's batch size means a collector is free to fan one payload out
to as many rows as the source gives it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from functools import lru_cache
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from nh.db.models import Base

#: Fraction of the backend ceiling we actually use, so a column added later does
#: not silently walk a working statement into the limit.
_HEADROOM = 0.9
#: SQLite before 3.32 caps at 999; assume that if the real limit is unreadable.
_SQLITE_FALLBACK = 999
#: Postgres is fixed at 65535 bind parameters per statement.
_POSTGRES_LIMIT = 65_535


class UnsupportedDialect(RuntimeError):
    pass


@lru_cache(maxsize=8)
def _param_limit(engine: Engine) -> int:
    """Bind parameters this backend accepts in one statement."""
    if engine.dialect.name == "postgresql":
        return _POSTGRES_LIMIT
    if engine.dialect.name == "sqlite":
        try:
            import sqlite3

            raw = engine.raw_connection()
            try:
                return raw.driver_connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
            finally:
                raw.close()
        except Exception:  # pragma: no cover - old Python or exotic driver
            return _SQLITE_FALLBACK
    return _SQLITE_FALLBACK  # pragma: no cover - conservative for anything else


def _batches(
    session: Session, model: type[Base], rows: Sequence[dict[str, Any]]
) -> Iterator[Sequence[dict[str, Any]]]:
    """Split rows so each statement stays inside the parameter ceiling.

    Width is the table's full column count, not `len(rows[0])`. SQLAlchemy binds a
    parameter for every column it inserts, including ones the caller omitted that
    carry a Python-side default — `first_seen` and `enriched` on `videos`, for
    instance. Sizing on the supplied keys alone under-counts by exactly those, and
    the resulting statement lands just over the limit.
    """
    width = max(len(model.__table__.columns), 1)
    per_statement = max(int(_param_limit(session.get_bind()) * _HEADROOM) // width, 1)
    for i in range(0, len(rows), per_statement):
        yield rows[i : i + per_statement]


def bulk_insert(session: Session, model: type[Base], rows: Sequence[dict[str, Any]]) -> int:
    """Plain multi-row INSERT, no conflict clause.

    For append-only tables keyed on a surrogate id where every write is genuinely
    a new row and there is nothing to collide on — ``raw_records`` is the case.
    Using ``insert_ignore`` there would name a conflict target that can never
    fire, which reads as dedup that isn't happening.
    """
    if not rows:
        return 0
    written = 0
    for batch in _batches(session, model, rows):
        written += session.execute(sa.insert(model).values(list(batch))).rowcount or 0
    return written


def _insert(session: Session):
    name = session.get_bind().dialect.name
    if name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover - we only ship these two (ADR-0002)
        raise UnsupportedDialect(f"no upsert support for dialect {name!r}")
    return insert


def upsert(
    session: Session,
    model: type[Base],
    rows: Sequence[dict[str, Any]],
    *,
    conflict_on: Sequence[str] | None = None,
    update: Sequence[str] | None = None,
) -> int:
    """INSERT ... ON CONFLICT DO UPDATE. Re-running a day is a no-op-ish rewrite.

    conflict_on defaults to the primary key. `update` defaults to every supplied
    column except the conflict key, so an absent column keeps its stored value
    instead of being nulled.
    """
    if not rows:
        return 0
    keys = list(conflict_on or [c.name for c in model.__table__.primary_key])
    cols = update if update is not None else [c for c in rows[0] if c not in keys]
    written = 0
    for batch in _batches(session, model, rows):
        stmt = _insert(session)(model).values(list(batch))
        stmt = (
            stmt.on_conflict_do_nothing(index_elements=keys)
            if not cols
            else stmt.on_conflict_do_update(
                index_elements=keys, set_={c: getattr(stmt.excluded, c) for c in cols}
            )
        )
        written += session.execute(stmt).rowcount or 0
    return written


def insert_ignore(
    session: Session,
    model: type[Base],
    rows: Sequence[dict[str, Any]],
    *,
    conflict_on: Sequence[str] | None = None,
) -> int:
    """INSERT ... ON CONFLICT DO NOTHING — the only way to write a snapshot.

    Re-running a collector for a day the snapshot already covers collides on
    (entity, observed_date, source) and is dropped, so the series never gains a
    duplicate point and never loses the original reading.
    """
    if not rows:
        return 0
    keys = list(conflict_on or [c.name for c in model.__table__.primary_key])
    written = 0
    for batch in _batches(session, model, rows):
        stmt = (
            _insert(session)(model).values(list(batch)).on_conflict_do_nothing(index_elements=keys)
        )
        written += session.execute(stmt).rowcount or 0
    return written
