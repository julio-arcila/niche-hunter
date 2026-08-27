# Decisions (ADRs)

One paragraph each. Don't relitigate — add a new ADR that supersedes an old one.

## ADR-0001 — Python 3.12 + uv
2026-08-27. Accepted. The five prototypes are already Python, and the analysis
work ahead (embeddings, HDBSCAN, regressions) has its centre of gravity there.
`uv` for env and dependency management: fast, lockfile-based, and it manages the
interpreter itself so the pinned 3.12 does not depend on what happens to be on
the machine.

## ADR-0002 — SQLite first, Postgres behind a URL
2026-08-27. Accepted. **Supersedes the stack table in `niche-hunter-PLAN.md`,
which specified Postgres 16 from day one.** For the first weeks the schema
changes daily and there is exactly one user; SQLite with WAL handles millions of
snapshot rows and removes a moving part while the table shapes are still being
discovered. The models are SQLAlchemy and the Alembic baseline is in place from
the start, so the swap is `NH_DATABASE_URL` and nothing else — `docker-compose.yml`
is already written for it. Move when clustering starts (Phase 2) and JSONB
queries and concurrent writers begin to matter. The plan's own principle — don't
build orchestration before there is something to orchestrate — applies to the
database too.

## ADR-0003 — Provenance and append-only are enforced in code, not reviewed
2026-08-27. Accepted. `.claude/rules/data.md` rules 1, 4 and 6 are the ones whose
violation is invisible after the fact: a snapshot overwritten or a NULL written
as 0 leaves no trace and silently corrupts every downstream median and z-score.
So they are mechanical: `Collector._stamp()` injects `source`/`run_id`/`at` on
every row, the `AppendOnly` mixin plus a `before_flush` listener raises
`AppendOnlyViolation` on any snapshot mutation, and `nh.collectors.parse.*`
return `None` rather than 0. Tests in `tests/test_base_collector.py` assert each.
The cost is a little indirection in `base.py`; the benefit is that a new
collector cannot get these wrong by omission.

## ADR-0004 — One `raw_records` table, not `raw_<source>` per source
2026-08-27. Accepted. The plan called for a `raw_*` table per source. A single
table with `(source, kind, key)` and a JSON payload satisfies the actual
requirement — the raw payload is stored before normalization, so re-normalizing
history is a query rather than a re-fetch — with far less schema churn while
sources are still being added. Revisit if a single source's payloads grow large
enough to want their own partitioning.

## ADR-0005 — Prototypes are frozen in `legacy/`, ported one at a time
2026-08-27. Accepted. The five `niche_hunter_*.py` scripts moved to `legacy/`
unchanged, are excluded from ruff, and are blocked from edits in
`.claude/settings.json`. They are the reference for what the domain logic is
supposed to do; a port that changes behaviour and breaks something should be
diffable against a fixed original. Each is deleted only once its collector is
ported, tested against a recorded fixture, and running in a nightly.

## ADR-0006 — RSS is the first collector to build
2026-08-27. Accepted; **ordering claim superseded by ADR-0007**. `youtube_rss` was the first collector to port because it is the only
collector whose output cannot be reconstructed later: view velocity is a
difference between observations, and no source serves historical view counts.
Everything else — search results, Trends shapes, keyword volumes — can be
re-fetched at close to its present value. RSS also costs zero quota, so running
it first never competes with anything.

## ADR-0007 — Nightly run order is discovery before RSS
2026-08-27. Accepted. **Supersedes the ordering claim in ADR-0006**; that ADR's
reasoning about implementation priority stands unchanged. `REGISTRY` order *is*
nightly run order, and ADR-0006 conflated the two. Only `youtube_api` can produce
a channel list, so RSS-first makes day 1 a guaranteed no-op — and on every later
night it delays a freshly discovered channel's first velocity reading by 24 hours,
permanently, for each new channel. The irreplaceability argument in ADR-0006 in
fact argues *for* API-first: velocity is a difference between observations, so the
earlier the first observation, the sooner velocity exists at all. The apparent
benefit of RSS-first — "run the precious thing before anything can break" — is
already provided by `run_nightly()`, which catches per-collector failures and
continues; a failed `youtube_api` does not stop `youtube_rss`. There is no write
conflict either: `video_snapshots` is unique per `(video, day, source)`, so both
collectors snapshot the same video on the same day without colliding.

## ADR-0008 — One snapshot per entity per day per source
2026-08-27. Accepted. `uq_video_snapshots_day (video_id, observed_date, source)`
means the first reading of a day wins and later ones are silently dropped by
`insert_ignore`. That is correct and deliberate for a daily job: re-running a day
is a safe no-op. The consequence to remember is that the future `hourly_hot` job
**cannot** write here — a second same-day poll would vanish. Intraday velocity
needs either a snapshot table keyed to the minute or an extended unique key.
Recorded now so nobody "fixes" the drop by making snapshots updatable, which
would violate data rule 4 and destroy the series.

## ADR-0009 — Collector batches commit as they go
2026-08-27. Accepted. `Collector.run()` originally wrapped a whole run in one
transaction and rolled it back on any failure, so a collector dying at feed 700 of
800 discarded all 700. For a pipeline whose entire premise is that snapshots
cannot be re-fetched tomorrow, that traded a partial success for a total loss.
`_flush()` now commits, and the rollback on failure drops only the batch in
flight. The cost is that a failed run leaves partial data — which is the right
trade here, and is visible in `job_runs` (`status='failed'` alongside non-zero
`snapshots_written`) rather than hidden.

## ADR-0010 — Bulk raw payloads are compressed and time-bounded
2026-08-27. Accepted. **Refines ADR-0004**, which is still right about one
`raw_records` table but was sized for JSON payloads of a few KB. Measured against
live data: YouTube's Atom feeds return **no cache validators** — no ETag, no
Last-Modified — so a conditional GET can never produce a 304 and every nightly
poll stores the full ~64 KB of XML per channel, near-identical to the night
before. Three runs produced 95.8 MB and a 127 MB database, tracking toward ~21 GB
a year and rising with the channel count. Two changes, because each alone still
grows without limit: payloads over 4 KB are gzipped into `payload_gz` with a
`codec` column saying which form is stored (95.8 MB → 18.9 MB, and the whole
database 127 MB → 49 MB), and `feed` payloads older than
`NH_RAW_RETENTION_DAYS` (14) are pruned nightly. The threshold is on **size, not
kind**, so nothing needs special-casing as a new source arrives; small payloads
stay readable JSON and remain queryable with JSON operators.

The retention prune is the only deliberate deletion in the codebase. It touches
`raw_records` and nothing else: `nh.db.retention.prune_raw_records` is hard-coded
to that model. Snapshots are never pruned — they are the unbackfillable asset and
the reason the pipeline exists, while raw payloads are a replay convenience whose
value decays. Note the prune uses a Core DELETE, which the `AppendOnly` ORM guard
in `nh.db.session` does not see; that guard prevents *accidental* mutation, and
the narrowness of this function is what prevents deliberate misuse.

The conditional-GET machinery in `youtube_rss` is kept despite being inert. It is
tested, costs nothing, and YouTube may add validators later. `requests` already
negotiates gzip on the wire (~7 MB a night for 955 feeds), so transfer was never
the problem — storage was.

## ADR-0011 — The YouTube quota ledger is per day, not per run
2026-08-27. Accepted. `QuotaLedger` was constructed fresh on every collector run
with the full 9,500-unit budget, but YouTube's quota is allocated **per day** and
tracked server-side across every call the key makes. A second run in the same day
— a manual retry, a re-run after a failure, two cron fires — therefore believed it
had a full budget, spent past the real ceiling, and got throttled. Found live: after
9,624 units of verification runs, the next invocation failed with `retries exhausted
for search` rather than stopping cleanly, because a 429 storm looks nothing like a
quota message. `YouTubeApiCollector` now sums `job_runs.quota_used` for this source
since **midnight America/Los_Angeles** — neither UTC nor local midnight — and starts
the ledger with what is left.

Two supporting changes. A `403 quotaExceeded` from Google is recognised and raises
`QuotaExhausted` immediately instead of being retried into an unrecognisable
"retries exhausted"; and `QuotaLedger.exhaust()` marks the budget spent without
charging anything, so once the upstream ceiling is hit every remaining query in the
run short-circuits rather than asking and being refused again. Hitting either
ceiling is a *degraded* run, not a failed one: what was collected before the stop is
kept, and `job_runs.quota_used` plus the `nh status --check` quota warning make the
degradation visible.

## ADR-0012 — The enrichment backfill runs inside the YouTube API collector
2026-08-27. Accepted. 12,483 RSS-discovered videos carry NULL duration, so format
filtering is impossible for 91% of the corpus. The backfill is a fourth stage of
`YouTubeApiCollector.fetch()` rather than a separate collector, because the
day-aware ledger (ADR-0011) lives in that class: a second collector would either
duplicate `_spent_today()` or run with its own fresh 9,500 budget, which is exactly
the bug ADR-0011 fixed. Ordering then falls out for free — discovery, the expensive
and irreplaceable stage, spends first, and the backfill consumes only what is left
under the same per-chunk `can_afford` gate. Cost is ~250 units once against ~6,459
spare, then ~10 a night.

A video that returns no item from `videos.list` (deleted or made private) is marked
`enriched=True` with duration still NULL. This slightly redefines the flag as "the
API has been consulted about this id" rather than "this id has a duration", which is
the honest reading: the raw record documents the absence, unknown duration correctly
excludes it from format-sensitive metrics, and the id stops being re-queried every
night forever. The mark is only applied when the quota was not exhausted, so an id
never asked about is not recorded as missing.

## ADR-0013 — One cluster per item; the ambiguous 14 resolve to a dominant seed
2026-08-27. Accepted. `ClusterMember.UniqueConstraint("item_type", "item_id")`
stays. It was tempting to drop it — 14 of 955 channels legitimately span two seeds,
and soft membership is what HDBSCAN will produce in Slice 4 — but hard assignment is
what makes `cluster_id` a **partition**, and every aggregate below assumes one. A
channel in two clusters counts its uploads and views toward two supply and openness
denominators, and scores across overlapping clusters stop being comparable because
they share evidence. Slice 4's HDBSCAN also hard-assigns, with a noise flag for the
remainder; soft membership, if ever wanted, is a later ADR where
`ClusterMember.confidence` does real work, and that column already exists so nothing
is foreclosed.

Dominance is computed from discovery lineage and is deterministic: rank a channel's
candidate seeds by distinct videos discovered under `order_by='date'` (descending),
then distinct videos total, then lowest `seed_id`. Distinct videos, not raw rows,
because `discoveries` appends nightly and row counts would drift dominance toward
whichever seed's queries re-surface the same videos most often. `order='date'` leads
because `order='viewCount'` hits select on success and should not decide identity.
`ClusterMember.confidence` records the dominant seed's share.

## ADR-0014 — Features and scoring are job_runs phases, and the gate checks them
2026-08-27. Accepted. The nightly gains three phases after the collectors —
`clustering`, `features`, `scoring` — each a `job_runs` row under the same `run_id`
with `source` set to the phase name and quota columns NULL. Phases are not
collectors: no fetch, no normalize, no quota, no raw payloads. They share exactly
two things with collectors, and both are extracted rather than inherited: provenance
stamping (`nh/db/provenance.py::stamp`, which `Collector._stamp` now delegates to)
and the write layer.

`nh/jobs/status.py::check` iterates `REGISTRY` ported sources, so phase rows would
have been **silently ignored** — a features phase failing every night behind a green
healthcheck, which is the same class of hole that `nh status --check` was built to
close for collectors. `check` now also requires each phase to be present and `ok`,
and warns on any `job_runs` source that is neither a registry source nor a phase, so
the next person to add one learns from the gate rather than from archaeology.

Phases run even when a collector failed: features compute over whatever is real and
`confidence` says how much that was, and a dead source must not also cost the
night's feature history. `--only` runs skip phases, so debugging one collector never
rewrites the day's features; `nh compute` is the deliberate recompute path and
records `job="partial"`, which the gate ignores by construction. Re-running a day
rewrites identical values in place — `run_id` and `at` are deliberately refreshed,
so provenance points at the computation that produced the values currently stored.
