> # VOID — 2026-10-23, one day after registering, before any outcome existed
>
> **The bar below can be cleared by two subscribers.** The frozen cohort's median member has
> 192 subscribers and the registered top decile's has **fifteen**, so the registered
> `top-decile lift >= 1.15` over 90 days is **+2.2 subscribers**. A PASS would have been
> uninterpretable and unactionable.
>
> The 1.15 floor was calibrated against the *relative* spread of realised growth (p50 +1.3%,
> p90 +18.4%) and never against the absolute magnitude that implies on a 15-subscriber
> channel. That is an error of omission in this document, found by measuring the cohort while
> building the surface ADR-0060 licensed.
>
> No outcome for either decision date existed when this was found — the first is readable
> 2026-11-30 — so this is a measurement decision, not tuning against a result. But this
> document's own void clause says a change to the bar voids it, so it is **void rather than
> amended**, and `REGISTERED_KEY_SHA256` is `None` in the module so the code cannot read it.
>
> **A successor cannot fix this with a threshold.** A cohort whose median member has 192
> subscribers cannot produce an actionable subscriber-growth result at any bar; it needs a new
> freeze with a subscriber floor (>= 500 puts it above the current median, where a 1.25 lift
> is +125 subscribers), registered before its predictors exist, reading ~late January 2027.
> See ADR-0070.
>
> Everything below is kept verbatim as the registration that was made, including the
> simulation that *was* right, so the error is legible rather than erased.

# Pre-registration — channel emergence: does short-run outperformance convert to audience?

**Registered 2026-10-22, before any outcome for either decision date exists.** The first
outcome becomes readable on **2026-11-30** (t = 2026-09-01 plus 90 days). Nothing in this
document may change after that date; see "What would make this void".

This is ADR-0060's sequel and is **not** a niche test. ADR-0068 established that a
cross-sectional niche-grain test cannot be passed at ten clusters — the critical rho is
0.636 and a true effect near 0.808 would be needed for 80% power — so the niche question is
not asked here and cannot be answered by this read. Niche enters only as a **stratum**.

## The claim

**H1e.** Among small channels, a channel whose recent videos outperform its own subscriber
base at time *t* gains more subscribers over the following 90 days than its peers in the
same cluster, holding its size, catalogue age and eligible-video count.

ADR-0060's H1 established that `views_per_sub` predicts **14-day reach** (rho +0.470,
p 0.0001, lift 2.59, 665 channels). That is persistence of attention. This asks the
different and more consequential question: **does that attention convert into audience?**

## Unit, cohort and predictor — all frozen already

| | |
|---|---|
| Unit | channel-date |
| Cohort | `reports/channel_reach_cohort_draw_key_2026-09-15.jsonl`, **unchanged** |
| sha256 | `1cb64d0acf07b50d5594389812c7725851adaabf3e38da2a0b6df2d28786e5f2` |
| Size | 1,473 channel-dates, 977 distinct channels, t ∈ {2026-09-01, 2026-09-08} |
| Predictor | `views_per_sub` at *t*, as frozen in that file |
| Controls | `ln_subs`, `catalogue_age`, `n_elig` at *t*, as frozen in that file |

**Nothing new is frozen and nothing is re-derived.** The predictor and every control are read
from the file whose bytes were hashed on 2026-09-15 and whose hash is already recorded in a
merged commit. This is the strongest position available: the predictors existed, sealed,
seven weeks before this registration was written, so no choice made here could have been
informed by them.

## Outcome

**Primary — `subs_growth_90d` = ln(subs_r / subs_t)** where

- `subs_t` = `exp(ln_subs)` from the frozen row;
- `subs_r` = the subscriber reading on the **smallest** `observed_date` in `[t+90, t+97]`
  that carries a non-NULL `subs`, taking `MAX(subs)` across sources on that date.

Absent if no reading falls in the window — **never zero** (data rule 7). A channel whose feed
has gone 404 before the window is reported per cluster-date as `n_terminated` beside the
statistic and excluded from the rank test as absent. Survivorship is therefore a stated
limitation of this test, with a labelled descriptive secondary: terminated share by predictor
decile.

**Robustness row, pre-committed — `ln(subs_r)` with `ln_subs` as a control.** Reported
alongside the primary whatever it shows.

### Why the ratio is primary, which was checked rather than assumed

`subs_t` appears in the predictor's denominator (`views_per_sub` = median views / subs) **and**
in the ratio outcome's denominator. Measurement error in `subs_t` — YouTube publishes
3-significant-figure subscriber counts — would inflate both together and could manufacture a
positive correlation out of nothing. That is the mechanism that killed ADR-0060's first
design, which passed by construction 40% of the time in simulation.

**Simulated before registering, on the 977 real frozen rows** (null world: subscribers move
only by rounding and idiosyncratic noise, so the true effect of `views_per_sub` is exactly
zero; 300 trials per cell; within-cluster ranks residualised on the three controls):

| outcome | noise sd | persistence | mean rho under null | false-PASS rate |
|---|---|---|---|---|
| ratio | 0.02 | no | +0.0007 | 2.7% |
| ratio | 0.02 | yes | −0.0129 | 1.7% |
| ratio | 0.05 | no | +0.0030 | 3.3% |
| ratio | 0.10 | no | −0.0000 | 2.0% |
| ratio | 0.25 | no | +0.0026 | 1.3% |
| level | 0.02–0.25 | both | −0.015 to −0.025 | 0.0–0.7% |

The ratio holds its false-PASS rate between **1.3% and 3.3%** across every noise magnitude
tested and with or without size-proportional drift — comfortably inside α = 0.05. The feared
inflation does not materialise, because residualising on `ln_subs` within cluster absorbs the
shared denominator. The level outcome is valid but conservative and probably less powerful,
which is why it is the robustness row rather than the primary.

**This result contradicted the expectation that motivated the check.** It is recorded because
a check that is only reported when it confirms is not a check.

## Statistic

`nh/backtest/stats.evaluate_stratified`, unchanged: within-cluster ranks scaled by
`rank/(n+1)`, residualised on the control ranks by OLS, Pearson of the pooled residuals,
mean over the two decision dates. Permutation null **within cluster**, 10,000 draws,
**seed 20261122**, p = (extreme + 1) / (draws + 1), two-sided.

Ties: ranks average tied values. **At least 10% of cohort channels show exactly zero
subscriber movement over 18 days** (p10 of realised ln-growth is 0.0000) because of the
3-significant-figure publication floor, so the outcome will carry ties. If more than **40%**
of outcomes in the read are exactly zero, the read returns **INSTRUMENT**, not FAIL — a
degenerate outcome cannot test a hypothesis.

## Floors and the bar

| | |
|---|---|
| Minimum channels with an outcome | **200** |
| Minimum clusters at ≥20 outcomes | **5** |
| Clusters below 10 outcomes at a date | dropped from that date |
| Expected n | ~1,300–1,450 channel-dates (954 of 977 channels carry nightly readings) |
| Bar | **rho > 0, p < 0.05, and top-decile lift ≥ 1.15** |

**Lift** = exp(mean residual growth of the top within-(date, cluster) decile of raw
`views_per_sub`) ÷ exp(mean residual growth of the rest): the top decile gains at least 15%
more subscribers over 90 days than its controls predict.

**1.15 is a judgement and is named as one.** Calibration, disclosed: realised cohort
subscriber growth over the 18 days to 2026-10-22 has p50 = +1.3%, p90 = +18.4%, and a raw
top-decile-by-outcome lift of **1.45** — which is a ceiling, since it sorts on the outcome
itself rather than on any predictor. A predictor capturing a useful share of a spread that
will be wider at 90 days than at 18 should clear 1.15. Significance alone was rejected as a
bar: at n ≈ 1,400 the critical rho is ≈ 0.052, so a statistically significant but tiny effect
would license nothing anyone could act on.

**Power.** At n ≈ 1,400 the critical rho is ≈ 0.052; at the 200 floor, ≈ 0.139. H1's +0.470 at
14 days means this clears significance if conversion to subscribers is even a fifth as strong
as persistence of views. The binding uncertainty is the lift floor, not the p-value.

## Instrument check, which runs first and can stop the test

**T0e — does 14-day reach convert to subscribers at all?** Correlate ADR-0060's measured
`next_reach_14d` outcome with `subs_growth_90d` over the same rows. If that correlation is
indistinguishable from zero, then the predictor cannot reach the outcome through any channel
and the read returns **INSTRUMENT**, not FAIL. ADR-0060's T0 (does the outcome track a
channel's own level) is **not** reused: `subs_r` versus `subs_t` is trivially ~0.99 and would
certify nothing.

Gated order: **T0e → H1e.** No H2. ADR-0060's H2 was registered at 5% power and its FAIL was
uninformative; repeating that pattern with `breakout_magnitude` would buy another
uninterpretable result. If it is ever worth asking, it gets its own registration and its own
power analysis.

## Read schedule

| read | date | dates included | status |
|---|---|---|---|
| verdict | **2026-12-14** | both 09-01 and 09-08 | the only read |

No interim. ADR-0060's interim was rendered late, added nothing the verdict did not contain,
and cost a clause in its own void list. `read()` refuses before the date is collected, refuses
an unset registration constant, refuses a key whose sha does not match, and refuses to
overwrite an existing report.

The 09-01 window closes 2026-12-07 and the 09-08 window closes 2026-12-14, so **the nightly
must be collecting subscriber readings continuously through 2026-12-14.** ADR-0065's channel
watchlist is what supplies them; `status._check_channel_watchlist` warns below 0.9 coverage.

## What would make this void

- Any change to the predictor, the controls, the outcome definition, the floors, the bar, the
  seed, the statistic or the gated order **after this document is committed**.
- The frozen key's sha256 not matching the constant recorded above.
- Any outcome being computed, for either decision date, before 2026-12-14.
- Any join of subscriber readings to the frozen predictors before that date. The nightly
  **collects** readings; nothing reads them against the key until the verdict.
- A re-freeze of the cohort. `write_key` refuses to overwrite; a new file would be a new test.

**Disclosed as-of-now reads, made while writing this and listed so a later reader can judge
them:** the simulation above (frozen predictors and controls, with *synthetic* outcomes); the
cohort's reading coverage (954 of 977 channels, 952 with ≥10 nights); and the realised 18-day
growth distribution used to calibrate the lift floor (p50 +1.3%, p90 +18.4%, raw top-decile
ceiling 1.45). **No realised subscriber growth was joined to any frozen predictor**, and no
correlation between a predictor and any outcome has been computed.

## What a PASS licenses, and what it does not

A PASS licenses a **ranked list of channels within a cluster, by emergence** — behind a human
verdict constant (`CHANNEL_EMERGENCE_H1E_VALIDATED`, set by a person in the commit that
records the result, on the `EXPOSITION_VALIDATED` pattern). It would be the first result in
this project speaking to emergence rather than persistence.

It licenses **nothing about any niche**: not a ranking, not `scorecards`, not a re-opening of
Gate E, and not an aggregation of channel growth to the ten clusters — at n = 10 that
aggregate is undetectable by ADR-0068's arithmetic.

A FAIL means `views_per_sub` predicts two-week attention but not ninety-day audience. That is
a publishable, useful negative: it would say the watchlist H1 licenses is a *reach* tool and
not a *growth* tool, and it would close the question rather than leave it hanging.

## Code

`nh/prospective/channel_emergence.py`, with `REGISTERED_KEY_SHA256` set to the constant above
and `REGISTRATION` pointing at this file. The git sha of the commit that registers this is
recorded in ADR-0069 — ADR-0060 omitted that, which made a later question about whether the
code had moved into an archaeology exercise instead of a lookup.
