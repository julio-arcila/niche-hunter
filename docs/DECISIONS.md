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

## ADR-0015 — Wikipedia is the primary demand signal; Trends is shape-only, with no anchor
2026-08-27. Accepted. **Supersedes the anchor-scaling language** in ROADMAP Slice 3,
the `trends` note in `nh/collectors/registry.py`, and the prototype docstring.

Measured against the live endpoints before designing:

* `related_queries` and `related_topics` return `TrendsQuotaExceededError`, and the
  documented referer workaround also fails. That removes `expand_seeds()` and, more
  importantly, topic-mid (`/m/0abc`) resolution — which the prototype's own
  docstring names as *the* fix for low-volume terms.
* Our seed phrases mostly read literal zero. Trends normalises 0–100 per request
  against the batch maximum, so a small term beside a large one rounds away. With
  `documentary` (mean 44.8) as anchor: 0 of 3 targets had data. With
  `air crash investigation` (17.7): 2 of 3. Queried alone,
  `aviation disasters documentary` is `nan` — no volume in any framing.
* Wikipedia pageviews return data for all five niches in **absolute** units,
  spanning 590x (with `agent=user`), from an official quota-free API, and hand over
  11.2 years of history on the first call.

So Wikipedia carries **level** and Trends carries **shape**.

**No anchor, and no anchor chain.** The anchor exists for exactly one purpose: to
carry level across batches. Once level comes from Wikipedia, Trends does not need
to. What per-request normalisation does *not* destroy is within-series shape —
momentum, log-slope and seasonality are scale-invariant — so Trends is queried one
term per request with no anchor at all. A chain was considered and rejected: every
link is an integer-quantised 0–100 ratio carrying ±5 points of sampling jitter, and
the weakest useful link measured (0.27 against a mean-17.7 anchor) is built from
weekly values that mostly round to 0 or 1 — near 100% relative error before the
chain multiplies it. It would also make every niche's number depend on every link
staying fetchable on a quota-blocked, 20-month-stale client. `Settings.trends_anchor`
is deleted rather than left in config inviting use; its default was `documentary`,
the measured-worst choice.

`observed_date` acquires two readings, and this ADR **refines ADR-0008** rather than
violating it. For `demand_snapshots` it is *the day the value describes*, with `at`
recording when we fetched — the affordance `nh/db/provenance.py::stamp` was built
for, since it uses `setdefault`. ADR-0008's rule then reads "one reading per
described day per source". For `video_snapshots` and `channel_snapshots` it keeps
meaning "when we looked", because a view count is only knowable as of the poll.
Wikimedia counts mature over 24–48h, so nothing closer than `day − 2` is ever
fetched and the feature window ends there symmetrically — otherwise first-write-wins
would freeze an undercount permanently.

Trends gets its own table rather than sharing `demand_snapshots`, because **its
weekly points cannot be appended across fetches**: each fetch renormalises to its
own peak, so a new all-time peak silently rescales future points against frozen old
ones and corrupts the series undetectably. The honest unit of observation is the
entire curve as seen on a date, which is also the leak-free replay shape Slice 6
needs.

`legacy/niche_hunter_trends.py` is **kept** despite ADR-0005's deletion clause. The
port is deliberately partial — `expand_seeds` (blocked upstream), `geo_tier1_share`
(uncited weights, see ADR-0016) and `trending_matches` (Slice 4 material) remain
reference. Its survival is a decision, not an oversight.

## ADR-0016 — Gate C: Keyword Planner deferred, and tier1_share resolved by fiat
2026-08-27. Accepted. `NH_GADS_CUSTOMER_ID` is empty and `google-ads.yaml` does not
exist, so there is no API access and no application in flight. Slice 3 therefore
ships **zero money metrics**; its exit criterion needs only `gap`, which depends on
Wikipedia and the existing supply side.

The four-week clock in the roadmap's Gate C starts today. On expiry, commit to the
UI CSV export path, which needs no approval and is adequate for five niches. What is
built now so that switching on is configuration rather than a rewrite: the
`seed_terms` table carries a `source='keyword_planner'` slot, and `docs/SOURCES.md`
records the storage contract (raw payloads to `raw_records`, monthly volumes to
`demand_snapshots` as month-start rows — a stable described-month fact of the same
shape as Wikipedia, plus a `keyword_metrics` entity table for bids and competition,
migrated when the data can actually be fetched). The prototype already proves API
and CSV rows normalise identically via its `source='ideas'|'ui_csv'` column.

The `tier1_share` double definition flagged in METRICS.md is resolved by decision:
Keyword Planner's `cpc_geo_spread` is **authoritative** for anything feeding a
dollar figure, because it is measured price times volume in absolute units; the
Trends `interest_by_region` share is context and display only and may never feed a
composite. `geo_tier1_share` is **not ported** until its ~29-country internet-user
weight dict carries a citation — an uncited constant must not sit under a dollar
figure. That is a Slice 5 task attached to the RPM model, which is where a dollar
figure first appears anyway.

## ADR-0017 — Retention may not delete the last copy of a description
2026-08-27. Accepted. **Refines ADR-0010**, which is still right that raw payloads
are a replay convenience whose value decays — but that argument holds only while
every fact a payload carries has been extracted into a typed table. Slice 4 found
one that had not been.

`videos.description` did not exist until this slice. Descriptions are the richest
text a video carries — median 1,052 characters against a 67-character title,
roughly 20x — and the relevance scorer needs them: on the corpus measured
2026-08-27, adding the description raises the share of videos matching their own
niche's lexicon from 22.2% to 42.4%. For the 14,899 videos already collected, that
text existed **only** inside gzipped `feed` payloads in `raw_records`, which
`scripts/run_nightly.sh` prunes after every nightly at
`NH_RAW_RETENTION_DAYS` (14). First deletion would have been ~2026-09-10.

The loss would have been permanent for a growing share of it. An Atom feed serves
15 entries and no history, so a video that has fallen out of its channel's window
cannot be re-fetched at any price; 1,873 of 14,899 were already past it the day
this was written, and that number grows every night a channel publishes. This is
the same class of loss `*_snapshots` retention is forbidden for (rule 4) — the
difference is only that nobody had noticed the description was in it.

So `prune_raw_records` now decodes its delete set and refuses, absent `--force`,
when it holds the only stored copy of any `videos.description`. `nh backfill
descriptions` is the way to satisfy it: a job, not a phase, because a phase runs
nightly forever and `nh/jobs/status.py` would then gate the healthcheck on a rescue
that does nothing after the first night. Both collectors now capture the field, so
the backfill is a one-off for history rather than a standing dependency.

The guard counts what the delete set **actually holds**, not every video missing a
description. The coarse version refuses forever: 1,044 videos have no description
in any payload we hold and never will, and a guard that cannot be satisfied is a
broken nightly rather than a safety feature. Cost is one decode of the delete set,
which in steady state is a single night's feeds.

Rejected: raising `raw_retention_days`. It re-inflates storage without bound —
the problem ADR-0010 exists to solve — and only moves the deadline. Also rejected:
stamping the rescued rows with the backfill's provenance. `nh.db.provenance.stamp`
uses `setdefault` precisely so a backfill can keep "the run that originally
produced them rather than the run that moved them", and the description came from
the payload the original collector fetched. Moving text between two columns of our
own database is not a new observation. The job's own provenance is its `job_runs`
row.

One implementation note worth keeping, because it will come up again: this write
is a targeted `UPDATE`, not an `upsert`. SQLite builds the full candidate row for
`INSERT ... ON CONFLICT DO UPDATE` before the conflict clause resolves, so a
payload carrying only `video_id` and `description` fails `NOT NULL constraint
failed: videos.channel_id`. Supplying the other columns to satisfy that would let
the job create video rows, which is exactly what it must never do.

## ADR-0018 — Gate D invoked: membership moves to video grain, sub-niches deferred
2026-08-27. Accepted. **Supersedes the Slice 4 plan in docs/ROADMAP.md.** That slice
was "sub-niches discovered rather than assumed": embeddings over YouTube titles,
Reddit question titles, Trends rising queries and Keyword Planner keywords **in one
space**, then HDBSCAN per seed. It is not built, and the reason is not the one Gate
D anticipated.

**The premise is void.** The roadmap's own justification for placing clustering
after Slice 3 was that *"clustering earns its keep only when there are multiple
sources to cluster together. Cluster YouTube titles alone and you have built a topic
model, not a demand–supply bridge."* Slice 3 then removed three of the four sources:
Reddit is unapproved and may never arrive, Trends `related_queries`/`related_topics`
are quota-blocked (ADR-0015), Keyword Planner is deferred (ADR-0016). Only YouTube
titles remain, so the roadmap's own argument says not to build it.

**And Gate D's criterion cannot be evaluated.** It says freeze to seed-level
clusters "if stability stays under 90% after honest effort", which presumes a
measurement. `cluster_members` had no day column and was overwritten in place, so
there was no day *t−1* to compare against, and there is one day of collection. The
criterion is not failing; it is unmeasurable. That is why this is an ADR and not a
checkbox.

Three measured facts make splitting actively harmful today, and each is a blocker
that must be cleared before sub-niches are attempted again:

1. **Demand cannot follow a split.** `nh/features/inputs.py::demand_terms` joins
   `clusters.seed_id → seed_terms.seed_id`, so every sub-cluster of a seed returns
   an identical article list and an identical `wiki_weekly_views`. `gap` would
   become a within-seed supply shuffle against a constant. `percentile_rank` now
   averages ties, but the deeper problem is that the demand side has no per-cluster
   mapping at all. `tests/test_features_demand.py` pins this invariant so a future
   split trips a red test rather than silently shipping identical demand.
2. **Openness dies.** `breakthrough_rate_cohort` and `views_per_sub` are NULL for 4
   of 5 clusters at ~190 channels per seed; a five-way split takes that to ~38 and
   makes them universally NULL. That would be trading a real metric group for fake
   resolution.
3. **The corpus was 80% off-niche.** HDBSCAN over that pool would have found real,
   tight, stable clusters — of Indian exam-prep content — and it would have looked
   like it worked.

**What shipped instead.** The third fact is not a clustering shortfall; it is a
correctness bug in the layer clustering owns, and it was poisoning every published
`supply.*` and `money.*` number. `nh/clustering/trivial.py` assigned *channels* to
seeds and videos inherited their channel's cluster, so one plane-crash video pulled
a channel's entire catalogue into aviation-disasters. Slice 4 keeps channel identity
exactly as ADR-0013 defines it and adds a second, separate question — is this
*video* about that niche — answered per video, hard-assigned, with an explicit
noise flag. That satisfies Slice 4's stated exit clause ("every item has a
`cluster_id` or a noise flag") without embeddings, and it delivers the substrate a
future sub-niche attempt needs.

**Embeddings are deferred with reasons, not by omission.** `tests/conftest.py`
blocks all sockets, so a model download at test time is impossible and a skipped
test on the decision gating every supply number is not a test. `sentence-transformers`
pulls torch, an order-of-magnitude change to a six-dependency project. And with no
labels an embedding threshold is a number chosen because the output looked nice.
Lexical fails legibly; embeddings fail invisibly. **No optional extra was added
either** — an unused extra invites use.

**The rule is calibrated and it missed its bar, which is recorded rather than
smoothed over.** Held-out precision 0.781 and recall 0.694 against a 28.6% base
rate; the plan asked for 0.90/0.70 and the 0.90 held only on the half the threshold
was chosen against (reports/relevance_2026-08-27.md). It ships anyway because the
status quo is *no* filter, which is a filter with precision 0.286 — refusing to
filter is choosing a measured-worse estimator, not staying neutral. Every dependent
metric carries a relevance-coverage leg in its confidence and a `definition` stamp
in `detail`, and `nh cluster calibrate` warns while precision is under 0.90. The
labeller was the same system that wrote the lexicon; an independent spot-check is
outstanding and is named as such at the top of the report.

**No membership history table, and this is the condition that reverses it.** A daily
`cluster_member_days` snapshot was designed and then dropped. Because the scorer is
deterministic and pure over `(title, description, lexicon_version)`, membership as
of any past day is reconstructible from `videos.first_seen` plus the frozen lexicon
— a recomputable artifact, not the unbackfillable kind data rule 4 protects — and a
day-over-day stability metric would read ~1.0 by construction and prove nothing.
**Any scorer whose output depends on the corpus makes this false.** That is the real
reason corpus IDF is banned in `nh/clustering/lexicon.py`: it would drift with the
corpus, break Slice 6's replay, and make the history table mandatory.

## ADR-0019 — Postgres deferred; the trigger restated in checkable terms
2026-08-27. Accepted. **Refines ADR-0002.** Its trigger read "move when clustering
starts (Phase 2) and JSONB queries and concurrent writers begin to matter."
Clustering shipped in Slice 4 and neither condition followed, which means the
trigger was a *prediction about what clustering would require* and the prediction
was wrong. Measured: no query anywhere in `nh/` indexes into a JSON column —
`JSONVariant` columns are read whole as Python objects — phases run sequentially in
one process, and the only concurrency is eight RSS fetch workers writing through a
single session.

Replacement trigger, any one of which fires the swap, all checkable by a person or
a script rather than by judgement:

1. a query filters or indexes *inside* a JSON payload (`payload ->> 'x'` in a
   `WHERE` or an index) — checkable by grep, which is how the current trigger was
   disproved;
2. more than one OS process writes concurrently — `nh/api` or `nh/web` writing
   (Slice 7), a second cron, or parallel phases;
3. the nightly backup copy stops fitting inside its cron window — measured, not a
   guessed byte threshold;
4. deploy leaves the laptop (Slice 8), where PITR is the driver and JSONB is
   incidental.

**ADR-0002's claim that "the swap is `NH_DATABASE_URL` and nothing else" is false**,
and is recorded as false here so nobody re-inherits it. Four specific things:

- `nh/db/retention.py::storage_report` called `length()` on `RawRecord.payload`,
  which is JSONB on Postgres. **`length(jsonb)` does not exist** — it raises
  `UndefinedFunction` at runtime, not a wrong number — and no test could catch it
  because `tests/conftest.py` is SQLite-only. Fixed in Slice 5 with a cast.
- **There is no data-migration path.** `alembic upgrade head` creates an empty
  Postgres schema; it does not move rows. Snapshots cannot be re-fetched (rule 4),
  so the swap needs a tested copy job with row-count and checksum verification.
- Integer primary keys become sequences that must be `setval`'d after a bulk copy,
  or the first insert collides.
- Zero tests have ever executed against Postgres.

`tests/test_migrations.py` (Slice 5) is the closest rehearsal available: it builds
the schema from empty and asserts it equals `Base.metadata.tables`, which is exactly
what the swap will do for the first time.

## ADR-0020 — Slice 5 is the decision layer; breadth waits behind Gate E
2026-08-27. Accepted. **Amends the Slice 5 ships list in docs/ROADMAP.md.** That
list is Reddit + `voice.*`, remaining `supply.*`/`openness.*`, all of `cost_risk.*`,
and the Postgres swap. It contradicts the roadmap's own risk register, #9:
*"Scope creep into more sources before calibration → Calibration (S6) precedes
breadth by construction. New sources wait."*

Every deferred group terminates in a NULL scorecard column: `voice.*` feeds Rule 7
(unimplemented) and `value`; `cost_risk.*` feeds `sustainability` and `value`; the
KP money metrics feed `value`. Building them would populate `features_daily` columns
nothing reads, none of which Gate E could backtest for lack of history.

Two of the four sources also do not exist to be collected (ADR-0021 for Reddit;
`niche_seeds.primary_sources` for the rest, where a live test found CourtListener
and EDGAR open, NTSB's CAROL API rejecting documented payloads, USCG 403, NIST no
API — 2 of 6 seeds).

Shipped instead: `scorecards.stage` (ADR-0023), both demand strata (ADR-0022), the
seed-coherence fixes (ADR-0024), `openness.winner_age_years`,
`supply.on_niche_share`'s companions, and an executable deferral register.

**`scorecards.opportunity` is a Slice 6 OUTPUT, not a Slice 5 input.** Its weight
vector is precisely what the backtest exists to choose; picking weights and then
calibrating them is circular. The roadmap has it in the wrong slice. `value`,
`sustainability`, `ci_low` and `ci_high` stay NULL behind checkable triggers.

This is the second consecutive slice amended by ADR after Slice 4/ADR-0018, and
that pattern is worth naming rather than repeating silently: the slice contents were
written before any data existed, and both amendments were forced by measurement.
The correction is to stop specifying slice contents more than one gate ahead — not
to stop amending.

## ADR-0021 — `voice.*` is unstarted, not pending
2026-08-27. Accepted. Every mention of Reddit in this repo is conditional — "if
approved", "may never arrive", "until credentials exist", "blocked on approval" —
and an exhaustive search found no ticket, no application id, no date, no submitter,
and no ADR. Contrast ADR-0016, which recorded "no application in flight" for Google
Ads **and started a dated clock**. Reddit got the phrasing and no clock, and has
been carried as a plan dependency across three slices on that basis.

It is therefore removed from every slice's ships list. `voice.*` is registered in
the deferral table with the trigger `NH_REDDIT_CLIENT_ID is set`, which is honest:
nothing happens until someone applies. Roadmap risk #4 already prescribes the
design — optional inputs with a confidence penalty, never required inputs — and
that shape is what a future port must fit.

Recorded so the distinction survives: "blocked on approval" describes a policy, not
a queue position.

## ADR-0022 — Two demand strata, arbitrated by Gate E
2026-08-27. Accepted. Slice 3 curated three topic-level Wikipedia articles per
niche. Slice 5 added twenty event-level articles per niche and found the two rank
the niches **almost exactly in reverse: Spearman rho = −0.70**. Under the topic
stratum `landmark-court-cases` is the portfolio's highest-demand niche; under the
event stratum it is the lowest, by 26x.

They are not two estimates of one quantity. Topic articles are reference pages and
carry standing, navigational, school-calendar interest; event articles are
occurrences and carry episodic attention. `demand.event_topic_ratio` therefore
becomes a metric in its own right — a news-drivenness proxy, and one of the
`cost_risk` measures that otherwise has no source.

**Neither is promoted.** `wiki_weekly_views` keeps its name and its topic articles
so the series stored since Slice 3 stays comparable; `wiki_weekly_views_event` runs
beside it. Choosing on the strength of a five-unit table would be deciding by
argument which of two things better proxies a quantity neither directly measures —
which is how the topic basket was chosen in the first place.

Carrying both is affordable because `wikipedia._resume_from` returns `None` for an
unseen term and falls back to `wiki_backfill_days`, so adding a `seed_terms` row
triggers a multi-year backfill on the next nightly, quota-free. 120 articles took
one run and 132,859 rows. Demand history is not the unbackfillable asset.

Selection is a **fixed-K uniform random sample from a class or category pool with
the RNG seed recorded**, not the largest articles. Ranking by pageviews selects for
fame, and that is not hypothetical: a hand-picked comparison in the planning notes
put aviation's event stratum at 4.9x its topic basket; the unbiased sample says
0.37x. Hand-picking inflated it roughly thirteenfold.

The pool generator differs per niche — three Wikidata classes, three category
fallbacks — and that heterogeneity is recorded per niche rather than smoothed over.
Gate E decides, against the criterion pre-registered in
`reports/demand_stratum_2026-08-27.md`.

## ADR-0023 — `stage` v1 is a demand-trajectory classifier with zero tuned constants
2026-08-27. Accepted. `scorecards.stage` is what Slice 6 replays for its go/no-go,
and it did not exist and had no definition anywhere.

`nh/scoring/lifecycle.py::classify` is **pure** — no `Session`, no clock, no
queries — and tests assert both the signature and that the module never imports
`nh.db` or `sqlalchemy`. That purity *is* the anti-leakage guarantee: a function
that cannot read anything cannot read a snapshot from after the decision date, so
Slice 6's audit is one call site rather than six feature modules.

It is named a **demand-trajectory** stage, not a lifecycle stage. A lifecycle
classifier would read supply momentum, and supply momentum does not exist:
`video_snapshots` holds one day against `demand_snapshots`' 1,096. Naming it
honestly narrows what Gate E can conclude, and the narrowing is the strongest
sequencing argument available — if demand trajectory alone predicts nothing, the
thesis is dead regardless of supply, and that is learnable from data already held.

Both cutoffs are **0**, because zero *is* the definition of growing and of a
positive gap — not a number chosen because the output looked right, which
docs/METRICS.md warns about three separate times. There is no confidence floor
either: that would be a fourth constant and would hide a weak call behind `unknown`
instead of reporting it, which `stage_confidence` does without discarding the stage.

The momentum axis is `demand.wiki_yoy`, not `wiki_momentum_28d`. Measured this
slice, **three of four niches peak in September**, so a late-August
month-over-month reading measures the school calendar — exactly what that metric's
own entry warned it might. The 28-day figure is carried into `detail` as evidence
and a test proves it cannot decide a stage.

Recorded as a known limitation: all four active niches have negative `wiki_yoy`
(−13.5% to −24.8%), so the momentum axis does not currently discriminate. That is a
fact about this portfolio, not a defect in the metric.

## ADR-0024 — A seed's label, keywords and articles must name the same subject
2026-08-27. Accepted. `gap` subtracts a supply rank from a demand rank, which is
only meaningful when both describe the same thing. For `court-cases` they did not.
Its label and demand articles were about landmark constitutional decisions; its
supply was contemporary true-crime trial streaming — measured, *Lindsay Clancy* in
59 of 520 on-niche titles, then Mario Fernandez Saldana, the Bridegan murder,
Karmelo Anthony. The gap it reported was a category error, and Slice 3's own note
predicted it ("may be measuring civics rather than the niche; revisit once
inspectable").

Split into `landmark-court-cases`, which keeps the demand articles and gets
keywords that ask for them, and `true-crime-trials`, which is what the supply was.
600 quota units a night.

**Seed coherence becomes a stated property with a validation rule.** The test is
*not* "does demand cover what supply names" — a niche with demand and no supply is
precisely the signal the product exists to find, so scoring baskets on supply
coverage would launder the signal into the selection. The test is that a seed's
**keywords and its articles refer to the same domain**; selection stays independent
of supply and only coherence is checked.

`niche_seeds.geo` now states the market a niche is *about*. This reverses the
earlier `test_geo_is_null_not_invented`, and the distinction matters: that test was
right that an invented geo must not become a *request parameter*, and
`seed_terms.geo` still carries that and is still `''`. `niche_seeds.geo` is a stated
intent that nothing sends anywhere, and `supply.geo_concentration` measures
divergence from it. Measured: **57–67% of every niche's supply sits outside the
market its seed claims**, while demand is read off English Wikipedia. The gap could
not see that; the metric reports it beside the gap rather than being folded into
it, because combining them would invent an exchange rate.

Successor disposition, the lexicon family change, and the post-Gate-E
re-grounding of this rule: **ADR-0028**.

## ADR-0025 — Wayback dropped; the leakage rule is `observed_date`, per table
2026-08-27. Accepted. Two corrections to instructions that would have sent the next
reader down a path returning no rows.

**The Wayback CDX collector and `historical_channel_weeks` are dropped.** The
roadmap listed both as Slice 6 deliverables: crawl `archive.org` for historical
subscriber counts of *our* channels. YouNiverse supplies weekly subscriber history
for its own 136,470 channels directly, which is what the backtest needs; Wayback
would cover the ~900 channels this pipeline has collected, which is a different and
much smaller question that nothing currently asks. Recorded here rather than
silently deleted, so a future slice that does ask it can find the reasoning.

**The leakage rule is `observed_date <= day`, applied per table — never `at < day`.**
ROADMAP Slice 6 said "compute features from rows whose `at` precedes it". Measured
on `demand_snapshots` for a 2024-06-01 decision date:

```
observed_date <= 2024-06-01  ->  31,971 rows
at            <  2024-06-01  ->        0 rows
```

Wikipedia was backfilled, so three years of `observed_date` sit behind four hours of
`at`. ADR-0015 already established that `observed_date` carries two meanings ("the
day we looked", "the day the value describes"); either reading is the day the *value*
belongs to, which is what a decision date must filter on. `at` is provenance — when
the row was written — and a backfill legitimately writes old readings today. Using it
as a time filter conflates "when we learned it" with "when it was true", and here it
would have produced an empty backtest that looked like a null result.

## ADR-0026 — The backtest reuses the production feature layer
2026-08-27. Accepted. The alternative was a separate replay computation path, which
would have been faster to write and would have invalidated the gate: backtesting
code that is not the product tells you nothing about the product. So the leaks got
fixed rather than worked around, and that audit is Slice 6's first deliverable.

An audit of every function in `nh/features/` and `nh/scoring/` found time-series
reads correctly bounded on `observed_date <= day` and **mutable entity reads not
bounded at all** — 9 of 16 registered metrics. Two were verified against the live
database: `on_niche_share` accepted `day` and never referenced it, and
`geo_concentration` used it only to write `detail["as_of"]`, so a 2019 row *looked*
replayed and was not, which is the most dangerous shape a leak can take.
`uploads_per_week` was worse in a different way: at 2019 it returned **0.0 with
confidence 0.871**, because its `known` denominator counted all 197 present-day
channels. A confident zero is data rule 9 in the metric most likely to be believed.

**No schema change was needed**, because relevance is a pure function of
`(title, description, lexicon_version)` and therefore time-invariant: membership as
of a past day is membership now, restricted to items that existed then. That is
ADR-0018's argument for not building a `cluster_member_days` table, and it holds.
So the fix is a `first_seen` / `published_at` bound on the join, not a history table.

`tests/test_features_leakage.py` covers all registered metrics in three differential
forms, and was confirmed to fail against the pre-fix code. `compute(metrics=...)` and
`build(supply_from=...)` are parameters so the backtest runs a reduced set without
forking the loop. `nh/backtest/replay.py` must never call `run_phases` — clustering
mutates and commits, and `retire_empty` would stamp `retired_on = 2019-01-01` onto
live clusters; a test asserts the module does not import `nh.jobs`.

Two consequences that are limitations rather than fixes. **Attribute leakage is the
residue and cannot be closed by a WHERE clause:** `videos.description`,
`videos.is_short`, `midroll_eligible` and `channels.country` are 2026 backfill facts,
so a 2019 replay of *our* corpus scores text we did not hold then. This does not
affect the YouNiverse backtest, whose descriptions come from its own 2019 crawl, and
that asymmetry goes in the report. And the **backtest lexicons are a separate family
of 36** (`nh/backtest/niches.py`), not additions to the live five: `lexicon.weights()`
weighs a term by `1/k` over the lexicons in its *family*, so adding niches to the live
set would silently rescore every production membership.

## ADR-0027 — YouNiverse weekly rows land on a week-ending `observed_date`
2026-08-27. Accepted. ADR-0015 defined two readings of `observed_date`: "the day we
looked" and "the day the value describes". A YouNiverse row describes **a week** —
this is the third reading, and it is recorded rather than left implicit because
`_window`'s `(lo, hi]` arithmetic downstream assumes daily readings.

The value lands on the week's final day and the reader names the field `week_ending`,
so no caller can mistake it for a daily observation. Two consequences follow and both
are deliberate: a 28-day window holds 4 points rather than 28, which `inputs_n` and
`confidence` report honestly; and a metric asking for "the value at `t`" gets the
week containing or preceding `t`, never a later one.

The same file forced a second decision. YouNiverse stores counts as **floats** —
`650.2222222222222` subscribers, `202494.5555555556` views — because it smooths across
its crawl cadence. `parse.as_int` refuses those, correctly: it exists to stop an API
returning "3.7" where an integer was promised. Reusing it here turned every numeric
column of an 18.9M-row file into NULL with no error anywhere, and the backtest would
have reported "no data" rather than "bug". `youniverse._count` parses and rounds at
the one place that knows the values are smoothed; `as_int` is unchanged.

## ADR-0028 — Seed coherence survives Gate E; the court-cases successors resolve asymmetrically
2026-08-28. Accepted. **Refines ADR-0024, which stands.** Nothing in Gate E's FAIL
(rho 0.091, p 0.4988, `reports/backtest_2026-08-28.md`) touches that ADR's diagnosis
or its rule that a seed's keywords and articles must name the same subject. What the
verdict changed is what coherence *protects*.

Coherence was justified as protecting `gap`. `gap` failed calibration, and the product
claim narrowed to *surfaces evidence for a human to judge*. The naive reading is that
coherence was scaffolding for a calibration that failed and can now be dropped. The
opposite is true: an uncalibrated composite misleads a model, but an **incoherent
evidence page misleads the judge** — and the numbers on one page must be about one
thing precisely because no calibration stands behind them any more. Coherence is
re-grounded, not retired, and it matters more than it did.

Coherence is a property and costs nothing per night. **The 600 units are the price of
two portfolio slots**, and slots are judged one at a time, against the narrowed
product's question: *would this niche's evidence page be worth a human's judgment?*
The two successors answer oppositely, so they resolve asymmetrically.

**`true-crime-trials` is completed.** It is where the old seed's supply actually was —
ADR-0024 measured *Lindsay Clancy* in 59 of 520 on-niche titles — and its channels are
already collected and RSS-polled. Its lexicon (41 terms, 53 with `_COMMON`) enters
`LEXICONS` in the same commit that removes `court-cases`, under one `LEXICON_VERSION`
bump to `2026-08-28.1`. One commit rather than two, for a reason worth stating: removal
is measured harmless — the four continuing lexicons are term-disjoint from the retired
one, so zero weights move — but *keeping* the corpse while adding the successor would
score the successor's most discriminative vocabulary at 0.5 under the `1/k` rule. A
dead lexicon would suppress exactly the terms its replacement needs. Both properties
are now tests, not claims, with the retired entry frozen as a literal in
`tests/test_lexicon_families.py` so neither needs git archaeology.

The civics vocabulary is deliberately not re-homed: importing `lawsuit`, `supreme
court`, `precedent`, `statute`, `constitutional`, `appeal`, `plaintiff`, `settlement`,
`damages`, `injunction`, `legal`, `law`, `litigation` or `landmark case` would rebuild
the civil-litigation false-positive shape ADR-0018 recorded. Nor is `fraud`,
`embezzlement`, `whistleblower` or `scandal`: each sits in `corporate-collapse` at
1.00, and adding any here would halve it for both — a white-collar trial belongs to
the niche that owns that vocabulary. A golden pin guards that, because the regression
would otherwise be silent. **The new lexicon's held-out precision is unmeasured** —
0.781 belongs to the old five-member family — so it joins the mandatory pre-Slice-7
human spot-check, and until then its dependent metrics carry that caveat.

**`landmark-court-cases` is deactivated**, with three sufficient reactivation triggers
in the deferral register. The RUNBOOK's "never cut a seed" protects unbackfillable
supply history; this niche has none by construction and its demand is re-fetchable
quota-free (ADR-0022, measured), which makes it the exception rather than a breach.

**Completing the split exposed a second freeze**, past the lexicon gap that
`lexicon_gaps()` now reports. `assign_channels` computed dominance over *every* seed's
lineage and discarded the winner afterwards if it was inactive — so a channel whose
majority history came from a deactivated seed was dropped from the loop and kept its
stale membership row indefinitely, however much lineage an active seed accumulated.
Measured 2026-08-28: 110 channels still sat in the retired `court-cases` cluster while
both successors collected. The lineage query now joins `NicheSeed` on `active`.
Filtering before the ranking rather than after also makes `confidence` a share among
the niches actually tracked, which is what it claims to be.

Identity still comes only from discovery lineage; **ADR-0013 is unchanged.** A
content-based one-off reassignment — scoring each channel's videos against the new
lexicon and moving it — was considered and rejected: it would overturn that ADR, and a
doctrinal change must not ride in on a cleanup. Migration is therefore gradual, as
successor queries re-surface each channel, and a channel no active seed claims gets no
membership invented for it.

Two things this ADR does not settle, carried forward. The new lexicon's precision,
until the spot-check. And whether the topic demand stratum means anything for *any*
niche — Gate E's failure analysis leaves that open, and `landmark-court-cases` is
parked on exactly that question rather than deleted over it.

## ADR-0029 — Resumed: sub-niche discovery is restored, the dashboard is not
2026-08-28. Accepted. **Supersedes the archival banner of the same day**, and
partially supersedes ADR-0018. This repo is the primary project again;
`../niche-hunter-2` is paused, its documents retained.

**What ADR-0018 actually said, and what has changed.** It did not judge sub-niche
discovery unworkable. It judged its *premise* void: the roadmap's own argument was
that "clustering earns its keep only when there are multiple sources to cluster
together — cluster YouTube titles alone and you have built a topic model, not a
demand–supply bridge", and Slice 3 had removed three of the four sources. Only
YouTube titles remained, so the argument said not to build.

Re-examined 2026-08-28, those three are in three different states, and conflating
them is what made the premise look permanently dead:

- **Keyword Planner is available today.** The original prototype
  (`legacy/niche_hunter_kp.py`) documents two access paths, and path B — the UI
  CSV export — needs no API, no developer token and no application. `parse_ui_csv()`
  is already written. ADR-0016 recorded this fallback and nobody used it. This alone
  restores "multiple sources": KP keywords + YouTube titles is two.
- **Reddit is obtainable but gated.** Approval under the Responsible Builder Policy;
  self-service registration closed late 2025. An application was never filed
  (ADR-0021). Cost is a form and a wait, not a blocker to starting.
- **Trends `related_queries`/`related_topics` remain blocked, and no credential
  opens them.** Measured: `TrendsQuotaExceededError`, and the documented referer
  workaround fails too. This one is a genuine technical wall; a proxy pool might
  clear it and might not. Sub-niche discovery must be designed to work *without* it.

So the premise is restored at two of four sources, three if Reddit approval lands.
That is enough to build against, and it is why this ADR exists rather than a
re-reading of ADR-0018.

**Why resume here rather than continue in the successor.** The N=5 live portfolio
is the root of every power failure this project hit, and sub-niche discovery is a
direct fix: seven niches yielding ten to thirty sub-niches each puts N in the
70–200 range. The successor pursues the same cure in the open field, from zero
code, against a corpus that does not exist yet. This repo has the corpus (21,238
videos, 1,244 channels, 47,482 view snapshots), working collectors, and 649 green
tests. Same cure, far shorter path.

**What resuming does NOT do — and this is the operative constraint.** Gate E's null
stands. It was a *powered* null: 29 of 36 niches, detectable rho 0.378, and the
size control clean at −0.019. Sub-niches do not repeal it. They raise N for future
tests and make the product more useful; they do not retroactively give `gap`
predictive validity, and no quantity of sub-niches converts a measured null into a
signal.

Therefore the roadmap resumes at **Slice 4 (sub-niche discovery)**, not at Slice 7.
`scorecards.opportunity` stays NULL, the ranked dashboard stays unbuilt, and the
prohibition in the Gate E section stands until a *new* pre-registered test passes
on the new grain. Anything ranked that ships before that is the failure the gate
exists to prevent, arriving through a side door.

**Inherited unchanged from the successor's founding work**, because it was paid for
and is unit-independent: the tested/never-attempted/descoped split in
`docs/SOURCES.md` (a source nobody applied for is not a finding), the rule that only
a demonstrated fetch moves a source into the proven table, and the six named design
errors. `../niche-hunter-2/docs/` is retained as the record; nothing there is
deleted on resumption.

## ADR-0030 — A collector may be manual: Keyword Planner arrives as a CSV a human downloads
2026-08-28. Accepted. **Refines ADR-0016** on where the data lands. Written 2026-08-28,
after nine call sites in `nh/` and `tests/` had already cited it — the citations were
correct, the entry was simply owed.

Keyword Planner's UI CSV export needs no API, no developer token and no application,
which is why ADR-0029 could restore sub-niche discovery at all. But it has no network
fetch a cron can run: its credential is *a human with a browser*. Rather than fake a
schedulable collector, `CollectorSpec` gains `manual: bool` and `manual_cmd: str`.
`nightly.plan()` reports such a source as `manual import — <cmd>` and never runs it;
`status.check()` excludes it from the ported-sources gate, because its absence from a
night says nothing about that night's health — conflating that with a schedulable
source silently collecting nothing would let a real regression hide behind the same
green. The import still goes through `Collector.run()` and still records a `job_runs`
row under its own job name, so provenance, raw-before-normalized and quota accounting
are unchanged. `Settings.configured("keyword_planner")` is `()` — no secret exists to
check.

**Where the rows land refines ADR-0016**, which anticipated "a `keyword_metrics` entity
table for bids and competition", upserted on the keyword. A bid is a *described-period
fact*, not a property of the keyword: every monthly re-export carries a new twelve-month
window, and an upsert would overwrite the previous period's price with the current one,
destroying the history the table exists to accumulate. So `keyword_metrics` is
`AppendOnly` and written with `insert_ignore` — re-ingesting an export is a no-op and
the first reading of a period survives. Using `Upsert` here would have reached the table
by Core `ON CONFLICT DO UPDATE` and bypassed the ORM append-only guard entirely; that
was tried and caught, and is why the model carries the reasoning in its docstring.
This collector writes no `demand_snapshots` at all.

## ADR-0031 — Bids keep the account's currency; no exchange rate may be invented
2026-08-28. Accepted. **Amends `CLAUDE.md`'s "Money in USD floats with 2 decimals."**
An earlier design pass claimed no such convention existed in the repo; it does, and
this ADR narrows it rather than pretending otherwise.

The export prices bids in the **Google Ads account's** currency, which on the account
we have is COP — measured, every row. Converting to USD would require an exchange rate
for the *period the numbers describe*, and no source in this project supplies one. A
constant would be a fabricated number silently multiplying every money metric, and the
result would be indistinguishable from a real one after the fact.

So bid columns are stored verbatim with `currency` beside them, and `median_bid_high`
and `vw_cpc` are account-currency figures. The convention now reads: money is USD with
2 decimals **except** where a source prices in its own currency, in which case the
currency is stored alongside and never converted.

That makes the renderer load-bearing. `nh/cli.py::_provenance` builds each metric's
detail line from a fixed list of named keys, and `currency` is not among them — so a
COP figure of 7,468.00 would print under a heading called **money** in a repo whose
convention says USD, a four-orders-of-magnitude misreading (the true figure is about
US$1.80) available at a glance, which a confidence of 0.23 does not prevent. Surfacing
`currency` in `_provenance` is therefore part of shipping these metrics, not a polish
item.

## ADR-0032 — Trends `related_*` is reachable; it buys vocabulary, not sub-niche level
2026-08-28. Accepted. **Supersedes the endpoint-availability bullets in ADR-0015 and
ADR-0029** — their decisions stand, only the measurement under them was wrong.

Re-probed live before writing this, because ADR-0029 rests a design constraint on the
claim. `related_queries` and `related_topics` **work**, via the library's own
documented header (`headers={"referer": "https://www.google.com/"}`). ADR-0015 recorded
that workaround as failing and ADR-0029 called it *"a genuine technical wall"* that
sub-niche discovery *"must be designed to work without"*. It is not a wall: it is a
per-endpoint rate limit. At a 3 s gap the third call failed; at 6–8 s every call
succeeded, while `interest_over_time` kept working from the same address throughout.

**This does not give sub-niches a demand level, and that is structural.** Trends
normalises 0–100 against *the term's own peak* (one term per request, no anchor), so
narrowing a term never lowers its ceiling — it concentrates traffic into the defining
events and lifts the peak against a baseline that rounds away. Measured across the
seven live seed terms, `max ÷ median` runs 2.1x for `court case` to ∞ for
`bridge collapse`, whose median is 0, whose p90 is 1 and which is 201/262 zeros — two
distinct values, no momentum expressible. Ordered by that ratio the list is ordered by
breadth, so resolution degrades in exactly the direction sub-niche work travels.

**Topic mids are not the fix the prototype claimed.** Measured both ways: the mid beat
its string for `murder trial` (2.0x vs 5.1x) and lost badly for `shipwreck` (14.3x vs
3.6x). One explanation — `/m/051_y` is *Murder*, far broader than the phrase, while
`/m/01nzyt` is *Shipwreck*, no broader than its string whose apparent advantage was
*Old School RuneScape* traffic flattening it. A mid helps when it **broadens** and
hurts when it disambiguates steady off-topic traffic away. Mids are a breadth knob on
the same axis, not an escape from it: buying resolution with one means measuring
something broader than the sub-niche in question.

So the enablement is **scoped to vocabulary**: `related_topics` (preferred over
`related_queries` — its `type` column drops the `Online game` homonyms that dominate
`shipwreck`'s rising list) may feed candidate sub-niche terms into clustering, priced
against absolute volume by the Keyword Planner export. Trends may **not** supply a
sub-niche level, and no ranking may rest on one. Note the ceiling this leaves: KP
quantises volume to four buckets (50/500/5000/50000), so order-of-magnitude is the
best level any current source gives a sub-niche.

Wiring `expand_seeds()` is not in this change — it needs the ≥6 s etiquette constant,
a cache, and `type` filtering, and it belongs to the slice that consumes it. What this
ADR settles is that the door is open and what is behind it. Full measurements and the
re-check triggers are in `docs/SOURCES.md`.

## ADR-0033 — The eleven domains are defined but cannot be activated: the relevance second axis asks "did something fail"
2026-08-28. Accepted. Lands the eleven-domain pivot as **definitions only** and records
the blocker that stops activation, found by measurement rather than by reasoning.

**What shipped.** Eleven lexicons in `LEXICONS`, eleven seeds in `SEEDS` with
`active=False`, and their terms: 89 Wikipedia articles, 11 Trends proxies, 66 Keyword
Planner keywords. Every Wikipedia title was verified against the live API before being
written — 88 of 88 candidates exist. Two were redirects and were replaced with their
canonical targets, because the pageviews API counts by requested title and a redirect
undercounts: `History_of_ideas` → `Intellectual history` (which also collided with an
existing entry, so `History_of_philosophy` and `Zeitgeist` were added instead), and
`Transformer_(deep_learning_architecture)` → `Transformer (deep learning)`.

**The lexicon cost that was feared is not real.** Adding eleven lexicons to the live
family moves **zero** live weights, measured over every term rather than the golden
handful. Two collisions existed and were designed out by word choice: `pipeline`
(engineering-failures vs geopolitics) became `energy pipeline`, and `evidence`
(true-crime-trials vs philosophy-of-science) became `empirical evidence`. A third,
`settlement`, collides only with the *retired* court-cases lexicon that
`test_lexicon_families` re-introduces, and became `urbanization`. The eleven separate as
cleanly as the live five — min 30 unique terms against the baseline's 38 — because their
discriminating vocabulary is technical (`falsifiability`, `gettier`, `panpsychism`) and
technical terms do not collide. `LEXICON_VERSION` is bumped to `2026-08-28.2` anyway,
because the family changed even though no weight did.

**The blocker.** `relevance.score()` is two axes, and the second one is
`lexicon.EVENT` — 82 terms of failure vocabulary (`accident`, `bankruptcy`, `collapse`,
`crash`, `deadly`, `explosion`, `fatal`). Its own docstring states the question it asks:
*"did something fail"*. That axis was added because a domain-only scorer topped out at
precision 0.62 against 298 hand labels, so it is load-bearing, not decorative.

None of the eleven domains are about things failing. Measured: a title packed with
philosophy-of-science terms scores **0.0**, because the domain axis matches
(`falsifiability` 1.0, `scientific method` 1.0) and the event axis matches nothing, and
the score is their geometric mean. Every video in all eleven niches would be marked
noise, and every one of the eleven clusters would then retire for holding no on-niche
video. Activating them today would collect nothing and look like a working pipeline
doing it.

**So the eleven stay `active=False`,** which costs no quota and leaves the five live
niches collecting. This is deliberately not fixed here: the second axis is part of the
scorer whose precision was measured against hand labels, and inventing a replacement
axis silently would put an unmeasured scorer under the same name. The fix wants its own
slice and its own labels — most likely a per-niche second axis, since "did something
fail" is right for disasters and wrong for topics, or a topic-domain axis of
explainer/analysis markers scored against fresh hand labels.

**A note on how this was found.** The dilution risk recorded in ROADMAP Slice 11 was
reasoned and wrong; this blocker was invisible until eleven real lexicons were scored
against real titles. Both facts argue the same thing: the cheap measurement goes first.

## ADR-0034 — The second relevance axis is per family: disasters ask "did something fail", topics ask "is this explaining something"
2026-08-28. Accepted. Resolves the question ADR-0033 left open and changes the definition
of `relevance`, which every `supply.*` number depends on.

ADR-0033 measured the blocker: `EVENT`, the global second axis, matches **1 of 120** real
discovered videos from the eleven pivot domains, and `score()` is a geometric mean, so
119 of 120 scored 0.0 however well their domain axis fitted. This decides the fix.

**The axis is selected per family from a frozen registry (`lexicon.AXES`), not from a
seed field and not by inference.** A seed field would put part of the scoring definition
in a database row applied by `nh seed`, free to drift out from under `LEXICON_VERSION`,
and the backtest niches have no seeds at all yet must be scorable. Inference from lexicon
content fails on this repo's own data: the live lexicons deliberately share 2–8 terms with
`EVENT`, so any overlap rule is a silent flip waiting on an innocent vocabulary edit.

**There is no default, and that is the load-bearing choice.** A niche whose family is
unset is skipped with a logged warning, never guessed. Defaulting to `event` would
reproduce ADR-0033's measured failure *invisibly* — every video marked noise, the cluster
retired as empty, a pipeline collecting nothing while looking like one that works. A test
asserts `set(AXES) == set(LEXICONS)`, so a seventeenth lexicon cannot land without
declaring its family.

**`EVENT` is untouched — same name, same 82 terms, same measurement.** `EXPOSITION` enters
under its own name with its own: held-out P 0.866 / R 0.736 / F1 0.794 against a
domain-alone baseline of 0.549 / 0.807 / 0.652, winning 168 of 200 splits, replicated
across two rules and two raters at kappa 0.845. **The two figures are not comparable** —
298 human labels at base rate 0.286 against 107 machine labels at 0.523 — and this ADR
records that as a decision rather than a footnote, because a reader who compares 0.866 to
0.781 will reach a false conclusion. `scripts/eval_topic_axis.py` reproduces it.

**No live number moves, and that is proved rather than sampled.** `score()` is a
deterministic pure function of `(title, description, weights, axis)`, so equal weights
plus an equal axis gives equal output for every input. The test asserts dict equality over
all 82 distinct `EVENT` terms for each of the five live niches — the same shape as
`test_removing_court_cases_moved_no_surviving_weight`, a property over the whole
vocabulary rather than a golden handful.

**`LEXICON_VERSION` bumps to `2026-08-28.3` anyway.** The version exists so a row's
decision stays attributable to the vocabulary that produced it, and the axis registry is
now part of that definition. Bumping at introduction rather than at activation means the
first exposition-scored row ever written carries a version that actually contains
`EXPOSITION`; deferring it would hang the bump on a hand-edited seed flag that touches no
versioned file. `Score.detail` now keys the second axis by its name, so every stored row
says which axis judged it.

**The eleven stay inactive**, behind a registered manual deferral. Activation requires a
human to label 60–100 rows sampled *from above* the threshold — the outstanding correction
from the 2026-08-28 interrater audit — against a precision bar pre-registered before
labelling starts. It also requires a quota decision that no validation result supplies:
11 pivots (6,600 units) plus the live five (3,000) is 9,600 against a 9,500 budget, so
activation retires or stages, and is never a flag flip.

**Deliberately not decided here:** whether 0.55 is the right threshold for this family. It
was chosen on disaster labels; the operating point is a product decision that belongs with
the human-validation pass, and the sample must be drawn above whatever threshold is
registered then.

## ADR-0035 — The four sources measure four different populations, and `gap` mixes them
2026-08-28. Accepted, then **substantially corrected the same day** after an adversarial
review. **Read this block before the body: the body's central empirical claim is
retracted.**

> **RETRACTED — "the mismatch varies per niche, so it does not cancel in a ranking".**
> Measured 2026-08-28, and it is false for the live pipeline. Recomputing on-niche
> supply restricted to US-domiciled channels moves the medians substantially
> (aviation-disasters 3,751 → 5,429; true-crime-trials 17,662 → 26,428) and leaves the
> **supply ranking identical across all five niches**. `scorecards.gap` is
> `demand_rank − supply_rank`, a difference of within-day percentile ranks — not the
> "ratio" the body and METRICS.md called it — so a perturbation that does not reorder
> cannot move it at all. This was already on record and I missed it: METRICS.md's
> `median_views` entry notes the Slice 4 redefinition moved supply values **0.42x–3.37x**
> and "supply RANKS did not change, and `gap` is unchanged for all five clusters".
> At N=5, ranks are extremely insensitive.
>
> **The evidence for the spread was also bad.** The 0.839 endpoint is `true-crime-trials`
> computed from **31 known-country channels of 34 members** — the smallest, newest
> cluster, measured on a date inside the ADR-0028 membership freeze. The four established
> niches span **0.324–0.426, a 1.3x spread, close to common-mode.** And
> `geo_concentration` counts *channels*, while supply weighs *videos*: measured, US share
> by on-niche video is materially higher than by channel in every niche. I quoted a
> display companion's `top_countries` as if it were a supply-composition measurement.
>
> **The Gate E sentence is withdrawn.** Gate E's demand was `wiki_weekly_views`
> (en.wikipedia) and its supply `views_per_new_video` over YouNiverse — both global
> English, the *most* geo-matched pairing the architecture has. The KP `geo=US` level the
> body leans on has never computed a number; no feature reads `keyword_metrics` yet. And
> `reports/backtest_2026-08-28.md` reports demand alone +0.049 and supply alone −0.073:
> a confound in how two populations are *mixed* cannot explain a null already present in
> each component before mixing.
>
> **What survives, and it is narrower:** the four sources genuinely do measure four
> different populations, and that becomes arithmetically live in **Slice 9**, which is
> the first time a `geo=US` demand level sits beside global-English supply. Until then
> this is a prospective warning, not a diagnosis. The decisions below stand on their own
> reasoning; only the empirical claim was wrong.

2026-08-28. Accepted. Records a confound that was implicit in the architecture from
Slice 3 and had never been written down, and decides what to do about it. Prompted by
the operator asking whether the sources need geo homogeneity — they do not have it.

**Measured, not asserted.** Each source is scoped to a different population:

| Source | Population it actually measures |
|---|---|
| `keyword_planner` | **United States** — `geo=US`, set per export |
| `trends` | **Worldwide** — `geo=""`, and ADR-0024 keeps `seed_terms.geo` empty for it |
| `wikipedia` | **`en.wikipedia`** — English readers globally; a language, not a country |
| `youtube_api` | **No region filter** — only `relevanceLanguage: "en"` |

`supply.geo_concentration` already measures the consequence, and it is large. Against a
stated `seed_geo` of `US`, on 2026-08-27:

```
aviation-disasters     0.423   US 63 · IN 50 · PK 13 · GB 5
maritime-disasters     0.432   US 51 · IN 22 · GB  9 · PK 6
corporate-collapse     0.330   IN 73 · US 61 · GB  6 · PK 5
engineering-failures   0.361   US 56 · IN 48 · PK 11 · GB 5
true-crime-trials      0.839   US 26 · IN  3 · BD  1 · GB 1
```

`corporate-collapse` has **more Indian member channels than American ones** while its
demand is read off US search volume and English Wikipedia.

**Why this is worse than a constant bias.** If every niche diverged equally, the error
would be common-mode and would largely cancel in a cross-niche *ranking*, which is what
`gap` is for. It does not: the US share runs **0.330 to 0.839, a 2.5x spread**, so the
mismatch between the demand population and the supply population is itself a
per-niche variable. It enters the ranking as signal that has nothing to do with
opportunity. This is a live candidate explanation for part of Gate E's null that the
2026-08-28 failure analysis did not isolate, and it is recorded here as such rather
than claimed as the cause.

**What already protects us, partly.** ADR-0015 put *level* on Wikipedia and *shape* on
Trends because momentum and seasonality are scale-invariant. A worldwide trend shape is
a valid shape whatever population produced it. The mixing bites on **level**, and level
is precisely what the Keyword Planner now supplies at `geo=US` while supply is counted
over an unfiltered global English corpus.

**Decisions.**

1. **The geo basis of every metric is recorded, not inferred.** Each source declares the
   population it measures, and any feature built on it carries that basis into its
   `detail`. A reader must not have to know that `en.wikipedia` is a language and
   `geo=US` is a country to avoid comparing them.
2. **No cross-basis arithmetic without the basis stated.** `gap` may continue to be
   computed — it is the project's central quantity — but it is a US-demand over
   global-English-supply ratio and must say so wherever it is displayed.
3. **Geo scaling is per-market instantiation, and is deferred.** The schema already
   supports it: `keyword_metrics` is unique over `(keyword, geo, lang, observed_date,
   source)` and `seed_terms` carries `geo`, both chosen so a second market sits beside
   the first. But a second market needs its own manual KP export, its own language's
   Wikipedia articles (`es.wikipedia` is a different project, not a geo filter), and its
   own YouTube keywords, since `relevanceLanguage` is the real constraint there. Only
   Trends is cheap per geo. **Do not open a second market until the first validates** —
   Gate E has already failed once, and a second market multiplies surface without
   testing the hypothesis.
4. **Homogenising by narrowing is rejected.** Restricting YouTube to US channels would
   discard half the observed supply in four of five niches, and that supply is real
   competition for the same English-language viewer. The divergence is a finding about
   these niches, not noise to filter out.

**Not decided here:** whether `gap` should be re-specified to compare like with like — a
US-demand-over-US-supply ratio, using `geo_concentration` to reweight. That is a change
to the central metric and belongs with a pre-registered test, not an ADR written after a
null.

## ADR-0036 — The product serves many operators, not one: no vetoes, more niches, and quota becomes the binding constraint
2026-08-28. Accepted. **Supersedes the single-operator premise** that the whole of
2026-08-28's decision work rested on, including `reports/niche_choice_procedure_2026-08-28.md`
and `reports/niche_veto_resolution_2026-08-28.md`.

The operator stated it plainly: *"I don't want vetos. in fact I want more niches because
it will be used for more people."* Everything built today assumed one person choosing 2–4
niches they would personally make videos about, and reasoned from *their* sustainable
weekly output. That premise is withdrawn.

**What this invalidates.** The veto questions measured one person's capacity — 25 titles in
30 minutes, does episode 20 get cheaper, do you make video #30. For a tool serving many
operators, those are the *user's* question at use time, not a filter applied at seeding
time. The portfolio rules (one Tier-A pick, one fit-first pick, no more than two per
audience cluster) were a hedging strategy for a single bet and do not apply to a catalogue.
Finalist selection is likewise moot: there are no finalists, there is coverage.

**What survives unchanged.** ADR-0029's prohibition — nothing ranked ships while Gate E's
null stands. The narrowed claim, "surfaces evidence for a human to judge", survives and
in fact fits better: many humans, each judging their own fit, is exactly what an evidence
surface is for. The source ceilings in `reports/source_audit_2026-08-28.md` are unaffected;
they are properties of the sources. And the production-economics ranking survives as
*displayable evidence per niche* rather than as an elimination — "this niche's catalogue
depreciates" is useful to a user choosing it, and it was never a fact about the operator.

**Quota is now the binding constraint, and it bites immediately.** Measured 2026-08-28
against the 9,500-unit daily search budget, at 3 keywords x 2 sort orders x 100 units:

```
5 live +11 niches =  9,600   OVER by 100
5 live +16 niches = 12,600   OVER by 3,100
5 live +21 niches = 15,600   OVER by 6,100
```

Dropping to 2 keywords per niche buys exactly one step — 5 live + 16 = 9,400, and 21 is
over again. So **keyword trimming does not scale and the constraint is structural.** Any
catalogue beyond ~16 niches needs a different discovery design, and the honest options are:
(a) **rotate** — discover each niche every Nth night, trading freshness for breadth, which
suits a catalogue nobody reads in real time; (b) **retire the five disaster niches from
discovery** while keeping their RSS polling, which costs zero quota and preserves the
snapshot history that is the compounding asset; (c) apply for a **YouTube quota increase**,
which requires a compliance audit; or (d) accept a hard cap on catalogue size. Not decided
here — it is the first question the next slice must answer, because every other
multi-niche plan is downstream of it.

**A second constraint that does not shrink:** each niche still needs a lexicon (ADR-0028 —
seeds without one can never gain members) and each family still needs a validated relevance
axis (ADR-0033/0034). Those are per-niche costs that no scheduling trick removes, and the
human-validation deferral now gates a catalogue rather than four finalists.

## ADR-0037 — Discovery sends the seed's stated geo as `regionCode`, because omitting it was never neutral
2026-08-29. Accepted. **Supersedes one sentence of ADR-0024** — "`niche_seeds.geo`
is a stated intent that nothing sends anywhere" — and corrects the geo-basis row
for `youtube_api` in ADR-0035's table and METRICS.md, which read "No region
filter". Prompted by the Slice 11 extraction audit asking whether `search.list`
should carry `regionCode` at all.

**The premise of the question was wrong, and Google's own reference says so.** The
response's `regionCode` property is documented as "the region code that was used
for the search query… The default value is US." A request without the parameter is
not unscoped — it is served **as a US query by a server-side default**, from
whatever IP the cron runs on (this one is in Colombia). So the true choice was
never "geo-scoped vs neutral"; it was "basis stated by us vs basis inferred by
Google's default and subject to drift". ADR-0035's rule 1 — the geo basis of every
metric is *recorded, not inferred* — decides that on its own: discovery now sends
`regionCode` from `niche_seeds.geo` when the seed states a market, and sends
nothing when it does not. The raw `search_hit` payload records what was sent
(`region`, None for the server default), so the basis is provenance, not
archaeology. We could not check the stored payloads for the served default because
`SEARCH_FIELDS` strips the response envelope — one more reason to stamp it
ourselves.

**Why per-seed, not a constant and not a run argument.** A constant re-buries
curation in code and contradicts ADR-0036 — a catalogue for many operators is
plausibly a catalogue across markets, and the market a niche is about is already a
per-seed field with exactly the right meaning. A run argument is the worst of the
three: the same seed discovered under different regions on different nights, with
nothing on the row saying so — a corpus forked invisibly per invocation. Per-seed
is also the only sourcing under which ADR-0035's deferred per-market
instantiation (rule 3) needs no further design here: a future `geo="GB"` seed
family discovers as a GB viewer from its first night.

**What this does NOT do.** It is not the supply-narrowing ADR-0035 rule 4
rejected. `regionCode` returns "results for videos that can be viewed in the
specified country" — nearly everything — ranked for that market; it filters
neither creator domicile nor audience location (both owner-only, per the source
audit's ceiling #2). Global English supply stays in the pool and
`supply.geo_concentration` keeps measuring the divergence rather than having it
hidden by the request. The honest basis statement for `youtube_api` becomes:
*search results as served for the seed's stated market (US today), English
relevance* — which is also what it was before, minus the pretence of neutrality.

**Continuity of the series.** All five live seeds state `geo="US"`, equal to the
documented server default, so the expected behavioural change tonight is zero.
That identity is **inferred from the documentation, not measured** — sending
explicit US could in principle differ from the default path — so it is recorded
here as the thing to watch: a step change in nightly `discoveries` volume dated to
this ADR is attributable, and the payload's `region` stamp marks the boundary
either way. The alternative — leaving the basis implicit so it could drift with
Google's default or the cron's IP without any mark in the data — is the recognised
shape of an undetectable series corruption, and that, not tidiness, is why this
ships now rather than with Slice 9.

## ADR-0038 — A seed term is geo-independent curation; the market lives on the observation
2026-08-29. Accepted. Decides the conflation `reports/geo_value_2026-08-28.md`
flagged and ROADMAP Slice 9 left open, choosing its option (b): **features join
seed terms to `keyword_metrics` on `(term, lang)`, and the market is a loader
argument resolved against `keyword_metrics.geo`** — never against the seed term.

The two fields answer different questions. A `seed_terms` row asserts *this niche
cares about this keyword* — curation, true in every market where the language
holds. `keyword_metrics.geo` records *which export this number came from* — a
property of the observation, set by `nh kp ingest --geo` and part of that table's
unique key precisely so a second market's numbers sit beside the first. The
Keyword Planner seed terms had been stamped `geo="US"` to make the ingest match
report agree with a `(keyword, geo, lang)` join, and the GB export then matched
**96/162**: sixty-six real observations attributable to niches by any honest
join, reported as orphans. Option (a) — duplicate seed rows per geo — cures the
report by multiplying curation 66×N and guarantees the next market repeats the
same miss until someone remembers to re-seed.

So `seed_terms.geo` returns to `''` for `keyword_planner`, which restores the
field to one meaning across all sources — for request-driving sources it is the
geo *sent* (still `''`, ADR-0024), and for KP nothing is sent at all. `''` on a
KP term means "curation, no market", not "worldwide observation"; the worldwide
reading belongs to `keyword_metrics.geo=''`, where an export run without a
location really would land. The ingest match report now matches on
`(keyword, lang)` and reports per-geo coverage — the earlier correction's
principle survives inverted: a report *stronger* than the real join is as false
a signal as one weaker, and 96/162 was exactly that. A second language market is
not this case: `es` keywords are different terms with `lang='es'`, and the
`(term, lang)` join carries them without any of this.

Measured after the re-seed, live database: 96 `keyword_planner` seed terms at
`geo=''`, and all **162/162** stored keyword rows (96 US + 66 GB) match a seed
term on `(keyword, lang)`. What this does NOT settle: which geo the Slice 9
feature loader defaults to. It must be an explicit argument with no default —
a default geo is a silently picked market, which `reports/geo_value_2026-08-28.md`
measured as a real reordering (the LOO-robust part: biohacking's GB rise, and the
18x GB/US value-ratio spread).

## ADR-0039 — Discovery retires for the five disaster niches; RSS keeps their history compounding
2026-08-29. Accepted. Implements the quota decision ADR-0036 left open, chosen by the
operator from four options.

ADR-0036 made a catalogue for many operators the goal and left quota as the binding
constraint: 3 keywords x 2 sort orders x 100 units means **15 niches** fit a 9,500-unit
budget, and the five disaster niches were consuming 3,000 of it.

**They are retired from discovery, not deleted.** The operator will not make videos about
aviation disasters or shipwrecks, so `search.list` spend on them buys nothing — but their
snapshot history is the compounding asset CLAUDE.md says never to break, and it cannot be
re-fetched at any price.

**This works because `youtube_rss` does not read seed state.** Verified rather than
assumed: `_targets()` selects "every known channel not currently circuit-broken" from the
`channels` table, with no join to `niche_seeds` and no `active` filter. So the 1,939
known channels keep being polled at **zero quota**, and `channel_snapshots` and
`video_snapshots` keep accruing. Also verified: cluster retirement stops `features_daily`
rows, not snapshots — `test_a_retired_cluster_keeps_its_history_but_accrues_no_new_rows`
is about the feature layer, and would otherwise have defeated the point of this decision.

**Interim state: zero active seeds, and that is expected.** The eleven pivot niches stay
inactive behind the human-validation deferral (ADR-0034), so nothing discovers tonight.
That is the intended trade — 3,000 units a night were being spent on niches with no user,
and RSS keeps the asset growing meanwhile.

**A coupling this exposed, and fixed.** Zero active seeds broke eleven clustering tests,
which built their fixtures from `SEEDS if active`. That coupling had already broken them
twice — at ADR-0028's court-cases retirement and at ADR-0033's pivot — so it is now
removed rather than patched a third time: `tests/test_clustering.py` owns its seed set,
forcing `active=True` on the two slugs its own fixtures and scoring titles name. Slugs
still come from the real set because `LEXICONS` is keyed on them and the relevance
scoring in those tests is real; only `active`, which was never any of production's
business, is local. An operational decision can no longer redden the clustering suite.

**Addendum, 2026-08-29: the code change alone did nothing for a day.** `nh/seeds.py`
carried `active: False` for all five, and the live database carried `active = 1` for all
five, because `apply_seeds` deliberately keeps `active` outside its upsert update set —
the behaviour `test_reseeding_does_not_reactivate_a_disabled_seed` exists to protect, so
that a niche someone stopped by hand survives the next `nh seed`. The same property that
stops a re-seed from restarting a niche stops it from retiring one. **Every nightly
between this ADR being accepted and this addendum still spent the 3,000 units it says
were saved.** The state change is a data change and had to be applied as one:

```sql
UPDATE niche_seeds SET active = 0 WHERE slug IN (
  'aviation-disasters','maritime-disasters','corporate-collapse',
  'engineering-failures','true-crime-trials');   -- 5 rows, applied 2026-08-29
```

Verified after: `nh seed`'s budget reports 0 units, `nh nightly --dry-run` shows
`youtube_api` still ready — correct, since enrichment and the 83-video backfill backlog
still run at 1 unit per 50 ids — and the 1,939 channels are untouched. `clusters` stay
active on purpose: retiring discovery must not also stop `features_daily`, which is
computed from the RSS snapshots that keep arriving.

The generalisation, which is why this is an addendum and not a fix: **`nh/seeds.py` is
the seed *catalogue*, not the seed *state*.** Anything in `SEEDS` that `apply_seeds` does
not include in its update set — `active` today — changes nothing on an existing row, and
an ADR that says "this niche is retired" is a claim about the database. `youtube_api`'s
no-seeds warning used to say "run `nh seed` first", which would have sent the next
operator down this exact dead end; it now names the UPDATE.

## ADR-0040 — The eleven domains activate for discovery; the exposition axis stays unshipped
2026-08-29. Accepted. Splits ADR-0034's deferral in two, and unblocks the half that was
blocking itself.

**The circularity.** ADR-0034 deferred the eleven pivot domains behind a human validation
of the exposition axis: 60-100 rows sampled *above* the 0.55 threshold, drawn from
pivot-domain videos. Measured today, that sample cannot be drawn. The corpus holds 120
pivot-domain videos, **19** of which clear 0.55 (48 in the `A_high` band), covering
**4 of 11** domains — against a requirement of 60-100.

That pool cannot grow by computation, and the reason is structural rather than
incidental: `phase.py::_video_rows` joins videos to a cluster through their **channel's**
membership, and channels are clustered from `search.list` discovery hits per seed. A
niche therefore gains members only through discovery on **its own seeds**. Re-clustering
the existing 6,976 videos against the eleven lexicons produces nothing — verified: all
eleven have lexicons of 32-34 terms, seed terms, and an `exposition` entry in `AXES`, and
still hold **zero** `cluster_members` rows, not even noise rows. Nothing is missing but
data, and nothing was collecting it.

So the gate was waiting on evidence that only the thing it gated could produce.

**The split.** Activation and shipping are different acts, and this repo already
separates them twice: ADR-0039 retired discovery while RSS kept polling, and cluster
retirement stops `features_daily` while snapshots keep accruing. Applied here:

- **Activated**: all eleven seeds, for discovery. They accrue channels, videos and
  snapshots like any other niche.
- **Still deferred, unchanged**: the exposition axis ships nothing. `scorecards.*` stay
  NULL behind Gate E (ADR-0029), the 0.55 threshold remains uncalibrated for exposition
  niches, and the human validation is still required before any of that moves. The
  deferral register keeps that entry; only its activation clause is discharged.

**Quota: the old arithmetic was stale in our favour.** ADR-0034 costed all eleven at
6,600 units against a 9,500 budget *plus* the disaster niches' 3,000 — 9,600, over
budget, which is why it proposed 2-4 finalists. ADR-0039 took the disasters to 0. All
eleven now cost **6,600 of 9,500 with 2,900 spare**, so the argument for picking
finalists before any evidence exists has expired. The operator chose all eleven, being
explicit (2026-08-29) that the catalogue is for many operators and should be wider, not
narrower.

**Applied as both a catalogue change and a state change**, per ADR-0039's addendum:
`nh/seeds.py` flips the eleven to `active: True`, *and*
`UPDATE niche_seeds SET active = 1 WHERE slug IN (...)` (11 rows) reaches the live row,
because `apply_seeds` keeps `active` outside its upsert update set and a code edit alone
would have changed nothing.

**What to expect, and what would falsify this.** The first nightly spends ~6,600 units
discovering across eleven domains that have never been searched. Two things are worth
watching before the axis is validated: whether `exposition` niches mark most of their
videos noise the way ADR-0033 measured a topic niche doing, and whether the above-0.55
pool actually reaches 60-100 rows across enough domains to draw the sample. If the pool
does not grow, the constraint was never quota and this decision is wrong.

**Verified immediately after applying, and one thing was better than predicted.**
Activation alone lit up **four** of the eleven — `trading`, `biohacking`,
`philosophy-of-science`, `geopolitics` — without a single new unit spent. Those are
exactly the four domains the 120-video sample covered: an earlier exploratory discovery
run had left search hits in `raw_records`, and `assign_channels` only reads them for
*active* seeds, so the channel memberships those hits imply had never been built. This
does not weaken the mechanism above — those four have members precisely because
discovery once ran on their seeds — but it does mean the corpus was slightly less empty
than "zero `cluster_members` rows" suggested. The remaining **seven** got cluster rows
and were retired as empty the same day, correctly: they have no channels yet and will
populate after the first nightly.

**The sharpest confirmation is the above-threshold pool**: it went from **0 to 514** on
activation alone, without a unit spent. The "19 of 120" figure that motivated this ADR
was measured on the static scored sample file of 2026-08-28; the live `cluster_members`
table held **zero** pivot rows at that moment, which is the stronger form of the same
point. Four domains now clear 0.55 at 196 / 176 / 83 / 59.

`features_daily` now carries 23 rows for each of nine clusters, and `scorecards` nine
rows whose `value`, `sustainability` and `opportunity` are **all NULL** — checked, not
assumed. The five disaster clusters retired on the same run, which is ADR-0039 working
as designed: their `features_daily` rows stop while `channel_snapshots` and
`video_snapshots` keep accruing from RSS.

## ADR-0041 — Pre-registration: the bar the exposition axis must clear
2026-08-29. Accepted. Written **before the sample can be drawn**, and the draw condition
is not yet met. Measured at the moment of writing: **514** above-threshold rows exist,
but across only **4 of 11** domains (`geopolitics` 196, `trading` 176, `biohacking` 83,
`philosophy-of-science` 59). Under the per-domain cap below that is a drawable **60**
against a required 80, so the binding constraint is **domain coverage, not volume** —
two more domains clearing 15 rows each makes the draw possible, and the other seven
began collecting only hours ago (ADR-0040). Nothing in this ADR may be revised after the
labels are written; a revision is a new ADR that says why, and re-labels.

**The test.** A human labels a sample of pivot-domain videos drawn from **above** the
0.55 threshold, scored by the committed `EXPOSITION` literal. Precision is the share of
labelled rows the human calls on-niche. The axis ships iff the **95% Wilson lower bound
on that precision is at least 0.70**.

**Why 0.70, and not parity with EVENT.** EVENT's held-out precision is 0.781 on 298
human labels, interval [0.732, 0.825]. Parity is not a decidable test at this sample
size, computed rather than assumed:

| bar (95% Wilson lower bound) | needs observed, n=80 | n=100 |
|---|---|---|
| ≥ 0.70 | 65/80 = 0.81 | 79/100 = 0.79 |
| ≥ 0.75 | 68/80 = 0.85 | 84/100 = 0.84 |
| ≥ 0.781 (parity) | 70/80 = 0.88 | 87/100 = 0.87 |

Requiring parity as a *lower* bound demands the human labels reproduce the machine
estimate (0.866) with no headroom, so any regression to the mean fails it. Requiring
parity as a *point* estimate is not a test at all: at n=80 the interval is ±0.17, so it
passes on noise — the exact defect the 2026-08-28 interrater audit killed the uniform-50
sample for, an interval "no gate can act on".

This matters because the deferral's objection is **evidence quality**, not precision
parity: `domain x exposition` rests on 107 machine labels from one model family, where
EVENT rests on 298 human ones, and kappa across two raters of the same family cannot
detect a bias they share. Independent human labels fix that at n=80-100. Whether the true
precision is 0.78 or 0.82 is not resolvable at any labelling budget a person will spend,
and pretending otherwise is how a bar becomes theatre.

**The sample, specified now so it cannot be chosen later.**
- **n**: target 100, minimum 80. Below 80 the draw is postponed, never shrunk.
- **Frame**: `cluster_members` rows with `item_type = 'video'`, `relevance >= 0.55`, in a
  cluster whose `AXES` family is `exposition`, as of the draw date.
- **Per-domain cap of 15**, and **at least 6 domains represented**. Without a cap one
  well-collected domain becomes the whole test; `trading` and `biohacking` have a head
  start (ADR-0040) and would otherwise dominate.
- **Drawn once**, uniformly at random within each domain, with the drawn ids and their
  scores written to `reports/` *before* labelling. A second draw is a new ADR.
- **The labeller sees title and description only.** Not the relevance score, not the
  band, and specifically **not `detail.matched`** — every membership row stores the terms
  that fired, and a labeller who sees them is scoring the lexicon's reasoning rather than
  the video, which is the machine-label problem wearing a human face.

**Both branches, decided now.**
- **Pass** (lower bound ≥ 0.70): the exposition axis is validated for scoring. The eleven
  keep their `relevance` values and become eligible for the feature layer on the same
  terms as the event niches. This still ships **no ranking** — `scorecards.value`,
  `sustainability` and `opportunity` stay NULL behind Gate E (ADR-0029), which this test
  does not touch.
- **Fail**: the axis scores nothing. The eleven **stay active and keep collecting** —
  snapshots are the compounding asset and a scorer's failure is not a reason to stop
  accruing history (the ADR-0039 principle). The lexicon or the axis is then the subject
  of the next slice, with this sample's failures as its evidence.

**What this test does NOT establish**, stated so a later reader does not over-read a
pass: it measures precision above the threshold only. It says nothing about **recall**
(what the axis misses is unsampled by construction), nothing about whether **0.55 is the
right cut** for exposition niches, and nothing about **Gate E**, whose null was measured
on a different grain entirely. A pass means the scorer is not inventing members. It does
not mean the catalogue ranks anything.

## ADR-0042 — The exposition criterion is re-specified to be labellable by a non-specialist; ADR-0041's bar is not touched
2026-08-30. Accepted. Supersedes **only** the labelling procedure of ADR-0041. Written
**before the replacement sample is drawn**, and before any human label exists anywhere.

**Trigger.** The operator — the intended labeller, and the only person the deferral ever
named — reports being unable to apply the criterion. That is a fact about the instrument,
not about the operator and not about the axis. An instrument only its author can operate
does not produce independent evidence, which is the entire thing ADR-0041 exists to buy.

### The goalpost objection, answered first because it is the strongest one

Earlier on 2026-08-30 a model was asked to label the drawn sample and did so, reaching
**78 of 99**, a 95% Wilson lower bound of **0.6974** against the 0.70 bar — a fail by
0.0026, one row. Revising an instrument after seeing a failing number is exactly how a
bar becomes theatre, so the defences are stated explicitly and are checkable:

- **That result is discarded and is not evidence of anything about the axis.** It is
  fable-5 grading a lexicon built from fable-5 labels — the circularity ADR-0041 was
  written to prevent. It was never written into the sample file; the write was refused
  and the file remains at 0 of 99, byte-identical to the draw.
- **The bar is unchanged.** 95% Wilson lower bound ≥ 0.70. Also unchanged: n (target 100,
  minimum 80), the frame, the per-domain cap of 15, the ≥6-domain rule, draw-once, and
  the labeller-sees-title-and-description-only rule. This ADR changes **how a row is
  judged**, and nothing about **what must be cleared**.
- **The trigger is independent of the result.** The operator's difficulty is not
  contingent on 78 versus 80, and would have been reported had the machine run passed.

There is one thing the machine run *is* legitimate evidence about, and it is evidence
about the **instrument**: the rater recorded roughly a dozen rows it could have called
either way, and the verdict moved on a single one of them. A criterion whose outcome sits
inside one rater's own noise is under-determined. That is an argument for specifying it
better, and it is the same argument as the operator's, arrived at from the other side.

### What changes

**1. Two passes, not one compound judgement.** ADR-0041 asked for SUBJECT and EXPOSITION
to be decided together, and a labeller who is unsure which one is failing cannot answer
either. The sample is now labelled twice, each pass one question over all rows:

- **Pass A — SUBJECT.** Is this video substantially *about* the named domain, rather than
  using its vocabulary?
- **Pass B — EXPOSITION.** Does it explain, analyse, teach, or argue a position, rather
  than report, vlog, promote, or entertain?

`label = 1` iff both passes are yes. This costs a second read of the sample and buys two
things: each pass is one consistent question, which is what calibration needs, and a
failure becomes **diagnosable** — subject-failures and exposition-failures say different
things about the lexicon, and ADR-0041 could not tell them apart.

**2. An explicit `unsure` per pass.** ADR-0041's "unjudgeable counts as 0" is kept for
the precision arithmetic, and its reasoning survives intact: the quantity measured is
"the scorer put this above the threshold — was it right?", and a row nobody can verify is
not evidence the scorer was right. What changes is that `unsure` is now **recorded per
pass** rather than folded silently into 0, so ADR-0041's >10% finding becomes measurable
on each axis separately.

**3. Worked archetypes, pre-registered as part of the instrument.** This is the actual
fix. Splitting a question a labeller cannot answer into two questions they cannot answer
teaches nothing; what teaches the standard is worked cases. These are fixed now, before
the draw, so they cannot be tuned to the sample, and they are deliberately generic — none
is taken from any drawn row.

*Pass A, SUBJECT — yes:* a lecture on Kant's categorical imperative for `history-of-ideas`;
exam-prep or coursework whose syllabus topic **is** the domain; a video in any language.
*Pass A — no:* a market bulletin tagged `#philosophy`; "paradigm shift" used as a
motivational metaphor for `philosophy-of-science`; a corporate-finance explainer under
`macro-economy`; a physics explainer under `philosophy-of-science` — explaining what
science *found* is not philosophy *of* science; a scientist's biography, which is history
of science.

*Pass B, EXPOSITION — yes:* explains a mechanism; teaches a method; argues a thesis;
analyses a case, including a market or a conflict.
*Pass B — no:* reports that a thing happened without saying why it matters; a personal
story with no general lesson; an advert or affiliate pitch, however fluently it uses the
vocabulary — the archetypal false positive on record is a law firm's citizenship advert
scoring as `landmark court cases`; a listicle or quote compilation; a **live
performance** — someone trading live, or delivering a channelled transmission, is doing
the thing rather than explaining it; a **roadmap or table of contents** for a series that
has not happened yet.

### The replacement draw

The 2026-08-29 sample is **retired unlabelled**, not re-used: it was drawn under the
superseded procedure, and it has been read and judged by a model whose judgements exist
in a session transcript. A fresh draw under a **new seed** removes any question of a row
carrying a machine opinion into a human pass. Same frame, same cap, same minimum. The
drawn ids and scores are written to `reports/` before labelling, as before.

**A contamination rule this ADR must add, because the risk is new:** the 2026-08-30
session transcript contains a model's row-by-row judgements of the retired sample. Anyone
labelling the replacement must not read it first. The rows overlap by construction — same
frame — and a remembered machine call is an anchor of exactly the kind the
title-and-description-only rule exists to prevent.

### Both branches, unchanged from ADR-0041

**Pass** (lower bound ≥ 0.70): the axis is validated for scoring; the eleven become
eligible for the feature layer. Still ships **no ranking** — `scorecards.value`,
`sustainability` and `opportunity` stay NULL behind Gate E (ADR-0029), untouched by this.
**Fail**: the axis scores nothing, the eleven stay active and keep collecting (ADR-0039's
principle), and the next slice takes the failures as evidence — now separable into
subject-failures and exposition-failures, which is this ADR's one substantive gain.

**What this still does not establish**, restated because a re-specification is exactly
when a reader over-reads: precision above the threshold only. Nothing about recall,
nothing about whether 0.55 is the right cut, nothing about Gate E.

## ADR-0043 — The eleven compute features before validation, and that is accepted rather than gated
2026-08-30. Accepted. Corrects a claim in **ADR-0041** and the wording of the exposition
deferral. Changes no code.

**What was found.** `nh/features/run.py:115` selects every `Cluster.active` cluster and
has **no axis-validation filter of any kind**. So when ADR-0040 activated the eleven for
*discovery*, they also entered `features_daily` and `scorecards` on the very next run.
Measured: nothing before 2026-08-29, then 253 feature rows and 11 scorecards per scored
day, `philosophy-of-science` among them reporting `gap 0.2`, `supply 0.0`, `openness
0.51`, `stage cooling`.

`active` is **one flag doing two jobs** — gating discovery and gating scoring — and
ADR-0040 meant to turn on only the first. That is the same shape as the ADR-0039
addendum, which is this repo's standing example of a state change reaching further than
intended, and it was invisible for the same reason: nothing failed.

**Two documents were wrong about this, and both are corrected here.** The deferral
register's entry was titled "human validation before it scores anything", and its
`consumer` field said "nothing they score ships until this clears". ADR-0041's pass
branch said a pass makes the eleven "eligible for the feature layer on the same terms as
the event niches", which only means something if they are not eligible now. They were
eligible the whole time. CLAUDE.md already warns that `nh deferrals` is expected to be
true and that three entries were once caught lying; this is a fourth, found by asking
whether the pipeline actually honours the register rather than assuming it.

**The decision: accept, do not gate.** The alternative — a validation-state column and a
filter in the feature phase — was considered and rejected as the more expensive answer to
a cheaper problem:

- **Features are recomputable by design.** The snapshots underneath them are the
  compounding asset and are untouched; a failed axis costs a recompute, not history. This
  is the same reasoning that lets `nh prune` bound `raw_records` but never snapshots.
- **What the deferral protects is TRUST, not computation.** `scorecards.value`,
  `sustainability` and `opportunity` are NULL behind Gate E (ADR-0029), no ranking ships,
  no evidence page cites these numbers, and none of that depends on whether the rows
  exist.
- **Gating would need state that does not exist.** There is no column recording that an
  axis has been validated, and inventing one to enforce a deferral that costs nothing to
  leave open is the kind of machinery ADR-0023 argues against.

**The cost of accepting, stated so it is not discovered later.** The stored rows carry
**no marker** that they predate validation. `detail.definition` records the metric
definition, not the scorer's status. Anyone reading a `features_daily` or `scorecards`
series that spans this period must check the day against this ADR themselves. That is a
real weakness of accepting rather than gating, and it is the reason to prefer gating if
this ever recurs for a scorer whose output *does* ship.

**Not licensed by this.** The eleven's numbers are not validated and are not more
trustworthy for being computed. On both machine labelling runs `philosophy-of-science`
scored 4 of 9 above threshold, failing almost entirely on SUBJECT
(`reports/exposition_result_2026-08-30.md`), and its supply figures rest on a corpus
where 60.9% of member channels have never produced an on-niche video
(`reports/supply_audit_2026-08-30.md`). Computing a number is not evidence for it.

## ADR-0044 — `philosophy-of-science` is retired as an editorial choice, and the sample re-drawn over ten domains
2026-08-31. Accepted. Retires one of the eleven pivot niches and narrows the exposition
validation frame with it. Written **before any label exists** on the replacement sample.

**The decision is editorial.** The operator will not make philosophy-of-science videos,
which is the same reason ADR-0028 retired `landmark-court-cases` and ADR-0039 retired the
five disaster niches: `search.list` spend on a niche nobody will publish into buys
nothing. Applied as code **and** data, because `apply_seeds` keeps `active` outside its
upsert update set and a code edit alone never reaches an existing row — the ADR-0039
addendum, which cost five nightlies of quota the last time it was forgotten:

```sql
UPDATE niche_seeds SET active = 0 WHERE slug = 'philosophy-of-science';  -- 1 row, 2026-08-31
```

Verified after: seed `active` 1 → 0, ten active seeds remain. `Cluster.active` reconciles
from the seed on the next clustering run (`nh/clustering/phase.py:215`), so features and
scorecards stop for it there rather than needing a second hand-edit.

### The side effect, stated because it is the thing a later reader will suspect

`philosophy-of-science` was **the worst-scoring of the eleven** on both machine labelling
runs — 4 of 9 above threshold, failing almost entirely on SUBJECT — and dropping it
**flips the machine precision result from FAIL to PASS**:

| sample | precision | 95% lower bound | verdict |
|---|---|---|---|
| all eleven domains | 78/99 | 0.6974 | FAIL |
| without philosophy-of-science | 74/90 | 0.7306 | PASS |

That is recorded here rather than discovered later, and three things follow from it.

**It is not why the niche is retired.** The editorial reason stands on its own and would
hold if the domain had scored best of the eleven.

**The flip is not evidence the axis works.** Dropping the *second*-worst domain
(`logic-linguistics-gnoseology`) also flips it to PASS, at 72/90 and 0.7059. A verdict
that moves when either weak domain is removed says the bar sits on a knife edge, not that
one niche was uniquely broken. Both numbers come from machine labels and are not evidence
about the axis at all (ADR-0042, `reports/exposition_result_2026-08-30.md`).

**No pass may be claimed from the old sample.** The 2026-08-30 sample is spent and its
result is discarded; a pass has to come from a human labelling the fresh draw. Removing a
domain and re-reading an old number would be exactly the post-hoc selection this section
exists to flag.

### The frame narrows, and the draw script now enforces it

`AXES` is keyed on `LEXICONS`, not on seeds, so a retired niche keeps its axis entry and
the family alone would have kept sampling it. `scripts/draw_exposition_sample.py` now
intersects the exposition family with **active** seeds: a validation sample for a
shipping decision has no business sampling a niche that is not shipping.

Replacement draw, seed `20260831`: **100 rows, 10 per domain across 10 domains**, capped
draw 150, relevance span 0.553–0.798. n is now the pre-registered *target* of 100 rather
than 99, so the bar is ADR-0041's own tabulated **79/100** for a 0.70 lower bound —
unchanged in substance. Overlap with the sample a model labelled is 4 rows of 100.

**Its lexicon stays in `LEXICONS`.** ADR-0028 removed `landmark-court-cases`' lexicon when
retiring it, and that is deliberately *not* done here: `weights()` is discriminative
across the family, so removing one lexicon re-weights every remaining one and would
re-score every live niche and invalidate the drawn frame. The measured case is in that
function's docstring — `crash` fell from 1.00 to 0.032 when the family grew. A retired
seed with a live lexicon scores nothing, because scoring runs per active cluster.

**Reactivation**, if the editorial judgement changes: `UPDATE niche_seeds SET active = 1
WHERE slug = 'philosophy-of-science'`. Its snapshots keep accruing meanwhile — `youtube_rss`
polls every known channel regardless of seed state (ADR-0039), so the history is not lost,
only the discovery spend.

## ADR-0045 — The exposition human-label requirement fires when a score is CITED, not while it merely exists
2026-08-31. Accepted. Narrows the trigger of the exposition deferral. **Weakens an
evidence standard, deliberately**, and says so rather than dressing it as a clarification.
The bar itself — two passes, 0.70 Wilson lower bound, 79/100 — is untouched.

**The problem is that the deferral is a wall.** `nh/jobs/deferrals.py`'s own docstring
sets the standard: *"a deferral without a trigger is a wall; a deferral with one is a work
queue."* This entry's trigger was "a human labels 60-100 rows", which is not a condition
the world can satisfy — it is a task waiting on one person, and it has now failed to
happen for three days across three drawn samples, two of which a model consumed instead.
A requirement nothing can discharge is not a standard; it is a stop.

**And it currently gates nothing.** ADR-0043 established that `features/run.py` filters on
`Cluster.active` alone, so the ten domains compute `features_daily` and `scorecards`
whether or not the axis validates; `value`, `sustainability` and `opportunity` are NULL
behind Gate E (ADR-0029) regardless; and no validation state exists anywhere for code to
read. So a PASS today would change no number, unblock no path, and ship no page. The
requirement is stricter than any consequence it protects, because the consequence does not
exist yet.

**The change.** Validation is required **before any artifact cites an exposition-domain
score to a person** — an evidence page, a ranking, a recommendation, an alert, an API
response a human reads. Until then the scores are computed, marked unvalidated, and used
for nothing outward-facing. The trigger becomes `kind="query"` and self-evaluates: it
fires when a scorecard row for an active exposition cluster carries a non-NULL `value`,
`sustainability` or `opportunity` — the first moment a number leaves the feature layer
toward a reader. A matching branch was added to `_query_fires`; a `query` trigger with no
branch returns `None` forever and is worse than `manual`, because it pretends to be
checkable, which that module already warns about in another entry.

**What is given up, stated plainly.** The eleven-domain scores will exist, unvalidated,
for as long as nothing cites them — possibly indefinitely. Anyone reading
`features_daily` or `scorecards` for an exposition cluster is reading a number whose
scorer has never been checked against an independent rater, and ADR-0043 already records
that those rows carry no marker saying so. This ADR makes that condition durable rather
than transitional, which is a real loss and the reason it is an ADR rather than an edit.

**What is not given up.** The standard is unchanged when it fires: the same two-pass
criterion (ADR-0042), the same 0.70 lower bound, the same drawn-once discipline. The
sample is already drawn and waiting (`reports/exposition_labelling_2026-08-31.jsonl`, seed
20260831, 100 rows across ten domains after ADR-0044). Nothing about this makes a pass
easier to claim — it makes the *requirement* fire later, not the *bar* lower.

**Rejected alternatives.** A second model family would partly answer the objection, which
is specifically that two raters of *one* family cannot detect a shared bias — but every
model reachable from this project is Anthropic, so it is the same family in the sense that
matters. Outcome-based validation instead of labels needs a forward outcome per video;
`video_snapshots` is one day deep and Gate E already returned a powered null at niche
grain. Crowdsourced labels remain the cheap honest answer if this ever fires — 100 rows
across three raters is roughly $20-40 and yields inter-rater agreement as well, which is
better evidence than one operator.

## ADR-0046 — A Latin-script non-English title is unscorable, not decided off-niche
2026-08-31. Accepted. Fixes a scoring defect that has been live since the second gate in
`score()` was written. Bumps `LEXICON_VERSION` to `2026-08-31.4`. No migration.

**The defect.** `_latin_share` marks a title unscorable below 50% Latin **letters**, and
its comment states the intent exactly: *"An English lexicon cannot read this. Scoring it 0
would call it off-niche."* But it catches scripts, not languages. A Spanish, French,
German, Portuguese or Italian title is ~100% Latin letters, so it passed the gate, matched
nothing in an English lexicon, scored exactly 0.0, and `is_noise = value <= RELEVANCE_LOW`
filed it as **decided** off-niche — the precise outcome the comment forbids.

Measured on **enriched** rows with an **exact-variant** `audio_lang` — the filter has
to be stated, because a looser prefix match over all rows gives 1,075 euro rows at 2.5%
on-niche, and an unstated filter is why two true numbers looked like a contradiction:

| group | n | unscorable | decided noise | on-niche |
|---|---|---|---|---|
| es/fr/pt/de/it and variants | 854 | **0** | 776 | 9 (**1.1%**) |
| en (`en%`, same filter) | 26,775 | 103 | 15,746 | 22.1% |
| ko (non-Latin) | 208 | 203 | — | 0% |
| hi (usually romanised) | 6,583 | 709 | — | 21.8% |

The pattern is diagnostic: non-Latin scripts are caught correctly; romanised Hindi, Urdu
and Tamil score like English because their titles carry English domain vocabulary; the
damage is confined to Latin-script European languages, where roughly 163 videos are
excluded from every supply numerator and 776 are counted as decisions in
`relevance_coverage` — inflating confidence in exactly the clusters
`reports/supply_audit_2026-08-30.md` found inverted.

**The fix.** Frozen per-language function-word sets (es, fr, de, pt, it) plus an English
set, matched over diacritic-**folded** tokens. A title is withdrawn when one language
contributes >= 2 distinct function words **and** foreign words outnumber English ones; a
description is consulted only when the title is not already clearly English. The reason
string names no language, because the sets incidentally catch Romanian, Albanian and
Swahili through shared words — the right outcome, since the lexicon cannot read those
either, but a named-language claim would sometimes be false.

**Why not `audio_lang`, which is the obvious answer.** Three reasons, and the first is
decisive:

1. **It breaks a load-bearing invariant.** `nh/features/inputs.py:160` states that
   relevance is *"a pure function of (title, description, lexicon_version), so a video's
   score never changes"* — which is why as-of-day membership needs no history table
   (ADR-0018). `audio_lang` is NULL until enrichment and can arrive later, so a score
   keyed on it would flip after the fact and break replay.
2. **It is blind where it matters.** 565 of the 1,347 rows the gate catches (42%) have a
   NULL `audio_lang` — unenriched or unreported, which is the normal state of a freshly
   discovered video.
3. **It is uploader-declared and measurably wrong in both directions.** All 34
   `en`-labelled rows the gate fires on are visibly foreign — German lecture series,
   Spanish geopolitics, Portuguese, Tagalog — so `audio_lang` would have *protected* them.
   Meanwhile roughly half the residual is English-titled videos on foreign-`audio_lang`
   channels, which the text gate correctly leaves scored and a language-keyed gate would
   have wrongly withdrawn.

Also rejected: a **language-detection dependency**, because a versioned statistical model
inside a scorer whose lexicon is deliberately *"data, not code… the thing a reviewer should
argue with"* is unreviewable and drifts between releases, breaking frozen replay. And
**"zero matches implies unscorable"**, which looks elegant and is destructive:
`RELEVANCE_LOW`'s own comment records that exactly-zero separates hard — 6.4% on-niche
against a 28.6% base rate — so it is the decided-noise mechanism for ~15,700 English rows,
and reclassifying it to rescue 854 would demolish `relevance_coverage` corpus-wide.

**The thresholds are one step off a cliff, on the safe side.** Swept on the live corpus:

| title thr | catch | English fires | Indic fires | **on-niche caught** |
|---|---|---|---|---|
| 1 | 1,873 | 137 | 32 | **30** |
| **2 (chosen)** | **1,347** | **34** | **0** | **0** |
| 3 | 1,199 | 31 | 0 | 0 |

**Re-measured on the final sets, and it undercuts the table above** — recorded because a
constant justified by a stale sweep is the thing a future reader trusts:

| title thr | catch | English fires | Indic fires | on-niche caught |
|---|---|---|---|---|
| 1 | 1,233 | 47 | 3 | 1 |
| **2 (chosen)** | **979** | **28** | **0** | **0** |
| 3 | 875 | 25 | 0 | 0 |

Dropping the short tokens flattened the cliff: threshold 1 now costs one on-niche row and
three Indic rows, not thirty and thirty-two. **The word list is doing the safety work, not
the threshold.** Two remains correct — strictly safer than one, and it buys 104 rows over
three — but the margin is thin and should be re-measured rather than trusted if the sets
change again.

At 1 the gate starts eating niches. At 3 it pays 148 rows of catch for ~3 fewer English
fires that were mislabeled-foreign anyway. The description threshold (6) sits mid-plateau;
that axis moves nothing sharply.

**The canaries were a training-set number, and review caught it.** The word sets were
edited until three corpus canaries read zero — no on-niche row caught, no romanised-Indic
row, no row of the drawn sample. All three reproduced exactly, independently, twice. They
were also nearly meaningless as a safety margin: with those sets, **9 of 11 constructed
English titles fired** — `Las Vegas`, `al-Assad`, `Su-24`, `die cast`, `Mac OS da Vinci`,
`Per Kastrup` — because digits and punctuation are separators, so proper nouns shed
function words. A number obtained by editing until it reads zero cannot then be quoted as
evidence that it is zero.

**The fix took two rounds, and the second round is the instructive one.** Twenty-two
tokens that are English words, proper-noun fragments or romanised-Hindi particles went
first — `las al su es son sin come per die hat est il sa os da na ed com comment el los
et` — taking that attack set from 9/11 to 0/11. Review then drew a **second, independent**
set of English titles and **10 of 11 fired**: `Du Pont, La Porte` (a real 2014
engineering-failures case, four dead), `Le Mans, La Sarthe`, `Del Rio, La Joya`, `Der
Spiegel im focus`, `Di Maio and La Russa`. The first set had been used to *choose* the 22
removals, so it was in-sample and structurally could not have caught them.

Every remaining two-character token was therefore dropped as well. Total cost **368 rows
of catch (1,347 → 979, 27%)**; benefit, both attack sets go to zero and all five target
languages are still caught on the corpus (es 267, pt 121, fr 112, de 52, it 18). An
earlier draft rejected the length rule for "losing a language": that was measured on one
hand-written fixture rather than the corpus, and was wrong. Both attack sets are pinned as
tests, because a margin established by editing until a corpus count reads zero is a
training-set number.

**The surface is narrowed, not empty, and this ADR must not be read as claiming
otherwise.** A third independent draw built only from the surviving three-character
tokens fired on **7 of 16** — `Von Neumann and MIT` (`mit`/`von`), `Che Guevara: Con Man
or Icon?` (`che`/`con`), `Hay Festival: Con Artists panel`. Removals stopped there
deliberately: every three-letter foreign function word is somebody's acronym or surname,
so the class cannot be closed by enumeration, and a fourth round would take `ser`, `ist`,
`tem`, `sao` and still not finish.

The reason it is safe to stop is a margin, not a canary. On-niche rows sitting **one token
away from withdrawal fell from 75 to 4**, and those needing one further same-language word
**from 30 to 1** — the survivor being `MIT Just Revealed the AI Bubble's Fatal Flaw`, one
German token from being withdrawn. Two of the third-draw titles are pinned as a test that
asserts they *do* fire, so the residual cannot change silently in either direction.

One entry in the removed list, `son`, was **already claimed as removed by a comment while
still present in the set** — colliding with 10 on-niche English titles. A comment that
miscounts its own exceptions has lost its force, which is the same lesson `python.md`
records about its broad-`except` count.

**Verified independently of the planner**, reproducing its pre-fix numbers exactly (1,347
fires, 1,286 formerly decided-noise, 565 NULL-lang) and re-run after the token removal:
**979 fires (923 formerly decided-noise), 0 of 11,495 on-niche rows caught, 0 of 9,243 romanised Indic, 0 of the 100
rows in the drawn validation sample.** That last one matters: the sample stays a valid
draw against the post-change scorer, so ADR-0044's draw survives.

**No migration.** `assign_videos` re-scores every member video each run and upserts on
`(item_type, item_id)`, so one nightly converges the corpus; `cluster_members` is an entity
table (`Base, Provenance` — **not** `AppendOnly`), so no data rule is engaged. Snapshots
untouched.

Two consequences of "converges per database", found in review and recorded because they
are the kind of thing discovered a month later:

- **`data/backtest.db` does not converge.** It keeps relevance computed under
  `2026-08-28.3`, so `reports/backtest_2026-08-28.md` is no longer reproducible from HEAD
  without a re-scan. That is acceptable — the backtest is a frozen artifact and Gate E's
  null does not depend on this gate — but the report is now tied to a lexicon version the
  code no longer produces, and anyone re-running it must re-scan first.
- **`nh/backtest/scan.py:192` folds `None` into the zero branch.** `if not value: continue`
  survives the new `None` without crashing, but treats a withdrawal as a zero, so
  `counts.scorable` under-counts. **Checked after this ADR was first written: the field is
  write-only** — assigned at `scan.py:196`, declared at `:46`, and read nowhere in the
  codebase. So the defect is real and currently inert, and the follow-up is to decide
  whether `ChannelCounts.scorable` should be wired up or deleted, not to hurry a fix for
  a number nobody consumes. Recorded rather than fixed here because it is a different
  module with its own tests and burying it in a scoring ADR would hide it.

**The accepted limit, as a number rather than a hedge.** Roughly 250 known Euro-language
rows remain decided-noise (222 by a prefix-match count, 251 by the exact-variant one — the
same filter ambiguity as above, stated rather than papered over), and the token removal
adds ~200 more. That is a ceiling, not the defect: inspection shows roughly half are
English-titled videos on foreign-`audio_lang` channels, correctly scored. The genuinely
foreign residual — short titles carrying no function words, "Hipotesis y capacidades de la
conciencia" — is on the order of 120–150 rows and is the accepted limit of a function-word
gate. It concentrates in metaphysical-battles (70) and esoterism-spirituality (41).

**Expected side effect, so `data-qa` does not misread it.** Corpus-wide decided share falls
~2 points, and `relevance_coverage` — hence `uploads_per_week` confidence — dips most for
esoterism-spirituality (−306 decided rows), metaphysical-battles (−241) and geopolitics
(−151). That is confidence becoming honest, per the audit's inversion finding, not a
regression.
