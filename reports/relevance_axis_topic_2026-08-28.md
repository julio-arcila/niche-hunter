# A second relevance axis for topic domains — fitted on determined rows, 2026-08-28

## What this answers

ADR-0033 found that `relevance.score()` returns 0.0 for all eleven pivot domains,
because its second axis is 82 terms of failure vocabulary whose docstring states the
question it asks: *"did something fail"*. Measured on 120 real discovered videos, that
axis matches **1 of 120** titles. The score is a geometric mean, so 119 of 120 score
zero however well the domain axis fits.

This finds the topic-domain analogue of that axis.

## The labels, and what they are not

103 determined rows from a 120-row blind stratified sample over four pivot domains
chosen for different shapes (philosophy-of-science, trading, geopolitics, biohacking).
Labelled by `fable-5` in a fresh context under `labelling_criterion_topic_domains_v2.md`,
barred from the scores, the source, the database and the URLs, and asked to flag rows
the **rule** could not settle. 17 rows were flagged and are excluded here — the
exclusion the criterion pre-committed to.

**These are machine labels.** The registered human-validation deferral remains open and
unmet. A prior cross-family pass measured kappa 0.883 between `claude-opus-5` and
`fable-5` on the disaster corpus, which bounds how much of a precision figure is one
family agreeing with itself, but it does not make these human labels.

## The candidates, derived from the criterion rather than the labels

Every marker traces to a clause in the criterion, which was written before any row was
read. Nothing was chosen by inspecting labels, so the rows are a test set.

- **exposition** — "an explanation, lecture, analysis, debate or critique within the
  domain": `explained`, `why`, `how`, `analysis`, `lecture`, `critique`, `mechanism`,
  `evidence`, `framework`, `deep dive`, and similar.
- **selling / tooling / tease** — the criterion's FALSE clauses on income claims, tool
  tutorials, signals and withheld-subject hooks.

## Result — replicated across two rules and two raters

A second blind pass under a self-contained v4 criterion (10.0% underdetermined, the
packaging defect that voided v3 eliminated) relabelled the same 120 rows. The two label
sets agree at **kappa 0.845 / raw 0.926** on the 95 rows both rules determined. That
bounds *rule* stability as well as rater stability, since the rule changed too.

Every candidate scored held-out on 200 random halves, under the stricter v4 labels
(n=107, base rate **0.523** — far closer to a real corpus than v2's stratified 0.670):

```
A  domain alone (baseline)   P 0.549  R 0.807  F1 0.652
B  domain x exposition       P 0.866  R 0.736  F1 0.794      <- winner, 168/200 splits
C  domain + negative filter  P 0.577  R 0.756  F1 0.652
D  B + negative filter       P 0.901  R 0.685  F1 0.777
```

Under the earlier v2 labels the same protocol gave B P 0.936 / R 0.682 / F1 0.788, and B
won 182/200. **B wins under both rules and both raters**, and A never won a single split
under v4. F1 is stable at 0.788 vs 0.794 across the two label sets even though precision
and recall trade places — which is what a real effect looks like rather than a fitted one.

**An exposition axis is the topic-domain analogue of the event axis.** Under v4 it takes
held-out precision from 0.549 to 0.866, and unlike the v2 fit it *also* improves nothing
away: recall falls only 0.807 -> 0.736.

## Three things this does not say

1. **The precision is not comparable to the 0.62 / 0.781 figures on the disaster
   corpus.** This sample's base rate is **0.670**, inflated by stratifying toward
   high-domain-score rows; theirs was 0.286. Precision moves with base rate, so only the
   within-corpus comparison (0.616 → 0.936, same rows, same labels) is valid.
2. **Recall 0.682 means roughly a third of on-niche videos are missed.** For a tool that
   surfaces evidence for a human, that is a real cost and not obviously the right
   trade — the threshold is a product decision, not a measurement.
3. **The negative filters are weaker than the criterion's emphasis on them suggests —
   but the first version of this claim was too strong.** Fitted on v2 they looked useless
   (held-out precision 0.616 → 0.565 for filter-only). Under v4, whose rule actually
   *encodes* tool tutorials, signals and comparisons as FALSE, they do real work: filter-
   only rises to 0.577 and D reaches the highest precision of any candidate at 0.901,
   winning 32/200 splits against 11/200 before. So part of the original finding was an
   artifact of labels produced by a rule that did not contain those clauses. What
   survives is narrower and still worth keeping: **B beats D under both label sets**,
   because the negative markers buy precision by discarding recall (0.736 → 0.685), and
   an exposition signal already excludes most of what they catch.

## What follows

The second axis is **family-specific, not global**: disasters ask "did something fail",
topics ask "is this explaining something". That argues for a per-niche-family second
axis rather than one replacement, and it means activating the eleven domains requires
choosing the axis per niche, not swapping one constant.

Implementation is deliberately not in this report. `EVENT` is a shipped constant whose
precision was measured against 298 hand labels; replacing it under the same name on 103
machine labels would put an unmeasured scorer where a measured one stands.
