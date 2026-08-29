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
