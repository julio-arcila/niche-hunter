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
> **Source states, which are three different things.** Keyword Planner = available now
> (CSV, no approval). Reddit = **application filed 2026-08-29, pending**. Trends
> `related_*` = **reachable** via the library's referer header, rate-limited — measured
> ≥6s between calls, and re-verified live 2026-08-31 (ADR-0032). It supplies **vocabulary,
> never a sub-niche level**, and no ranking may rest on one: Trends renormalises against a
> term's own peak, so narrowing a term never lowers its ceiling.
>
> *Two of those three sentences said the opposite until 2026-08-31, and both were true when
> written.* The Trends claim was contradicted by ADR-0032 **1h48m** after this banner was
> committed, and survived three days and one explicit flagging because the correction went
> into DECISIONS.md and SOURCES.md and nobody swept the echo. See ADR-0053.

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
- `uv run nh niche show <slug> [--unvalidated]` — every metric, with confidence and basis
- `uv run nh niche trace <slug> <metric>` — the input rows behind one number (ADR-0052)
- `uv run nh web` — the evidence surface; needs `uv sync --extra web`
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
- Phase: **Slice 7 SHIPPED 2026-08-31 (ADR-0052) — the evidence surface.** `nh/api/`,
  `nh/web/`, `nh/scoring/rules.py`; `uv run nh web`. Suite green at **967**. **`PHASES` is
  now FOUR** — clustering, features, scoring, rules — and `nh status --check` iterates it,
  so a new phase silently extends the nightly gate (it reads FAIL until the next nightly
  runs the new one; `run_nightly.sh` runs the phases before the check, so no page).
  **Next is NOT Slice 10.** Its endpoint premise is fine — settled and re-probed live
  2026-08-31 (ADR-0053) — but it has **no consumer**: nothing in `nh/` consumes a candidate
  sub-niche term, and the only consumer worth having, lexicon expansion, re-weights every
  domain through the discriminative `weights()` and would move the 0.55 frontier **both
  drawn samples were drawn against**, one of which expires 2026-09-14. Label first. TWO drawn samples still wait on a human labeller, and one has a
  2026-09-14 deadline. The ROADMAP headers for slices 9 and 11 said "PLANNED, not started"
  until 2026-08-31, three days after both shipped — read `nh/seeds.py` and
  `features/run.py::METRICS`, not the roadmap, for what exists.
- **THE LABELLING IS CLOSED, BY DECISION (ADR-0054).** The operator declines to label
  either drawn sample and will not crowdsource them. **Do not raise it again, and do not
  treat it as pending work** — it is the third branch ADR-0050 pre-committed to, taken
  deliberately. Both samples remain drawn and reproducible
  (`reports/exposition_labelling_2026-08-31.jsonl`, `reports/recall_labelling_2026-08-31.jsonl`,
  seeds 20260831 and 20260901) should a rater ever appear; nothing about the instrument
  decayed. **A model labelling them is still not evidence** — ADR-0041's objection is
  unchanged and two samples were already spent that way.
- **So ballast reverts on 2026-09-14 and that is the expected outcome, not a failure.**
  `ballast_active()` goes False, `supply.definition()` stamps `v2-on-niche`, and
  `history-of-ideas on_niche_share` returns to 0.0758 — verified end to end, no migration,
  no lost history. Rule 2 fires that night and names the cause; `nh status --check` warns
  on the ballast delta. Expect both. The eight scorer-dependent metrics and the whole
  `scorecards` row stay withheld from every surface indefinitely.
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
  happened once (ADR-0039 addendum) and is the repo's standing example. **`keywords` is
  the opposite** — it IS in the update set, so a seed-query change needs only `nh seed`
  and a hand UPDATE would be cargo-cult (ADR-0049). Discovery costs 6,000 of 9,500 units
  at ten domains. The five disaster niches are retired from discovery at 0 units
  while RSS keeps compounding their history.
- **The corpus is a preimage of its own queries, and ADR-0051 only makes that
  measurable.** 25 of 30 discovery queries carried an "explained" token while relevance
  is the geometric mean of domain x **exposition** — selected for explainers, then scored
  on being explainers. Five queries moved register (`... explained` -> `... lecture` /
  `... debate`), topic held fixed so the two arms differ in one dimension; register-free
  goes 5/30 -> 10/30, quota unchanged. **The probe arm is expected to yield worse** — do
  not read that as failure. A test holds the floor, with one exemption
  (`logic-linguistics-gnoseology`, ADR-0049's control, itself 3/3 "explained" and so
  explicitly NOT a register control) that expires on that re-measure.
- **`nh status --check` now gates on provenance and on the ballast cut.** Two feature
  runs on one day, or a scorecard naming a run its features did not come from, is a
  **problem** — that happened on 2026-08-31 and nothing looked. `detail.ballast.channels`
  moving more than 5% of member channels night-over-night is a **warning**, on the delta
  and never the level (history-of-ideas is 126 of 205 by construction). A missing stamp is
  tolerated on a day where no row has one, and warned on when only some rows do.
- **Every change on 2026-08-31 removed negative evidence from a denominator and none
  added any**, which is the independent review's structural finding and is not repaired
  by any of ADR-0050/0051. The class that would have LOWERED shares — tightening an
  over-firing lexicon — was declined as tuning against machine-identified failures, while
  ADR-0047 rests on the same machine judgements and shipped. The recall sample is what
  breaks that: it is the repo's first human-labelled **negative** evidence, and a failing
  row there is what legitimately licenses a lexicon tightening.
- Nothing ranked ships, and neither validation changes that.
  `scorecards.value` / `sustainability` / `opportunity` stay NULL behind **Gate E's
  2026-08-28 null** (rho 0.091, p 0.4988, detectable rho 0.378 — a null, not an
  underpowered run; demand alone +0.049 and supply alone -0.073, so the failure is not
  in how they are combined).
- **"Do not build the dashboard" is AMENDED, not lifted (ADR-0052).** What stays forbidden
  is the ranked surface: no radar scatter, no niche list ordered by a score, no rendering
  of `scorecards`. What Slice 7 builds is the **evidence** surface — the demand series, the
  corpus, the source feed, and `value / confidence / inputs_n / detail` traced back to the
  rows each number came from. The roadmap's own Slice 7 text still shipped a radar scatter
  three days after Gate E retired that framing; it is rewritten.
- **A UI is a citation surface, and ADR-0045's trigger cannot see it.** That trigger queries
  non-NULL `value`/`sustainability`/`opportunity` — which Gate E holds NULL *permanently*,
  because Gate E failed — while `gap`, `supply`, `demand`, `stage` and `openness` are
  non-NULL for all ten unvalidated exposition clusters. So the register stays green while
  the numbers sit there. `nh/api/gates.py` is the answer: the read layer refuses to serve
  what the deferral covers, holding `EXPOSITION_VALIDATED: bool | None` on the
  `BALLAST_VALIDATED` pattern — a human's verdict, and explicitly **no env-var escape
  hatch**, which would be a file the code reads standing in for one.
- **`nh/api/` is the read layer every surface goes through**, and the gate lives in it,
  not in a presenter: `jobs/niche.py::load` withholds by DEFAULT, so forgetting the
  argument fails safe. `nh niche show` was ALREADY citing — it printed `gap=0.50` and all
  eight scorer-dependent metrics for unvalidated clusters — which is why the gate shipped
  before any web page. `--unvalidated` shows them: a human asking once, recording nothing.
  `drilldown.REGISTRY` maps every metric to its input rows and is tested to return
  **non-empty** — an empty result satisfies "did not raise" forever. `nh niche trace` is
  its first consumer. Gated metrics still show their ROWS, deliberately: the aggregate
  claim is withheld, the evidence to check it is not — but do not browse them before
  labelling a sample.
- **Which metrics the scorer decided is DERIVED, never tabulated.** Run all 22 twice, once
  at `RELEVANCE_HIGH` and once at an impossible threshold, and diff. Measured: **14 are
  independent** (all `demand.*`, `breakthrough_rate_cohort`, `views_per_sub`, the four KP
  `money.*`) and **8 read relevance** (all six `supply.*`, `midroll_eligible_share`, and
  **`openness.winner_age_years`**, which joins `on_niche_join` at `openness.py:167`). That
  last one is why: a plan that reasoned from the query text put all of `openness.*` in the
  safe tier, conflating "unaffected by ballast" — true — with "does not read relevance",
  which was never measured.
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
  (`tests/test_lexicon_families.py`'s ruff I001 is fixed — it was held only because the
  branch was shared, and that branch is merged. `uv run ruff check .` is clean.)
- Blocked on other people: Reddit Data API (applied 2026-08-29, pending) and Google Ads
  Basic access (applied). `nh deferrals` is the register and is expected to be true —
  three entries were caught lying this session; read it, don't assume it.
- Never point a backtest command at the live corpus. `load.refuse_live` requires
  "backtest" in the database URL; `NH_DATABASE_URL=sqlite:///data/backtest.db`.
