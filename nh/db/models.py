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
    #: The market this niche is *about*, stated rather than left to inference.
    #: `supply.geo_concentration` measures how far the supply we actually collect
    #: diverges from it — measured 2026-08-27, 234 of 719 channels are Indian
    #: against 290 US, while demand is read off English Wikipedia. A seed whose
    #: supply sits outside its stated geo has a demand number that does not
    #: describe its supply, and the metric says so rather than `gap` absorbing it.
    geo: Mapped[str | None] = mapped_column(sa.String(8))
    lang: Mapped[str | None] = mapped_column(sa.String(8))
    #: Dated hand research: `[{name, url, status, reviewed_on}]` with
    #: `status in {collected, exists_uncollected, none_found}`. Primary-source
    #: availability is a constant property of a niche with n=5, not a daily
    #: measurement, so it lives here rather than in `features_daily` — where NULL
    #: already means "we looked and could not compute" and would have to carry
    #: "there is nothing to look at" as well (ADR-0020).
    primary_sources: Mapped[list | None] = mapped_column(JSONVariant)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class SeedTerm(Base):
    """Curated demand-side identifiers per seed.

    The YouTube seed keywords are demand-dead elsewhere — measured, most read
    literal zero on Trends and `aviation disasters documentary` is NaN even alone
    — so demand needs its own mapping. Like `niche_seeds` this is hand curation
    written by `nh seed`: edit the literal in nh/seeds.py and re-run. It carries
    no Provenance mixin for the same reason.

    One row per (seed, source, term). `wikipedia` rows hold article titles,
    `trends` rows hold the broad proxy terms that clear Trends' volume floor, and
    `keyword_planner` rows are the slot Gate C fills later (ADR-0016).
    """

    __tablename__ = "seed_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    seed_id: Mapped[int] = mapped_column(sa.ForeignKey("niche_seeds.id"), index=True)
    source: Mapped[str] = mapped_column(sa.String(32))  # wikipedia | trends | keyword_planner
    term: Mapped[str] = mapped_column(sa.String(256))
    #: Wikidata QID — the join key docs/ARCHITECTURE.md already names.
    qid: Mapped[str | None] = mapped_column(sa.String(16))
    #: '' means worldwide. NOT NULL on purpose: a NULL would split the unique key,
    #: since NULL never equals NULL in SQL.
    geo: Mapped[str] = mapped_column(sa.String(8), default="")
    #: Which *level* of the subject this term measures: `topic` for the index-page
    #: articles Slice 3 curated, `event` for named occurrences. The two are carried
    #: in parallel rather than one replacing the other — measured, they invert the
    #: demand ranking end to end, and Gate E arbitrates against a criterion
    #: registered before the new ranking was looked at (ADR-0022). NOT NULL for the
    #: same reason `geo` is: it is part of the unique key.
    stratum: Mapped[str] = mapped_column(sa.String(16), default="topic")
    lang: Mapped[str | None] = mapped_column(sa.String(8))
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        # `stratum` is in the key so one article may serve both strata; the shared
        # `demand_snapshots` rows are then fetched once and read twice.
        sa.UniqueConstraint("seed_id", "source", "term", "stratum", name="uq_seed_terms_term"),
    )


class DemandSnapshot(Base, AppendOnly, Provenance):
    """One absolute demand reading per *described* day.

    `observed_date` is the day the value DESCRIBES, not the day we fetched it —
    `at` records that. This is the one place the two readings diverge, and
    `stamp()` supports it deliberately: it uses `setdefault`, so a backfilled row
    keeps the described day it was given (ADR-0015 refines ADR-0008).

    Wikipedia dailies now; Keyword Planner monthly volumes later as month-start
    rows, which are the same shape of stable described-period fact.
    """

    __tablename__ = "demand_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(sa.String(256), index=True)
    geo: Mapped[str] = mapped_column(sa.String(8), default="")
    observed_date: Mapped[date] = mapped_column(sa.Date)
    value: Mapped[float | None] = mapped_column(sa.Float)

    __table_args__ = (
        sa.UniqueConstraint(
            "term", "geo", "observed_date", "source", name="uq_demand_snapshots_day"
        ),
        sa.Index("ix_demand_snapshots_series", "term", "observed_date"),
    )


class DemandSeries(Base, AppendOnly, Provenance):
    """One observation of a whole normalised series (Google Trends).

    Points CANNOT be appended across fetches. Trends renormalises every response
    to its own peak, so a new all-time peak silently rescales later points against
    frozen earlier ones and corrupts the series undetectably. The honest unit of
    observation is therefore the entire curve as seen on a date — which is also
    exactly the leak-free replay shape Slice 6 needs (ADR-0015).
    """

    __tablename__ = "demand_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(sa.String(256), index=True)
    geo: Mapped[str] = mapped_column(sa.String(8), default="")
    timeframe: Mapped[str] = mapped_column(sa.String(24))  # e.g. "today 5-y"
    observed_date: Mapped[date] = mapped_column(sa.Date)
    points: Mapped[list] = mapped_column(JSONVariant)  # [["2021-09-05", 41.0], ...]

    __table_args__ = (
        sa.UniqueConstraint(
            "term", "geo", "timeframe", "observed_date", "source", name="uq_demand_series_day"
        ),
    )


class KeywordMetric(Base, AppendOnly, Provenance):
    """One Keyword Planner reading per keyword per described period.

    **Append-only, not the entity table ADR-0016 anticipated.** That ADR called for
    "a `keyword_metrics` entity table for bids and competition", which would be
    upserted on the keyword. But a bid is a *described-period fact*, not a property
    of the keyword: every monthly re-export carries a new twelve-month window, and an
    upsert would silently overwrite the previous period's price with the current
    one, destroying exactly the history this table exists to accumulate. Written with
    `insert_ignore`, so re-ingesting the same export is a no-op and the first reading
    of a period is the one that survives — the same rule the `*_snapshots` tables live
    under (ADR-0030 refines ADR-0016 on this point).

    `observed_date` is the **last day of the period the numbers describe**, taken from
    the export's own header line, with `period_start` making the window explicit. That
    is ADR-0027's third reading of the column — "the period the value covers, landed on
    its final day" — extended from a week to twelve months rather than inventing a
    fourth reading. `at` remains the day the file was exported.

    `avg_monthly_searches` is stored **exactly as the export gives it**, which on a
    zero-spend account means power-of-ten bucket midpoints (measured 2026-08-28: only
    50, 500, 5000 and 50000 occur across 30 keywords). It is a bucket centre, not a
    count; nothing here may de-bucket it, and every metric built on it inherits that
    coarseness. NULL means the export carried no volume for the keyword — 8 of 30 on
    the first US export — and never zero, which would be a different and false claim
    (data rule 7).

    `currency` is stored verbatim because no exchange rate may be invented to
    normalise it (ADR-0031). `method` distinguishes the UI CSV path from an eventual
    API path; the prototype proved both normalise identically.
    """

    __tablename__ = "keyword_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(sa.String(256), index=True)
    #: '' means worldwide, matching `seed_terms.geo`. NOT NULL: a NULL would split
    #: the unique key, since NULL never equals NULL in SQL.
    geo: Mapped[str] = mapped_column(sa.String(8), default="")
    lang: Mapped[str | None] = mapped_column(sa.String(8))
    observed_date: Mapped[date] = mapped_column(sa.Date)
    period_start: Mapped[date | None] = mapped_column(sa.Date)
    avg_monthly_searches: Mapped[float | None] = mapped_column(sa.Float)
    three_month_change: Mapped[float | None] = mapped_column(sa.Float)
    yoy_change: Mapped[float | None] = mapped_column(sa.Float)
    #: The locale label as exported ("Baja"/"Low"). Kept verbatim beside the numeric
    #: index so a locale change is visible rather than silently remapped.
    competition: Mapped[str | None] = mapped_column(sa.String(32))
    competition_index: Mapped[int | None] = mapped_column(sa.Integer)
    bid_low: Mapped[float | None] = mapped_column(sa.Float)
    bid_high: Mapped[float | None] = mapped_column(sa.Float)
    currency: Mapped[str | None] = mapped_column(sa.String(8))
    method: Mapped[str] = mapped_column(sa.String(16), default="ui_csv")
    #: Ties every row to the exact bytes it came from, so a number on a page can be
    #: traced to a file in `raw_records` without trusting a filename.
    file_sha256: Mapped[str | None] = mapped_column(sa.String(64))

    __table_args__ = (
        sa.UniqueConstraint(
            "keyword", "geo", "lang", "observed_date", "source", name="uq_keyword_metrics_period"
        ),
        sa.Index("ix_keyword_metrics_series", "keyword", "observed_date"),
    )


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
    #: The richest text a video carries — ~20x the title, and the input the
    #: relevance scorer needs. Captured by both collectors, but for videos already
    #: collected it exists only inside `raw_records`, which `nh prune` deletes at
    #: `raw_retention_days`; `nh backfill descriptions` rescues those (ADR-0017).
    description: Mapped[str | None] = mapped_column(sa.Text)
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
    #: Reserved for an embedding centroid. Stays NULL while clustering is
    #: lexical — a bag-of-words vector in a column named `centroid` would be a
    #: placeholder that looks like a score (ADR-0018).
    centroid: Mapped[list | None] = mapped_column(JSONVariant)
    member_counts: Mapped[dict | None] = mapped_column(JSONVariant)  # by item_type and decision
    #: Retirement, not deletion. `nh/features/run.py` iterates `clusters`, so a
    #: cluster whose seed was deactivated would otherwise keep generating feature
    #: rows forever; deleting it would orphan its `features_daily` history.
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    retired_on: Mapped[date | None] = mapped_column(sa.Date)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)


class ClusterMember(Base, Provenance):
    __tablename__ = "cluster_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    item_type: Mapped[str] = mapped_column(sa.String(24))  # video, question, query, keyword
    item_id: Mapped[str] = mapped_column(sa.String(256))
    confidence: Mapped[float | None] = mapped_column(sa.Float)
    #: How strongly the item's text matches its cluster's lexicon. NULL means the
    #: item could not be scored at all — no text, or a script the lexicon cannot
    #: read — which is not the same as scoring zero (data rule 7). The on-niche and
    #: noise cuts are applied at read time from this, so changing a threshold is a
    #: query rather than a rewrite of history.
    relevance: Mapped[float | None] = mapped_column(sa.Float)
    #: Which terms matched, at what weight, under which lexicon version — or why
    #: the item was unscorable. This is what makes a supply number traceable to the
    #: rows underneath it.
    detail: Mapped[dict | None] = mapped_column(JSONVariant)
    is_noise: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    __table_args__ = (
        sa.UniqueConstraint("item_type", "item_id", name="uq_cluster_members_item"),
        # The table grows from ~955 channel rows to ~15,900 once videos are members,
        # and every feature query filters on both columns.
        sa.Index("ix_cluster_members_cluster_type", "cluster_id", "item_type"),
    )


class RelevanceLabel(Base):
    """Hand labels: is this video actually about its cluster's niche?

    The ground truth the relevance thresholds are chosen against, and the only
    reason `reports/relevance_*.md` can state a precision rather than an impression.
    Deliberately not a snapshot and not `Provenance`-stamped: a correction should
    overwrite, and this is hand curation like `SeedTerm`, not a pipeline write.
    """

    __tablename__ = "relevance_labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(sa.String(16), unique=True)
    cluster_id: Mapped[str] = mapped_column(sa.String(48), index=True)
    #: True = about this niche. False = not. There is no "unsure" — a label that
    #: cannot be given is left unwritten rather than recorded as a third state.
    label: Mapped[bool] = mapped_column(sa.Boolean)
    labeller: Mapped[str] = mapped_column(sa.String(64))
    labelled_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=utcnow)
    notes: Mapped[str | None] = mapped_column(sa.Text)


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
    #: Percentile rank of demand.wiki_weekly_views. Stored for the same reason
    #: `supply` is: gap must be reconstructible from the row that reports it.
    demand: Mapped[float | None] = mapped_column(sa.Float)
    #: min(demand confidence, supply confidence) — the weaker leg bounds the chain.
    gap_confidence: Mapped[float | None] = mapped_column(sa.Float)
    openness: Mapped[float | None] = mapped_column(sa.Float)
    value: Mapped[float | None] = mapped_column(sa.Float)
    sustainability: Mapped[float | None] = mapped_column(sa.Float)
    opportunity: Mapped[float | None] = mapped_column(sa.Float)
    ci_low: Mapped[float | None] = mapped_column(sa.Float)
    ci_high: Mapped[float | None] = mapped_column(sa.Float)
    #: Demand-trajectory stage, not a lifecycle stage — supply momentum does not
    #: exist yet and the name must not promise it (ADR-0023).
    stage: Mapped[str | None] = mapped_column(sa.String(24))
    stage_confidence: Mapped[float | None] = mapped_column(sa.Float)
    #: The input vector, the threshold-set version, which axes were available, and
    #: the alternate-stratum stage. When supply momentum lands in a few weeks and
    #: stages move, the move has to be attributable rather than mysterious.
    detail: Mapped[dict | None] = mapped_column(JSONVariant)

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
