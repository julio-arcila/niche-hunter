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
- Phase: Slice 5 complete (amended — ADR-0020). Built the decision layer rather
  than breadth, because every deferred group ends in a NULL scorecard column and
  the roadmap's own risk #9 says calibration precedes breadth.
- `scorecards.stage` exists — a **demand-trajectory** classifier, pure (no Session,
  no clock), zero tuned constants, ADR-0023. It is what Slice 6 replays.
- **Gate E cannot run as specified.** YouNiverse contains only channels that
  crossed 10k subs by 2019, so "will this emerge?" has a base rate near 1 and no
  sampling fixes it. Slice 6 must use rank correlation instead —
  `reports/gate_e_feasibility_2026-08-27.md`, and `outcome.growth_180d` is now
  defined in METRICS.md.
- **The demand strata rank the niches near-inverted (Spearman −0.70).** Both are
  carried; Gate E arbitrates against a pre-registered criterion (ADR-0022).
- Seeds: 6 (court-cases split — its demand measured civics while its supply was
  true-crime trials, ADR-0024). 57–67% of every niche's supply sits outside the
  market its seed states; `supply.geo_concentration` reports it beside `gap`.
- 376 tests, zero network. 17 metrics registered.
- **Outstanding, deferred to before Slice 7:** a *human* pass over
  `reports/spotcheck_50.jsonl`. A second model agreed at kappa 0.943 — the criterion
  is unambiguous, which is not the same as right. Slice 6 buys insurance instead by
  running the backtest at three relevance thresholds; the score is stored and the
  cut applied at read time, so that is a query. Building Slice 7's product surface
  on an unvalidated definition of "niche" is not deferrable.
- Still blocked: openness needs the enrichment backfill (274 units) — `is_short` is
  NULL for 92% of videos, so 4 of 5 cohorts are empty. `nh deferrals` lists this and
  seven others, each with a checkable trigger.
- Next: Slice 6, redesigned per the feasibility report.

## Commands added since the list above
- `nh deferrals` — unimplemented metrics and what would unblock each
- `nh cluster inspect|sample|import|calibrate` — relevance decisions and labels
- `nh doctor --repair` — clear leftovers from an interrupted batch migration
- `nh backfill descriptions` — re-derive `videos.description` from `raw_records`
