# Channel reach pre-registration — a 14-day test at channel grain

**Written 2026-09-15, before any outcome exists.** The earliest outcome reading this test
uses is a 2026-09-02 upload at age 14, which the nightly first collects on 2026-09-16. At
the time of writing no such reading exists, no outcome has been computed for any channel,
and no correlation involving an outcome has been run. The frozen cohort below was computed
from rows dated on or before each decision date.

This exists because ADR-0029 lifts the prohibition on anything ranked only when *"a new
pre-registered test passes on the new grain"*, and the operator will not wait months. Ten
live niches cannot be that grain: at n = 10 the repository's power rule
(`2/sqrt(n−1)`) gives a detectable rho of 0.667, and `report.verdict` returns
INCONCLUSIVE below 20 units. Channels can: the small channels this pipeline discovers,
snapshotted nightly, include the channels that fail, which YouNiverse never did.

**What this test cannot do, before anything else.** It makes no claim about any niche.
Every comparison is within a cluster; the cross-cluster question has n = 10 and is not
asked. It does not touch `scorecards`, `gap`, `nh/api/gates.py::scorecard_citable`, or
Gate E's null. A PASS licenses a ranked list of **channels** under its own gate constant,
nothing more.

## State of the data at writing

| | |
|---|---|
| Decision dates | 2026-09-01, 2026-09-08 |
| Openness cohort at t | 497 channels (09-01), 981 (09-08) — `inputs.cohort`, from the registered freeze |
| Frozen rows | 1,473 channel-dates, 977 distinct channels |
| Absent at freeze | 5 channel-dates (1 on 09-01, 4 on 09-08): a zero median has no ratio and no log |
| Ballast pin | cohort identical under `pinned_ballast(True)` and `(False)` (checked on ai-and-software at 09-08, 162 channels); the read is pinned `False` |
| Frozen predictors (all rows) | breakout_magnitude p10/p50/p90 0.525 / 1.46 / 3.135; views_per_sub 0.032 / 0.448 / 4.531; catalogue_age 18 / 31.5 / 150 days; n_elig 6 / 10 / 15 |
| Censoring before ADR-0059 | on 2026-09-14, 2,359 of 5,985 small-member videos aged 14-17 had any reading (39.4%) |
| Watchlist (ADR-0059) | re-reads those videos nightly from its merge; must be live by 2026-09-19 for the first date's uploads |

The frozen rows are `reports/channel_reach_cohort_draw_key_2026-09-15.jsonl`,
sha256 `1cb64d0acf07b50d5594389812c7725851adaabf3e38da2a0b6df2d28786e5f2`, produced by `nh prospective channel-reach freeze` at commit
`6c64c5f4082068a37ff783e20ef9046745957b9a`. Every read recomputes the hash and refuses to proceed on a mismatch.

## The hypotheses, in the order they are tested

| Step | Predictor at t | Controls | Claim | Why this one |
|---|---|---|---|---|
| **T0** instrument | `ln_median` | none | the outcome tracks a channel's own level | If it does not, the outcome is broken, and nothing below it may be read. |
| **H1** | `channel.views_per_sub` | ln_subs, catalogue_age, n_elig | a small channel outperforming its subscriber count keeps doing so at 14 days | The one question this data answers with power. Narrow, and stated as narrow. |
| **H2**, only if H1 passes | `channel.breakout_magnitude` | ln_subs, catalogue_age, n_elig | a channel's best past video predicts its next uploads beyond its size | The original question. Tested behind the gate so it costs no alpha. |

Outcome, for every step: `outcome.next_reach_14d` — mean over the channel's long-form
uploads on civil days t+1..t+7 of ln(1 + views at the smallest age in [14, 17] with a
non-NULL reading, max across sources on that day). No upload, or no reading → absent.
Definitions are in `docs/METRICS.md`, fixed before any predictor distribution was
computed.

**Why `ln_median` is a control in no hypothesis.** It is estimated from the same videos as
the breakout ratio's denominator; partialling it on its own noise manufactures a
correlation. Simulated at dispersion fitted to the frozen cohort, the design first approved
for this test — breakout with ln_median as a control — read rho +0.107 under no effect and
passed in 40% of seeds. That design is retired. The evidence is in the amendment log.

## The statistic

Per decision date: rank every variable within its cluster, scaled to (0, 1) by
`rank / (n_cluster + 1)` so clusters of different size pool; OLS-residualise the predictor's
ranks and the outcome's ranks on the control ranks; Pearson of the residuals, pooled across
clusters. The step's rho is the mean over the two dates. T0 has no controls, so it is the
pooled within-cluster Spearman.

Null: channel labels permuted **within cluster**, one permutation per replication applied
to both dates; outcomes move, predictor and controls stay with their channel; a channel
whose partner is absent at a date is dropped, never re-matched. 10,000 draws, seed
20260916, two-sided, `(extreme + 1) / (completed draws + 1)`, where a draw counts only if at
least one date yields a correlation.

Effect floor, H1 and H2: **top-decile lift ≥ 1.25** — exp of the mean residual of the
outcome, from OLS on the controls plus cluster and date fixed effects, over channels in the
top within-(date, cluster) decile of the predictor — at least one channel, ties broken by
channel id. A ranked list is read from the top, and
the lift is what its reader gets. The floor is a judgement, named as one.

Clusters with fewer than 10 outcomes at a date drop from that date.

## The verdict rule, stated before the number

In this order, and the order is part of the registration:

1. **INTERIM** (the 2026-09-25 read) — reported with the same code, and never a verdict.
2. **INCONCLUSIVE — UNDERPOWERED** if fewer than 200 distinct channels have an outcome, or
   fewer than 5 clusters reach 20 outcomes at some date. H2 is NOT TESTED.
3. **INCONCLUSIVE — INSTRUMENT** if T0's rho is not positive or its p is not below 0.05.
   H2 is NOT TESTED.
4. **H1 FAIL** if its rho ≤ 0, or p ≥ 0.05, or lift < 1.25. H2 is NOT TESTED: the gate is closed.
5. **H1 PASS**, and then H2 is judged on the same three conditions: **H2 PASS** or **H2 FAIL**.

Fixed-sequence gatekeeping holds the chance of any false PASS at 0.05 without splitting
it: H2 is never examined unless H1 has already rejected at full alpha. A negative rho is a
result and is reported. There is no branch where anything is re-run with other settings.

## Power, stated before the result

Expected outcome n, from the design pass: ~250 channels with an outcome at 09-01 and ~470
at 09-08, ~720 channel-dates, ~600-650 distinct channels — higher once the watchlist
restores the censored readings. At 720 the two-sided critical rho is about 0.073; by the
repository's `2/sqrt(n−1)` it is 0.075.

Simulated in a model calibrated to the frozen cohort (sigma 1.0, level sd 1.84, subscriber
noise sd 1.90), 40 seeds:

| world | T0 passes | H1 passes | H2 passes behind the gate |
|---|---|---|---|
| no level persistence, no effect | 2% | 2% | 0% |
| level persists, no breakout effect | 100% | 100% | 0% |
| level persists, breakout effect 1.0 | 100% | 100% | 5% |
| level persists, breakout effect 2.0 | 100% | 100% | 5% |

**So, before the result: H1 is expected to pass if channel reach persists at all, and H2 is
expected to fail even if breakouts do persist.** An H2 FAIL is weak evidence of absence. An
H2 PASS would be strong evidence, because the model says it is hard to get by chance or by
construction. The report states H2's registered low power among its caveats, before any number.

## The caveats that lead the report

1. **No niche claim.** Stated first, because the product's history is a niche ranking and
   this test cannot supply one.
2. **Frozen membership.** `cluster_members` has no history; the cohort's cluster
   assignment is as of 2026-09-15, not as a nightly at t would have stored it. Measured
   churn is small (0 channels left the cohort between 09-01 and 09-08) and unmeasurable in
   general.
3. **Censoring.** Before the watchlist, six in ten 14-17-day readings were missing, and
   missing non-randomly by upload rate. Nights the watchlist did not run are recorded in the
   commit that adds the report — the report itself is rendered once, by code.
4. **Outcome survivorship.** Videos deleted before day 14, failing feeds, and any four-night
   collection gap remove readings non-randomly.
5. **H1 is narrow.** Given subscribers, it is close to "past views predict future views".
6. **H2 cannot separate "a breakout persists" from "the channel is trending".**

## What each result licenses

- **H1 PASS**: a ranked list of small channels by `views_per_sub`, gated by
  `CHANNEL_REACH_H1_VALIDATED: bool | None` in `nh/api/gates.py` on the
  `EXPOSITION_VALIDATED` pattern — a constant a person sets in the commit that writes the
  result, never a file or an environment variable. The list surface is a later slice.
- **H2 PASS**: ranking by `breakout_magnitude` too, under `CHANNEL_REACH_H2_VALIDATED`.
- **Anything else**: no ranked surface. The niche list stays alphabetical.

## Reads

| Date | What | Status |
|---|---|---|
| 2026-09-25, after the nightly | t = 09-01 only (uploads through 09-08 read by 09-25) | **INTERIM**, cannot pass |
| **2026-10-02, after the nightly** | both dates (09-15 uploads read by 10-02) | **the verdict** |

The 90-day channel-emergence panel is **not** registered here. Its outcome is subscriber
growth, which T0's "tracks its own level" cannot instrument, so it needs its own design. It
must be registered before 2026-11-30, the first t+90 — still before its outcome exists.

## What would make this pre-registration void

If any of the following happens, the read is exploratory and the report says so instead of
stating a verdict:

- Any step is computed more than once with different code.
- The frozen file's sha256 does not match the one above.
- A predictor, control, outcome definition, floor, seed, draw count, cluster set or step
  order is changed after any outcome reading has been joined to any frozen row.
- Anything at all is changed after the 2026-09-25 interim read.
- An outcome is computed for any decision date before its scheduled read.

## Amendment log

Every change after the first commit, with the date and the state of the data. An amendment
made after an outcome is joined voids the registration.

**2026-09-15 — changes from the design approved earlier the same day. State of the data:
no outcome reading exists for any upload in either window.**

- *The approved primary is retired.* It was breakout_magnitude with ln_median among the
  controls. A falsification simulation at dispersion fitted to the frozen predictors showed
  it passing by construction: rho +0.107 and a 40% PASS rate under no effect. An earlier
  simulation at half the real dispersion had shown the bias as +0.011; that one was
  miscalibrated, and its result is superseded, not averaged in.
- *The unbiased alternatives were measured before one was chosen.* Splitting the videos
  removed the bias and the power (3% at a strong effect). Dropping ln_median removed the
  bias and kept a little power (significant in 3-13% of 30 seeds and past the floor in 3-10%;
5% in the 40-seed gated ladder). H2 uses the latter.
- *The operator chose the gated pair* over registering the low-power breakout test alone
  and over redesigning for about a week: H1 on views_per_sub, H2 behind it, T0 as the
  instrument.
- *The outcome reading was tightened* to a non-NULL views snapshot, so a NULL cannot
  become the smallest day and turn a real later reading into an absence.
- *Dates.* Registered 2026-09-15 rather than the planned 09-16/09-17, so it precedes every
  outcome reading. The 90-day panel moves to its own registration.

**Direction.** Every change makes a false PASS harder, not easier.
