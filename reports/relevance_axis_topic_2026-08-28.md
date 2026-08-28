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

## Result

Winner chosen on a random half and scored on the other half, 200 splits:

```
chosen 182/200   B  domain x exposition      held-out  P 0.936  R 0.682  F1 0.788
chosen  11/200   D  B + negative filter      held-out  P 0.961  R 0.570  F1 0.713
chosen   5/200   A  domain alone (baseline)  held-out  P 0.616  R 0.761  F1 0.681
chosen   2/200   C  domain + negative filter held-out  P 0.565  R 0.639  F1 0.600
```

**An exposition axis is the topic-domain analogue of the event axis.** Within this
corpus it takes held-out precision from 0.616 to 0.936, costing recall 0.761 → 0.682.

## Three things this does not say

1. **The precision is not comparable to the 0.62 / 0.781 figures on the disaster
   corpus.** This sample's base rate is **0.670**, inflated by stratifying toward
   high-domain-score rows; theirs was 0.286. Precision moves with base rate, so only the
   within-corpus comparison (0.616 → 0.936, same rows, same labels) is valid.
2. **Recall 0.682 means roughly a third of on-niche videos are missed.** For a tool that
   surfaces evidence for a human, that is a real cost and not obviously the right
   trade — the threshold is a product decision, not a measurement.
3. **The negative filters did not work as scoring features**, though they work well as
   labelling rules. Selling and tool markers alone barely move precision (0.616 → 0.565
   held-out), and combined with exposition they buy 0.025 precision for 0.112 recall.
   The rules that help a rater decide are not the same as the features that help a
   scorer, and the criterion's own FALSE clauses are the evidence.

## What follows

The second axis is **family-specific, not global**: disasters ask "did something fail",
topics ask "is this explaining something". That argues for a per-niche-family second
axis rather than one replacement, and it means activating the eleven domains requires
choosing the axis per niche, not swapping one constant.

Implementation is deliberately not in this report. `EVENT` is a shipped constant whose
precision was measured against 298 hand labels; replacing it under the same name on 103
machine labels would put an unmeasured scorer where a measured one stands.
