# Channel reach — the verdict

Registered in advance: `reports/channel_reach_preregistration_2026-09-15.md`. Frozen cohort sha256 `1cb64d0acf07b50d5594389812c7725851adaabf3e38da2a0b6df2d28786e5f2`, verified against the registered constant before any outcome was read.

## Read these before any number

1. **No niche claim.** Every comparison is within a cluster; nothing here says any niche is open.
2. **Frozen membership.** Cluster assignment is as of the registration, not as a nightly at t stored it.
3. **Censoring.** Readings before the ADR-0059 watchlist were missing non-randomly by upload rate.
4. **H2 was registered as low-power**: 5% of simulated seeds passed with a strong breakout effect, so an H2 FAIL is weak evidence of absence.

## Power, before the result

- Distinct channels with an outcome: **665** (floor 200)
- Clusters reaching 20 outcomes at some date: **10** (floor 5)
- Channel-dates: **873**; two-sided critical rho ≈ **0.066**

## Verdict

> **H1: PASS** — rho +0.470, p 0.0001, lift 2.592
>
> **H2: FAIL** — rho -0.031 is not positive

## Every step

| step | rho | p | top-decile lift |
|---|---|---|---|
| T0 instrument | +0.649 | 0.0001 | n/a |
| H1 views_per_sub | +0.470 | 0.0001 | 2.592 |
| H2 breakout | -0.031 | 0.5789 | 0.983 |

## Outcomes per cluster and date (descriptive only)

| date | cluster | outcomes | in the test |
|---|---|---|---|
| 2026-09-01 | ai-and-software | 45 | yes |
| 2026-09-01 | anthropocene-anthropology | 26 | yes |
| 2026-09-01 | biohacking | 18 | yes |
| 2026-09-01 | esoterism-spirituality | 39 | yes |
| 2026-09-01 | geopolitics | 19 | yes |
| 2026-09-01 | history-of-ideas | 25 | yes |
| 2026-09-01 | logic-linguistics-gnoseology | 27 | yes |
| 2026-09-01 | macro-economy | 24 | yes |
| 2026-09-01 | metaphysical-battles | 28 | yes |
| 2026-09-01 | trading | 25 | yes |
| 2026-09-08 | ai-and-software | 106 | yes |
| 2026-09-08 | anthropocene-anthropology | 45 | yes |
| 2026-09-08 | biohacking | 29 | yes |
| 2026-09-08 | esoterism-spirituality | 52 | yes |
| 2026-09-08 | geopolitics | 61 | yes |
| 2026-09-08 | history-of-ideas | 62 | yes |
| 2026-09-08 | logic-linguistics-gnoseology | 42 | yes |
| 2026-09-08 | macro-economy | 67 | yes |
| 2026-09-08 | metaphysical-battles | 61 | yes |
| 2026-09-08 | trading | 72 | yes |
