"""The Collector contract.

Every source subclasses this and implements exactly two methods:

    fetch()      -> yields Raw payloads, verbatim, as the source returned them
    normalize(r) -> turns one Raw into a Batch of upserts and snapshots

Everything else — provenance stamping, raw-before-normalized ordering,
idempotent upserts, append-only snapshot writes, quota accounting, job_runs
bookkeeping, surviving a source outage — is handled here, once, so that a new
collector cannot get it wrong by omission.

Porting one of the legacy/ prototypes means splitting it along these seams:

    legacy/niche_hunter_X.py         nh/collectors/X.py
    -------------------------        ----------------------------------------
    HTTP client + retries       ->   fetch()
    row shaping / dict building ->   normalize()
    SCHEMA + INSERT statements  ->   deleted (nh/db/models.py owns the schema)
    run()/__main__              ->   deleted (nh/jobs/nightly.py owns orchestration)
    pure analysis functions     ->   nh/features/*.py, unchanged
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy.engine import Engine

from nh.collectors.quota import QuotaLedger
from nh.config import Settings, get_settings
from nh.db.models import AppendOnly, Base, JobRun, RawRecord
from nh.db.provenance import stamp
from nh.db.raw import encode as encode_payload
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.db.upsert import bulk_insert, insert_ignore, upsert

log = logging.getLogger(__name__)

FLUSH_EVERY = 500


class NotPorted(NotImplementedError):
    """Placeholder collector: the prototype in legacy/ has not been ported yet."""


@dataclass(frozen=True, slots=True)
class Raw:
    """One payload exactly as the source returned it."""

    kind: str
    key: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Upsert:
    """A normalized entity row. Idempotent: safe to write again tomorrow."""

    model: type[Base]
    values: dict[str, Any]
    conflict_on: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One point on a time series. Written with ON CONFLICT DO NOTHING and never
    updated — the model must inherit AppendOnly or persist() refuses it."""

    model: type[Base]
    values: dict[str, Any]


@dataclass(slots=True)
class Batch:
    upserts: list[Upsert] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)

    def extend(self, other: Batch) -> None:
        self.upserts.extend(other.upserts)
        self.snapshots.extend(other.snapshots)

    def __bool__(self) -> bool:
        return bool(self.upserts or self.snapshots)


@dataclass(slots=True)
class RunStats:
    raw_written: int = 0
    rows_upserted: int = 0
    snapshots_written: int = 0


class Collector(ABC):
    source: ClassVar[str]
    description: ClassVar[str] = ""
    #: None means the source has no countable quota (RSS, Trends).
    quota_budget: ClassVar[int | None] = None

    def __init__(
        self,
        run_id: str,
        *,
        settings: Settings | None = None,
        engine: Engine | None = None,
        observed_at: datetime | None = None,
    ) -> None:
        self.run_id = run_id
        self.settings = settings or get_settings()
        self.engine = engine
        self.observed_at = observed_at or utcnow()
        self.quota = QuotaLedger(self.quota_budget)
        self.log = logging.getLogger(f"nh.collectors.{self.source}")

    # -- subclass surface ---------------------------------------------------

    @abstractmethod
    def fetch(self) -> Iterable[Raw]:
        """Yield raw payloads. Network lives here and nowhere else."""

    @abstractmethod
    def normalize(self, raw: Raw) -> Batch:
        """Turn one raw payload into rows. Pure: no I/O, no clock, no network."""

    def is_configured(self) -> bool:
        return self.settings.configured(self.source)

    # -- machinery ----------------------------------------------------------

    @property
    def observed_date(self) -> date:
        return self.observed_at.date()

    def _stamp(self, model: type[Base], values: dict[str, Any]) -> dict[str, Any]:
        """Inject provenance and the observation day. A collector physically
        cannot write a row without `source`, `run_id` and `at`.

        Delegates to `nh.db.provenance.stamp`, which the computation phases in
        `nh/jobs/phases.py` also use — features are not collectors and must not
        inherit this contract just to borrow one method.
        """
        return stamp(
            model,
            values,
            source=self.source,
            run_id=self.run_id,
            at=self.observed_at,
            observed_date=self.observed_date,
        )

    def _flush(self, session, raws: list[Raw], batch: Batch, stats: RunStats) -> None:
        if raws:
            # Uniform by construction, so a plain insert is safe and honest here.
            stats.raw_written += bulk_insert(
                session,
                RawRecord,
                [
                    self._stamp(
                        RawRecord,
                        {"kind": r.kind, "key": r.key, **encode_payload(r.payload)},
                    )
                    for r in raws
                ],
            )
        for (model, _cols, conflict_on), rows in _group(batch.upserts, self._stamp).items():
            stats.rows_upserted += upsert(session, model, rows, conflict_on=conflict_on)
        for (model, _cols, _), rows in _group(batch.snapshots, self._stamp).items():
            if not issubclass(model, AppendOnly):
                raise TypeError(
                    f"{model.__name__} is written as a snapshot but does not inherit AppendOnly"
                )
            stats.snapshots_written += insert_ignore(
                session, model, rows, conflict_on=_unique_key(model)
            )
        # Commit, not flush: each batch must survive a later failure in the same run.
        session.commit()
        raws.clear()
        batch.upserts.clear()
        batch.snapshots.clear()

    def run(self, job: str = "nightly", *, raise_on_error: bool = False) -> JobRun:
        """Fetch, normalize and persist, recording the outcome in `job_runs`.

        A source outage must not kill the nightly job (.claude/rules/python.md),
        so failures are recorded and returned rather than raised. Pass
        raise_on_error=True when debugging a single collector.

        Each `_flush` commits. A collector that dies at feed 700 of 800 keeps the
        first 600-odd rows instead of discarding the night — which matters here
        more than almost anywhere, because a lost snapshot cannot be re-fetched
        tomorrow. The rollback on failure therefore drops only the batch that was
        in flight.
        """
        stats = RunStats()
        record = JobRun(
            run_id=self.run_id,
            job=job,
            source=self.source,
            status="running",
            started_at=self.observed_at,
            quota_budget=self.quota.budget,
        )
        with session_scope(self.engine) as session:
            session.add(record)
            session.commit()  # durable before any fetching, so a crash still leaves a trace

            if not self.is_configured():
                record.status = "skipped"
                record.error = "credentials not configured"
                record.finished_at = utcnow()
                self.log.warning("%s skipped: not configured", self.source)
                return record

            pending_raw: list[Raw] = []
            pending = Batch()
            try:
                for raw in self.fetch():
                    pending_raw.append(raw)
                    pending.extend(self.normalize(raw))
                    if len(pending_raw) >= FLUSH_EVERY:
                        self._flush(session, pending_raw, pending, stats)
                self._flush(session, pending_raw, pending, stats)
                record.status = "ok"
            except Exception as exc:
                # Discards only the in-flight batch; everything _flush committed stands.
                session.rollback()
                record.status = "failed"
                record.error = f"{type(exc).__name__}: {exc}"[:4000]
                self.log.exception("%s failed", self.source)
                if raise_on_error:
                    raise
            finally:
                record.finished_at = utcnow()
                record.quota_used = self.quota.used
                record.raw_written = stats.raw_written
                record.rows_upserted = stats.rows_upserted
                record.snapshots_written = stats.snapshots_written
        return record


def _group(
    items: Sequence[Upsert] | Sequence[Snapshot],
    stamp: Callable[[type[Base], dict[str, Any]], dict[str, Any]],
) -> dict[tuple[type[Base], frozenset[str], tuple[str, ...] | None], list[dict[str, Any]]]:
    """Bucket rows into homogeneous batches, keyed by model + column set + conflict target.

    Grouping by model alone is not enough. A multi-row ``VALUES`` requires every
    dict to carry identical keys, and ``upsert()`` derives its SET clause from the
    first row — so a batch mixing a sparse row and a rich row for the same model
    either fails to bind or silently omits the rich row's columns from the update.

    ``youtube_api`` produces exactly that shape: a video first appears from a
    search result with four columns, then again from ``videos.list`` with a dozen.
    Bucketing on the column set keeps each statement uniform without unioning keys
    and filling the gaps with NULL, which would overwrite good data (data rule 6).

    Rows are stamped before bucketing, so provenance columns cannot split a bucket
    that would otherwise be uniform.
    """
    buckets: dict[tuple[type[Base], frozenset[str], tuple[str, ...] | None], list[dict]] = {}
    for item in items:
        values = stamp(item.model, item.values)
        key = (item.model, frozenset(values), getattr(item, "conflict_on", None))
        buckets.setdefault(key, []).append(values)
    return buckets


def _unique_key(model: type[Base]) -> list[str]:
    """The conflict target for a snapshot: its declared UNIQUE constraint if it
    has one (entity + observed_date + source), else the primary key."""
    from sqlalchemy import UniqueConstraint

    for constraint in model.__table__.constraints:
        if isinstance(constraint, UniqueConstraint):
            return [c.name for c in constraint.columns]
    return [c.name for c in model.__table__.primary_key]
