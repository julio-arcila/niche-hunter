"""SQLAlchemy models.

Layer map (docs/ARCHITECTURE.md):
    raw_records                 every payload, verbatim, before normalization
    channels / videos           normalized entities, idempotent upsert
    *_snapshots                 append-only time series — the compounding asset
    clusters / cluster_members  Phase 2
    features_daily              one row per cluster per day per metric
    scorecards / alerts         Phase 4

Non-negotiables enforced here rather than by convention:
  * Provenance — every table carries `source`, `run_id`, `at` via Provenance.
  * Append-only — snapshot tables inherit AppendOnly; nh.db.session installs a
    listener that raises on any UPDATE to them. Rule 4 of .claude/rules/data.md
    is a runtime error, not a code-review note.
  * Idempotency — snapshots are keyed (entity, observed_date, source), so a
    re-run of the same day collides and is skipped instead of duplicating.
  * Absent is NULL — measure columns are all nullable. Nothing defaults to 0.
"""

from __future__ import annotations

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from nh.db.types import NAMING_CONVENTION, JSONVariant, utcnow


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class AppendOnly:
    """Marker: rows in this table are never updated or deleted.

    nh.db.session.guard_append_only() turns this into an enforced invariant.
    """


class Provenance:
    """Who wrote this row, in which run, and when."""

    source: Mapped[str] = mapped_column(sa.String(32), index=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# Run bookkeeping
# ---------------------------------------------------------------------------


class JobRun(Base):
    """One collector execution. Quota spend and failures land here, not stdout."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    job: Mapped[str] = mapped_column(sa.String(64))  # "nightly", "hourly_hot"
    source: Mapped[str] = mapped_column(sa.String(32), index=True)
    status: Mapped[str] = mapped_column(sa.String(16))  # running|ok|failed|skipped
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    quota_used: Mapped[int | None] = mapped_column(sa.Integer)
    quota_budget: Mapped[int | None] = mapped_column(sa.Integer)
    raw_written: Mapped[int | None] = mapped_column(sa.Integer)
    rows_upserted: Mapped[int | None] = mapped_column(sa.Integer)
    snapshots_written: Mapped[int | None] = mapped_column(sa.Integer)
    error: Mapped[str | None] = mapped_column(sa.Text)

    __table_args__ = (sa.Index("ix_job_runs_source_started", "source", "started_at"),)


class NicheSeed(Base):
    """Hand-picked starting point. Everything downstream hangs off a seed."""

    __tablename__ = "niche_seeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(sa.String(64), unique=True)
    label: Mapped[str] = mapped_column(sa.String(200))
    keywords: Mapped[list] = mapped_column(JSONVariant)
    geo: Mapped[str | None] = mapped_column(sa.String(8))
    lang: Mapped[str | None] = mapped_column(sa.String(8))
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class RawRecord(Base, AppendOnly, Provenance):
    """Every payload as the source returned it, before any interpretation.

    One table with a `kind` discriminator rather than raw_youtube / raw_reddit /
    ... — see ADR-0004. Re-normalizing a week of history is then a query, not a
    re-fetch, which matters most for the sources that cannot be backfilled.

    Exactly one of `payload` (readable JSON) and `payload_gz` (gzipped, for bulk
    documents) is set; `codec` says which. Read through `nh.db.raw.decode` rather
    than touching either column — see ADR-0010.

    Append-only like every other raw table, with one sanctioned exception:
    `nh.db.retention.prune_raw_records` deletes aged bulk payloads. That is a
    storage-reclaim operation on a replay convenience, and it never touches a
    snapshot — snapshots are the asset and are kept forever.
    """

    __tablename__ = "raw_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(sa.String(48))  # video, channel, feed, post, keyword
    key: Mapped[str] = mapped_column(sa.String(256))  # natural id within (source, kind)
    payload: Mapped[dict | None] = mapped_column(JSONVariant)
    payload_gz: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    codec: Mapped[str] = mapped_column(sa.String(8), default="json")

    __table_args__ = (
        sa.Index("ix_raw_records_lookup", "source", "kind", "key", "at"),
        # Retention prunes by (kind, at); without this it is a full scan.
        sa.Index("ix_raw_records_prune", "kind", "at"),
    )


# ---------------------------------------------------------------------------
# YouTube entities
# ---------------------------------------------------------------------------


class Channel(Base, Provenance):
    __tablename__ = "channels"

    channel_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    title: Mapped[str | None] = mapped_column(sa.String(256))
    country: Mapped[str | None] = mapped_column(sa.String(8))
    created_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    uploads_playlist: Mapped[str | None] = mapped_column(sa.String(32))
    keywords: Mapped[str | None] = mapped_column(sa.Text)
    topics: Mapped[list | None] = mapped_column(JSONVariant)
    first_seen: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class ChannelSnapshot(Base, AppendOnly, Provenance):
    """Subscriber / view trajectory. `subs` is NULL when the channel hides it —
    never 0, which the prototypes' int(st.get("subscriberCount", 0)) produced."""

    __tablename__ = "channel_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[str] = mapped_column(sa.String(32), index=True)
    observed_date: Mapped[date] = mapped_column(sa.Date)
    subs: Mapped[int | None] = mapped_column(sa.BigInteger)
    total_views: Mapped[int | None] = mapped_column(sa.BigInteger)
    video_count: Mapped[int | None] = mapped_column(sa.Integer)

    __table_args__ = (
        sa.UniqueConstraint(
            "channel_id", "observed_date", "source", name="uq_channel_snapshots_day"
        ),
    )


class Video(Base, Provenance):
    __tablename__ = "videos"

    video_id: Mapped[str] = mapped_column(sa.String(16), primary_key=True)
    channel_id: Mapped[str] = mapped_column(sa.String(32), index=True)
    title: Mapped[str | None] = mapped_column(sa.Text)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), index=True)
    duration_s: Mapped[int | None] = mapped_column(sa.Integer)
    category_id: Mapped[str | None] = mapped_column(sa.String(8))
    audio_lang: Mapped[str | None] = mapped_column(sa.String(16))
    tags: Mapped[list | None] = mapped_column(JSONVariant)
    topics: Mapped[list | None] = mapped_column(JSONVariant)
    is_short: Mapped[bool | None] = mapped_column(sa.Boolean)
    midroll_eligible: Mapped[bool | None] = mapped_column(sa.Boolean)
    sponsor_signal: Mapped[bool | None] = mapped_column(sa.Boolean)
    first_seen: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    enriched: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class VideoSnapshot(Base, AppendOnly, Provenance):
    """The compounding asset. RSS writes here nightly at zero quota cost; every
    day this is not running is velocity history that cannot be backfilled."""

    __tablename__ = "video_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(sa.String(16), index=True)
    channel_id: Mapped[str | None] = mapped_column(sa.String(32), index=True)
    observed_date: Mapped[date] = mapped_column(sa.Date)
    views: Mapped[int | None] = mapped_column(sa.BigInteger)
    likes: Mapped[int | None] = mapped_column(sa.BigInteger)
    comments: Mapped[int | None] = mapped_column(sa.BigInteger)

    __table_args__ = (
        sa.UniqueConstraint("video_id", "observed_date", "source", name="uq_video_snapshots_day"),
        sa.Index("ix_video_snapshots_series", "video_id", "observed_date"),
    )


class Discovery(Base, AppendOnly, Provenance):
    """Which query surfaced which video, under which sort order.

    `order_by` is load-bearing: order=date is the unbiased pool (the denominator
    for breakthrough rate), order=viewCount is the winners (the numerator).
    Losing this column collapses the openness metric.
    """

    __tablename__ = "discoveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(sa.String(16), index=True)
    seed_id: Mapped[int | None] = mapped_column(sa.ForeignKey("niche_seeds.id"), index=True)
    query: Mapped[str] = mapped_column(sa.String(256))
    order_by: Mapped[str] = mapped_column(sa.String(16))  # date | viewCount
    observed_date: Mapped[date] = mapped_column(sa.Date)

    __table_args__ = (
        sa.UniqueConstraint(
            "video_id", "query", "order_by", "observed_date", name="uq_discoveries_day"
        ),
    )


class FeedState(Base):
    """Per-channel RSS polling state: conditional-GET validators and the
    circuit breaker. Not a snapshot — it is mutable by design."""

    __tablename__ = "feed_state"

    channel_id: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    etag: Mapped[str | None] = mapped_column(sa.String(256))
    last_modified: Mapped[str | None] = mapped_column(sa.String(64))
    last_polled: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    last_status: Mapped[int | None] = mapped_column(sa.Integer)
    fail_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    hot: Mapped[bool] = mapped_column(sa.Boolean, default=False)


# ---------------------------------------------------------------------------
# Clustering (Phase 2) — every collected item resolves to a cluster_id
# ---------------------------------------------------------------------------


class Cluster(Base, Provenance):
    __tablename__ = "clusters"

    cluster_id: Mapped[str] = mapped_column(sa.String(48), primary_key=True)
    seed_id: Mapped[int | None] = mapped_column(sa.ForeignKey("niche_seeds.id"), index=True)
    label: Mapped[str | None] = mapped_column(sa.String(200))
    centroid: Mapped[list | None] = mapped_column(JSONVariant)
    member_counts: Mapped[dict | None] = mapped_column(JSONVariant)  # by source
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class ClusterMember(Base, Provenance):
    __tablename__ = "cluster_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    item_type: Mapped[str] = mapped_column(sa.String(24))  # video, question, query, keyword
    item_id: Mapped[str] = mapped_column(sa.String(256))
    confidence: Mapped[float | None] = mapped_column(sa.Float)
    is_noise: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    __table_args__ = (sa.UniqueConstraint("item_type", "item_id", name="uq_cluster_members_item"),)


# ---------------------------------------------------------------------------
# Features & scoring (Phases 3-4)
# ---------------------------------------------------------------------------


class FeatureDaily(Base, Provenance):
    """One metric, one cluster, one day. `confidence` and `inputs_n` are
    mandatory: a metric computed from 3 rows must not read like one from 300."""

    __tablename__ = "features_daily"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    day: Mapped[date] = mapped_column(sa.Date, index=True)
    # `metric_group`, not `group`: the latter is a SQL keyword, so every
    # hand-written traceability query would have to quote it forever — and
    # traceability is one of the eight production criteria in docs/ROADMAP.md.
    metric_group: Mapped[str] = mapped_column(sa.String(24))
    """demand | supply | openness | voice | money | cost_risk"""

    name: Mapped[str] = mapped_column(sa.String(64))
    value: Mapped[float | None] = mapped_column(sa.Float)
    confidence: Mapped[float | None] = mapped_column(sa.Float)
    inputs_n: Mapped[int | None] = mapped_column(sa.Integer)
    detail: Mapped[dict | None] = mapped_column(JSONVariant)

    __table_args__ = (
        sa.UniqueConstraint("cluster_id", "day", "name", name="uq_features_daily_metric"),
    )


class Scorecard(Base, Provenance):
    __tablename__ = "scorecards"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    day: Mapped[date] = mapped_column(sa.Date, index=True)
    gap: Mapped[float | None] = mapped_column(sa.Float)
    #: Supply is an input to `gap` (= demand - supply), so it has to be stored
    #: for the gap to be reconstructible once Slice 3 brings the demand side.
    supply: Mapped[float | None] = mapped_column(sa.Float)
    openness: Mapped[float | None] = mapped_column(sa.Float)
    value: Mapped[float | None] = mapped_column(sa.Float)
    sustainability: Mapped[float | None] = mapped_column(sa.Float)
    opportunity: Mapped[float | None] = mapped_column(sa.Float)
    ci_low: Mapped[float | None] = mapped_column(sa.Float)
    ci_high: Mapped[float | None] = mapped_column(sa.Float)
    stage: Mapped[str | None] = mapped_column(sa.String(24))

    __table_args__ = (sa.UniqueConstraint("cluster_id", "day", name="uq_scorecards_day"),)


class Alert(Base, AppendOnly, Provenance):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    rule: Mapped[str] = mapped_column(sa.String(64), index=True)
    severity: Mapped[str] = mapped_column(sa.String(16))
    fired_on: Mapped[date] = mapped_column(sa.Date)
    evidence: Mapped[dict] = mapped_column(JSONVariant)

    __table_args__ = (sa.UniqueConstraint("cluster_id", "rule", "fired_on", name="uq_alerts_day"),)
