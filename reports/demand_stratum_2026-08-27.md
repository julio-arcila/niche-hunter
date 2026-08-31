# Demand stratum — topic pages or event articles?

`scorecards.demand` is a percentile rank of `demand.wiki_weekly_views`, and `gap`
is that rank minus the supply rank. Which Wikipedia articles feed it is therefore
load-bearing for the product's headline number. Slice 3 curated three topic-level
index articles per niche. This is what happened when the question was asked
properly.

## The finding

**The two strata rank the niches almost exactly in reverse. Spearman rho = −0.70.**

| niche | topic (3 articles) | event (20 articles) | event/topic |
|---|---|---|---|
| maritime-disasters | 151,730 | **1,582,040** | 10.4x |
| corporate-collapse | 201,248 | **1,301,299** | 6.5x |
| engineering-failures | 65,136 | **749,705** | 11.5x |
| true-crime-trials | — | 679,021 | — |
| aviation-disasters | **546,443** | 203,906 | 0.37x |
| landmark-court-cases | **1,168,816** | 44,462 | 0.04x |

12-month user pageviews to 2026-08-25, from collected `demand_snapshots`.

- ordering by **topic**: landmark > aviation > corporate > maritime > engineering
- ordering by **event**: maritime > corporate > engineering > aviation > landmark

The first and last places swap in both directions. Under the topic stratum,
landmark-court-cases is the highest-demand niche in the portfolio; under the event
stratum it is the lowest, by a factor of 26.

## What the two are actually measuring

They are not two estimates of one quantity, and the correlation says so. Topic
articles are **reference pages** — *Supreme Court of the United States*,
*Shipwreck* — and their traffic is standing, navigational, school-calendar-driven
interest in a subject. Event articles are **specific occurrences**, and their
traffic is episodic attention to things that happened.

That distinction is the finding, not a nuisance to resolve. A niche can have large
standing interest and few notable events (landmark-court-cases: 1.17M topic, 44K
event) or the reverse (maritime: 152K topic, 1.58M event). Those are different
kinds of niche and the product should be able to tell them apart.

Hence `demand.event_topic_ratio` as a metric in its own right: a news-drivenness
versus evergreen proxy, obtained free from data already collected, and one of the
`cost_risk.*` measures that otherwise has no source at all.

## Why the sample is random, and what that already caught

The pool is enumerated from a Wikidata class where one is populated enough and
from category membership otherwise; from that pool, **20 articles are drawn
uniformly at random with the seed recorded** (`--seed 20260827`).

Ranking a pool by pageviews and taking the top 20 would select for fame. That is
not a hypothetical: the Slice 5 planning notes contain a hand-picked comparison
using five famous events per niche, and it reported aviation's event stratum at
**4.9x** its topic basket. The unbiased sample reports **0.37x**. Hand-picking
inflated aviation by roughly thirteen-fold, and would have produced a confident,
wrong conclusion about the one niche the prototype was built around.

Fixed K=20 for every niche because `wiki_weekly_views` is a sum and its confidence
divides by article count; pools of 19 and 3,202 would otherwise be incomparable on
both axes.

**Coverage is not the problem I expected.** Obscure articles were the obvious risk
of unbiased sampling — a randomly chosen 1937 air crash might have no measurable
traffic. Measured: 86–99% of article-days carry a value, against 99–100% for the
hand-curated topic articles. The cost of unbiasedness here is small.

## The generator differs by niche, and that is a confound

| niche | pool | generator |
|---|---|---|
| aviation-disasters | 2,017 | Wikidata `Q744913` aviation accident |
| landmark-court-cases | 3,202 | Wikidata `Q19692072` US Supreme Court decision |
| maritime-disasters | 104 | Wikidata `Q906512` shipwrecking |
| true-crime-trials | 594 | category — the class `Q10855414` has 19 articles |
| corporate-collapse | 380 | category — WDQS was rate-limiting |
| engineering-failures | 151 | category — WDQS was rate-limiting |

Category pools are noisier by construction: *Corporate scandals* contains
*35_day_month*, an accounting concept rather than an event. **The sample is not
hand-cleaned**, because cleaning it reintroduces exactly the selection the random
draw exists to remove. Two of the three category fallbacks were caused by endpoint
flakiness rather than by an unpopulated class, so re-running may move them to
Wikidata — which would itself change the numbers, and is a reason to treat pool
provenance as part of the measurement.

## What is NOT being decided here

Both strata ship. `wiki_weekly_views` keeps its name and its topic articles, so the
series stored since Slice 3 stays one comparable thing; `wiki_weekly_views_event`
runs beside it. Neither feeds a composite yet.

Swapping the primary stratum on the strength of the table above would be choosing
by argument, from a five-unit sample, about which of two things is the better proxy
for a quantity neither directly measures. That is how the topic basket was chosen
in the first place.

Carrying both is affordable because of a property of the collector: for an unseen
term `wikipedia._resume_from` returns `None` and falls back to
`wiki_backfill_days`, so adding a `seed_terms` row triggers a full multi-year
backfill on the next nightly, quota-free. 120 event articles took one run and
produced 132,859 rows. Unlike `video_snapshots`, demand history is not the
unbackfillable asset — a wrong choice costs one overnight run to undo.

## Pre-registered criterion for Gate E

Stated now, before the outcome data exists. **The rankings above have been seen, so
they are not what is being pre-registered** — the predictive test is, and its
inputs do not exist yet.

> Slice 6 replays both strata against 90- and 180-day outcomes and reports the rank
> correlation of each with what actually happened. **The stratum with the higher
> correlation on the validation window — the one not used for tuning — becomes the
> primary.** If the two are within the confidence interval of each other, the topic
> stratum stays primary on the grounds that it is the incumbent and has the longer
> comparable series, and `demand.event_topic_ratio` is kept as its own signal.
>
> If **neither** correlates with outcomes, that is a Gate E finding about the demand
> side and not an argument for a third stratum.

## Known limitations

- **n = 5 niches with both strata.** Every correlation here is descriptive.
- **Pool provenance is heterogeneous** (above), and two of the three fallbacks were
  incidental rather than structural.
- **Category pools contain non-events.** Not cleaned, deliberately.
- **A pool is itself curation.** Which Wikidata class, which category — those are
  choices, and the honest claim is that they are *auditable and re-runnable*
  choices rather than that they are neutral.
- **Neither stratum measures intent to watch a video.** That caveat from
  `demand.wiki_weekly_views` applies unchanged to both.
