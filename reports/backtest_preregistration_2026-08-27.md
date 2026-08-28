# Backtest pre-registration — Slice 6, Gate E

**Written 2026-08-27, before any outcome data has been joined to any score.**

At the time of writing: the 36 backtest niches are committed (`nh/backtest/niches.py`,
PR 3), `df_channels_en` and `df_timeseries_en` are on disk, `yt_metadata_en.jsonl.gz`
is still downloading, and **no scan, no load, no replay and no correlation has been
run.** Nothing in this document was chosen after seeing a result, because no result
exists.

This exists because the analysis has 24 defensible variants — 2 demand strata ×
2 horizons × 3 relevance thresholds × 2 supply proxies — and a gate that picks its
number afterwards is a gate that always passes. The primary is fixed here.

---

## The primary result

> **Spearman rank correlation between `scorecards.gap` and `outcome.growth_180d`,
> using the topic demand stratum, the `supply.views_per_new_video` supply proxy, at
> the frozen relevance threshold 0.55, computed per decision date over the
> validation window and aggregated across dates, reported with a permutation-test
> p-value and the number of quasi-independent windows.**

Each choice, and why it was made without reference to any outcome:

| Choice | Value | Why this one |
|---|---|---|
| Score | `gap` | The one composite Slice 3 shipped and Slice 5 aligned. `opportunity` has no weights yet — they are an *output* of this gate. |
| Outcome | `growth_180d` | Defined in METRICS.md before the backtest existed. 90d is secondary. |
| Stratum | topic | The incumbent, with the longer comparable series. Pre-registered in `reports/demand_stratum_2026-08-27.md`. |
| Supply | `views_per_new_video` | The analogue of what `scorecards.supply` actually ranks. `uploads_per_week` alone is volume without reach. |
| Threshold | 0.55 | Frozen 2026-08-27 on held-out data. METRICS.md forbids tuning it. |
| Window | validation | Tuning happens on the earlier window; the later one is untouched until the primary is computed once. |
| Statistic | Spearman | Rank, not value: the product ranks niches, and the composites are percentile ranks already. |

Everything else computed is **secondary** and will be labelled as such in the report,
including any result that is more favourable than the primary.

## The verdict rule, stated before the number

- **Gate E passes** if the primary correlation is positive and its permutation
  p-value is below 0.05, **and** it survives controlling for niche size (partial
  Spearman with member-channel count held constant). A correlation that disappears
  under that control means the scorecard ranks niches by how big they are, which
  needs no pipeline.
- **Gate E fails** if the primary is indistinguishable from zero, or is
  distinguishable only before the size control. The consequence is written into
  `docs/ROADMAP.md` and is not renegotiable here: do not build the dashboard; either
  return to Slice 5's feature work with what the failure analysis taught, or narrow
  the product claim to "surfaces evidence for a human to judge".
- **A negative correlation is a result, not a bug**, and gets the same treatment as
  a null: reported, analysed, and acted on.

There is no third branch where the gate is re-run with different settings until it
passes. If the primary fails and a secondary variant succeeds, that is a hypothesis
for a *later* slice with a *fresh* validation window — it is not this gate's verdict.

## Power, stated before the result

Spearman's standard error is ≈ `1/sqrt(N-1)`, so the smallest correlation
distinguishable from noise at two SE is:

| niches surviving selection | smallest detectable rho |
|---|---|
| 6 | 0.89 |
| 20 | 0.46 |
| 30 | 0.37 |
| 36 | 0.34 |

36 niches are committed; selection floors (`MIN_ON_NICHE_VIDEOS = 5`,
`MIN_MEMBER_CHANNELS = 15`) will drop some unknown number of them. **The report
states N after selection and the detectable rho at that N, before stating the
correlation.** If N lands below 20 the gate is underpowered and the report says the
result is inconclusive rather than null — those are different verdicts and only one
of them licenses abandoning the thesis.

## Permutation scheme

The null shuffles niche labels **within each decision date**, preserving the
temporal structure and breaking only the score↔outcome link. Computed per date, then
aggregated across dates, and compared against the same aggregation of the shuffled
series.

Roughly 195 weekly decision dates exist in the window, and they are heavily
autocorrelated: consecutive 180-day outcome windows overlap by 179 days. **The report
quotes the number of quasi-independent windows (~8), never 195.** Treating 195
overlapping dates as independent observations would shrink every interval by a factor
of about five and manufacture significance out of autocorrelation.

## Tune / validate split

Split by time, with an embargo of one outcome horizon between them so no tuning date's
outcome overlaps a validation date's inputs.

The tuning surface is **exactly** `lifecycle.Thresholds`, which is frozen and versioned
so every stored stage stays attributable. Not tuned, under any result:

- **Relevance thresholds.** METRICS.md forbids it. The three-threshold run is a
  robustness check; if the correlation moves with the threshold, that is a finding
  about the relevance rule and goes in the report as one.
- **Lexicon contents.** Editing a niche's terms after seeing its correlation is
  selection on the outcome.
- **The niche set.** The 36 are committed. Niches dropped by the selection floors are
  reported with their counts; none may be revived or replaced.

## The three caveats that lead the report

Before any number, in this order:

1. **Survivorship.** Every channel in YouNiverse crossed 10,000 subscribers by the
   2019-10-27 crawl. This measures relative growth *among successes*, never
   emergence, and no sampling recovers the missing negative class.
2. **The niches were defined by an unvalidated relevance rule** — held-out precision
   0.781, labelled by the same system that wrote the lexicon, kappa 0.943 against a
   second model, human spot-check deferred to before Slice 7.
3. **The backtested `gap` is not the live `gap`**, because `median_views` is not
   replayable and `views_per_new_video` stands in for it.

## What would make this pre-registration void

If any of the following happens, the run is exploratory and the report says so
instead of stating a verdict:

- The primary is computed more than once with different code.
- The validation window is inspected before the tuning window is closed.
- A niche is added, edited or removed after the scan runs.
- The relevance threshold, the supply proxy or the stratum is changed after seeing
  any correlation.
