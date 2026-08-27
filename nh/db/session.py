"""Engine, session factory, and the append-only guard.

The guard is the point of this module. .claude/rules/data.md rule 4 says
"snapshots are append-only; never update a snapshot row" — here that is a
raised exception at flush time rather than something a reviewer has to notice.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from nh.config import Settings, get_settings
from nh.db.models import AppendOnly


class AppendOnlyViolation(RuntimeError):
    """Raised when a flush would UPDATE or DELETE an append-only row."""


@sa.event.listens_for(Session, "before_flush")
def _block_snapshot_mutation(session: Session, _flush_context, _instances) -> None:
    for obj in session.dirty:
        if isinstance(obj, AppendOnly) and session.is_modified(obj, include_collections=False):
            raise AppendOnlyViolation(
                f"{type(obj).__name__} is append-only; write a new row instead of updating "
                f"{obj!r}. See .claude/rules/data.md rule 4."
            )
    for obj in session.deleted:
        if isinstance(obj, AppendOnly):
            raise AppendOnlyViolation(
                f"{type(obj).__name__} is append-only and cannot be deleted: {obj!r}"
            )


def _configure_sqlite(engine: Engine) -> None:
    """WAL + foreign keys. WAL is what makes concurrent RSS workers and a
    reading dashboard coexist on one file (ADR-0002)."""

    @sa.event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # pragma: no cover - driver callback
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


def make_engine(settings: Settings | None = None, url: str | None = None) -> Engine:
    settings = settings or get_settings()
    url = url or settings.database_url
    if url.startswith("sqlite:///") and (path := url.removeprefix("sqlite:///")) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(url, echo=settings.sql_echo, future=True)
    if engine.dialect.name == "sqlite":
        _configure_sqlite(engine)
    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine()


def get_sessionmaker(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """Commit on clean exit, roll back on any exception."""
    session = get_sessionmaker(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
