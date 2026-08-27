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

from nh.db.models import RawRecord, Video
from nh.db.session import session_scope
from nh.db.types import utcnow

#: Kinds whose payloads are bulk and highly redundant night to night. Everything
#: else — search hits, videos, channels — is small and kept indefinitely.
BULK_KINDS: tuple[str, ...] = ("feed",)


class LastCopyRefused(RuntimeError):
    """Raised when pruning would destroy the only stored copy of some text."""


@dataclass(slots=True)
class PruneResult:
    deleted: int
    kinds: tuple[str, ...]
    older_than_days: int
    dry_run: bool
    #: Videos whose description exists only in the payloads this run deleted. Zero
    #: unless `force` was used — otherwise the run refuses instead (ADR-0017).
    orphaned_descriptions: int = 0


def prune_raw_records(
    engine: Engine | None = None,
    *,
    days: int = 14,
    kinds: tuple[str, ...] = BULK_KINDS,
    dry_run: bool = False,
    force: bool = False,
) -> PruneResult:
    """Delete bulk raw payloads older than `days`.

    Fourteen days is chosen to comfortably cover a re-normalization window: long
    enough to replay a bad parse or a schema change across two weeks of feeds,
    short enough that storage stays bounded as the channel set grows.

    Refuses, absent `force`, when the delete set holds the last copy of a video
    description (ADR-0017). Rule 2 promises that re-normalizing history is a query
    rather than a re-fetch; for a source that serves 15 entries and no history, that
    promise is only true while the payload survives. This is the promise enforced
    rather than trusted.
    """
    if days < 1:
        raise ValueError("retention must be at least 1 day; use 0 rows deleted, not 0 days")
    cutoff = utcnow() - timedelta(days=days)
    where = sa.and_(RawRecord.kind.in_(kinds), RawRecord.at < cutoff)

    with session_scope(engine) as session:
        orphaned = _undescribed_videos(session, where)
        if orphaned and not force:
            raise LastCopyRefused(
                f"pruning would destroy the last copy of {orphaned} video description(s); "
                "run `nh backfill descriptions` first, or pass --force to accept the loss"
            )
        if dry_run:
            count = session.scalar(sa.select(sa.func.count()).select_from(RawRecord).where(where))
            return PruneResult(count or 0, kinds, days, True, orphaned)
        result = session.execute(sa.delete(RawRecord).where(where))
        return PruneResult(result.rowcount or 0, kinds, days, False, orphaned)


def _undescribed_videos(session, where) -> int:
    """Count videos whose description exists *only* in the payloads about to go.

    Decodes the delete set and keeps ids that are still NULL in `videos`. The coarse
    alternative — "any video missing a description" — refuses forever, because 1,044
    of the corpus measured on 2026-08-27 have no description in any payload we hold
    and never will. A guard that can never be satisfied is a broken nightly, not a
    safety feature.

    Cost is one decode of the delete set. In steady state that is a single night's
    feeds; it is only large the first time, when everything ages out at once.
    """
    from nh.jobs.backfill import extract  # local: retention is imported by the CLI

    missing = set(
        session.scalars(sa.select(Video.video_id).where(Video.description.is_(None))).all()
    )
    if not missing:
        return 0
    doomed = set()
    records = session.scalars(sa.select(RawRecord).where(where))
    for record in records.yield_per(200):
        doomed.update(vid for vid, _ in extract(record) if vid in missing)
    return len(doomed)


def storage_report(engine: Engine | None = None) -> list[tuple[str, str, int, int]]:
    """Rows and bytes per (kind, codec), so growth is visible before it is a problem."""
    with session_scope(engine) as session:
        rows = session.execute(
            sa.select(
                RawRecord.kind,
                RawRecord.codec,
                sa.func.count(),
                sa.func.sum(
                    # `payload_gz` is LargeBinary -> bytea, where length() is bytes.
                    # `payload` is JSONVariant -> JSONB on Postgres, where
                    # `length(jsonb)` DOES NOT EXIST: it raises UndefinedFunction at
                    # runtime, not a wrong number. No test catches it because
                    # tests/conftest.py is SQLite-only. Cast first, on both dialects,
                    # so the swap does not discover this the hard way (ADR-0019).
                    sa.func.coalesce(sa.func.length(RawRecord.payload_gz), 0)
                    + sa.func.coalesce(sa.func.length(sa.cast(RawRecord.payload, sa.Text)), 0),
                ),
            )
            .group_by(RawRecord.kind, RawRecord.codec)
            .order_by(sa.desc(sa.text("4")))
        ).all()
    return [(k, c, n, b or 0) for k, c, n, b in rows]
