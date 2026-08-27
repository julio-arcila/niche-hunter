---
name: add-metric
description: Add a feature metric — define it in docs/METRICS.md first, then implement, test and expose it. Use when adding anything that writes to features_daily.
---

# Add a metric

The definition comes before the code. A metric whose formula lives only in a
Python function cannot be reviewed, backtested or compared across a schema change.

1. **Define it in `docs/METRICS.md`** — and stop there until this is complete:
   - **Formula**, written out, including the normalization (z-score within
     which universe? anchor-scaled against what?).
   - **Inputs**: which tables and columns, over which time window.
   - **Join key**: `cluster_id` for nearly everything.
   - **Confidence**: how it is computed, e.g. `min(cohort_n / 30, 1)`.
   - **Failure mode**: what makes this metric lie, and what value it takes when
     inputs are too sparse (NULL, never a fabricated default).

2. **Implement** in the right `nh/features/*.py` module: `demand`, `supply`,
   `openness`, `voice`, `money`, `cost_risk`. One function, pure, taking a
   session and a `(cluster_id, day)` and returning value + confidence + inputs_n.
   Several of these already exist in the `legacy/` prototypes as pure functions —
   `channel_baseline`, `trend_features`, `anchor_scaled_interest`,
   `supply_signals`, `niche_features`. Port them, do not rewrite them.

3. **Test against a fixture database**, not a mock. Cover: the normal case, the
   sparse case (confidence drops, value may be NULL), and the empty case (no
   row written, or a row with NULL value — never 0).

4. **Expose** in `nh/scoring/scorecard.py` if it feeds a composite score, and
   say which composite in `docs/METRICS.md`.

5. **Verify**: `uv run pytest -q`, then confirm `features_daily` has one row per
   cluster per day with `confidence` and `inputs_n` populated.
