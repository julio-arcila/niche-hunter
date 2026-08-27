# Relevance calibration — 2026-08-27

What a video's `cluster_members.relevance` means, how the thresholds were chosen,
and how well it actually works. Every `supply.*` number in Slice 4 depends on this,
so it gets a precision figure with its base rate rather than an impression.

## The headline, stated plainly

**The stated bar was not met.** The plan required precision ≥ 0.90 with recall ≥
0.70. On labels never used to choose the threshold, the scorer delivers:

| | precision | recall | base rate |
|---|---|---|---|
| tuning half (n=162) | 0.900 | 0.562 | 29.6% |
| **held-out half (n=126)** | **0.781** | **0.694** | **28.6%** |

The 0.90 was reached on the half the threshold was chosen against and **did not
generalise**. 0.781 is the number to quote.

It is still a large improvement on the status quo, and that comparison is the one
that matters for the decision to ship. The current pipeline applies no filter at
all, which is a filter with precision equal to the base rate: **0.286**. The
scorer is 2.7x that purity while keeping 69% of genuinely on-niche videos.

Refusing to filter is not the neutral option. It is choosing a measured-worse
estimator over a measured-better one.

## What was measured

298 videos labelled by hand (300 sampled, 2 skipped as genuinely undecidable),
60 per cluster, stratified and seeded (`nh cluster sample --seed 20260827`).
Criterion written before any row was read: `reports/labelling_criterion.md`.

**Labeller: claude-opus-5 — the same system that wrote the lexicon.** This is the
weakness in this report. The scorer's author is also its judge, so these numbers
measure self-consistency as much as correctness, and they should not be read as an
independent evaluation until the spot-check below is done. Mitigations that do
apply: the scorer's output was absent from the labelling file, the sample was
interleaved across niches in randomised order, and the criterion was fixed in
advance. Mitigation that does not: the question "is this about the niche" cannot be
asked with the niche hidden, so the labelling was never blind to *that*.

**Outstanding: an independent spot-check of 50 rows**, to be labelled by the
operator without seeing these labels. The agreement rate on those 50 is what will
make — or break — the 0.781 figure. Until it exists, treat every number here as
provisional.

## Threshold discipline

Labels were split in half deterministically by `sha256(video_id) % 2`, so the split
does not move when the scorer does. `RELEVANCE_HIGH` was chosen on the tuning half
by a rule fixed in advance — the smallest threshold reaching precision 0.90 — and
then measured once on the held-out half. Chosen value: **0.55**.

Three states, not two:

| state | rule | held-out on-niche rate | n |
|---|---|---|---|
| on-niche | `relevance >= 0.55` | **78.1%** | 32 |
| undecided | `0 < relevance < 0.55` | 37.5% | 16 |
| noise | `relevance == 0` | 6.4% | 78 |

Against a 28.6% base rate, the top and bottom bands separate strongly and the
middle band carries almost no information — which is why it is excluded from both
numerator and denominator wherever a metric counts videos, and lowers confidence
instead, rather than being guessed into one side.

## Iteration count, because it affects how much to trust this

Three revisions were made against these labels. Held-out precision by revision:

| revision | change | held-out precision | recall |
|---|---|---|---|
| 1 | domain lexicon only | 0.62 (best F1) | — |
| 2 | + event axis | 0.774 | 0.667 |
| 2b | + domain failure verbs | 0.774 | 0.667 |
| 3 | + suffix matching | **0.781** | **0.694** |

Revision 2 is the substantive one and it came from reading the errors, not from
moving a number: a domain-only scorer's false positives were **all the same
shape** — on-domain, off-niche. "Changi Airport Plane Spotting". "Why Concrete
Needs Steel Reinforcement". "Settlement vs Adjudication: Quick legal breakdown".
"What's Swiggy's Secret?" Every one is squarely inside its niche's vocabulary and
squarely outside the niche, because **the niche is domain AND event** and a domain
lexicon can only see half of it.

Revision 2b moved no measured number at all, which is the evidence that it was a
correctness fix rather than a tuning step. Iteration stopped at three: further
passes over 298 labels would be fitting noise.

## Negative control — does it measure topic, or documentary-ness?

Mean score of each cluster's videos against every lexicon. If a niche's text scored
as well against a foreign lexicon, the scorer would be measuring genre and the
slice would have failed.

| videos from | aviation | corporate | court | engineering | maritime | margin |
|---|---|---|---|---|---|---|
| aviation-disasters | 0.252 | 0.065 | 0.057 | 0.060 | 0.088 | **2.9x** |
| corporate-collapse | 0.032 | 0.188 | 0.094 | 0.084 | 0.013 | **2.0x** |
| court-cases | 0.016 | 0.067 | 0.223 | 0.032 | 0.010 | **3.3x** |
| engineering-failures | 0.061 | 0.084 | 0.073 | 0.183 | 0.065 | **2.2x** |
| maritime-disasters | 0.055 | 0.059 | 0.081 | 0.086 | 0.175 | **2.0x** |

**Passes for all five**, by 2.0x-3.3x, diagonal dominant in every row. The
off-diagonal structure is semantically sensible rather than noise: corporate-collapse
videos score second-highest against the court-cases lexicon, which is what you would
expect when fraud reaches trial.

## What it decides about the real corpus

| cluster | videos | on-niche | undecided | noise | unscorable |
|---|---|---|---|---|---|
| aviation-disasters | 3,067 | 899 (29.3%) | 231 (7.5%) | 1,771 (57.7%) | 166 (5.4%) |
| corporate-collapse | 3,613 | 627 (17.4%) | 558 (15.4%) | 2,337 (64.7%) | 91 (2.5%) |
| court-cases | 2,395 | 520 (21.7%) | 393 (16.4%) | 1,445 (60.3%) | 37 (1.5%) |
| engineering-failures | 3,406 | 494 (14.5%) | 492 (14.4%) | 2,020 (59.3%) | 400 (11.7%) |
| maritime-disasters | 2,418 | 437 (18.1%) | 264 (10.9%) | 1,662 (68.7%) | 55 (2.3%) |
| **total** | **14,899** | **2,977 (20.0%)** | 1,938 (13.0%) | 9,235 (62.0%) | 749 (5.0%) |

Internal consistency check: recall 0.694 x base rate 28.2% = 19.6%, against a
measured on-niche share of 20.0%. The two agree, which they need not have.

**This is the finding the slice exists for.** Only 20% of the videos currently
feeding `supply.*` and `money.*` are about the niche they are filed under. The
cause is structural: `cluster_members` assigns *channels* to seeds and videos
inherit their channel's cluster, so one plane-crash video pulls a channel's entire
catalogue into aviation-disasters.

`unscorable` is 5.0% overall and 11.7% for engineering-failures — videos with no
title text, no letters, or a title under 50% Latin script. **None of the 10
unscorable rows in the labelled sample was truly on-niche**, so the script gate is
not silently discarding non-English niche content at a measurable rate. It is still
excluded from both sides rather than counted as noise, because absent is not zero.

## Known failure modes

- **It measures our lexicon as much as the corpus.** `supply.on_niche_share` moves
  if the lexicon changes, and `LEXICON_VERSION` is recorded per row so a shift can
  be attributed rather than guessed at.
- **Precision 0.781 means roughly one in five "on-niche" videos is not.** Every
  metric built on it inherits that, which is why they gain a relevance-coverage leg
  in their confidence rather than being presented as clean.
- **Recall 0.694 means roughly three in ten genuine niche videos are dropped.** If
  those are systematically different — shorter titles, non-English, less
  conventional vocabulary — then the surviving pool is biased, not merely smaller.
  Untested. The most likely direction is against non-English and against
  minimal-metadata uploads.
- **English-only.** 10.5% of titles are non-Latin script and are excluded by
  construction, so this pipeline currently cannot see a non-English niche at all.
- **The labeller is not independent.** See above; the spot-check is outstanding.

## Reproducing this

```bash
uv run nh cluster sample --out reports/relevance_sample.jsonl --per-cluster 60 --seed 20260827
# label the `label` field: true / false / null to skip
uv run nh cluster import reports/relevance_labels.jsonl --labeller <you>
uv run nh cluster calibrate           # prints every table above
```

## Sensitivity — is the filter producing the ranking?

Cluster ordering on `supply.median_views` across relevance thresholds. If the
ordering moved with the threshold, the filter rather than the data would be
producing it, and no amount of precision would make that acceptable.

| threshold | ordering (lowest median first) |
|---|---|
| 0.40 | corporate < maritime < engineering < aviation < court |
| 0.45 | corporate < maritime < engineering < aviation < court |
| 0.51 | **maritime < corporate** < engineering < aviation < court |
| **0.55 (chosen)** | corporate < maritime < engineering < aviation < court |
| 0.60 | corporate < maritime < engineering < aviation < court |
| 0.65 | corporate < maritime < engineering < aviation < court |
| 0.70 | **maritime < corporate** < engineering < aviation < court |

**The top three are stable at every threshold tested.** Only corporate-collapse
and maritime-disasters swap, and their medians are 979.5 and 1,000.5 — within 2%
of each other. Their relative order is not determined by the data and should not be
read as a finding at any threshold.

## Effect on the published numbers

Applying the filter changed every supply and money value, and changed **no supply
rank**:

| metric | aviation | corporate | court | engineering | maritime |
|---|---|---|---|---|---|
| median_views before | 323,768 | 933 | 330,181 | 7,729 | 1,696 |
| median_views after | 209,845 | 980 | 408,594 | 7,729 | 1,000 |
| uploads/wk before | 24.25 | 23.00 | 30.00 | 24.50 | 14.75 |
| uploads/wk after | 20.50 | 17.25 | 20.00 | 18.25 | 10.50 |
| midroll share before | 0.373 | 0.368 | 0.536 | 0.252 | 0.337 |
| midroll share after | 0.397 | 0.383 | 0.690 | 0.314 | 0.421 |

`gap` is unchanged for all five clusters (0.0, +0.5, 0.0, −0.5, 0.0) because the
supply *ordering* survived the filter. That is a stronger result than a changed gap
would have been: the ranking was not an artifact of contamination.

What did change is **confidence**, downward everywhere — `gap_confidence` fell from
0.35–0.47 to 0.16–0.27. The numbers did not get less true; we found out they rest on
a filter whose precision is 0.781, and the confidence column now says so.

`supply.on_niche_share`, the new metric:

| cluster | on-niche share | confidence |
|---|---|---|
| aviation-disasters | 33.7% | 0.871 |
| court-cases | 26.5% | 0.820 |
| corporate-collapse | 21.2% | 0.820 |
| maritime-disasters | 20.8% | 0.868 |
| engineering-failures | 19.6% | 0.738 |

Aviation is the cleanest niche and engineering the dirtiest, which matches where
the seed keywords are most and least specific.
