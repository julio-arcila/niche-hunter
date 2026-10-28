# The niche choice — pre-registration, 2026-10-28

Written under `reports/niche_choice_procedure_2026-08-28.md`, which is the operator's
document and whose rules bind this one: **no composite score, no weights, no ordering within
a value tier, and no claim that this tool ranked anything.** Step 0 was discharged in
`reports/niche_choice_step0_2026-10-22.md`. This document records Steps 1–5 and the
tripwires, and it is dated before any video is made so the reasoning cannot be reconstructed
after the outcome.

**What this is not.** It is not a prediction of views. Gate E's niche-grain null stands and
ADR-0068 closed the re-test as arithmetically unreachable at ten clusters. Every number below
is **elimination evidence and texture about the supply side as it exists today**, never a
forecast and never an ordering.

## Step 2 — the operator's vetoes, recorded 2026-10-28

| question | answer |
|---|---|
| **25-title test** | Passes for all four groups presented. **Eliminates nothing.** |
| **Episode 1 vs episode 20** | **Cheaper — a reusable format.** This is the binding answer below. |
| **Video #30 after 29 videos at 200 views** | **Makes it anyway.** Tolerates a long flat start. |
| **Publish language** | **English.** The US Keyword Planner reading describes the market that will be served, so the Step-0 value table applies as measured. |

The vetoes were the procedure's strongest filter and they removed nothing, which is itself
the finding: **the choice is not constrained by what the operator can sustain, so it falls
entirely to Step 3/4 evidence.** The "cheaper at #20" answer is load-bearing from here on —
it favours a *library* format (a repeatable template over a fixed subject space) against a
*treadmill* (current events, product demos) and that distinction eliminates more candidates
below than any number in the value column.

## Step 4 measurement — the supply eyeball, run off the corpus

The procedure specifies an incognito top-20 search, ~30 min per candidate. **This is not
that, and the substitution is stated rather than glossed.** It is measured against the
project's own corpus: on-niche (relevance ≥ 0.55) long-form videos published **30–120 days
ago** — old enough to have settled — from channels under **10,000 subscribers**, views as
`MAX` over all snapshots, subscribers as the newest non-NULL reading.

It answers a narrower and more useful question than the manual eyeball: **what does a small
channel's video actually get in this niche?** It is uniform across all ten, which is the
property the procedure wanted from the eyeball and the reason it required running on every
survivor.

| niche | videos | par (median) | p75 | p90 | top-20 from sub-100k |
|---|---|---|---|---|---|
| **metaphysical-battles** | 769 | **157** | **1,030** | **6,733** | 6/20 |
| geopolitics | 3,486 | 97 | 638 | 2,977 | 1/20 |
| trading | 6,122 | 79 | 295 | 1,351 | 4/20 |
| history-of-ideas | 313 | 74 | 443 | 1,818 | 7/20 |
| esoterism-spirituality | 612 | 72 | 267 | 780 | 4/20 |
| anthropocene-anthropology | 1,057 | 63 | 262 | 1,351 | **13/20** |
| ai-and-software | 5,671 | 61 | 175 | **500** | 4/20 |
| logic-linguistics-gnoseology | 635 | 59 | 191 | 868 | 8/20 |
| macro-economy | 2,271 | 26 | 100 | 478 | 0/20 |
| biohacking | 726 | 33 | 186 | 1,133 | 2/20 |

**Its known bias, stated before it is used.** The corpus is a preimage of its own discovery
queries — `order=date` lineage over-samples recent uploads by small channels, which is
exactly the population being measured here, so the sample is dense where it needs to be. It
under-samples channels that never surface in a seed query at all. The `top-20 from sub-100k`
column is therefore "of the most-viewed videos *this corpus saw*", not "of YouTube's search
results", and is read as openness texture, not as a ranking.

### The one result that changes the obvious answer

**`ai-and-software` has the highest advertiser bid (33,834), the largest demand of the ten
(5.7M monthly US searches) — and the worst upside tail of all ten.** A sub-10k channel's
90th-percentile video reaches **500 views**, measured on 5,671 settled videos, against 6,733
for metaphysical-battles and 2,977 for geopolitics. It also carries the largest supply pool
in the corpus at 50,522 member videos, more than double any other niche.

High demand, high advertiser value, enormous incumbent supply, and small channels do not
break through. That is a demand–supply gap pointing the wrong way, and it is the strongest
thing this measurement produced. **It is elimination evidence, not a prediction** — the claim
is about the niche's current occupancy, not about what any particular channel would do.

## Step 1 and Step 3 — eliminations, each with its reason

| niche | out on | reason |
|---|---|---|
| `philosophy-of-science` | Step 1, already executed | Retired 2026-08-31 (ADR-0044) as an editorial choice. The procedure's strongest robust finding — zero priced keywords against 565,500 searches — was **not** the stated reason and is not retro-fitted as one. |
| `macro-economy` | Step 4, supply | Worst par of the ten (26) and **0 of 20** top videos from a sub-100k channel. The top is closed. |
| `geopolitics` | Step 4, supply + format | **1 of 20.** Good par (97) and tail (2,977), but the top is owned by incumbents, and current-events turnaround is a treadmill — it contradicts the binding "cheaper at #20" answer. |
| `ai-and-software` | Step 4, supply | p90 of 500 on the largest supply pool measured. See above. Highest value and highest demand, and that is not enough. |
| `biohacking` | Step 4, supply + YMYL | Par 33, 2 of 20, and YMYL scrutiny on a niche with no compensating value reading (11,950, lower band). |
| `esoterism-spirituality` | Step 3, value | **The only value-based elimination the evidence supports.** 8,130 against ai-and-software's 33,834 and trading's 31,503 is the single ≥2–3× gap in the table that survives the procedure's own rule. |
| `history-of-ideas` | Step 3, demand | 160,500 monthly searches — an order of magnitude under most of the field and >6× below the median niche. Mid-band on value (19,042) and decent on supply (7/20, par 74); eliminated on demand alone. |
| `trading` | Step 4, format + YMYL | Live charts contradict the reusable-format answer; YMYL limits ads on the highest-bid survivor. Tier A and a genuine loss — see the residue. |
| `metaphysical-battles` | Step 4, **format, at the title read** | Best measured economics of all ten, and the format behind them is not makeable. See the section below. |

Survivors: **`anthropocene-anthropology`**, **`logic-linguistics-gnoseology`**.

## The title read, which overturned the measurement

The aggregate chose `metaphysical-battles` and a 43× median-to-p90 ratio is the shape that
demands a look at what the tail is actually made of. **Its top ten settled small-channel
videos are debate re-cuts of other creators' content** — "DEMOLISHES", "SHREDS",
"HUMILIATES", "TAKES DOWN", "STUNS" — with three of the ten from a single 6,480-subscriber
channel and two more from a pair of channels re-cutting the same two debaters.

That tail is real and it is not available. It is a clip format over other people's recorded
debates, which is not a library the operator builds, is not what the "cheaper at #20" answer
described, and carries reused-content monetization exposure on top. **The p90 of 6,733
measures that format's reach, not the niche's.**

The titles are an impression; the concentration is the measurement, and it agrees. Taking
each niche's **top decile of settled small-channel videos** and asking how many channels it
comes from:

| niche | top-decile videos | distinct channels | videos per channel | top 5 channels hold |
|---|---|---|---|---|
| metaphysical-battles | 76 | **21** | **3.6** | **62%** |
| anthropocene-anthropology | 105 | 55 | 1.9 | 32% |
| logic-linguistics-gnoseology | 62 | 36 | 1.7 | 35% |

`metaphysical-battles`' upside is **twice as concentrated per channel** as either other
finalist, and five channels hold nearly two-thirds of it. A newcomer does not inherit a tail
that belongs to twenty-one channels running one repeatable clip format; they inherit the par,
and the par is where the other niches are competitive. `anthropocene-anthropology`'s tail is
spread across 55 channels — the most diffuse of the three, which is what "reachable" looks
like.

`anthropocene-anthropology`'s tail, by contrast, is made of precisely the format the veto
answer described — repeatable explainers over a fixed subject space, from channels between
313 and 7,680 subscribers:

```
334,120 views   3,530 subs  Why Humans Live So Much Longer Than Most Wild Animals
257,211 views   7,680 subs  Scientists Ran Geronimo's DNA Against Every Native Tribe in America
 69,600 views     313 subs  If Humans Came From Apes, Why Are Apes Still Here?
 24,003 views   3,360 subs  What Happened To The Other 8 Human Species?
 22,131 views   2,700 subs  The Entire History of Human Evolution Explained Slowly (For Sleep)
```

`logic-linguistics-gnoseology`'s tail is the weakest of the three and partly off-niche: its
best small-channel video reaches 29,034, and the top ten include two reaction videos, a 1922
public-domain audiobook, a cloud-computing explainer and a video in Odia. Its on-niche share
is 17.3%, so the cluster is admitting material the niche does not describe, and its 8-of-20
openness reading inherits that doubt.

**This is the fourth time in this project that a green aggregate was overturned by reading
ten rows of real output.** The measurement was not wrong — par 157 and p90 6,733 are correct
— it was answering a question one step away from the one being asked. Recorded here because
the next person to read the supply table will see metaphysical-battles at the top of it.

## Step 4 — the portfolio

**Two picks, not three.** The procedure allows 2–4. At one video per week, three niches
interleaved from week 1 gives each a video every three weeks, and 20 videos per niche takes
60 weeks — past the 26-week review horizon, so a three-niche portfolio could not be judged at
its own horizon. Two is what the horizon can carry.

### Pick 1 — `anthropocene-anthropology` (Tier B, chosen on fit)

The procedure's required pick "chosen primarily on fit, explicitly allowed to be lower-tier",
which is what makes the tier assumption falsifiable rather than self-confirming. It is the
**most open niche of the ten** (13 of 20 top videos from sub-100k channels, against 8 for the
next), its tail is made of the exact format the veto answer described, and it carries 1.11M
monthly searches at a mid-band value reading of 19,246.

### Pick 2 — `logic-linguistics-gnoseology` (Tier A)

The Tier-A requirement, and the only Tier-A niche that survives the format answer. **Held
with explicitly lower confidence than Pick 1** after the title read, which is the honest
position and is recorded rather than smoothed over.

### The portfolio rules, checked

| rule | status |
|---|---|
| At least one Tier-A pick | ✓ `logic-linguistics-gnoseology` |
| At least one pick chosen primarily on fit, allowed to be lower-tier | ✓ `anthropocene-anthropology`, Tier B |
| No more than two from one audience cluster | ✓ one philosophy, one anthropology — **different clusters**, so the concentration risk the procedure named does not apply |
| At most one YMYL-heavy niche | ✓ zero |

## Step 5 — the residue

**`anthropocene-anthropology`.** Deciding reason: it is the only niche where the openness
reading and the title read agree. 13 of 20 top videos from sub-100k channels is the highest
of the ten by a wide margin, and unlike `metaphysical-battles` the videos behind that number
are makeable — template explainers over a fixed subject space, from channels as small as 313
subscribers reaching five and six figures. Its par (63) and p90 (1,351) are mid-field and
that is accepted: what is bought here is *reachability of the top*, which is the quantity the
operator's "I'd make #30 anyway" answer says matters more than the floor. **What would have
flipped it:** a tail made of a format the operator would not produce — the exact test
`metaphysical-battles` failed, applied to this niche and passed.

**`logic-linguistics-gnoseology`.** Deciding reason: the Tier-A slot, and nothing else
survived to fill it. Tier A on value (25,658), 1.6M searches, library-shaped, 8 of 20 on
openness. **This is the weakest pick in the document and is labelled as such:** its tail is
the thinnest of the three finalists (best small-channel video 29,034), its top ten include
off-niche material, and its 17.3% on-niche share means the cluster is admitting videos the
niche does not describe. **What would have flipped it:** any Tier-A niche with a clean
supply reading. There was none — trading went out on format and YMYL, ai-and-software on a
p90 of 500, macro-economy on 0 of 20. **That absence is itself a finding:** on this corpus,
advertiser value and newcomer reachability point in opposite directions across all four
Tier-A niches. If the Tier-A requirement is relaxed, `history-of-ideas` (par 74, p90 1,818,
7 of 20, mid-band value, but 160k searches) is the better second pick on supply.

**`metaphysical-battles`, the measurement's choice, rejected.** It led every supply column —
par 157, p75 1,030, p90 6,733, all ≥1.6× the next niche. Out because the format behind those
numbers is clip-farming other creators' debates. **What would have flipped it:** finding that
tail distributed across many channels running many formats rather than concentrated in a few
running one. Measured, and it was not: 21 channels hold its top decile at 3.6 videos each,
against 55 channels at 1.9 for the pick.

**`trading`, the strongest thing not picked.** Tier A, 31,503, and par 79 / p90 1,351 — a
respectable supply reading, better than either pick on par. It is out on the operator's own
format answer and on being the one YMYL survivor. **What would flip it:** a format thesis
that does not require live charts, at which point it displaces `logic-linguistics-gnoseology`
on value and demand.

**`ai-and-software`, the obvious pick that the evidence argues against.** Out on a p90 of 500.
**What would flip it:** a sub-niche inside it with a different occupancy profile. The tool
cannot currently find one — Slice 10's sub-niche discovery has no consumer, and ADR-0068
means no sub-niche ranking could be validated at this portfolio size either.

## Cadence, horizon and tripwires

| | |
|---|---|
| Cadence | **1 video per week per niche, interleaved from week 1** — *the operator's own commitment number is the one input Step 2 did not record; this is the planning default and the tripwires below work at any cadence.* |
| Interleaving | Alternating weeks. Sequential blocks give the first niche the worst videos and make its failure uninterpretable. |
| Review horizon | **26 weeks or 20 videos per niche, whichever is later.** |
| Quota | **No action needed.** Both picks are already active and collecting; the 08-28 note about activating finalists assumed a retired starting state. |

### Tripwires, thresholds filled in

- **Cadence, week 8.** Fewer than 4 of any 6 consecutive committed videos shipped, with
  production cost the cause → the sustainability answer was wrong. Drop or restructure within
  two weeks. Earliest and most reliable, because it measures what the operator controls.
- **Audience, at the horizon.** No video reached ≥5× the channel median **and** the median of
  the last 10 is below the niche's own measured par:
  - `anthropocene-anthropology`: **63 views**
  - `logic-linguistics-gnoseology`: **59 views**

  These replace the procedure's suggested 200, which was a placeholder nothing measured. The
  floor is each niche's own small-channel par from the table above, so the test is "below par
  for a small channel *here*" rather than against a number carried in from nowhere. **A floor
  of 200 would have fired on both picks regardless of performance** — it sits 3.2× and 3.4×
  above the par a sub-10k channel actually achieves in them, measured on 1,057 and 635
  settled videos. Setting a tripwire above the measured par guarantees it fires, which makes
  it a countdown rather than a test.

  The par is a **property of the corpus on 2026-10-28** and will drift. Re-measure it at the
  review rather than carrying these two integers forward as constants — the repo has made the
  opposite mistake three times with the watchlist unit cost.
- **Monetization.** Limited ads on >30% of uploads for two months → drop or pivot format.
  Neither pick is YMYL, so this is not expected to fire; it stays because it is cheap.
- **Realized RPM.** No disclosure range exists to compare against — Step 3 returned **n = 0**
  and the reason was structural (`reports/niche_choice_step0_2026-10-22.md`, addendum). So
  this tripwire **cannot be armed**, and recording that is better than arming it against
  marketing-blog numbers. First realized RPM at mid views becomes the baseline instead.
- **Promotion.** A non-chosen niche enters only when a slot opens, only at a scheduled review.
  Named first alternate: **`history-of-ideas`** — the best supply reading among the eliminated
  (par 74, p90 1,818, 7 of 20), out only on 160k monthly searches, so it is the pick to
  revisit if demand turns out not to bind. Thrash is the one-person failure mode.
- **Drop semantics.** Stop producing, keep the seed collecting one more month (history is the
  asset), then deactivate.

## What is checkable at the review, and what is not

**Checkable:** whether the sustainability self-assessment was accurate — did the videos ship?
Whether the two picks' measured par predicted anything about realized views. Whether either
niche showed a breakthrough.

**Not checkable:** whether the eight unchosen would have done better. There is no
counterfactual and none will be manufactured. Whether a views failure was the niche or the
execution — the procedure said this on 2026-08-28 and it is still true.

**The tier assumption is only partly falsifiable here.** The procedure wanted a portfolio
spanning tiers so the tier evidence could be checked, and this one does — Tier A and Tier B,
one pick each. But with n = 2 the check is anecdote, not evidence, and will be reported as
such.

## Provenance

Measured read-only against `data/niche_hunter.db` on 2026-10-28, after that day's nightly
completed, by `scripts/` equivalents of the three queries recorded in this session: the
90-day eyeball, the 30–120-day settled floors, and the small-channel title read. The value
and demand columns come from `reports/niche_choice_step0_2026-10-22.md` and rest on a single
Keyword Planner export of **2026-07-31**, now 89 days old, whose confidence under ADR-0058 is
**~0.34**. Nothing in this document turns on ordering within the value band, which is the
only use that staleness would invalidate.
