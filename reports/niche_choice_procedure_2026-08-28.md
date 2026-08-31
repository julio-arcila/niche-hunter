# Choosing 2–4 finalist niches — the decision procedure

Written before the choice, so the reasoning cannot be reconstructed after the outcome.
Designed against a hard constraint the rest of this repo established: **this tool cannot
rank the eleven by profitability.** Profitability is views × RPM − production cost. Gate E
is a powered null on views; `bid_high` is an advertiser *search-ad* bid, not RPM, at
power-of-ten resolution; nothing here measures cost. The procedure's job is to **eliminate
defensibly**, pick a portfolio that survives six months of production, and pre-commit to
the checks that say when it was wrong.

## What the evidence can carry

**Strongest, and LOO-robust:** `philosophy-of-science` has **zero priced keywords in
either market** against 565,500 monthly US searches. For a profitability-only goal that is
categorically different from "low" — it is absent advertiser demand.

**Directional only — a three-tier structure**, which survives leave-one-keyword-out
*across* tiers while within-tier order does not:

```
A  ai-and-software · logic-linguistics-gnoseology · macro-economy · trading
B  biohacking · metaphysical-battles · esoterism-spirituality · anthropocene-anthropology
?  history-of-ideas · geopolitics        <- UNKNOWN, not low
–  philosophy-of-science                 <- unpriced in both markets
```

The `?` tier matters. `geopolitics` rests on **one** priced keyword; `history-of-ideas` is
70% `humanism`, whose US bid is byte-identical to `inflation` (64,083 COP — suspected
close-variant collapse). Reading "unmeasured" as "low" is exactly the mistake class this
repo corrected twice on 2026-08-28.

**Demoted to qualitative texture:** the ~900 discovered videos for philosophy-of-science,
trading, geopolitics and biohacking. Those four were chosen for the *labelling sample*
because their formats differ — not on merit. Nothing in the procedure may cite "the tool
has data on it" as a reason, or a decision made hours ago for unrelated reasons decides
this one by availability.

**Not obtainable at any effort:** actual per-niche RPM; any prediction of views; a
profitability ranking. Anyone producing one is inventing the exchange rate data rule 6
forbids.

## Manual work before choosing

1. **Check the `humanism`/`inflation` row** (~10 min). Until then history-of-ideas is
   unquotable.
2. **Answer the publish-language question first.** The Ads account prices in COP. If the
   channel publishes in Spanish, the US/GB measurement describes a market it will not
   serve, and a `geo=CO`/`MX`/`ES` export (ten minutes) must precede any use of tiers.
3. **Creator RPM disclosures**, ~30–45 min per surviving candidate — the actual quantity
   from the actual auction, unlike `bid_high`. Registered queries, **every** qualifying hit
   in the top 20 (no cherry-picking), n ≥ 5, report **min–median–max, never a point**
   (ROADMAP risk #7). Fewer than 5 disclosures is itself information. Only a **≥2–3×**
   median difference between identically-sampled niches counts as evidence.
4. **Uniform supply eyeball**, ~30 min per candidate — incognito search on the three seed
   keywords; top-20 channel sizes, cadence, faceless/personality, and whether any sub-100k
   channel ranks. Run on **every** survivor, which is what levels the four-vs-seven
   asymmetry.

## The operator's own inputs — veto questions first

Sustainability dominates because it is the only term the operator controls and the only
one measurable before publishing.

1. **The 25-title test.** 30 minutes, 25 concrete titles. Reach 25? Watch 10 yourself?
2. **Episode 1 vs episode 20.** Does #20 get cheaper (reusable format) or not (each video
   a fresh research project)?
3. **The video-#30 question.** Videos 1–29 averaged 200 views. Do you make #30?
4. Unfair advantage — one nameable thing, or "none".
5. Format capability: trading needs live charts; geopolitics needs current-events
   turnaround (a treadmill, not a library); philosophy needs long-form essay writing;
   AI/software demos age in weeks.
6. **YMYL risk posture.** Trading and biohacking invite limited ads and scrutiny — on
   precisely the highest-RPM candidates.
7. Publish language (feeds the manual work above).
8. Cadence commitment for 26 weeks — the number that enters the tripwires.

**1–3 are vetoes.** A niche failing any of them is out regardless of tier.

## The procedure — ordered filters, no composite score

No 1–10 scoring, no weights: this repo forbids invented exchange rates, and that applies
to the human's decision too.

- **Step 0.** Corrections: the humanism row, the language answer, re-file geopolitics and
  history-of-ideas as *value unknown*.
- **Step 1.** Eliminate `philosophy-of-science` on evidence — unless a specific non-ad
  monetization thesis is written down, accepting that the strongest robust finding in the
  repo is against it. **Nothing else is eliminated on value.**
- **Step 2.** Self-assessment vetoes. Record each in one sentence.
- **Step 3.** RPM disclosures + supply eyeball on every survivor, uniformly.
- **Step 4. Portfolio rules.** At least one Tier-A pick. **At least one pick chosen
  primarily on fit, explicitly allowed to be lower-tier** — this is what makes the tier
  assumption falsifiable rather than self-confirming. No more than two from one audience
  cluster (the four philosophy niches fail together; so do macro-economy and trading). At
  most one YMYL-heavy niche. **Never choose between two same-tier niches on their value
  numbers** — that ordering is measured noise.
- **Step 5.** Write the residue: one paragraph per pick giving the deciding reason and what
  would have flipped it. Undocumented judgment is where preference gets laundered.

## Pre-registration, and what six months can actually settle

A dated document before acting, following the Gate E pattern: candidate list, every
elimination with its reason, the picks with their Step-5 paragraphs, the tier table as of
today, per-pick cadence and review horizon (**26 weeks or 20 videos, whichever is later**),
and the tripwires with thresholds filled in.

**Checkable at review:** whether the sustainability self-assessment was accurate (did you
ship?); whether tier evidence was directionally right *for the niches run*, if the picks
span tiers; whether any niche showed a breakthrough signal.

**Not checkable:** whether the seven unchosen would have done better — there is no
counterfactual. Whether a views failure was the niche or the execution.

**Interleave uploads across chosen niches from week 1.** Sequential blocks give the first
niche your worst videos and make its failure uninterpretable.

## Tripwires, per niche, stated in advance

- **Cadence, week 8:** fewer than 4 of any 6 consecutive committed videos shipped, with
  production cost the cause → the sustainability answer was wrong. Drop or restructure
  within two weeks. Earliest and most reliable, because it measures what you control.
- **Audience, at the horizon:** no video reached ≥5× your channel median **and** median of
  the last 10 is below a floor written in advance (suggested 200) → drop.
- **Monetization:** limited-ads on >30% of uploads for two months → drop or pivot format.
  Realized RPM below the bottom of the niche's disclosure range for 3 months at mid views
  → that evidence was wrong for you.
- **Promotion:** a non-chosen niche enters only when a slot opens, only at a scheduled
  review. Thrash is the one-person failure mode.
- **Drop semantics:** stop producing, keep the seed collecting one more month (history is
  the asset), then deactivate.

## Sequencing — nothing in the pipeline gates the choice

The human relevance validation validates the **scorer**, not the niches, and after Gate E
even a validated supply metric carries no predictive claim. Waiting for activation would
be waiting for a number the choice may not use.

**After choosing:** activate only the finalists. Measured 2026-08-28 — 2 finalists cost
4,200 units, 3 cost 4,800, 4 cost 5,400, all beside the live five's 3,000 against a 9,500
budget. The "retire the five" forcing move was an artifact of assuming all eleven
activate; the disaster niches keep compounding their snapshot history.

**File the Reddit application now**, independent of the choice — a form and a wait, and
its lead time is the whole argument for starting before it is needed.

**Not needed for this decision:** activating the unchosen seven; the Slice 9 geo-join
redesign; further market exports beyond the language check; the 0.55 threshold question;
any re-run of Gate E.
