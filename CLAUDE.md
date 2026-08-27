# Niche Hunter

Nightly pipeline + dashboard that scores YouTube niche clusters on demand–supply
gap, openness, RPM, sustainability and risk using free sources. The compounding
asset is snapshot history; never break the collectors.

## Read first
- docs/ROADMAP.md — the slices, the gates, and what ships next
- docs/RUNBOOK.md — cron, alerting, the drills, day-1 procedure
- docs/ARCHITECTURE.md — layers: collectors → raw → normalized → clusters → features → scorecard → views
- docs/SOURCES.md — every source's auth, quota, fields, caveats (update when you learn something)
- docs/METRICS.md — every metric's formula, inputs, join key, confidence (define BEFORE implementing)
- docs/INSIGHT_RULES.md — cross-source rules that emit alerts
- docs/DECISIONS.md — ADRs; don't relitigate, add a new ADR to change one
- legacy/README.md — the five prototypes and how to port one

## Commands
- `uv run pytest -q` — must be green; tests never touch the network
- `uv run nh nightly --dry-run` — list collectors that would run, and why not
- `uv run nh nightly --since 2026-01-01 --only youtube_api,youtube_rss` — partial run
- `uv run nh sources` — ported / configured / quota per source
- `uv run nh seed` — write the niche seeds; prints the nightly quota cost
- `uv run nh status [--check]` — what got collected; --check gates the cron ping
- `uv run nh prune [--dry-run]` — storage report + bounded retention on raw payloads
- `uv run nh doctor` — database reachable, schema present
- `uv run alembic upgrade head` / `alembic revision --autogenerate -m "..."`
- `docker compose up -d db` — only when NH_DATABASE_URL points at Postgres

## Architecture in one paragraph
Collectors subclass `nh/collectors/base.py::Collector` and implement two methods:
`fetch()` owns all network and yields `Raw` payloads verbatim; `normalize()` is
pure and returns a `Batch` of upserts and snapshots. Everything else —
provenance, raw-before-normalized, idempotent upserts, append-only snapshots,
quota, `job_runs`, surviving an outage — lives once in `Collector.run()`. Raw
payloads land in `raw_records` (JSONB/JSON), normalized rows in typed tables,
time series in append-only `*_snapshots`. `nh/clustering` assigns every item a
`cluster_id`. `nh/features/*` compute one row per cluster per day into
`features_daily`. `nh/scoring` builds `scorecards` and `alerts`. `nh/api` is a
thin FastAPI read layer; `nh/web` is Streamlit v1.

## Non-negotiables (details in .claude/rules/data.md)
- Every write carries `at` (UTC), `source`, `run_id`. Snapshots are append-only —
  `AppendOnlyViolation` is raised at flush time if you try to update one.
- Idempotent upserts: re-running a day is safe. Never `INSERT OR REPLACE`.
- Absent data is NULL, never 0 — use `nh.collectors.parse.*`. Every feature row
  has `confidence` and `inputs_n`.
- Respect per-source quotas in .claude/rules/sources.md. Log quota per run.
- No live API calls in tests. Record fixtures to tests/fixtures/<source>/.
- Never edit .env or secrets. Never run DROP/TRUNCATE/DELETE-without-WHERE.
- A new metric starts as an entry in docs/METRICS.md, then code, then a test.

## Conventions
- Python 3.12, ruff-formatted (hook runs it), type hints, functions < 60 lines.
- Collectors must survive a source outage: log, mark `job_runs.status`, continue.
- Join keys: `video_id`, `channel_id`, `cluster_id`, `wikidata_qid`, `keyword+geo+lang`.
- Money in USD floats with 2 decimals; volumes as integers; timestamps UTC.
- `legacy/` is frozen: not linted, not edited, ported one file at a time.

## Workflow
- Plan mode for schema, base classes, scoring changes. One branch per task.
- Use `source-researcher` before writing a collector, `reviewer` before merge,
  `data-qa` after any job run. Don't delegate core implementation to subagents.
- Skills: /new-collector, /add-metric, /run-backtest, /db-migration.
- Update docs/ in the same PR when a source, metric, or decision changes.

## Compact instructions
When compacting: keep the list of modified files, migration revision ids, any
quota numbers observed this session, open TODOs, and rule violations found by
reviewer. Summarize exploration briefly.

## Current status
- Phase: Slice 4 complete (amended — see ADR-0018). Gate D invoked: sub-niche
  discovery deferred, per-video relevance shipped instead.
- Membership is now two questions: channel identity (ADR-0013, unchanged) and
  per-video topicality (`nh/clustering/relevance.py`). Before this, videos
  inherited their channel's cluster and **only 20% were about their niche**;
  every `supply.*` and `money.*` number was computed over the rest.
- Relevance is a two-axis lexical rule — domain vocabulary AND failure/case
  markers, geometric mean. Calibrated on 298 hand labels, held-out **precision
  0.781, recall 0.694, base rate 28.6%**. That is below the 0.90 the plan asked
  for; it ships because no filter is precision 0.286. reports/relevance_2026-08-27.md.
  **Outstanding: an independent 50-row spot-check** — the labeller was the same
  system that wrote the lexicon.
- `videos.description` rescued from `raw_records` before the prune took it
  (13,855 rows, 93.0% coverage). `nh prune` now refuses to delete the last copy
  of a description (ADR-0017).
- 315 tests, zero network. Supply/money values all moved; supply RANKS and `gap`
  did not, so the ranking was not an artifact of contamination. Confidence fell
  everywhere, which is the honest half.
- Still blocked: openness needs the enrichment backfill (274 units, ~2.9% of
  budget) — `is_short` is NULL for 92% of videos, so `eligible_videos` sees 8.3%
  of the corpus and 4 of 5 cohorts are empty. Expected at the next 09:10 cron.
- Next: Slice 5 (full feature set) per docs/ROADMAP.md. Carried forward from
  Slice 4 as a Slice 5 candidate: event-level Wikipedia articles dwarf the
  topic-level baskets demand currently uses (Chernobyl_disaster alone is 4.59M
  views/12mo against the entire aviation basket's 719K).
