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
- Phase: Slice 6 in flight — the calibration instrument is built and green, the
  Gate E verdict is not in. Branch `slice-6-calibration`.
- `nh/backtest/`: 36 niches in 6 families (committed before the data landed), an
  exact prefilter, YouNiverse readers, loader, `outcome.growth_180d`, the replay,
  the statistics and the report writer. CLI: `nh backtest seed|scan|load|replay|score`.
- The primary result, verdict rule and permutation scheme are pre-registered in
  `reports/backtest_preregistration_2026-08-27.md`, with an amendment log.
- 625 tests, zero network. The whole feature layer is day-*bounded* now, not just
  day-parameterised; `tests/test_features_leakage.py` is the standing guard.
- Blocking, and both are operator time not design: `yt_metadata_en.jsonl.gz` is
  still downloading (~8 of 13.64 GB), and the scan cannot run until it lands. The
  Wikipedia backfill for the 36 backtest niches runs against `data/backtest.db`
  independently and does not wait for it.
- Never point a backtest command at the live corpus. `load.refuse_live` requires
  "backtest" in the database URL; `NH_DATABASE_URL=sqlite:///data/backtest.db`.
