> **RESUMED 2026-08-28 as the primary project** (ADR-0029), reversing the archival
> banner of the same morning. `../niche-hunter-2` is **paused**, its documents kept.
>
> **What resumed:** the original roadmap at **Slice 4 — sub-niche discovery**. Its
> premise (ADR-0018: "multiple sources to cluster together") is restored, because
> Keyword Planner turns out to be available today with no approval at all via the UI
> CSV export, whose parser already exists in `legacy/niche_hunter_kp.py`.
>
> **What did NOT resume: the dashboard.** Gate E's null was *powered* — 29 of 36
> niches, detectable rho 0.378, size control clean at −0.019 — and sub-niches do not
> repeal it. `scorecards.opportunity` stays NULL and nothing ranked ships until a new
> pre-registered test passes on the new grain. See `reports/backtest_2026-08-28.md`.
>
> **Source states, which are three different things:** Keyword Planner = available
> now (CSV, no approval). Reddit = obtainable, needs an application filed, never was.
> Trends `related_queries` = measured blocked, no credential opens it — sub-niche
> discovery must work without it.

# Niche Hunter

Nightly pipeline + dashboard that scores YouTube niche clusters on demand–supply
gap, openness, RPM, sustainability and risk using free sources. The compounding
asset is snapshot history; never break the collectors.

## Read first
- docs/ROADMAP.md — the slices, the gates, and what ships next
- docs/RUNBOOK.md — cron, alerting, the drills, day-1 procedure, known defects
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
- Phase: **Gate E returned FAIL on 2026-08-28** — rho 0.091, permutation p 0.4988,
  29 of 36 niches, detectable rho 0.378. A null, not an underpowered run. Branch
  `slice-6-calibration`. `reports/backtest_2026-08-28.md` carries the verdict and a
  hand-written failure analysis.
- The instrument was checked before the null was accepted: `gap` is not flat (sd
  0.402), the outcome is not flat (within-date sd 0.079, 6.5x range), and nothing
  hides under niche size (rho -0.019). Demand alone +0.049, supply alone -0.073 —
  neither input carries signal, so the failure is not in how they are combined.
- **Do not build the dashboard.** Of the roadmap's two pre-committed branches, the
  evidence points to narrowing the claim to "surfaces evidence for a human to judge":
  zero of 4,517 niche-dates show negative growth, so the corpus tested relative growth
  among channels that had already succeeded and cannot express emergence at all.
- Known defect from this run: `winner_age_years` and `top10_concentration` were in
  `replay.BACKTEST_METRICS` but `video_snapshots` is empty in `data/backtest.db` by
  design, so both were 100% NULL and openness never entered the backtest.
- Outstanding from the 2026-08-28 audit (`reports/relevance_interrater_2026-08-28.md`,
  fix plan in the session artifact): the human relevance check — sample from ABOVE the
  0.55 threshold, 60-100 rows, not the uniform 50; `uploads_per_week`'s 29-day window
  and its spec-divergent confidence; the court-cases successors, which have seeds and
  demand terms but **no lexicon**, so they can never gain members and will stay retired.
- Never point a backtest command at the live corpus. `load.refuse_live` requires
  "backtest" in the database URL; `NH_DATABASE_URL=sqlite:///data/backtest.db`.
