# Cross-family inter-rater pass on the relevance rule — 2026-08-28

## What this is, and what it is not

**This is not the human spot-check.** The deferral registered in `nh/jobs/deferrals.py`
("relevance rule — independent human validation") **remains open and unmet.** A model
labelling rows that a model labelled does not become independent by changing which
model; the value of the registered check is that a person is the judge, and nothing
here supplies that.

What this *is*: a **cross-family inter-rater pass**. All 298 existing labels in
`relevance_labels` come from `claude-opus-5` — the same system that wrote the lexicon
— and the reassurance usually quoted alongside them (kappa 0.943) was measured against
a second model of the same family. This run puts a different model family on the same
50 rows under the same written criterion, which bounds one specific thing: how much of
the measured precision is an artifact of Claude agreeing with Claude.

## Method

`fable-5`, in a **fresh context with no prior exposure to this repository**, was given
exactly two files: the 50 rows stripped to `{niche, title, description}`, and
`reports/labelling_criterion.md`. It was explicitly forbidden from reading
`nh/clustering/lexicon.py`, `nh/clustering/relevance.py`, any relevance score, the
`relevance_labels` table, prior reports, or the database, and asked to declare whether
it had. It declared it read those two files and nothing else, and its tool log is
consistent with that.

Two controls beyond blindness. It was told to **judge every row on its own and never
reason about what proportion should be relevant** — any such balancing destroys the
measurement. And it was asked to flag rows where the *rule itself* underdetermines the
answer, which is the one output that does not depend on trusting the rater.

Labels: `reports/spotcheck_50_fable.jsonl` (with the paired `claude-opus-5` label and
the stored relevance score on each row).

## Agreement

```
n = 50          raw agreement 48/50 = 96.0%
                both TRUE 10 · both FALSE 38 · fable-only 1 · claude-only 1

Cohen's kappa   0.883   cross-family
                0.943   within-family (previously measured)

high-confidence rows (43 of 50):  43/43 = 100.0% agreement
```

**Every disagreement is a row `fable-5` itself flagged low-confidence, and both score
0.000** — far below the frozen 0.55 cut. Neither touches any precision figure.

## Precision at the frozen threshold — identical under both raters

```
                   above 0.55    precision   recall    TP  FP  FN
claude-opus-5           8          0.875      0.636     7   1   4
fable-5                 8          0.875      0.636     7   1   4
```

The rate does not move when the rater changes family. That is the finding this run was
run for, and it is a real if narrow reassurance: **the 0.781 held-out precision is not
visibly an artifact of same-family labelling.**

## The result this run actually turns on — the sample is too small to bound anything

```
precision 7/8 = 0.875    95% Wilson interval [0.529, 0.978]
```

A 50-row sample stratified across five niches yields **8 rows above the relevance
threshold**, and 8 is the entire denominator of the precision estimate. The interval
spans from "worse than no filter is tolerable" to "near-perfect."

**This is a defect in the deferral's design, not in the labelling.** The registered
check asks a human for 50 rows; 50 rows cannot answer the question it is registered to
answer, however careful the human is. Whoever eventually sits down to it should be
handed a sample **drawn from above the threshold**, not a uniform sample of the corpus
— the quantity under test is precision at 0.55, and rows scoring 0.000 contribute
nothing to it. Roughly 60–100 above-threshold rows would bring the interval to
something a gate could act on.

## Gaps the criterion leaves open

`fable-5` flagged 7 of 50 rows as underdetermined *by the rule*. These stand
independently of whether its labels are any good:

- **The maritime / engineering-failures boundary is undefined** (n=19, General Slocum).
  The criterion fixes rail-vs-maritime and space-vs-aviation but never says whether
  "engineering failures" includes ship disasters with mechanical causes. One of the two
  disagreements sits exactly here.
- **"Landmark" is never operationalised** (n=42, n=6). The niche is *Landmark court
  cases*; the rule body makes any trial coverage TRUE, so current coverage of ordinary
  cases passes the written rule while arguably failing the niche name.
- **Decline versus insolvency** (n=36). The corporate-collapse edge call requires
  "failure, fraud or insolvency"; it does not say whether serious decline short of
  insolvency counts.
- **Simulator recreations of real incidents** (n=43). "Gaming" is categorically FALSE,
  but this row narrates a real engine failure rendered in a simulator. **This is the one
  low-confidence row above the 0.55 threshold**, so it is the single place where rule
  ambiguity touches the precision number. Both raters resolved it TRUE.
- **The skip clause covers non-English but not illegible English** (n=38, title
  "english today 20110328", description "2000-08-22"). A row can be unlabelable in
  English and the rule offers no `null` for it.

## A schema finding, surfaced by trying to store this

`relevance_labels.video_id` carries a **UNIQUE constraint**, so the table can hold
exactly one label per video and **physically cannot store an inter-rater study** — in
the project whose documented top risk is single-labeller bias. The insert was refused
and rolled back; the live table is unchanged at 298 rows, and these labels live in
`reports/` instead.

The fix is a migration moving the unique key to `(video_id, labeller)`, which is what
the column exists for. It is not urgent and was deliberately not done here: an
unplanned schema change while the Gate E chain is running is the wrong trade. Recorded
for the fix plan.

## What remains open

The human pass. Unchanged, still registered, still the most consequential unscheduled
hour of work in the project — and now with a concrete instruction attached: **sample
from above the threshold, and take enough rows to make the interval mean something.**
