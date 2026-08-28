---
name: run-backtest
description: Replay the classifier over historical data and score its rank correlation with what happened. Use to tune thresholds or validate a scoring change.
---

# Run a backtest

Purpose: produce a **rank correlation** between the score at a decision date and
what actually happened afterwards, with a null distribution, plus a written
account of where the ranking is wrong.

**Not precision and recall.** That was this skill's instruction until Slice 6 and
it is not obtainable: YouNiverse contains only channels that had crossed 10,000
subscribers by its 2019 crawl, so every channel in it succeeded and the base rate
of "emerged" is ~1 by construction. No sampling recovers the missing negative
class — the channels that stayed small were never crawled. See
`reports/gate_e_feasibility_2026-08-27.md`.

1. **Load history.** `nh/backtest/youniverse.py` for the YouNiverse dump, into a
   **separate database file** (`NH_DATABASE_URL=sqlite:///data/backtest.db`).
   Never into the live corpus: the backtest writes 30 fake clusters and millions
   of 2019 rows, and `nh nightly` would then RSS-poll dead channels and rank live
   niches against phantom ones. There is no Wayback collector and no
   `historical_channel_weeks` table — both were dropped in ADR-0025.

2. **Pick the window and niches.** State them explicitly — a backtest over a
   window you chose after seeing the result is not a backtest. The niche set is
   `nh/backtest/niches.py`, and it is committed before the data lands so that
   this is checkable rather than promised.

3. **Replay.** `nh/backtest/replay.py`: for each historical date, compute features
   bounded at that date, run `nh/scoring/lifecycle.py`, record the call. Leakage
   is the failure mode — if a feature reads a row from after the decision date,
   every number that follows is meaningless and will look excellent.

   The rule is **`observed_date <= day`, per table**, not `at < day`: bounding
   demand on `at` returns zero rows, because Wikipedia was backfilled. Call
   `features_run.compute` and `scorecard.build` **directly** — `run_phases` runs
   clustering first, which mutates and commits.

4. **Score.** Per-date Spearman between the score and `outcome.growth_180d`, then
   the mean across dates, with a p-value from permuting niche labels **globally**
   — once per replication, not within each date. Permuting within dates destroys
   the serial structure of both series and manufactures significance out of the
   autocorrelation.

   Report the **size baseline** alongside: the rank correlation of niche size with
   growth, and the partial correlation of the score controlling for size. A score
   that ranks by size is not a finding.

5. **Write `reports/backtest_<date>.md`.** Three things before any number:
   survivorship; that the niches were defined by a relevance rule whose 0.781
   precision has no independent human validation; and that the backtested `gap`
   is not the live `gap`, because `median_views` had to be substituted.

   Then the pre-registered primary result, its p-value, the number of
   independent windows, and a paragraph on where the ranking fails.

6. Only then tune thresholds, and re-run on a window you did not tune against.
   **Relevance thresholds are not tunable** — METRICS.md forbids moving them
   against a metric. The three-threshold run is robustness, not a search.
