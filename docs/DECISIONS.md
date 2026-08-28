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
