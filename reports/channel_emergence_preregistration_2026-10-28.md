# Pre-registration — channel emergence, on a cohort large enough to measure

**Registered 2026-10-28.** The cohort was frozen the same day, before any outcome for its
decision date can exist: the window opens **2027-01-26** and the verdict reads
**2027-02-03**. Nothing in this document may change after it is committed.

This replaces `reports/channel_emergence_preregistration_2026-10-22.md`, which was **void**
one day after registering (ADR-0070): it reused ADR-0060's cohort, whose median member has
192 subscribers and whose registered top decile's median has **fifteen**, so its
`lift >= 1.15` bar amounted to **+2.2 subscribers**. The failure was not the threshold. It was
testing subscriber growth on channels too small for subscriber growth to mean anything.

**It is not a niche test.** ADR-0068 established that a cross-sectional niche-grain test
cannot be passed at ten clusters — critical rho 0.636, 80%-power effect 0.808. Cluster enters
only as the stratum ranks are taken within.

## The claim

**H1e.** Among channels with a real audience, one whose recent videos outperform its
subscriber base at *t* gains more subscribers over the next 90 days than its peers in the same
cluster, holding size, catalogue age and eligible-video count.

ADR-0060's H1 established that `views_per_sub` predicts **14-day reach** (rho +0.470). This
asks whether that attention converts to **audience** — persistence against conversion.

## The cohort, frozen today

| | |
|---|---|
| file | `reports/channel_emergence_cohort_draw_key_2026-10-28.jsonl` |
| sha256 | `ed466f9bfd9845a5a544933e94811140e7f75d68ba4417b7b6205ded78e80243` |
| rows | **1,931** channels, one decision date |
| clusters | **10** |
| subscriber floor | **500** (`COHORT_MIN_SUBS`) |
| subscribers | min 500, p10 673, **p50 1,920**, p90 7,358, max 10,000 |
| **top decile of `views_per_sub`, median subs** | **1,480** |

The last row is the number this test exists because of. On the voided cohort it was **15**; a
relative bar there was unfalsifiable in practice. At 1,480, a 1.25 lift is **+370
subscribers**.

**The floor was chosen inside a measured feasible range, not at the edge of one.** Measured
2026-10-28 before choosing: at ≥250 the population is 2,695 channels, at ≥500 it is 2,141, at
≥1,000 it is 1,623, all across ten clusters and all far above the 200/5 floors. 500 is the
point where the absolute arithmetic works without narrowing the population unnecessarily.

**Predictors and controls are computed by `channel_reach.freeze_date`, unchanged** — the same
code that produced the cohort H1 was measured on. The floor is a *selection* on those rows, so
there is no second definition of `views_per_sub` to keep honest.

**One decision date, deliberately.** ADR-0060 used two and its reports then described
"agreement across two cohorts" as independent corroboration; that overstated it, because the
two dates shared roughly half their channels. One date cannot invite the error.

## Predictor, controls, outcome

| | |
|---|---|
| Predictor | `views_per_sub` at *t*, as frozen |
| Controls | `ln_subs`, `catalogue_age`, `n_elig`, as frozen |
| Outcome | `ln(subs_r / subs_t)` |

`subs_r` = the reading on the **smallest** `observed_date` in `[t+90, t+97]` carrying a
non-NULL `subs`, taking `MAX(subs)` across sources that date. `subs_t` = the frozen `ln_subs`.
Absent if no reading lands — **never zero** (data rule 7). A channel whose feed goes 404
before the window is reported as `n_terminated` beside the statistic and excluded as absent;
survivorship is a stated limitation, with a descriptive secondary of terminated share by
predictor decile.

**Robustness row, pre-committed:** `ln(subs_r)` with `ln_subs` as a control.

### The construction check, re-run on THIS cohort

`subs_t` is in the predictor's denominator and in the outcome's. Rounding error in it could
inflate both and manufacture a correlation — the mechanism that killed ADR-0060's first
design. Simulated on the 1,931 real frozen rows under a null where subscribers move only by
rounding and noise, 300 trials per cell:

| noise sd | persistence | mean rho under null | false-PASS |
|---|---|---|---|
| 0.02 | no / yes | +0.0001 / −0.0018 | 2.7% / 1.7% |
| 0.05 | no / yes | −0.0007 / +0.0001 | 2.0% / 2.3% |
| 0.10 | no / yes | +0.0014 / +0.0002 | 3.0% / 3.3% |
| 0.25 | no / yes | −0.0018 / −0.0015 | 1.3% / 3.0% |

Inside α everywhere. **Re-run rather than inherited from the 2026-10-22 document**: the
subscriber distribution changed by an order of magnitude, and at 500+ subscribers
three-significant-figure rounding is ±0.5% rather than ±5%, so the earlier result did not
transfer by argument.

## Statistic

`nh/backtest/stats.evaluate_stratified`, unchanged: within-cluster ranks scaled by
`rank/(n+1)`, residualised on control ranks by OLS, Pearson of pooled residuals. Permutation
null **within cluster**, 10,000 draws, **seed 20270203**, p = (extreme + 1)/(draws + 1),
two-sided. Ties average.

## The bar — two floors, and the second is why this document exists

**rho > 0, p < 0.05, top-decile lift ≥ 1.25, AND top-decile median absolute gain ≥ 50
subscribers.** All four.

- **1.25** is the registered relative effect: the top decile grows 25% more than its controls
  predict.
- **50 subscribers** is the absolute floor, and it is not redundant. **A lift is a ratio, so
  it is satisfiable at any scale — including a scale at which the result is worthless.** That
  is exactly how the voided registration's bar came to mean two people. On this cohort's top
  decile (median 1,480 subs) a 1.25 lift implies ~+370, so the relative floor binds and the
  absolute one is a safety net rather than the constraint. It is there because the previous
  version had no such net and nothing caught it until a surface was built and read.

**Power.** At n ≈ 1,900 the critical rho is ≈ 0.045; at the 200 floor, ≈ 0.139. H1's +0.470 at
14 days means significance is easy if conversion is even a tenth as strong. The binding
uncertainty is the two effect floors, not the p-value — which is the intended shape.

## Floors

| | |
|---|---|
| Minimum channels with an outcome | 200 |
| Minimum clusters at ≥20 outcomes | 5 |
| Clusters under 10 outcomes | dropped |
| Expected n | ~1,800 of 1,931 (ADR-0065's watchlist reads ~97% of member channels nightly) |

Floors count **distinct channels**, not channel-dates. With one decision date the two coincide
here, and the code counts distinct anyway so a later second date cannot quietly inflate it.

## Instrument check, which runs first and can stop the test

**T0e — does 14-day reach reach subscribers at all?** Correlate ADR-0060's measured
`next_reach_14d` with `subs_growth_90d` over the same rows. If that is indistinguishable from
zero, the predictor had no route to the outcome and the read returns **INSTRUMENT**, not FAIL.
ADR-0060's T0 is not reused: `subs_r` against `subs_t` is trivially ~0.99.

Gated order: **T0e → H1e**. **No H2** — ADR-0060's was registered at 5% power and its FAIL
said nothing.

Three ways to return neither PASS nor FAIL, so a measurement failure is never recorded as a
finding: under the floors → **INCONCLUSIVE**; more than 40% of outcomes exactly zero →
**INSTRUMENT** (at a 500 floor one new subscriber is 0.2% and visible, so ties should be rare
— that is a prediction, which is why the guard stays); T0e null → **INSTRUMENT**.

## Read schedule

| read | date | status |
|---|---|---|
| verdict | **2027-02-03** | the only read |

No interim. `read()` refuses an unset constant, a key whose sha does not match, a date not yet
collected, and a report that already exists.

**The nightly must keep writing subscriber readings through 2027-02-02.** ADR-0065's channel
watchlist supplies them; `status._check_channel_watchlist` warns below 0.9 coverage. That is
the single operational dependency of this test.

## What would make this void

- Any change to the predictor, controls, outcome, floors, either effect floor, the seed, the
  statistic or the gated order after this document is committed.
- The key's sha256 not matching the constant above.
- Any outcome computed before 2027-02-03.
- Any join of subscriber readings to the frozen predictors before then. The nightly
  **collects**; nothing reads them against the key until the verdict.
- A re-freeze. `write_key` refuses to overwrite; a new file is a new test.

**Disclosed as-of-now reads:** the population counts at four candidate floors; this cohort's
subscriber and top-decile distributions; and the simulation above, which uses frozen
predictors with *synthetic* outcomes. **No realised subscriber growth has been joined to any
frozen predictor, and no predictor-outcome correlation has been computed.**

## What a PASS licenses

A ranked list of **channels within a cluster, by emergence**, behind
`CHANNEL_EMERGENCE_H1E_VALIDATED` set by a person. Nothing about any niche — not a ranking,
not `scorecards`, not an aggregation to the ten clusters, which ADR-0068 measured as
undetectable.

A FAIL means `views_per_sub` predicts two-week attention but not ninety-day audience: the
watchlist H1 licenses is a **reach** tool and not a **growth** tool. That is a useful negative
and it closes the question.

## Code

`nh/prospective/channel_emergence.py`, with `REGISTERED_KEY_SHA256` set to the sha above and
`REGISTRATION` pointing here. The git sha of the registering commit is recorded in ADR-0071 —
ADR-0060 omitted that and made a later question into archaeology.
