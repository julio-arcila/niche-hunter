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
  `slice-11-eleven-domain-pivot`. Suite green at **721**.
- **THE ONE THING WAITING ON A HUMAN — and BOTH drawn samples have now been spent by a
  model.** 2026-08-29 (ADR-0041) and 2026-08-30 (ADR-0042) were each labelled by fable-5
  at the operator's repeated instruction. Both came to **78/99**, lower bound 0.6974,
  failing the 0.70 bar by 0.0026 — one row, twice, from opposite sides of a criterion
  revision. **Neither is evidence**: it is fable-5 grading a lexicon built from fable-5
  labels, the exact circularity the test exists to prevent.
  **The third sample is DRAWN and waiting**: `reports/exposition_labelling_2026-08-31.jsonl`,
  seed 20260831, **100 rows, 10 per domain across the ten remaining domains** (ADR-0044),
  4 rows overlapping what a model labelled. Bar is ADR-0041's tabulated **79/100**.
  Run `uv run python scripts/label_exposition.py` — it now defaults to the newest draw.
  ~20 minutes, and it need not be the operator: ADR-0041 requires a rater independent of
  the model family, not a specialist. See `reports/exposition_result_2026-08-30.md`.
- **BUT THIS NO LONGER BLOCKS ANYTHING (ADR-0045).** The requirement now fires when an
  exposition score is CITED — a scorecard row for an active exposition cluster carrying a
  non-NULL `value`/`sustainability`/`opportunity` — not while the score merely exists. The
  deferral is `kind="query"` and self-evaluates (verified both ways: False now, True on a
  scratch copy with a value set), so it is a work queue rather than a wall. Until
  something cites these numbers they are computed, unvalidated, and used for nothing
  outward-facing. The BAR is unchanged when it fires: two passes, 0.70 lower bound,
  79/100. This is a deliberate weakening of an evidence standard, recorded as one.
- **What the machine runs did establish, and it is not the number.** ADR-0042's two-pass
  split decomposed the 21 failures into **subject 13, exposition 8** — the axis under
  test is not the main problem, the DOMAIN lexicons are. `philosophy-of-science` is the
  outlier at **4/9**, failing almost entirely on subject: bone biology, electromagnetic
  induction and a trading book summary all scored above 0.55 as philosophy of science.
  This converges with `reports/supply_audit_2026-08-30.md`, which independently found
  that domain worst on on-niche share (4.3%) and ballast (60.9%). Treat it as the
  hypothesis to test first — **do not tune the lexicon against machine-identified
  failures**, which compounds the circularity rather than escaping it.
- **Do not revise the bar or the sampling rule.** ADR-0042 re-specified only HOW a row is
  judged — two passes plus an explicit `unsure`, and pre-registered worked archetypes —
  because the intended labeller could not apply the single compound criterion. n, frame,
  cap, the >=6-domain rule and the 0.70 bound are unchanged, deliberately: the bar has
  now been missed by one row twice, which is a reason to get a real rater, not to move
  it. Parity with EVENT's 0.781 was considered and rejected as undecidable at this n.
- **Title+description is a sufficient basis** — measured, unsure came in at 1 and 2
  against a 9.9 threshold, so ADR-0041's ">10% is itself a finding" did not trigger. The
  blinding rule is not starving the labeller, and the archetypes resolved cases that were
  coin-flips under the compound criterion. Keep both when re-running with a person.
- **TEN domains are active** — `philosophy-of-science` was retired 2026-08-31 (ADR-0044)
  as an EDITORIAL choice (the operator will not make that content), applied as code AND
  an `UPDATE`, verified 1 -> 0. Recorded there and repeated here because it is the thing
  a later reader will suspect: it was also the worst-scoring domain, and dropping it
  flips the machine precision run from FAIL to PASS (78/99 lb 0.6974 -> 74/90 lb 0.7306).
  That is a side effect, not the reason, and **no pass may be claimed from the old
  sample** — dropping the second-worst domain flips it too, so the bar is on a knife
  edge. Its lexicon stays in `LEXICONS`: `weights()` is discriminative, so removing one
  re-weights all the rest. Discovery now costs 6,000 of 9,500.
- **The remaining ten domains are ACTIVE and collecting** (ADR-0040), applied as both a
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
  09:10 fire land in the same Pacific quota day and each believes it has the full 9,500.
  `echo "why" > .skip-once` skips one fire and is consumed by it; never disable the
  scheduled job instead. Quota day resets midnight Pacific = 02:00 local.
- **The nightly runs from launchd** (`com.niche-hunter.nightly`, 09:10), not cron:
  cron silently skips a fire the Mac sleeps through and never retries it, which is
  how 2026-08-30 was lost for good. The backup and disk check stay in cron, because
  **cron holds Full Disk Access** (granted 2026-08-30) and the launchd agent does not:
  measured, an agent can CREATE a new file in iCloud but cannot overwrite one or
  enumerate the directory, so retention would break there. Each job has exactly one
  scheduler; two means two runs in one quota day. Plists live in `scripts/launchd/`;
  see docs/RUNBOOK.md "Scheduling".
- **`observed_date` is UTC**, so the snapshot day boundary is **19:00 local** — not
  the 02:00 Pacific quota reset. A catch-up nightly started after 19:00 collects for
  *tomorrow*; that is how 2026-08-30's gap became permanent even after a rerun.
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
