"""One-shot re-normalization of text we already hold but never stored.

`videos.description` was added in Slice 4. Every video collected before it existed
still has its description — inside `raw_records`, which is exactly what data rule 2
promises: *"the payload lands in `raw_records` exactly as the source returned it...
re-normalizing a week of history must be a query, never a re-fetch."* This is that
query. No network, no quota, no new raw record.

It is a **job, not a phase**. A phase runs every night under `run_phases` and
`nh/jobs/status.py` gates the nightly on each one being present and `ok` — which
would mean gating forever on a rescue that does nothing after the first night. It
records a `job_runs` row with `job="backfill"`, which the gate ignores the same way
it ignores `job="partial"` (ADR-0014).

Urgency, measured 2026-08-27: 13,333 of the recoverable descriptions exist only in
gzipped feed payloads, `scripts/run_nightly.sh` prunes after every run, and
`raw_retention_days` is 14. A feed serves 15 entries, so a video that has fallen out
of its channel's window cannot be re-fetched at any price — 1,873 were already past
it on the day this was written. ADR-0017 stops the prune from taking the last copy;
this puts the text somewhere the prune cannot reach.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from nh.collectors.youtube_rss import parse_feed
from nh.db.models import JobRun, RawRecord, Video
from nh.db.raw import decode
from nh.db.session import session_scope
from nh.db.types import utcnow

SOURCE = "descriptions"
#: Raw kinds that carry description text, newest-wins when both hold one.
KINDS: tuple[str, ...] = ("feed", "video")
#: Rows per write. The same limit `nh.db.upsert` chunks for; kept explicit here
#: because a single feed payload fans out to ~15 videos.
CHUNK = 500


@dataclass(slots=True)
class BackfillResult:
    scanned: int
    found: int
    written: int
    dry_run: bool


def _from_feed(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Feed payloads are the fetch envelope; the XML sits under `xml`."""
    xml = payload.get("xml")
    if not xml:
        return []
    return [
        (entry["video_id"], entry["description"])
        for entry in parse_feed(xml)
        if entry["video_id"] and entry["description"]
    ]


def _from_video(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """`youtube_api` video payloads are the API item verbatim."""
    video_id = payload.get("id")
    description = (payload.get("snippet") or {}).get("description")
    return [(video_id, description)] if video_id and description else []


def extract(record: RawRecord) -> list[tuple[str, str]]:
    """`(video_id, description)` for every description a raw payload carries.

    Public because `nh.db.retention` uses it to decide whether pruning a payload
    would destroy the last copy of some text (ADR-0017).
    """
    payload = decode(record)
    if not isinstance(payload, dict):
        return []
    return _from_feed(payload) if record.kind == "feed" else _from_video(payload)


def _missing(session: Session) -> set[str]:
    """Only videos we hold and have no description for.

    Both halves matter. Restricting to known ids keeps the upsert an UPDATE, so a
    stray id in an old payload cannot insert a provenance-less stub. Restricting to
    NULL makes the job resumable and idempotent, and means a re-run after the
    collectors have captured richer text does not overwrite it.
    """
    return set(session.scalars(sa.select(Video.video_id).where(Video.description.is_(None))).all())


def backfill_descriptions(
    engine: Engine | None = None,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> BackfillResult:
    """Recover `videos.description` from stored raw payloads.

    A failure is recorded to `job_runs` before it is raised: the status mutation is
    committed by the session scope on the way out, and the exception is re-raised
    afterwards so the CLI still exits non-zero. Raising from inside the scope would
    roll the row back to `running` and leave a failed job looking like a hung one.
    """
    run_id = str(uuid4())
    at = utcnow()
    failure: Exception | None = None
    result = BackfillResult(0, 0, 0, dry_run)
    with session_scope(engine) as session:
        record = JobRun(
            run_id=run_id, job="backfill", source=SOURCE, status="running", started_at=at
        )
        if not dry_run:
            session.add(record)
            session.commit()
        try:
            result = _scan(session, run_id, at, limit=limit, dry_run=dry_run)
        except Exception as exc:  # recorded, then re-raised below
            session.rollback()
            failure = exc
        if not dry_run:
            record.status = "failed" if failure else "ok"
            record.error = (
                None if failure is None else f"{type(failure).__name__}: {failure}"[:4000]
            )
            record.rows_upserted = result.written
            record.finished_at = utcnow()
    if failure is not None:
        raise failure
    return result


def _scan(
    session: Session, run_id: str, at: datetime, *, limit: int | None, dry_run: bool
) -> BackfillResult:
    """Stream the raw payloads, keeping only text for videos still missing one."""
    wanted = _missing(session)
    found: dict[str, str] = {}
    scanned = 0
    written = 0
    records = session.scalars(
        sa.select(RawRecord).where(RawRecord.kind.in_(KINDS)).order_by(RawRecord.at)
    )
    for record in records.yield_per(200):
        scanned += 1
        for video_id, description in extract(record):
            if video_id in wanted:
                # Later payloads win: `youtube_api` carries the untruncated text and
                # is ordered after the feed that first surfaced the video.
                found[video_id] = description
        if limit is not None and len(found) >= limit:
            break
    rows = [{"video_id": vid, "description": text} for vid, text in found.items()]
    if limit is not None:
        rows = rows[:limit]
    if not dry_run:
        for start in range(0, len(rows), CHUNK):
            written += _write(session, rows[start : start + CHUNK], run_id, at)
    return BackfillResult(scanned, len(rows), written, dry_run)


def _write(session: Session, rows: list[dict[str, Any]], run_id: str, at: datetime) -> int:
    """A targeted UPDATE, deliberately not an upsert, and deliberately not stamped.

    Not an upsert: `INSERT ... ON CONFLICT DO UPDATE` builds the full candidate row
    before the conflict clause resolves, so SQLite raises `NOT NULL constraint
    failed: videos.channel_id` on a payload carrying only `video_id` and
    `description`. Supplying the other columns to satisfy that would let this job
    create video rows, which is exactly what it must never do. The `description IS
    NULL` guard keeps it idempotent — a second run writes nothing.

    Not stamped: rewriting `source`/`run_id`/`at` would replace the provenance of the
    collector that actually fetched the payload with the provenance of the job that
    moved the text between two columns of our own database. `nh.db.provenance.stamp`
    names this case directly — a backfill keeps "the run that originally produced
    them rather than the run that moved them". This run's provenance is its
    `job_runs` row.
    """
    written = 0
    for row in rows:
        result = session.execute(
            sa.update(Video)
            .where(Video.video_id == row["video_id"], Video.description.is_(None))
            .values(description=row["description"])
        )
        written += result.rowcount or 0
    session.commit()
    return written
