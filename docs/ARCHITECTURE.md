# Architecture

## The layers

```
sources ──▶ collectors ──▶ raw_records ──▶ normalized ──▶ clusters
                                                            │
                                                            ▼
                                   scorecards ◀── features_daily
                                        │
                                        ├──▶ alerts
                                        └──▶ api ──▶ web
```

**Collectors** (`nh/collectors/`) subclass `base.Collector` and implement two
methods. `fetch()` owns all network and yields `Raw` payloads verbatim.
`normalize(raw)` is pure — no I/O, no clock, no network — and returns a `Batch`
of `Upsert` (entities) and `Snapshot` (time series). Everything else —
provenance stamping, raw-before-normalized ordering, idempotent upserts,
append-only snapshot writes, quota accounting, `job_runs` bookkeeping, surviving
a source outage — happens once in `Collector.run()`.

**Storage** (`nh/db/`). Raw payloads land in `raw_records` (JSONB on Postgres,
JSON on SQLite) before interpretation, so re-normalizing a week of history is a
query rather than a re-fetch. Normalized entities live in typed tables and are
upserted idempotently. Time series live in `*_snapshots`, append-only, keyed
`(entity, observed_date, source)`.

**Clustering** (`nh/clustering/`, Phase 2) embeds YouTube titles, Reddit
question titles, Trends rising queries and Keyword Planner keywords into one
space and assigns every item a `cluster_id`. `cluster_id` is the join key for
everything downstream — it is what makes a demand signal and a supply signal
comparable.

**Features** (`nh/features/`, Phase 3) compute one row per cluster per day per
metric into `features_daily`, each with `confidence` and `inputs_n`. Six groups:
demand, supply, openness, voice, money, cost_risk.

**Scoring** (`nh/scoring/`, Phase 4) builds composite `scorecards` with
confidence intervals, classifies lifecycle stage, and evaluates the insight
rules into `alerts`.

**Serving** — `nh/api` is a thin FastAPI read layer; `nh/web` is Streamlit v1.
Both are Phase 6 and deliberately last.

## Why the order is collectors-first

Every other layer can be recomputed from stored data. Snapshot history cannot:
no source serves it retroactively. A day the RSS poller does not run is a day of
view-velocity history that is gone permanently. So the build order is collectors
→ clustering → features → scoring → dashboard, and the dashboard is last even
though it is the part you want to look at.

## Enforcement, not convention

The rules in `.claude/rules/data.md` are implemented rather than documented:

| Rule | Where it is enforced |
|---|---|
| Provenance on every write | `Collector._stamp()` injects `source`, `run_id`, `at` |
| Raw before normalized | `Collector._flush()` writes `raw_records` first |
| Idempotent upserts | `nh.db.upsert.upsert` — real conflict key, supplied columns only |
| Snapshots append-only | `AppendOnly` mixin + `before_flush` listener raising `AppendOnlyViolation` |
| Snapshots deduped per day | `UniqueConstraint(entity, observed_date, source)` + `insert_ignore` |
| Absent is NULL | `nh.collectors.parse.*` return `None`; every measure column is nullable |
| Outage does not kill the run | `Collector.run()` records `job_runs.status="failed"` and returns |
| No network in tests | autouse `no_network` fixture blocks sockets |
| No destructive SQL | `scripts/hooks/block_dangerous_sql.sh` on `PreToolUse(Bash)` |

## Join keys

`video_id`, `channel_id`, `cluster_id`, `wikidata_qid`, `keyword+geo+lang`.
Money is USD floats with 2 decimals, volumes are integers, timestamps are UTC.
