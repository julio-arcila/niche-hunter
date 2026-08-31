# Roadmap — from scaffold to production

**Canonical.** The visual summary published as an Artifact is generated from this
file; when they disagree, this wins.

Supersedes the phase list in `niche-hunter-PLAN.md`, which remains the reference
for source inventory and prompt patterns. See "Why reslice" below.

---

## Definition of done: what "production grade" means here

This is a single-operator analytical product whose output is a claim about the
future. It is production grade when all eight hold:

| | Criterion | Verified by |
|---|---|---|
| 1 | **Unattended** — 30 consecutive nights, no manual intervention | `job_runs` query |
| 2 | **Alarmed** — a dead cron or failed source reaches a human within 24h | killing the cron on purpose |
| 3 | **Recoverable** — restore from backup, replay features from `raw_records` | a drill, performed, twice |
| 4 | **Calibrated** — a published rank correlation with its null distribution, its universe, and known failure modes | `reports/backtest_*.md` |
| 5 | **Traceable** — every displayed number reaches its input rows in ≤3 clicks | the UI itself |
| 6 | **Bounded** — quota headroom and monthly cost are known and monitored | quota dashboard |
| 7 | **Lawful** — every source's ToS reviewed, rate limits respected, review dated | `docs/SOURCES.md` |
| 8 | **Maintainable** — fixtures re-recorded monthly, one command runs everything | `uv run nh nightly` |

Criterion 4 is the one that decides whether this is a product or a toy, which is
why Slice 6 is a gate and not a task.

---

## Why reslice

`niche-hunter-PLAN.md` builds horizontally: every collector, then all
clustering, then all features, then scoring, then backtest, then dashboard. Two
problems.

**Nothing is usable until week 6.** Six weeks of building with no feedback from
using the thing. The first time the `features_daily` shape meets a real metric
is week 3, and by then four layers sit on top of it.

**The dashboard is scheduled regardless of the backtest result.** Phase 5
measures whether the classifier predicts anything; Phase 6 builds a UI on it
either way. If precision comes in at the base rate, Phase 6 is six weeks spent
rendering noise attractively.

Vertical slices fix both: each slice threads all layers and ends with something
you can run, and calibration happens before the product surface is built.

What carries over unchanged: collectors-first, snapshot history as the
compounding asset, fixture-based tests, one branch per task, subagents for
research and review only.

---

## The ratchet: production concerns start at Slice 1

Hardening is not a phase. For an app whose asset is unbackfillable history,
three of these are night-one concerns — if the RSS poller dies silently on night
3 and you notice on night 20, seventeen nights are gone permanently.

| Concern | S1 | S2–3 | S4–5 | S6–7 | S8 |
|---|---|---|---|---|---|
| **Secrets** | `.env`, gitignored, hook-blocked | — | — | — | secret manager, rotation |
| **Backup** | nightly copy offsite + **one real restore** | verify weekly | — | Postgres PITR | automated monthly drill |
| **Failure alerting** | dead-man switch + `job_runs.status != ok` → email | quota threshold | `data-qa` anomalies | feature drift | paging, SLOs |
| **Data quality** | `data-qa` after every run | NULL-rate trend | snapshot monotonicity | cluster drift | QA dashboard |
| **Deploy** | laptop cron | — | — | small VM | managed + IaC |
| **Database** | SQLite (ADR-0002) | — | **Postgres swap** | — | managed Postgres |
| **Observability** | logs to file | `job_runs` queries | per-`run_id` trace | request tracing | metrics dashboard |
| **Legal / ToS** | review recorded in SOURCES.md | — | re-check | — | monthly re-check |

The Postgres swap lands in S4–5 because that is when clustering starts writing
concurrently and JSONB queries begin to matter — the trigger named in ADR-0002,
not a calendar date.

---

## Slices

Sizes are for one person part-time. Calendar is indicative; variance is
dominated by Slice 4 and by external approvals outside your control.

### Slice 1 — First light · size M · the clock starts

**Goal:** irreplaceable data starts accumulating tonight.

Ships:
- `niche_seeds` populated with 5 hand-picked niches
- `youtube_rss` collector ported (the whole point)
- `youtube_api` collector ported — **discovery + enrichment only**; channel
  baselines and comment sampling are deferred, they are quota-expensive and not
  needed to start the clock
- both on cron; `data-qa` after each nightly
- dead-man switch, failure email, nightly offsite backup, one real restore

Why the two collectors together: RSS polls a channel list, and only the API can
produce one. Neither ships alone.

**Exit:** 7 consecutive unattended nights · `video_snapshots` grows every night ·
quota under 9,500 every night · killing the cron produces an alert within 24h ·
yesterday's database has been restored from backup once, for real.

**Risk:** the quota model is theoretical until it meets real seed keywords.
Measure on night 1. If 5 niches overrun, cut `search_pages` before cutting
niches — pages are cheap to restore later, history is not.

---

### Slice 2 — Walking skeleton · size M · one niche, all the way through

**Goal:** prove the architecture end to end before deepening any layer.

Ships:
- **Deliberately trivial clustering:** `cluster_id = seed slug`. No embeddings.
- Four features spanning three groups — e.g. `supply.uploads_per_week`,
  `openness.breakthrough_rate_cohort`, `supply.median_views`,
  `openness.views_per_sub` — each defined in METRICS.md first
- One `scorecards` row per seed per day, from a stub composite
- `nh niche show <slug>` — text output, no web

Why now, before real clustering or real features: the join keys, the confidence
plumbing, and the `features_daily` shape are the things most likely to be
subtly wrong. Finding out here costs a day. Finding out at Slice 5, with four
layers on top, costs a rewrite.

**Exit:** `nh niche show aviation-disasters` prints each metric with its value,
`confidence`, `inputs_n`, and the rows it came from. Re-running the day changes
nothing.

**Gate B:** if `features_daily` cannot represent one of these four metrics
cleanly, change the schema now — not later.

---

### Slice 3 — Demand side online · size M–L · the gap becomes computable

**Goal:** the core thesis — demand minus supply — becomes a number.

Ships:
- `trends` collector + `demand.*` features (anchor-scaled; the anchor trick is
  what makes batches comparable at all)
- `keyword_planner` collector + `money.*` features
- resolution of the `tier1_share` ambiguity flagged in METRICS.md — Trends region
  interest and KP geo runs currently compute it twice by different methods; pick
  one as authoritative or define how they combine
- replacement or citation for the hard-coded internet-population weights in
  `geo_tier1_share`, before any dollar figure rests on them

Until this slice the scorecard is supply-only, which measures competition, not
opportunity.

**Exit:** gap score computable for every seed, with confidence.

**Gate C — external:** Google Ads Basic access. The UI CSV export path works
today with no approval and is entirely adequate for 5 niches. If approval has
not arrived within 4 weeks, commit to the CSV path and stop waiting.

---

### Slice 4 — Real clusters · size L · **AMENDED, shipped 2026-08-27**

**Planned:** embeddings over YouTube titles, Reddit question titles, Trends rising
queries and KP keywords in one space; HDBSCAN per seed; centroid stored daily;
drift monitoring and weekly frozen cluster IDs; a label / merge / split review UI.

**Shipped instead:** per-video relevance. See **ADR-0018**; the short version is
that this slice's premise was removed by Slice 3 and its exit criterion was not
measurable.

The premise: this slice sat after Slice 3 because *"clustering earns its keep only
when there are multiple sources to cluster together"*. Slice 3 then found Reddit
unapproved, Trends' related-queries endpoints quota-blocked (ADR-0015) and Keyword
Planner deferred (ADR-0016). One source left, so the argument that ordered this
slice now argues against building it.

The criterion: ">90% membership overlap across consecutive days" needed a day *t−1*
that did not exist — `cluster_members` had no day column and one day of collection
had happened. Gate D was invoked on those grounds rather than on a stability number.

What the measurement found instead was a correctness bug in this layer. Membership
assigned *channels* to seeds and videos inherited their channel's cluster, so
**only 20% of the videos feeding every `supply.*` and `money.*` number were about
the niche they were filed under**. Slice 4 fixed that:

- `videos.description` rescued from `raw_records` before the nightly prune reached
  it — 13,855 recovered, 1,873 already past the point of re-fetching (ADR-0017)
- channel identity unchanged (ADR-0013); a second, separate per-video question
  added, hard-assigned with a noise flag
- a two-axis lexical scorer, calibrated against 298 hand labels on a held-out split
- `supply.*` and `money.*` moved to the on-niche pool; `openness.*` deliberately
  did not, and has regression tests saying so
- `nh cluster sample` / `import` / `calibrate` / `inspect`

**Exit, as met:** every video carries a relevance decision or a stated reason it
could not be scored (0 silently absent), and the rule has a published precision
with its base rate: **0.781 precision, 0.694 recall, 28.6% base rate** on held-out
labels. That is **below the 0.90 the plan asked for**, and it is recorded in
`reports/relevance_2026-08-27.md`, in METRICS.md beside every dependent metric, and
in a warning `nh cluster calibrate` prints. It ships because the status quo is no
filter, which is precision 0.286.

**Deferred to a later slice, with named blockers** (ADR-0018): sub-niche discovery,
embeddings, and the review UI. The blockers to clear first are `demand_terms`
resolving per seed rather than per cluster (pinned by a test), openness cohorts
already starving at seed size, and more than one day of collection.

### Slice 5 — Decision layer and Gate E readiness · size M · **AMENDED, shipped 2026-08-27**

**Planned:** Reddit + `voice.*`, remaining `supply.*`/`openness.*`, all of
`cost_risk.*`, the Postgres swap. Exit: every metric implemented or explicitly
deferred.

**Shipped instead:** the decision layer. See **ADR-0020**. The planned list
contradicts this roadmap's own risk #9 — *"calibration precedes breadth by
construction. New sources wait"* — and every group in it terminates in a NULL
scorecard column that Gate E could not backtest anyway. Two of its four sources do
not exist to be collected: nobody had ever applied for Reddit access (ADR-0021),
and primary sources resolve for 2 of 6 seeds.

Ships:
- `scorecards.stage` — a **demand-trajectory** classifier, pure and
  threshold-parameterised, with zero tuned constants (ADR-0023). It is what Slice 6
  replays, and it did not exist.
- Both demand strata carried in parallel; they rank the niches near-inverted at
  Spearman −0.70 and Gate E arbitrates (ADR-0022).
- Seed coherence: `court-cases` split, `geo` stated, `supply.geo_concentration`
  measuring the 57–67% divergence between a seed's market and its supply (ADR-0024).
- `openness.winner_age_years`; `supply.top10_concentration`;
  `supply.pressure_index`, the long-named fix for gap compression; `demand.wiki_yoy`,
  `wiki_volatility_365d`, `wiki_seasonality` — all from history already on disk.
- `nh deferrals`, which makes the exit criterion executable rather than prose.

**Exit, as met:** `nh niche show` prints a stage with its basis; two strata each
carry three years of history with a pre-registered criterion; `nh deferrals` lists
eight deferrals each with a checkable trigger; `reports/gate_e_feasibility_*.md`
answers whether Slice 6 is runnable.

**Deferred with triggers, not prose:** `voice.*` (nobody has applied), all KP money
metrics (clock expires 2026-09-24), `cost_risk.*` (2 of 6 sources),
`supply.format_mix` and `openness.rss_acceleration` (need history), the Postgres
swap (ADR-0019), and `value`/`sustainability`/`opportunity`/`ci_*`.

### Slice 6 — Calibration · size L · **GO / NO-GO**

**Goal:** find out whether any of this predicts anything.

**Status 2026-08-28: the instrument is built and green; the verdict is not in.**
All of `nh/backtest/` ships — `niches.py` (36 niches in 6 families, committed before
the data landed), `scan.py`, `select.py`, `youniverse.py`, `load.py`, `outcome.py`,
`replay.py`, `stats.py`, `report.py` — behind `nh backtest seed|scan|load|replay|score`.
The primary result, the verdict rule and the permutation scheme are fixed in
`reports/backtest_preregistration_2026-08-27.md` with an amendment log. What remains
is operator time, not design: `yt_metadata_en.jsonl.gz` is still downloading, and the
scan cannot run until it lands.

Ships:
- YouNiverse loader → the existing `channels` / `channel_snapshots` / `videos`
  tables in a **separate database file**, so no backtest row can reach the live
  corpus (ADR-0025)
- ~30 backtest niches, curated before the data arrives, because at N=6 the smallest
  detectable correlation is 0.89 and a null result would mean nothing
- `replay.py` — for each historical date, compute features bounded at that date,
  run the lifecycle classifier, compare to `outcome.growth_180d`
- `supply.views_per_new_video`, because `median_views` is NULL at every historical
  date and would otherwise take `gap` and `stage` with it
- threshold tuning on one window, validation on a window you did not tune against
- `reports/backtest_<date>.md`, with the verdict rule applied by `report.verdict`
  rather than by the writer's judgement on the day

**Dropped from this list (ADR-0025):** the Wayback CDX collector and
`historical_channel_weeks`. YouNiverse supplies historical subscriber counts for
its own channels directly; Wayback would only cover *our* channels, which is a
different and much smaller question that nothing currently asks.

**Leakage is the failure mode.** If any feature reads a row from after the decision
date, every number downstream is meaningless and will look excellent.

The rule is `observed_date <= day`, per table, **not** `at < day` as this document
said until Slice 6. Measured on `demand_snapshots`: bounding on `observed_date`
gives 31,971 rows for a 2024 decision date and bounding on `at` gives **zero**,
because Wikipedia was backfilled and three years of described days sit behind four
hours of fetch time. ADR-0015 already established that `observed_date` carries two
meanings; `at` is provenance, not a filter.

Slice 6 also found the feature layer was day-*parameterised* but not day-*bounded*:
time-series reads were bounded, mutable entity reads were not, and two metrics
accepted `day` and never read it. `tests/test_features_leakage.py` is the standing
guard, parametrised over the metric registry so it covers every metric added later.
Budget real time for auditing this, not for building it.

**Exit — AMENDED by the Slice 5 feasibility spike
(`reports/gate_e_feasibility_2026-08-27.md`):** rank correlation between the score
at date *t* and realised growth over the next 90/180 days, with a permutation-test
p-value, over a population described as survivorship-limited — plus a written
analysis of where the ranking goes wrong.

**The null permutes niche labels globally**, one permutation per replication applied
to every date — not within each date. Consecutive weekly decision dates share 179 of
their 180 outcome days, so a within-date null treats them as independent replicates
and shrinks the standard error by `sqrt(D)`. Measured: four weekly copies of a single
date with rho = 0.486 return p = 0.034 under a within-date null. The effective sample
size is the number of *niches*, which is what the power table is computed on; the
count of quasi-independent windows is reported as a diagnostic and never as an N.

**A null and an underpowered run are different verdicts.** Below 20 surviving niches
the smallest detectable rho exceeds any effect worth having, so `report.verdict`
returns INCONCLUSIVE — UNDERPOWERED rather than FAIL. Only a null licenses abandoning
the thesis.

Precision and recall for a binary "emerging" is **not obtainable**. YouNiverse is
"all channels with >10k subscribers and >10 videos" as of 2019-10-27, so every
channel in it succeeded and a channel that stayed small was never crawled. The base
rate of "emerged" on that population is ~1 by construction, and no sampling
recovers absent rows. `docs/METRICS.md` already specifies rank correlation for
`gap`; that framing wins.

`outcome.growth_180d` is defined in METRICS.md, written before any replay code
exists so it cannot be chosen after seeing results.

**Also required, and it substitutes for a check that was deferred:** run the
backtest at **three relevance thresholds** and report whether the rank correlation
survives. Slice 4 stores the relevance *score* and applies the cut at read time, so
this is a query rather than a re-run.

The niches Slice 6 constructs from YouNiverse are defined by a relevance rule whose
held-out precision (0.781) was measured against labels written by the same system
that wrote the lexicon. A second model agreed at kappa 0.943 — which shows the
criterion is unambiguous, and cannot detect a bias two language models share. The
independent human pass is deferred to before Slice 7 (`nh deferrals`).

A correlation stable across thresholds means the labelling bias does not reach the
conclusion. A correlation that moves with the threshold means the relevance rule is
producing the result, and the human check becomes urgent before anything here is
believed.

**`reports/backtest_*.md` must state that its niches were defined by an unvalidated
rule**, so a null result is not over-read: "the thesis is dead" and "the features
were wrong" look identical from the outside, and only that sentence keeps them
apart.

**Gate E — the real one.** If the rank correlation is indistinguishable from zero — or is distinguishable only before controlling for niche size:
**do not build the dashboard.** Choose one:
- return to Slice 5 with what the failure analysis taught you, or
- narrow the product claim from "predicts emerging niches" to "surfaces evidence
  for a human to judge" — a defensible product, but a different UI and a
  different promise.

Building a dashboard on an uncalibrated score is how this project fails while
appearing to succeed.

### Gate E FIRED, 2026-08-28 — **FAIL**

```
rho = 0.091   permutation p = 0.4988   95% CI -0.167 to 0.327
29 of 36 niches   detectable rho at that N = 0.378
```

A **null, not an underpowered run**: 29 niches clears the pre-registered floor of 20,
so the pre-registration's own rule says this verdict may be acted on. Full result and
failure analysis in `reports/backtest_2026-08-28.md`.

The consolations were checked before the null was accepted and none survived. `gap`
is not flat (sd 0.402 over 4,558 scorecards, 2.6% at exactly zero). The outcome is
not flat (median within-date sd 0.079, range 0.379; a representative date spans
0.082–0.530 across 29 niches) — there was ample variance to rank. Nothing hides under
size (size-vs-growth −0.019; partialling it out moves 0.091 → 0.085). And neither
input predicts alone: demand +0.049 (p 0.73), supply −0.073 (p 0.56), so the failure
is not in how the two are combined.

**The branch taken: narrow the claim**, not return to Slice 5's feature work. The
reason is in the data — **zero of 4,517 niche-dates show negative growth.** YouNiverse
holds only channels that had already crossed 10k subscribers, so what was tested is
relative growth *among successes*, and the corpus cannot express emergence at all. A
better feature computed against it would be a better answer to the wrong question.
Reviving the predictive claim needs a corpus containing channels that failed — a
different instrument, not a different threshold.

This does not license re-running the primary with another stratum, threshold, horizon
or supply proxy; `reports/backtest_preregistration_2026-08-27.md` voids on exactly
that.

---

### Slice 7 — Evidence surface · size L · **RESCOPED by ADR-0052, ready to build**

**Goal:** every number this pipeline computes reaches the rows it came from, in three
clicks — and no number the scorer decided reaches a reader before the scorer is validated.

**2026-08-28:** Gate E returned FAIL, so "a radar that predicts emerging niches" is
retired. **2026-08-31 (ADR-0052):** the rest of this entry is rewritten, because the
version standing here after the FAIL still listed "radar scatter" as the first thing it
shipped and still began its exit criterion with "radar →". Nobody edited the list after
writing the note. That is the defect this repo keeps finding, and it survived in the
roadmap's own text for three days.

What survives the null is the evidence layer, because none of it claims to predict. What
does not survive is any ranked surface: `scorecards.opportunity`'s weights were to be a
Gate E *output*, and there is no calibration to derive them from.

**The load-bearing constraint, not a detail.** ADR-0045 fires the exposition-labelling
requirement when a score is CITED, and implemented that as a query on `value` /
`sustainability` / `opportunity` — columns Gate E holds NULL, permanently, because Gate E
failed. So the trigger **cannot fire**, while `gap`, `supply`, `demand`, `stage` and
`openness` are non-NULL for all ten unvalidated exposition clusters. Built as previously
written, this slice would have put them in front of a person on day one with the register
green. See ADR-0052 for the gate that resolves it.

Ships:
- `nh/api/` — a pure read layer, no web imports, extending the `nh/jobs/niche.py` pattern:
  `queries.py` (niche list, niche view, demand series, channel table, source feed, metric
  history), `drilldown.py` (every registered metric → the query returning its input rows),
  `gates.py` (`EXPOSITION_VALIDATED`, and the scorer-dependence classification derived by
  execution), `basis.py` (ADR-0035's population per metric — this discharges the render
  half of the `geo_basis` deferral, whose trigger fired when Slice 9 shipped)
- `nh/web/` — Streamlit: niche list (**alphabetical, never sorted by a score**), niche page
  (metric table with `value · confidence · inputs_n · definition · basis`, demand series,
  channel table, source feed), alerts feed, reports viewer
- `nh/scoring/rules.py` — Rules 1–3 from INSIGHT_RULES.md, as a phase after scoring,
  writing `alerts` with `insert_ignore`. Three rules, not ten: the page now records which
  are refused and why.

**Not in this slice** (ADR-0052): the radar scatter · any rendering of `scorecards` ·
FastAPI (a module boundary already gives replaceability; a second process for one local
operator does not) · the question bank and topic queue (`voice.*` has no source) · the
cost model (defined nowhere) · Rule 7 (refused on three independent grounds).

**Exit:** niche list → niche page → metric drill-down → input rows or source document in
≤ 3 clicks · every registered metric has a drilldown returning a **non-empty** row set on a
synthetic corpus · every registered metric is classified gated-or-not by a test that fails
on an unclassified one · each shipped rule has a synthetic test that fires it and one that
does not.

---

### Slice 8 — Hardening and handover · size M

**Goal:** it runs without you.

Ships:
- deploy off the laptop; managed Postgres; IaC
- secret manager with rotation
- automated monthly restore drill
- SLOs + paging; quota alarms with headroom projection
- daily digest of alerts
- monthly maintenance runbook: re-record fixtures, re-check ToS, re-run backtest

**Exit:** all eight production criteria met and evidenced.

---

### Slice 9 — Keyword Planner consumption · size M · **SHIPPED 2026-08-31**

*Recorded 2026-08-28, shipped 2026-08-31. `METRICS` went 17 → 22 and all five KP metrics
return non-NULL for all ten clusters; the doc-rot items below are fixed and both KP
deferrals now carry evidence-shaped triggers. This header read "PLANNED, not started"
until 2026-08-31 — three days after the work landed. The plan below is kept as the record
of what was decided, not as a to-do list.*

**Ships five metrics**, registered in `nh/features/run.py::METRICS` (17 → 22):
`demand.total_monthly_searches`, `money.priced_share`, `money.competition_index_mean`,
`money.vw_cpc`, `money.median_bid_high` — behind a shared
`inputs.keyword_planner_rows(session, cluster_id, day, geo)` returning mapped terms and
the latest reading per term as of `day` **in the requested market**. The join is
`(term, lang)` against seed terms with `geo` resolved against `keyword_metrics.geo`
(ADR-0038, decided 2026-08-29): a seed term is geo-independent curation, and the market
a number was measured in is a property of the observation. `geo` must be an explicit
argument with no default — a defaulted geo silently picks a market, and
`reports/geo_value_2026-08-28.md` measured market choice as a real reordering. Two more
constraints from the same slice's verification: **sentinel bids are unpriced** —
64,083.40 and 6,408.34 COP are imputed round-USD defaults on 8 of 107 priced rows (see
SOURCES.md), and `median_bid_high`/`vw_cpc` must exclude them **per cell, not per row** —
`humanism` GB carries a sentinel `bid_low` beside a real `bid_high`, so a per-row rule
would discard a genuine measurement — or one fake $16 dominates a 1–6-keyword niche.

**Constraints that decide the implementation:**

- `tests/test_features_leakage.py` parametrises over `METRICS`, so five metrics add
  **fifteen cases that must pass with no new test written**: bound on
  `keyword_metrics.observed_date <= day`; NULL ten years before the data; never a
  confident zero. `priced_share` and `competition_index_mean` are the risky pair — a
  share whose denominator is "keywords we have rows for" happily returns `0.0` before
  any export existed. The denominator must be day-bounded, and an empty bounded set must
  return `empty()`.
- **The leakage fixture holds no `keyword_metrics` rows**, so all five would hit
  `empty()` and pass vacuously. It must gain rows. This trap has bitten twice already
  (`geo_concentration`, `on_niche_join`).
- **Do not reuse `money.CONFIDENCE_N = 100`** — it is documented as per-video, and the
  export had 30 keywords, so reusing it pins confidence near 0.30 forever. Use
  `KP_ADEQUATE_KEYWORDS = 30`. `money.WINDOW_DAYS = 90` is a video-publication window
  and is irrelevant to a twelve-month keyword period.
- **`_provenance` must surface `currency`** before these ship — see ADR-0031; this is a
  renderer bug, not a caveat.
- `nh/jobs/status.py` gains `KP_STALE_DAYS = 70` on `MAX(KeywordMetric.observed_date)`,
  into `warnings`, not `problems` — the export is refreshed by hand, monthly.
- Both KP deferrals claim a blocker (`NH_GADS_CUSTOMER_ID empty`) that stopped being the
  blocker when the CSV path shipped, and a superseded `2026-09-24` date trigger. Replace
  with evidence-shaped triggers: populated monthly columns; exports from ≥2 geos.
- Doc rot to fix in the same PR: `docs/METRICS.md:44` "Eighteen metrics",
  `tests/test_features_leakage.py:16` "all sixteen", plus five METRICS.md entries.

**Multi-geo: RESOLVED 2026-08-29 by ADR-0038 — option (b).** A `geo=GB` export beside
the US one had the ingest reporting **96/162 matched**, because `seed_terms` rows for
`keyword_planner` carried `geo='US'` and the match keyed on `(keyword, geo, lang)`. The
conflation: a seed says *this niche cares about this keyword* (geo-independent), while
`geo` says *which export these numbers came from* (a property of the observation).
Option (a) — seed rows per geo, 66×N — was rejected as duplicated curation that misses
every new market until re-seeded. Shipped: KP seed terms back to `geo=''`, the ingest
match report on `(keyword, lang)` with per-geo coverage lines, and the loader contract
above. Measured after the re-seed: **162/162** stored rows match a seed term.
`reports/geo_value_2026-08-28.md` measured why the explicit geo argument matters: the
value ranking of the eleven **reorders between US and GB**, so a features layer that can
only see one geo silently picks a market.

**Explicitly not in this slice:** the eleven-domain expansion; `kp_trend_last3_vs_first3`
(the twelve monthly columns are 0/360, entirely empty) and `tier1_cpc_ratio` (needs ≥2
geos); any FX conversion; anything ranked — ADR-0029's prohibition stands.

### Slice 11 — The domain pivot · size L · **SHIPPED 2026-08-31, as TEN domains**

*Recorded 2026-08-28 as eleven, shipped as ten. `landmark-court-cases` was already retired
(ADR-0028); of the eleven planned, `philosophy-of-science` was retired on the day it
shipped (ADR-0044, an editorial choice), so `nh/seeds.py` carries ten active domains at
6,000 of 9,500 quota units. ADR-0038 through ADR-0051 are this slice. Read `nh/seeds.py`,
not the table below, for what is active. Its validation — a human labelling two drawn
samples — is the open task, and one of the two has a 2026-09-14 deadline (ADR-0050).*

| Domain | Subreddits (verified to exist, 2026-08-28) |
|---|---|
| Philosophy of science | r/PhilosophyofScience, r/philosophy, r/epistemology, r/askphilosophy |
| Esoterism & spirituality | r/occult, r/EsotericOccult, r/mysticism, r/esotericart |
| Metaphysical battles (clashes between worldviews) | r/Metaphysics, r/PhilosophyofMind, r/PhilosophyofReligion |
| Logic, linguistics, gnoseology | r/linguistics, r/epistemology, r/askphilosophy |
| History of ideas | r/HistoryofIdeas, r/philosophy |
| Anthropocene / anthropology | r/Anthropology, r/AskAnthropology, r/CulturalAnthro |
| Macro economy | r/Economics, r/economy, r/EmergingMarket |
| Trading | r/Daytrading, r/algotrading, r/optionstrading, r/FuturesTrading |
| AI & software | r/MachineLearning, r/artificial, r/agi, r/learnmachinelearning |
| Biohacking | r/Biohackers, r/Biohacking, r/LongevityBiohacking |
| Geopolitics | r/geopolitics, r/ProfessorGeopolitics, r/GeopoliticsIndia |

`r/logic` does not exist; r/askphilosophy and r/linguistics are the substitutes.
"Metaphysical battles" has no direct community, which is itself a reachability signal.

**Why this is a slice and not a seed edit.** Three costs, none of them optional:

1. **Seeds without lexicons are inert.** ADR-0028 established it: the court-cases
   successors have seeds and demand terms but no lexicon, so they can never gain
   members and stay retired. Eleven seeds means eleven lexicons.
2. **Lexicons re-weight their whole family.** `lexicon.weights()` scores a term `1/k`
   across the family; its own docstring measures `crash` going 1.00 → 0.032 when 30
   niches were added. Adding eleven dilutes the live five, moves every stored
   `supply.*` number, and needs a `LEXICON_VERSION` bump plus an ADR saying
   pre-pivot relevance scores are not comparable to post-pivot ones.
3. **Nine test files** reference the current slugs, including `test_lexicon_families.py`,
   which pins golden weights precisely so this cannot happen silently.

**The design risk was measured on 2026-08-28, and it is not real.** The concern was
that five philosophy-adjacent domains would share vocabulary heavily, so `1/k` would
dilute exactly the terms meant to separate them. A draft family of eleven lexicons
(~33 terms each) was written and scored. It does not happen:

| family | unique terms (weight 1.0) | mean weight | worst collision |
|---|---|---|---|
| live five (baseline) | min 38, median 40 | 0.975–1.000 | `collapse` = 0.500 |
| draft eleven | min 30, median 32 | 0.956–1.000 | `consciousness` = 0.500 |

The philosophy domains separate as cleanly as the disaster domains, because their
discriminating vocabulary is *technical* — `falsifiability`, `gettier`, `hermeticism`,
`panpsychism`, `incommensurability` — and technical terms do not collide. Only eight
terms collide anywhere in the family, each between exactly two lexicons.

**Nor does the pivot have to disturb the live five.** Scoring the combined 16-lexicon
family moved **zero of six** golden weights, and across *every* live term only two
moved at all: `pipeline` (engineering-failures vs geopolitics) and `evidence`
(true-crime-trials vs philosophy-of-science). Substituting `energy pipeline` and
`empirical evidence` in the draft makes coexistence **exactly lossless** — measured, 0
live weights move. So the eleven lexicons can be added without a `LEXICON_VERSION`
break and without invalidating a single stored `supply.*` number.

That removes the largest cost this slice was thought to carry. What remains is real but
ordinary: eleven lexicons and eleven seeds to write, wikipedia demand terms per niche
(article titles must be verified to exist, or the collector 404s), and the golden test
plus eight other test files to update. The draft family lives in the session scratchpad
and should be re-derived rather than trusted, since it was never committed.

**Quota is not the constraint, and the forced retirement was an artifact.** 11 active
*plus* the current five is 9,600 against a 9,500 budget — but nothing requires activating
eleven. Measured 2026-08-28: **2 finalists cost 4,200, 3 cost 4,800, 4 cost 5,400**, all
beside the live five, with 4,100+ units of headroom. Activating only the niches the
operator will actually make videos about leaves the disaster niches collecting, so the
compounding snapshot history is not sacrificed to a constraint that only bites at eleven.


### Slice 10 — Trends seed expansion · size S–M · **PLANNED, not started**

*Recorded 2026-08-28 on ADR-0032, which reversed the "technical wall" premise ADR-0029
had written against.*

`related_topics` is reachable via the referer header and supplies **sub-niche
vocabulary**. Wire `expand_seeds()` to feed candidate terms into clustering:

- **Prefer `related_topics` over `related_queries`** — its `type` column drops the
  `Online game` homonyms that dominate `shipwreck`'s rising list. Filter to `Topic`.
- **`TRENDS_RELATED_GAP = 6.0` seconds minimum**, not the 2.5s in
  `.claude/rules/sources.md` — that figure was set for `interest_over_time`, and at 3s
  the third consecutive `related_*` call failed. Update the rules table when this lands.
- **Cache aggressively.** The whole expansion is ~66 calls for 11 domains × ~6 terms,
  ≈7 minutes, and the vocabulary does not churn daily.
- **The referer header is a workaround, not a contract.** Drop it when a bare
  `related_queries("shipwreck")` returns rows; treat its disappearance as a source
  outage, not a crash — the collection-boundary `except` already covers this.
- **It may not produce a level.** Trends normalises against the term's own peak, so a
  narrow term's baseline quantises away (`bridge collapse`: median 0, p90 1, 201/262
  zeros). Candidate terms get priced by the Keyword Planner export, which is itself
  bucketed to 50/500/5000/50000 — order-of-magnitude is the best level any current
  source gives a sub-niche, and nothing may present it as finer.
- Untested and worth one measurement first: whether a **narrow** term's topic mid beats
  its string. The two tested are mid-breadth and disagreed; `bridge collapse` hit the
  rate limit before it could be tested.

## Timeline

Rough, one person part-time. S1→S3 is predictable; S4 onward is not.

```
S1  First light        ██                      week 1
S2  Walking skeleton     ██                    week 2
S3  Demand online          ███                 weeks 3-4      ← Gate C (external)
S4  Relevance (amended)       ███              week 5         ← Gate D invoked, ADR-0018
S5  Full features                  ████        weeks 8-9
S6  Calibration                        ████    weeks 10-11    ← GATE E: go/no-go
S7  Product surface                        ███ weeks 12-13
S8  Hardening                                ██ week 14
```

Three to four months part-time to production. The honest variance is ±6 weeks,
concentrated in Slice 4 and in approvals you do not control.

---

## Risk register

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **Backtest shows no signal** | Product thesis fails | Gate E exists precisely so this is discovered before the UI is built, not after. Reposition rather than rationalize. |
| 2 | Cron dies silently | Permanent history loss | Dead-man switch from night 1. This is why alerting is S1, not S8. |
| 3 | Cluster instability | Metrics non-comparable over time | Store centroid daily, alert on drift, freeze cluster IDs weekly. Gate D allows shipping without sub-niches. |
| 4 | Reddit approval never arrives | `voice.*` unavailable | Optional inputs with a confidence penalty, never required inputs. |
| 5 | Google Ads access denied | No absolute volumes or CPC | UI CSV path, already documented, adequate at 5 niches. |
| 6 | Trends blocks the endpoint | Demand *shape* lost | Aggressive caching; KP monthly volumes give a coarser substitute; proxy pool. |
| 7 | RPM model overfits sparse disclosures | Fabricated confidence in dollars | n≥5 required before any figure is shown; always a CI, never a point estimate. |
| 8 | YouTube quota policy changes | Discovery degrades | Collectors are independent; the nightly skips a failed source and lowers confidence rather than failing. |
| 9 | Scope creep into more sources before calibration | Breadth on an uncalibrated core | Calibration (S6) precedes breadth by construction. New sources wait. |
| 10 | Leakage in the backtest | A precision number that is a lie | Explicit audit task inside S6; features read only rows with `at` < decision date. |

---

## Standing rules across every slice

- One branch per task; `reviewer` before merge; `data-qa` after any job run.
- A metric starts in `docs/METRICS.md`, then code, then a test — no exceptions.
- Tests never touch the network. Fixtures are recorded from real responses.
- Snapshots are append-only. `AppendOnlyViolation` is a bug in your code, not an
  obstacle to route around.
- Absent is NULL. A fabricated zero is undetectable a week later.
- Update `docs/` in the same PR when a source, metric or decision changes.
- Add an ADR to change a decision; do not relitigate one.
