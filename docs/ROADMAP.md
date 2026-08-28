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
| 4 | **Calibrated** — a published precision figure with its base rate and known failure modes | `reports/backtest_*.md` |
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

Ships:
- YouNiverse loader → `historical_channel_weeks`
- Wayback CDX collector → historical subscriber counts for current top channels
- `replay.py` — for each historical date, compute features from rows whose `at`
  precedes it, run the lifecycle classifier, compare to what happened at 90 and
  180 days
- threshold tuning on one window, validation on a window you did not tune against
- `reports/backtest_<date>.md`

**Leakage is the failure mode.** If any feature reads a snapshot from after the
decision date, every number downstream is meaningless and will look excellent.
Budget real time for auditing this, not for building it.

**Exit — AMENDED by the Slice 5 feasibility spike
(`reports/gate_e_feasibility_2026-08-27.md`):** rank correlation between the score
at date *t* and realised growth over the next 90/180 days, with a permutation-test
p-value, over a population described as survivorship-limited — plus a written
analysis of where the ranking goes wrong.

Precision and recall for a binary "emerging" is **not obtainable**. YouNiverse is
"all channels with >10k subscribers and >10 videos" as of 2019-10-27, so every
channel in it succeeded and a channel that stayed small was never crawled. The base
rate of "emerged" on that population is ~1 by construction, and no sampling
recovers absent rows. `docs/METRICS.md` already specifies rank correlation for
`gap`; that framing wins.

`outcome.growth_180d` is defined in METRICS.md, written before any replay code
exists so it cannot be chosen after seeing results.

**Gate E — the real one.** If precision is at or near the base rate:
**do not build the dashboard.** Choose one:
- return to Slice 5 with what the failure analysis taught you, or
- narrow the product claim from "predicts emerging niches" to "surfaces evidence
  for a human to judge" — a defensible product, but a different UI and a
  different promise.

Building a dashboard on an uncalibrated score is how this project fails while
appearing to succeed.

---

### Slice 7 — Product surface · size L

**Goal:** three clicks from radar to a source document.

Ships:
- FastAPI read layer (so the front end is replaceable)
- Streamlit v1: radar scatter · niche page (scorecard, overlaid demand series,
  cohort chart, channel map, question bank, source feed, topic queue) · alerts
  feed · backtest report viewer · cost model
- `nh/scoring/rules.py` — the insight rules from INSIGHT_RULES.md as predicates
  emitting `alerts` rows with evidence attached

**Exit:** radar → niche → topic queue → source document in three clicks · every
displayed number reaches its input rows · each rule has a synthetic test that
fires it and one that does not.

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
