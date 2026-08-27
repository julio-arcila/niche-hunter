"""Bounded retention for bulk raw payloads.

The one place in this codebase that deliberately deletes rows, and it is narrow on
purpose.

**It touches `raw_records` and nothing else.** Snapshots are the compounding asset
— unbackfillable, and the entire reason the pipeline exists — so they are kept
forever. Raw payloads are a replay convenience: valuable for re-normalizing recent
history, worth far less at six months old, and for feed XML they arrive at ~64 KB
per channel per night whether or not anything changed.

`RawRecord` inherits `AppendOnly`, and `nh.db.session` raises on ORM deletion of
such rows. That guard exists to stop *accidental* mutation, not deliberate
retention, so this uses a Core DELETE — which the ORM-level guard does not see.
That is a real hole, so the safety is enforced here instead: the statement is
hard-coded to `RawRecord` and the function refuses any other model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.db.models import RawRecord
from nh.db.session import session_scope
from nh.db.types import utcnow

#: Kinds whose payloads are bulk and highly redundant night to night. Everything
#: else — search hits, videos, channels — is small and kept indefinitely.
BULK_KINDS: tuple[str, ...] = ("feed",)


@dataclass(slots=True)
class PruneResult:
    deleted: int
    kinds: tuple[str, ...]
    older_than_days: int
    dry_run: bool


def prune_raw_records(
    engine: Engine | None = None,
    *,
    days: int = 14,
    kinds: tuple[str, ...] = BULK_KINDS,
    dry_run: bool = False,
) -> PruneResult:
    """Delete bulk raw payloads older than `days`.

    Fourteen days is chosen to comfortably cover a re-normalization window: long
    enough to replay a bad parse or a schema change across two weeks of feeds,
    short enough that storage stays bounded as the channel set grows.
    """
    if days < 1:
        raise ValueError("retention must be at least 1 day; use 0 rows deleted, not 0 days")
    cutoff = utcnow() - timedelta(days=days)
    where = sa.and_(RawRecord.kind.in_(kinds), RawRecord.at < cutoff)

    with session_scope(engine) as session:
        if dry_run:
            count = session.scalar(sa.select(sa.func.count()).select_from(RawRecord).where(where))
            return PruneResult(count or 0, kinds, days, True)
        result = session.execute(sa.delete(RawRecord).where(where))
        return PruneResult(result.rowcount or 0, kinds, days, False)


def storage_report(engine: Engine | None = None) -> list[tuple[str, str, int, int]]:
    """Rows and bytes per (kind, codec), so growth is visible before it is a problem."""
    with session_scope(engine) as session:
        rows = session.execute(
            sa.select(
                RawRecord.kind,
                RawRecord.codec,
                sa.func.count(),
                sa.func.sum(
                    sa.func.coalesce(sa.func.length(RawRecord.payload_gz), 0)
                    + sa.func.coalesce(sa.func.length(RawRecord.payload), 0)
                ),
            )
            .group_by(RawRecord.kind, RawRecord.codec)
            .order_by(sa.desc(sa.text("4")))
        ).all()
    return [(k, c, n, b or 0) for k, c, n, b in rows]
