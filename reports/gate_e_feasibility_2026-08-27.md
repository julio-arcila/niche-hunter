# Gate E feasibility — can Slice 6 run as specified?

**Short answer: not as written.** Two of the four things Gate E needs are missing,
and one of them cannot be fixed by building anything — it is a property of the only
historical dataset available. Slice 6 should be redesigned before it starts, and
the redesign narrows the claim rather than the effort.

Timeboxed spike. No loader was built. Everything below is either from the dataset's
own documentation or measured against this repo.

## What Gate E needs, and what exists

| | state |
|---|---|
| a decision function (`stage`) | **exists** as of Slice 5. Pure, threshold-parameterised, replayable |
| replayable demand history | **exists**. Wikimedia serves from 2015-07-01; YouNiverse starts 2015-01 |
| replayable supply history | **exists** in YouNiverse: 18.9M weekly points, 153,550 channels, 2015-01→2019-09 |
| an outcome label | **does not exist anywhere in the repo** |
| an unbiased universe | **not obtainable from YouNiverse** — see below |

## The universe is not n=5, and that was the wrong worry

The concern going in was that five clusters cannot produce a precision figure. That
concern was misplaced. YouNiverse ships `yt_metadata_en.jsonl.gz`: **73M videos
across ~137k channels, each with `title`, `description` and `tags`** — precisely
the fields `nh/clustering/relevance.py` reads. The scorer is pure, so it runs over
those rows unchanged; verified here on a YouNiverse-shaped row.

So niches are **constructible inside the dataset** rather than limited to our live
seeds. The replay universe is a design choice, not a constraint. Our six seeds are
the production portfolio; the backtest population is whatever the lexicon carves
out of 137k channels.

That removes the objection that would have forced expanding the live seed set for
statistical reasons. Seed expansion is still worth doing — ranks over six clusters
are coarse — but it is no longer a Gate E blocker.

## The real blocker: YouNiverse contains only channels that succeeded

From the dataset README, verbatim:

> We obtained all channels with **>10k subscribers and >10 videos** from
> `channelcrawler.com` in the 27 October 2019.

`nh/features/inputs.py` sets `COHORT_MAX_SUBS = 10_000` and selects channels **at
or below** it. The design pass predicted these two populations would be disjoint.
They are not quite — the weekly series reaches back to when a channel was small, so
a ≤10k cohort *is* reconstructible at a historical date.

**The problem is worse than disjointness.** Every channel in the dataset crossed
10k subscribers by October 2019. A channel that was small in 2016 and stayed small
is not in the data at all. So a replay that asks *"will this small channel emerge?"*
is asking it of a population where **the answer is yes for everyone**, and the base
rate is ~1 by construction.

That is the exact failure Gate E exists to catch — "a precision number that is a
lie" — arriving through the front door rather than through leakage. A backtest run
without noticing this would report excellent precision and mean nothing.

It is not fixable by careful sampling: the channels that would form the negative
class were never crawled. No filter recovers absent rows.

## What YouNiverse *can* answer

Not "will this emerge", but **"among things that did, did our score rank them
correctly?"** — which is a genuine question, and happens to be the one
`docs/METRICS.md` already specifies for `gap`:

> Slice 6 backtests it as one (rank correlation with 90/180-day outcomes, replayed
> against each day's own cluster set).

So the recommendation is to take METRICS.md's framing literally and drop the
roadmap's:

- **Roadmap:** "precision and recall for 'emerging' at 90 and 180 days, stated
  alongside the base rate."
- **Recommended:** rank correlation between the score at date *t* and realised
  growth over the next 90/180 days, with a permutation-test p-value, over a
  population explicitly described as survivorship-limited.

Precision on a binary label needs a credible negative class. Rank correlation does
not, and it is a fair test of the thing the product actually claims: that it can
*order* niches by opportunity. Gate E's decision rule survives intact — if the
correlation is indistinguishable from zero, do not build the dashboard.

## The outcome variable, which is defined nowhere

`ROADMAP.md` and `niche-hunter-PLAN.md` both say "compare to what happened" and
neither says what *happened* means. It has to be written into METRICS.md before any
replay code exists, or it will be chosen after seeing the results.

Proposed, for the rank-correlation framing:

```
outcome.growth_180d
Formula   : log(channel subs at t+180d / channel subs at t), aggregated to the
            niche as the median across its member channels. Log because growth is
            multiplicative and a median because one viral channel should not
            define a niche's outcome.
Inputs    : YouNiverse df_timeseries_en (weekly subs per channel)
Window    : t from 2015-07 (first Wikipedia data) to 2019-03 (last t with a
            180-day outcome inside the data)
Failure   : survivorship — every channel in the population crossed 10k by 2019, so
            this measures relative growth among successes, not emergence.
```

Subscribers rather than views because `delta_views` is contaminated by a channel's
back catalogue, and because subscriber growth is closer to what a creator choosing
a niche cares about.

## Feature availability at a historical decision date

| feature group | replayable | note |
|---|---|---|
| `demand.*` | **yes** | Wikipedia serves from 2015-07-01, per article, quota-free. Any article added to `seed_terms` backfills automatically. |
| `supply.median_views` | **partly** | YouNiverse has per-video `view_count` but only *at crawl time* (Oct 2019), not per week. Views-at-date is not reconstructible; channel-level weekly views are. |
| `supply.uploads_per_week` | **yes** | `delta_videos` and `activity` are weekly. |
| `openness.*` | **compromised** | survivorship, above. |
| `money.*` | **no** | not defined, and no historical source. |
| relevance | **yes** | scorer is pure; title/description/tags are present. |

The `supply.median_views` limitation matters more than it looks: it is the current
input to `scorecards.supply`, and therefore to `gap`, and therefore to `stage`. A
replay would have to substitute a channel-level supply measure and **state that the
backtested `gap` is not the same `gap` the live pipeline computes**. That is a real
threat to the whole exercise and it deserves to be decided deliberately rather than
discovered mid-replay.

## Practical constraints

- **Download**: 2.83 GB (`yt_metadata_helper.feather`, no descriptions) or 13.64 GB
  (`yt_metadata_en.jsonl.gz`, with them). The relevance scorer wants descriptions —
  measured in Slice 4, they take lexical recall from 22% to 42% — so the large file
  is the one that matters. 70 GB free here, at 84% used.
- **Window**: data ends 2019-09-30, so the last usable decision date with a
  180-day outcome is around 2019-03.
- **Wayback CDX** was in the Slice 6 ships list for historical subscriber counts.
  YouNiverse supplies those directly for its own channels; Wayback would only be
  needed for *our* channels, which is a different and much smaller job. Reconsider
  whether it is in scope at all.

## Recommended changes to Slice 6, before it starts

0. **Run the backtest at three relevance thresholds** and report whether the rank
   correlation survives. The niches are constructed by a relevance rule that has
   not been independently validated — kappa 0.943 between two language models shows
   the criterion is unambiguous, not that it is right. The score is stored and the
   cut applied at read time, so this costs a query. Stability across thresholds
   means the bias does not reach the conclusion; instability means the rule is
   producing the result. This is why the human spot-check could be deferred to
   before Slice 7 rather than before Slice 6.
1. **Replace precision/recall with rank correlation** and say why in the report.
2. **Define `outcome.growth_180d` in METRICS.md first**, as every other metric.
3. **Decide the supply substitution explicitly** — a channel-level stand-in for
   `median_views` — and record that the backtested gap differs from the live one.
4. **Drop Wayback** unless a specific question needs it.
5. **State survivorship at the top of `reports/backtest_*.md`**, not in a footnote.
   It is the single fact most likely to make a good-looking number worthless.

## What this does not change

Gate E still decides whether the dashboard gets built. A rank correlation
indistinguishable from zero is the same verdict as precision at the base rate. The
gate is intact; only the instrument changes.
