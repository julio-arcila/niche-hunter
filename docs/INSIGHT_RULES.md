# Insight rules

Cross-source predicates over `features_daily` that emit `alerts` rows. Each rule
is a testable predicate with the evidence attached, so an alert can always be
traced back to the numbers that fired it.

Implemented in `nh/scoring/rules.py` (Phase 4). Each needs a synthetic-data test
that fires it and one that does not.

## Template

```
### Rule N — <name>
Predicate  : the condition, in terms of named metrics from docs/METRICS.md
Window     : over how many days / cohorts
Severity   : info | watch | act
Evidence   : which values to attach to the alert row
Why it matters : what the operator should do differently
False positive : the common way this fires and is wrong
```

## Rules to define

The plan calls for ten. The two below are worked examples of the shape; the rest
are named but undefined, and each needs its metrics to exist first.

### Rule 4 — Closing window
```
Predicate  : openness.breakthrough_rate_cohort falls across three consecutive
             cohorts AND supply.uploads_per_week rises over the same span
Window     : 3 cohorts
Severity   : act
Evidence   : the three cohort rates, the uploads series, n per cohort
Why        : the niche is being colonized; entry cost is rising while the
             chance of an outlier is falling
False pos  : a seasonal upload spike with no real change in openness — check
             demand.season_index for the months involved before acting
```

### Rule 7 — Demand without supply
```
Predicate  : demand.trends_momentum_13w above the universe 80th percentile AND
             supply.uploads_per_week below the universe 20th percentile AND
             voice.unanswered_rate > 0.5
Window     : current day, with 28-day smoothing on demand
Severity   : act
Evidence   : demand percentile, supply percentile, unanswered rate, the
             unanswered thread titles
Why        : people are asking and nobody is answering on video
False pos  : demand that is a single news event rather than a standing interest
             — check demand.volatility and whether breakout_z is driving it
```

> **Naming note (Slice 5).** This rule was written against `demand.momentum_13p`,
> a prototype name that resolves to no shipped metric; the shipped one is
> `demand.trends_momentum_13w` and the predicate now says so. A rule that names a
> metric which does not exist cannot be implemented and cannot be tested, so the
> mismatch was invisible until someone tried.

### Undefined
Rules 1, 2, 3, 5, 6, 8, 9, 10 — name and define as their input metrics land.
Candidates from the source material: RPM/CPM divergence between advertiser value
and audience geo; a cluster whose centroid drifts faster than its membership
turns over; newcomer share collapsing while total uploads hold steady;
evergreen-vs-news mix inverting.
