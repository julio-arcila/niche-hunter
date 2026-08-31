# Insight rules

Cross-source predicates over `features_daily` that emit `alerts` rows. Each rule
is a testable predicate with the evidence attached, so an alert can always be
traced back to the numbers that fired it.

Implemented in `nh/scoring/rules.py`. Each needs a synthetic-data test that fires
it and one that does not.

## Two constraints every rule on this page obeys (ADR-0052)

**1. An alert is a citation.** ADR-0045 names "an alert" as a surface that puts a
number in front of a person, so a rule may not read a metric the scorer decided
while the exposition axis is unvalidated. The eight gated metrics are the six
`supply.*`, `money.midroll_eligible_share` and `openness.winner_age_years` —
derived by execution, not by reading, and re-derived by a test. All ten active
clusters are exposition clusters, so "while unvalidated" means "now".

**2. Night-over-night means consecutive STORED days, never consecutive calendar
days.** `features_daily` holds 2026-08-27, -28, -29 and -31: **2026-08-30 is a
permanent hole**, the nightly a sleeping Mac ate before the launchd port. A rule
comparing calendar-adjacent days fires on that gap and on every future one, which
is how an alerts feed teaches its reader to ignore it.

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

## Defined and implementable today

Three, and the count is the point. An earlier version of this page listed ten
planned rules, defined two, and both of those named metrics that do not exist. A
rule that cannot fire is worse than no rule: it reads as coverage.

### Rule 1 — Demand breakout
```
Predicate  : demand.wiki_momentum_28d exceeds the cluster's own trailing
             365-day distribution by z >= 2.0
Window     : current day; baseline is the metric's own 365-day history in
             demand_snapshots, which holds ~3 years
Severity   : info
Evidence   : the 28-day and baseline window sums, z, the articles that
             contributed, and demand.wiki_volatility_365d beside it
Why        : attention moved on the demand side, before anything about supply
             is claimed. This is an observation, not a forecast — Gate E's null
             is about prediction and this rule does not predict.
False pos  : a single news event rather than standing interest. wiki_volatility_365d
             is attached rather than thresholded, because the operator can read a
             spike and a rule cannot.
Gated?     : no — demand.* is scorer-independent (ADR-0052).
```

### Rule 2 — Definition step
```
Predicate  : detail.definition for any supply metric differs from the previous
             STORED day, or detail.ballast.channels moves more than 5% of the
             cluster's member channels between those two days
Window     : two consecutive stored feature days
Severity   : watch
Evidence   : both definitions, both ballast counts, the member-channel
             denominator, and the metrics affected
Why        : a value that moved because the definition moved is not news about
             the niche. This is the rule that fires on 2026-09-14 when ADR-0050's
             sunset reverts supply.* to v2-on-niche, and on any lexicon change
             that tips channels into ballast in a batch.
False pos  : the first night after a new stamp lands, when the previous day has
             no detail.ballast at all. Absent is not a change — skip the pair.
Gated?     : no. It cites no metric VALUE, only that a definition moved, which is
             a fact about the pipeline rather than about the niche.
```

### Rule 3 — Evidence collapse
```
Predicate  : a metric non-NULL on the previous stored day is NULL today, or its
             inputs_n falls by more than half between those two days
Window     : two consecutive stored feature days
Severity   : watch
Evidence   : both inputs_n, both confidences, the metric's empty() reason
Why        : a source went quiet, a join broke, or a retirement removed a
             population. Every one of those looks like a working pipeline from
             `nh status`, which checks that collection happened rather than that
             it produced anything readable.
False pos  : a cluster retired between the two days — check niche_seeds.active
             before firing. That is not a collapse, it is a decision.
Gated?     : no. It reads existence and inputs_n, never a value.
```

## Refused, with the reason recorded

Not "undefined" — considered and declined. Recorded so the next reader does not
re-derive them as obvious wins.

### Rule 7 — Demand without supply — REFUSED
The original predicate needs `voice.unanswered_rate`, which exists only as a
deferral blocked on a Reddit application pending since 2026-08-29. **Rule 7 minus
the voice term is computable and is still refused**, for three separate reasons,
any one of which is sufficient:

1. It is the demand–supply gap claim wearing an alert costume, and **Gate E
   measured that exact shape at ρ 0.091, p 0.4988** — a null on 29 niches against
   a floor of 20. Emitting it as an `act` alert would ship the retired predictive
   claim through a side door.
2. It reads `supply.uploads_per_week`, a gated metric (ADR-0052).
3. Its percentile framing is a ranking across clusters, which ADR-0029 forbids.

> **Naming note, kept from Slice 5, because it is the reason this page now
> refuses rules instead of listing them.** Rule 7 was originally written against
> `demand.momentum_13p`, a prototype name resolving to no shipped metric. The
> mismatch was invisible until someone tried to implement it. Rule 4 below carries
> the same defect and was on this page for weeks reading as a defined rule.

### Rule 4 — Closing window — NOT IMPLEMENTABLE
Needs per-cohort breakthrough rates across three cohorts, which `features_daily`
does not store — `openness.breakthrough_rate_cohort` stores one number per day,
not a cohort series — and `demand.season_index`, which is defined nowhere. Both
would have to land first. The predicate is kept below as the record of what it
would need, and is deliberately no longer formatted as a rule.

```
would need : a stored cohort series for openness.breakthrough_rate_cohort
             + demand.season_index, neither of which exists
```

### Never defined
Rules 5, 6, 8, 9, 10 were counted in a plan and never written. The candidates
from the source material — RPM/CPM divergence between advertiser value and
audience geo; a cluster whose centroid drifts faster than its membership turns
over; newcomer share collapsing while total uploads hold steady; evergreen-vs-news
mix inverting — each need metrics that do not exist. They are listed here as
candidates, not as a backlog: **the count of rules is not a target.**
