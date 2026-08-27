---
name: run-backtest
description: Replay the lifecycle classifier over historical data and score its precision/recall. Use to tune thresholds or validate a scoring change.
---

# Run a backtest

Purpose: produce a precision number for "emerging" calls that you would actually
bet on, plus a written account of where the classifier is wrong.

1. **Load history.** `nh/backtest/youniverse.py` for the YouNiverse dump;
   `nh/collectors/wayback.py` for sub-count history of current top channels via
   the CDX API. Both write to `historical_channel_weeks`.

2. **Pick the window and niches.** State them explicitly — a backtest over a
   window you chose after seeing the result is not a backtest.

3. **Replay.** `nh/backtest/replay.py`: for each historical date, compute
   features using *only* rows whose `at` precedes that date, run
   `nh/scoring/lifecycle.py`, and record the call. Leakage is the failure mode
   here — if a feature reads a snapshot from after the decision date, every
   number that follows is meaningless.

4. **Score** at 90 and 180 days: precision, recall, and the base rate. Precision
   without the base rate is not interpretable.

5. **Write `reports/backtest_<date>.md`**: window, niches, n, precision/recall
   at both horizons, the threshold set used, and a paragraph on the false
   positives — what they had in common is usually the next feature.

6. Only then tune thresholds, and re-run on a window you did not tune against.
