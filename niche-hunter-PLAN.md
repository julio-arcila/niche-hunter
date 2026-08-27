# Niche Hunter — implementation plan (Claude Code)

Goal: a nightly pipeline plus dashboard that scores YouTube niche clusters on
demand–supply gap, openness, RPM, sustainability and risk, using only free
sources, with snapshot history as the compounding asset.

Principle for the whole plan: **collectors first, dashboard last.** Every day the
RSS/API snapshot jobs aren't running is a day of velocity history you can never
backfill. Phase 1 ships the collectors to a cron before anything else exists.

---

## 0. Stack decisions (make once, write to docs/DECISIONS.md)

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12, `uv` for env/deps | Collectors already written in Python |
| DB | Postgres 16 (docker compose locally) | Snapshot tables will pass millions of rows; JSONB for raw payloads |
| Migrations | Alembic | Schema will change weekly in the first month |
| Scheduler | cron (v1) → Prefect/Temporal only if jobs exceed ~10 | Don't build orchestration before there's something to orchestrate |
| Embeddings | `sentence-transformers` (`bge-small`/`e5-small`) locally; HDBSCAN + UMAP for clusters | Titles are short; local is free and fast |
| API | FastAPI | Thin read layer over Postgres for the dashboard |
| Dashboard v1 | Streamlit | Radar + niche page in a day; replace later |
| Dashboard v2 | React + Recharts on FastAPI | Only after the metrics stabilize |
| Tests | pytest + recorded fixtures (`responses`/`vcrpy`) | No live API calls in tests, ever |
| Lint/format | ruff (enforced by hook) | |
| Secrets | `.env` (gitignored) + `pydantic-settings` | Hook blocks Claude from editing `.env` |

---

## 1. Repository layout

```
niche-hunter/
├── CLAUDE.md                     # project memory (see separate file)
├── .claude/
│   ├── settings.json             # hooks + permissions
│   ├── rules/
│   │   ├── python.md             # style, typing, error handling
│   │   ├── data.md               # snapshot/provenance/idempotency rules
│   │   └── sources.md            # quota + rate-limit etiquette per source
│   ├── skills/
│   │   ├── new-collector/SKILL.md
│   │   ├── add-metric/SKILL.md
│   │   ├── run-backtest/SKILL.md
│   │   └── db-migration/SKILL.md
│   └── agents/
│       ├── source-researcher.md  # reads API docs, returns constraints summary
│       ├── reviewer.md           # read-only code review
│       └── data-qa.md            # runs SQL sanity checks, read-only DB
├── docs/
│   ├── ARCHITECTURE.md           # the layered diagram in words
│   ├── SOURCES.md                # every source: URL, auth, quota, fields, caveats
│   ├── METRICS.md                # every metric: formula, inputs, join key, CI method
│   ├── INSIGHT_RULES.md          # the 10 cross-source rules, as testable predicates
│   └── DECISIONS.md              # ADRs, one paragraph each
├── nh/
│   ├── config.py                 # pydantic-settings
│   ├── db/
│   │   ├── models.py             # SQLAlchemy
│   │   └── migrations/           # alembic
│   ├── collectors/
│   │   ├── base.py               # Collector ABC: fetch → normalize → upsert + snapshot
│   │   ├── youtube_api.py        # from niche_hunter_yt.py
│   │   ├── youtube_rss.py        # from niche_hunter_rss.py
│   │   ├── trends.py             # from niche_hunter_trends.py
│   │   ├── reddit.py             # from niche_hunter_reddit.py
│   │   ├── keyword_planner.py    # from niche_hunter_kp.py
│   │   ├── wikipedia.py          # pageviews + wikidata
│   │   ├── wayback.py            # CDX → historical sub counts
│   │   └── primary/              # ntsb.py, edgar.py, courtlistener.py, ...
│   ├── clustering/
│   │   ├── embed.py
│   │   └── cluster.py            # niche assignment, centroid drift
│   ├── features/
│   │   ├── demand.py  supply.py  openness.py  voice.py  money.py  cost_risk.py
│   ├── scoring/
│   │   ├── scorecard.py          # composite scores + CI
│   │   ├── lifecycle.py          # stage classifier
│   │   └── rules.py              # insight rules → alerts
│   ├── backtest/
│   │   ├── youniverse.py         # loader
│   │   └── replay.py             # run classifier on history, score precision
│   ├── jobs/
│   │   ├── nightly.py            # orchestrates collectors → features → scoring
│   │   └── hourly_hot.py         # RSS for hot channels
│   ├── api/                      # FastAPI
│   └── web/                      # Streamlit v1
├── tests/
│   ├── fixtures/                 # recorded responses per source
│   └── ...
├── scripts/                      # one-off: seed niches, load YouNiverse, etc.
├── docker-compose.yml            # postgres
└── pyproject.toml
```

---

## 2. Claude Code configuration

### CLAUDE.md
Short, stable, load-bearing. See `CLAUDE.md` file alongside this plan. Keep under
~150 lines; move detail to `docs/` and `.claude/rules/`.

### .claude/rules/
- `python.md` — type hints everywhere; `raise` over silent `None` except in
  collectors where a source outage must not kill the nightly job; no bare
  `except`; functions under 60 lines.
- `data.md` — the non-negotiables:
  1. Every collector write carries `at` (UTC ISO), `source`, `run_id`.
  2. Raw payloads go to `raw_*` tables as JSONB before normalization.
  3. Upserts are idempotent; re-running a job for the same day is safe.
  4. Snapshots are append-only. Never update a snapshot row.
  5. Every feature row stores its input row counts and a `confidence` field.
  6. No numeric fabricated defaults: absent = NULL, never 0.
- `sources.md` — quota budgets and politeness per source (YouTube 9,500 units
  reserve, RSS 8 workers with jitter, Trends 2.5 s gap, Reddit watch
  `X-Ratelimit-Remaining`, Keyword Planner cache 7 days).

### .claude/settings.json (hooks + permissions)
```json
{
  "permissions": {
    "deny": ["Edit(.env)", "Edit(.env.*)", "Write(.env)", "Bash(rm -rf *)"]
  },
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "scripts/hooks/block_dangerous_sql.sh" }] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|Write", "hooks": [{ "type": "command", "command": "uv run ruff format --quiet $CLAUDE_FILE_PATHS && uv run ruff check --fix --quiet $CLAUDE_FILE_PATHS" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "uv run pytest -q -x --no-header 2>&1 | tail -20" }] }
    ]
  }
}
```
`block_dangerous_sql.sh` rejects commands containing `DROP TABLE`, `TRUNCATE`,
or `DELETE FROM` without a `WHERE`. Verify the exact hook JSON shape and env
variable names against the current Claude Code hooks docs before committing —
they have changed across versions.

### .claude/skills/
Skills carry the repeatable playbooks so they don't bloat CLAUDE.md:
- `new-collector` — scaffold a collector: subclass `base.Collector`, add
  `raw_<source>` + normalized tables via migration, record fixtures, write the
  quota/etiquette entry in `docs/SOURCES.md`, add to `nightly.py`.
- `add-metric` — add a feature: define in `docs/METRICS.md` first (formula,
  inputs, join key, CI), then implement in `features/`, then a test against a
  fixture DB, then expose in the scorecard.
- `run-backtest` — load a history slice, run `lifecycle.py` at each historical
  date, compute precision/recall of "emerging" calls at 90/180 days, write a
  report to `reports/backtest_<date>.md`.
- `db-migration` — alembic revision with a reversible downgrade; run against a
  scratch DB before applying.

### .claude/agents/
- `source-researcher` (tools: WebFetch, WebSearch, Read) — given a source,
  return auth model, quota, endpoints, fields, known caveats. Keeps doc-reading
  out of the main context.
- `reviewer` (tools: Read, Grep, Glob; read-only) — reviews diffs against
  `.claude/rules/data.md`; flags any write that lacks `at`/`run_id`, any
  non-idempotent upsert, any test that hits the network.
- `data-qa` (tools: Bash restricted to `psql` read-only role) — after a job
  runs, checks row counts vs previous run, NULL rates, snapshot monotonicity
  (views never decrease for the same video), and orphaned foreign keys.

---

## 3. Phases

Each phase = one or more Claude Code sessions. Start each in **plan mode**,
approve the plan, then execute. One task per branch; `reviewer` before merge.

### Phase 0 — Bootstrap (day 1)
- Init repo, `uv`, `pyproject`, docker compose Postgres, alembic baseline.
- Write CLAUDE.md, rules, hooks, agents, skills (copy from this plan; trim).
- `docs/SOURCES.md` from the source inventory; `docs/METRICS.md` skeleton.
- Port the five existing modules into `nh/collectors/` behind `base.Collector`.
  No new behavior — just structure, config, and Postgres instead of SQLite.
- Record fixtures for each source (one real call each, saved to `tests/fixtures`).
- **Exit criteria:** `uv run pytest` green with zero network; `nightly.py --dry-run`
  lists the collectors it would run.

Prompt sketch:
> Plan mode. Read CLAUDE.md, docs/SOURCES.md and nh/collectors/*.py. Design
> `base.Collector` so each existing module becomes a subclass with `fetch()`,
> `normalize()`, `persist()`; persistence must satisfy .claude/rules/data.md.
> Propose the Postgres schema and the alembic baseline. Don't write code yet.

### Phase 1 — Collectors live (week 1) — highest priority
- Seed table `niche_seeds` with 5–10 hand-picked niches and their keywords.
- Nightly job: YouTube discovery (date + viewCount) → enrich → channel
  baselines → RSS poll of every known channel → Trends → Reddit (if approved)
  → Keyword Planner (cached).
- Hourly job: RSS for `hot` channels.
- Cron both. Log quota usage per run to `job_runs`.
- `data-qa` agent runs after each nightly and posts a summary.
- **Exit criteria:** 7 consecutive nightly runs with no manual intervention;
  `rss_snapshots` growing daily; quota under budget every night.

### Phase 2 — Clustering (week 2)
- `embed.py`: embed titles (YouTube), question titles (Reddit), rising
  queries (Trends), keywords (KP) into one space.
- `cluster.py`: HDBSCAN per seed niche → sub-niche clusters; store
  `cluster_id`, centroid, member counts by source, centroid drift per day.
- Manual review UI (Streamlit, 50 lines): label clusters, merge/split.
- **Exit criteria:** every collected item has a `cluster_id` or `noise` flag;
  cluster membership is stable across two consecutive days (>90% overlap).

### Phase 3 — Features (week 3)
Implement in this order, each with `add-metric` and a fixture-DB test:
1. `supply.py` — uploads/week, active channels, top-10 concentration,
   median top-video age, format mix.
2. `openness.py` — cohort breakthrough rate, views-per-sub distribution,
   newcomer share, RSS acceleration.
3. `demand.py` — Trends features, Wikipedia pageviews, KP volume, Reddit
   question rate; anchor-scaled and z-scored within the cluster universe.
4. `voice.py` — question clusters, unanswered rate, shared-channel counts.
5. `money.py` — vw_cpc, priced share, tier-1 share (comments + Trends geo +
   KP geo), advertiser count, RPM regression with CI.
6. `cost_risk.py` — primary-source density/cadence, PD asset density,
   evergreen score, brand-safety lexicon, enforcement trend.
- **Exit criteria:** `features_daily` has one row per cluster per day for all
  six groups, with `confidence` populated.

### Phase 4 — Scoring, lifecycle, rules (week 4)
- `scorecard.py`: gap, openness, value, sustainability, opportunity, CI.
- `lifecycle.py`: rule-based v1 (signs of deltas), leave hooks for a
  learned model after backtesting.
- `rules.py`: the 10 insight rules from `docs/INSIGHT_RULES.md` as predicates
  over `features_daily`; emits `alerts` rows with the evidence.
- **Exit criteria:** every cluster has a scorecard and stage; alerts fire on
  synthetic test data for each rule.

### Phase 5 — Backtest (week 5)
- Load YouNiverse; build `historical_channel_weeks`.
- Wayback CDX collector for sub-count history of current top channels.
- `replay.py`: for each historical date, compute features from history only,
  run `lifecycle.py`, compare to what happened 90/180 days later.
- Tune thresholds; record results in `reports/`.
- **Exit criteria:** a precision/recall number for "emerging" you'd bet on, and
  a written note on where the classifier is wrong.

### Phase 6 — Dashboard (week 6)
- Streamlit: Radar (scatter), Niche page (scorecard, overlaid demand series,
  cohort chart, channel map, question bank, source feed, topic queue), Alerts
  feed, Backtest report viewer, Cost model.
- FastAPI read endpoints under it so v2 can swap the front end.
- **Exit criteria:** you can go from radar → niche → topic queue → source
  document in three clicks.

### Phase 7 — Ops and hardening (ongoing)
- Slack/email digest of alerts; quota alarms; failed-job retries.
- Quota-increase request to YouTube; Reddit approval follow-up; Google Ads
  basic access.
- Monthly: re-record fixtures, re-check source ToS, re-run backtest.

---

## 4. Working pattern with Claude Code

1. **Plan mode first** for anything touching schema, base classes, or scoring.
   Approve, then execute. Reject plans that don't cite `docs/METRICS.md` for
   new metrics.
2. **One branch per task**, PR-sized. Use worktrees for parallel tasks
   (e.g. a collector and a feature at the same time) so sessions don't collide.
3. **Subagents for research and review**, never for core implementation.
   `source-researcher` before writing a collector; `reviewer` before merging;
   `data-qa` after any job run.
4. **Tests are fixture-based.** If Claude proposes a test that calls a live
   API, that's a rule violation — the `reviewer` agent flags it.
5. **Compaction instructions** live in CLAUDE.md so long sessions keep the
   list of modified files, migration names, and any quota numbers observed.
6. **Session hygiene:** `/clear` between phases; `/compact` when context is
   mostly old tool output; keep `docs/DECISIONS.md` current so new sessions
   don't relitigate choices.
7. **Definition of done** for every task: tests green (hook), reviewer pass,
   `docs/` updated if a source/metric/decision changed, entry in CHANGELOG.

---

## 5. Prompt bank (copy into sessions)

- Collector: "Use the `new-collector` skill to add a Wikipedia pageviews
  collector. Have `source-researcher` confirm the REST endpoint, rate limits and
  the per-article daily granularity first. Join key is `wikidata_qid`."
- Metric: "Use `add-metric` to implement `openness.breakthrough_rate_cohort`.
  Definition is in docs/METRICS.md §3.1. Fixture DB: tests/fixtures/db_small.sql.
  Confidence = min(cohort_n/30, 1)."
- Rule: "Implement insight rule #4 (closing window) from docs/INSIGHT_RULES.md
  as a predicate in nh/scoring/rules.py with a synthetic test where breakthrough
  rate falls over three cohorts while uploads/week rises."
- Backtest: "Use `run-backtest` on YouNiverse 2017-01 → 2018-12 for the
  history and science niches. Report precision of 'emerging' at 180 days."
- QA: "Run `data-qa` against last night's `run_id` and summarize anomalies."

---

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Source access changes (Reddit approval, Trends blocks, Ads token) | Collectors are independent; nightly job skips failed sources and logs; scorecard confidence drops instead of pipeline failing |
| Clusters drift and metrics become non-comparable | Store centroid per day; alert on drift; freeze cluster IDs weekly for scoring |
| RPM model overfits sparse disclosures | Report CI; require n≥5 calibration points before showing a dollar figure |
| Claude Code makes destructive DB changes | Read-only DB role for agents; hook blocks dangerous SQL; migrations reviewed |
| Context bloat in long sessions | Skills for playbooks, subagents for research, compaction rules in CLAUDE.md |
