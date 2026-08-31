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

## Non-negotiables (details in .claude/rules/data.md)
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
- Phase: **Slice 9 shipped; the exposition-axis labelling is the open task.** Branch
  `slice-11-eleven-domain-pivot`. Suite green at **716**.
- **THE ONE THING WAITING ON A HUMAN — do not do this for them.**
  `reports/exposition_labelling_2026-08-29.jsonl` holds **99 unlabelled rows**. The
  operator labels them (said 2026-08-29 they would do it the next day). Fill `label`
  with 1/0. The criterion, the bar and both branches are fixed in
  `reports/exposition_draw_2026-08-29.md` and **ADR-0041**, written before the sample
  existed. **Ships iff the 95% Wilson lower bound >= 0.70, i.e. 79 of 99 correct.**
  A model must not label these: the whole objection is that the existing evidence is
  107 machine labels from one model family, and kappa between two raters of that family
  cannot detect a bias they share. When the file comes back: compute the interval, write
  the result report, and if it fails say what that means about the lexicon.
- **Do not revise ADR-0041 or the criterion.** Not the bar, not the sampling rule, not
  the unjudgeable-counts-as-0 rule. Revision after labels is a new ADR that says why,
  and a re-label. Parity with EVENT's 0.781 was already considered and rejected as
  undecidable at this n (needs 87/100); do not relitigate it.
- **The eleven domains are ACTIVE and collecting** (ADR-0040), applied as both a
  catalogue change and an `UPDATE` — `apply_seeds` keeps `active` outside its upsert
  update set, so a code edit alone never reaches an existing row. That mistake already
  happened once (ADR-0039 addendum) and is the repo's standing example. Discovery costs
  6,600 of 9,500 units. The five disaster niches are retired from discovery at 0 units
  while RSS keeps compounding their history.
- Nothing ranked ships, and the exposition test does not change that.
  `scorecards.value` / `sustainability` / `opportunity` stay NULL behind **Gate E's
  2026-08-28 null** (rho 0.091, p 0.4988, detectable rho 0.378 — a null, not an
  underpowered run; demand alone +0.049 and supply alone -0.073, so the failure is not
  in how they are combined). **Do not build the dashboard.**
- `QuotaLedger`'s budget is per-**RUN**, not per-day. A manual `nh nightly` plus the
  09:10 cron land in the same Pacific quota day and each believes it has the full 9,500.
  `echo "why" > .skip-once` skips one fire and is consumed by it; never comment out the
  crontab line. Quota day resets midnight Pacific = 02:00 local.
- Known defects, unfixed: the `court-cases` successors have seeds and demand terms but
  **no lexicon**, so they can never gain members and stay retired. `winner_age_years`
  and `top10_concentration` were in `replay.BACKTEST_METRICS` while `video_snapshots` is
  empty in `data/backtest.db` by design, so openness never entered the backtest.
  `tests/test_lexicon_families.py` has a pre-existing ruff I001, untouched deliberately
  on a shared branch.
- Blocked on other people: Reddit Data API (applied 2026-08-29, pending) and Google Ads
  Basic access (applied). `nh deferrals` is the register and is expected to be true —
  three entries were caught lying this session; read it, don't assume it.
- Never point a backtest command at the live corpus. `load.refuse_live` requires
  "backtest" in the database URL; `NH_DATABASE_URL=sqlite:///data/backtest.db`.
