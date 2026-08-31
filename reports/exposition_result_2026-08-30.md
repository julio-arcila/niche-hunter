# Exposition axis — machine labelling of the 2026-08-30 sample. NOT the ADR-0042 evidence.

> **Read this first.** These 99 rows were labelled by **fable-5**, at the operator's
> explicit and repeated instruction, after the objection below was raised three times.
> The number in this report **cannot ship the axis** and is not the test ADR-0041 and
> ADR-0042 specify. The whole point of that test is a rater independent of the model
> family that wrote the lexicon and the 107 machine labels behind it; agreement between
> two raters of one family cannot detect a bias they share. This is that failure mode,
> executed deliberately and with eyes open.
>
> **Consequence: the 2026-08-30 sample is now consumed**, as the 2026-08-29 one was. A
> genuine result requires a **third draw** and a human — any human, not a specialist.
> `scripts/draw_exposition_sample.py --seed <new>` produces it in one command.

## The result

```
precision        78/99 = 0.7879
95% Wilson       [0.6974, 0.8569]
bar >= 0.70      FAIL   (margin -0.0026; 79/99 would pass)
unsure           subject 1, exposition 2   (threshold for a finding: 9.9)
```

**It fails by one row**, exactly as the retired sample did.

## The thing worth noticing: 78/99 both times

The 2026-08-29 sample, judged under ADR-0041's single compound criterion, also came to
**78/99** — lower bound 0.6974, the same fail by 0.0026. Two different draws, different
seeds, largely different videos, a re-specified criterion, and an identical count.

That is not a result about the axis. Two readings, and they are not exclusive:

1. **The estimate is stable.** ~0.79 is close to the true precision of this scorer as
   this rater sees it, and the two samples agree because they are drawn from the same
   frame and measure the same thing.
2. **The bar sits exactly where this instrument cannot resolve it.** 0.70 as a lower
   bound needs 79 of 99. Landing on 78 twice, from opposite sides of a criterion
   revision, says the true value is near enough to the bar that sampling noise and rater
   noise both straddle it. A test that lands on the knife edge twice is not measuring
   the thing it was built to decide.

Reading 2 is why a human matters more, not less. The retired run recorded ~12 rows the
rater could have called either way; a single flip carries the verdict. Whatever a human
would decide on those dozen rows **is** the answer, and no amount of machine relabelling
substitutes for it.

## What ADR-0042's two-pass split bought, immediately

This is the one thing here that is genuinely informative, because it is a decomposition
rather than a verdict:

```
FAILURE SPLIT     subject 13     exposition 8
```

**The axis under test is not the main problem.** EXPOSITION — whether a video explains,
analyses, teaches or argues — accounts for 8 of 21 failures. **SUBJECT** — whether the
video is about the domain at all — accounts for 13. ADR-0041's compound criterion could
not have told these apart; that is precisely the gain ADR-0042 was written for, and it
paid on the first run.

Subject failures by domain:

| domain | subject fails |
|---|---|
| philosophy-of-science | 5 |
| logic-linguistics-gnoseology | 3 |
| macro-economy | 2 |
| geopolitics, anthropocene-anthropology, biohacking | 1 each |

Exposition failures are scattered — trading 2, then one each across six domains — which
is what a broadly-working axis looks like.

Per-domain precision:

| domain | precision | | domain | precision |
|---|---|---|---|---|
| ai-and-software | 8/9 | | logic-linguistics-gnoseology | 6/9 |
| anthropocene-anthropology | 8/9 | | macro-economy | 7/9 |
| esoterism-spirituality | 8/9 | | trading | 7/9 |
| history-of-ideas | 8/9 | | geopolitics | 7/9 |
| metaphysical-battles | 8/9 | | biohacking | 7/9 |
| | | | **philosophy-of-science** | **4/9** |

**philosophy-of-science is the outlier by a distance**, and its failures are almost
entirely SUBJECT: bone biology, electromagnetic induction, a trading book summary and a
Penrose consciousness theory all scored above 0.55 as philosophy of science. The
recurring shape is that **explaining what science found is being read as philosophy of
science** — a domain-lexicon problem, not an exposition-axis problem.

## This converges with the supply audit, from a different direction

`reports/supply_audit_2026-08-30.md` found philosophy-of-science had the lowest on-niche
share of the eleven (4.3%), the most ballast channels (60.9% with zero on-niche videos),
and the lowest supply score at nearly the highest confidence. This sample now finds it
has the worst above-threshold precision, 4 of 9, failing on subject.

Two independent lines — one over the whole corpus, one over a drawn sample — point at the
same domain lexicon. That convergence is worth more than either alone, and it survives
the machine-label objection, because it does not depend on the precision *number*: it
depends on *which* rows failed and *why*, which the two-pass split records.

## What the instrument itself showed

**Title and description are a sufficient basis.** Unsure came in at 1 (subject) and 2
(exposition) against a 9.9 threshold — nowhere near ADR-0041's ">10% is itself a finding".
Only two rows were genuinely unjudgeable, both with empty or purely promotional
descriptions. The blinding rule is not starving the labeller.

**The archetypes did work.** Cases that were coin-flips under the compound criterion
resolved cleanly under the pre-registered examples — a physics explainer under
philosophy-of-science is a subject failure, an audiobook reading marked "no commentary"
is an exposition failure, an affiliate product review is an exposition failure. That is
the part of ADR-0042 worth keeping when this is re-run with a person.

## What must happen next

1. **A third draw and a human.** New seed, same command, 20 minutes of any person's
   attention. Nothing in this report substitutes for it, and the axis ships nothing
   until it exists.
2. **Do not tune the lexicon against this.** These failures are machine-identified; using
   them to adjust `philosophy-of-science` would compound the circularity rather than
   escape it. The convergence with the supply audit makes that domain the *hypothesis* to
   test first, not a finding to act on.
3. **The bar stays at 0.70.** It has now been missed by one row twice. That is a reason to
   get a real rater, not to move it.
