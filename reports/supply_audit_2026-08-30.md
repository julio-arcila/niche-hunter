# What is `uploads_per_week` actually measuring? — audit of the 2026-08-31 run, 2026-08-30

## Why this was run

Data rule 9 names `uploads_per_week` as the repo's standing example of a metric that
came out flat because it normalised away the dimension it was comparing on. The span-rate
form ("v3-span-rate-on-niche") landed **2026-08-29** and this is the second run to use it,
so this is the first opportunity to ask whether the fix works on real data rather than on
the Slice 2 measurement that motivated it.

Two threads were opened, both about whether the number can be trusted to *rank* niches:

1. **The denominator.** `_observed_weeks` has no floor, so a channel first seen two days
   ago is read as a weekly rate from a two-day span.
2. **The numerator.** Every supply metric is computed over on-niche videos only, and
   on-niche share ranges 4.3%–43.9% across the eleven active domains.

The answer is that thread 1 is a real defect with no consequence at this grain, and
thread 2 is the one that decides the ranking. A third finding fell out of thread 2 that
is sharper than either: **the metric is most confident exactly where it has least signal.**

## The run being audited

`run_id=a6d35aee-826e-4851-84ff-78dabca9f47a`, all phases ok, 7,190/9,500 units.
79,847 video and 1,902 channel snapshots, 66,385 cluster memberships, 253 features
(23 metrics × 11 active clusters), 11 scorecards. Integrity clean: 0 orphan snapshots,
0 orphan members, 0 provenance nulls.

> **Two date caveats, because they affect how this run should be read.**
>
> The 09:10 cron **did not fire on 2026-08-30** — the machine was asleep on battery
> across the window (slept 09:05:10 for 722s, woke 09:17:12) and macOS cron does not
> replay missed jobs. **2026-08-30 is a permanent gap in the snapshot series**; no source
> serves history. The series reads 08-27, 08-28, 08-29, 08-31.
>
> The catch-up run was started manually at 19:00:24 local, which is **00:00:26 UTC on
> 08-31** — 26 seconds past the UTC day boundary. `Collector.observed_date` is
> `observed_at.date()` in UTC (`nh/collectors/base.py:137`), so every row is stamped
> 08-31 and Aug 30 was already unrecoverable when the run started. The `observed_date`
> boundary is 19:00 local, **not** the 02:00 local Pacific quota reset; conflating the
> two is what cost the day.
>
> Nothing in this audit depends on the gap — every metric here is a 28-day window or a
> point-in-time read, so one missing day widens no denominator.

## Thread 1: the missing floor is real, and it does not move the ranking

`_observed_weeks` (`nh/features/supply.py:87`) returns
`((day - max(window_start, oldest_known)).days + 1) / 7.0` with **no lower bound**. A
channel whose oldest known video is `day` itself gets a one-day span, so a single video
reads as 7/week.

**First, a correction to my own earlier reading.** I flagged that `channels_span_censored`
exceeded `inputs_n` for two clusters (history-of-ideas 68 vs 62, philosophy-of-science
87 vs 86) and called it arithmetically suspicious. That was wrong: `inputs_n` is
`sum(counts.values())`, a count of **videos**; `censored` counts **channels**. Different
units, no anomaly.

**Is the inflation legitimate?** Against a pooled fixed-window count, the span form is
1.13×–1.96× higher, with 56%–79% of each value coming from censored channels:

| cluster | span (shipped) | pooled | inflation | % from censored |
|---|---|---|---|---|
| macro-economy | 150.3 | 76.5 | 1.96× | 77% |
| ai-and-software | 185.9 | 95.0 | 1.96× | 73% |
| trading | 299.6 | 158.3 | 1.89× | 79% |
| geopolitics | 205.2 | 118.0 | 1.74× | 69% |
| … | | | | |
| esoterism-spirituality | 42.5 | 37.5 | 1.13× | 31% |

That looked alarming until the distribution of oldest-known-video dates was checked. It is
**flat across the window at ~15–21 known videos per channel** — 52 to 88 channels on every
day from 08-05 to 08-27, tailing to 33 and 14 on 08-29 and 08-30. That is the signature
of the RSS 15-entry cap biting at different depths depending on upload rate, which is
precisely the censoring the span form exists to correct. The inflation is the fix
working, not an artifact.

The genuinely thin slice — span < 1 week **and** fewer than 15 known videos, i.e. observed
too briefly rather than feed-capped — is **35 channels and 3.8% of total value** across all
17 clusters. It concentrates at spans of 2–3 days (6 channels at 2 days averaging 3.5 known
videos; max single-channel rate 22.8/week at a 4-day span).

**The decisive test is whether a floor reorders the niches. It does not:**

| cluster | shipped | floor 1wk | floor 2wk | pooled |
|---|---|---|---|---|
| trading | 299.6 | 283.6 | 229.6 | 158.3 |
| geopolitics | 205.2 | 197.3 | 158.7 | 118.0 |
| ai-and-software | 185.9 | 164.5 | 128.4 | 95.0 |
| macro-economy | 150.3 | 132.0 | 108.7 | 76.5 |
| biohacking | 81.0 | 78.8 | 67.2 | 48.0 |
| metaphysical-battles | 51.2 | 51.1 | 45.6 | 35.3 |
| esoterism-spirituality | 42.5 | 42.1 | 39.9 | 37.5 |
| logic-linguistics-gnoseology | 38.9 | 36.4 | 34.2 | 25.8 |
| philosophy-of-science | 28.6 | 27.3 | 26.6 | 21.5 |
| anthropocene-anthropology | 26.7 | 25.0 | 22.0 | 17.3 |
| history-of-ideas | 21.9 | 20.6 | 18.8 | 15.5 |

Spearman against shipped: **1wk floor ρ = 1.000, 2wk floor ρ = 1.000**, pooled ρ = 0.991
(one adjacent swap, metaphysical-battles ↔ esoterism-spirituality). Magnitudes move
materially — up to −12.2% at a 1-week floor and −30.9% at 2 weeks — but the order is
identical.

**Conclusion.** Add the floor for defensibility, not for correctness: it is an unguarded
divide-by-small-number that will grow on any night discovery adds many channels, and it
costs nothing to bound. It does not currently change any decision. This is a code change
and has not been made.

**One reporting gap worth fixing alongside it.** `channels_span_censored` is computed over
all known member channels while `value` sums only contributing ones, so it cannot say how
much of a stored value is affected. history-of-ideas stores 68, but only **13 of its 34
contributing channels** are censored; philosophy-of-science stores 87 against **22 of 51**.
Data rule 9 names this counter as the attribution marker for the definition bump, so as
stored it overstates in absolute terms while being uninformative about the actual
inflation.

## Thread 2: the lexicon filter is the dominant lever, and the cause is membership

Recomputing the identical span-rate arithmetic over **all** long-form videos from member
channels, rather than on-niche only:

| cluster | all videos | on-niche only (shipped) | retained |
|---|---|---|---|
| geopolitics | 756.1 | 205.2 | 27.1% |
| macro-economy | 665.8 | 150.3 | 22.6% |
| ai-and-software | 513.5 | 185.9 | 36.2% |
| trading | 502.3 | 299.6 | **59.6%** |
| philosophy-of-science | 485.5 | 28.6 | **5.9%** |
| metaphysical-battles | 478.1 | 51.2 | 10.7% |
| history-of-ideas | 376.4 | 21.9 | 5.8% |
| esoterism-spirituality | 285.8 | 42.5 | 14.9% |
| logic-linguistics-gnoseology | 253.8 | 38.9 | 15.3% |
| biohacking | 229.3 | 81.0 | 35.3% |
| anthropocene-anthropology | 201.7 | 26.7 | 13.2% |

**Spearman between the two orderings: ρ = 0.664.** philosophy-of-science moves from rank 5
to rank 9, history-of-ideas from 7 to 11, trading from 4 to 1, biohacking from 10 to 5.

Set against thread 1 this is the whole story: **the denominator choice cannot reorder the
niches (ρ = 1.00) and the numerator filter reorders them substantially (ρ = 0.66).** The
metric's sensitivity lives entirely in the lexicon, and data rule 9 is about the wrong
half of the fraction.

### It is not a narrow lexicon — it is cluster membership

A narrow lexicon that lacked vocabulary would leave videos undecided in the mid-band. It
does not. The undecided band is **stable at 14.4%–26.5%** across all eleven, and the
low-precision clusters instead show high *confident noise*:

| cluster | on-niche | undecided | noise | unscorable |
|---|---|---|---|---|
| trading | 43.9% | 24.0% | 30.3% | 1.7% |
| ai-and-software | 24.6% | 26.5% | 48.4% | 0.5% |
| … | | | | |
| history-of-ideas | 6.1% | 16.6% | 74.3% | 3.0% |
| philosophy-of-science | 4.3% | **14.4%** | **77.7%** | 3.6% |

philosophy-of-science has the *lowest* indecision and the *highest* confident rejection.
The scorer is not hesitating; it is confidently rejecting.

Resolving to channels (≥5 long-form videos each) shows why:

| cluster | channels | never on-niche | % never | mostly on-niche | % mostly |
|---|---|---|---|---|---|
| philosophy-of-science | 161 | 98 | **60.9%** | 1 | **0.6%** |
| history-of-ideas | 118 | 66 | 55.9% | 4 | 3.4% |
| metaphysical-battles | 128 | 65 | 50.8% | 9 | 7.0% |
| logic-linguistics-gnoseology | 95 | 41 | 43.2% | 7 | 7.4% |
| esoterism-spirituality | 109 | 44 | 40.4% | 13 | 11.9% |
| anthropocene-anthropology | 54 | 19 | 35.2% | 4 | 7.4% |
| macro-economy | 141 | 42 | 29.8% | 17 | 12.1% |
| geopolitics | 141 | 27 | 19.1% | 36 | 25.5% |
| biohacking | 67 | 11 | 16.4% | 21 | 31.3% |
| ai-and-software | 119 | 18 | 15.1% | 37 | 31.1% |
| trading | 121 | 17 | 14.0% | 67 | **55.4%** |

**61% of philosophy-of-science's channels have five or more videos and not one on-niche.
Exactly one channel of 161 is mostly on-niche.** These are ballast: discovery surfaced them
via seed queries, `trivial.dominant_seed` assigned them to the cluster by counting
discovery rows, and the lexicon then rejects everything they publish. They contribute
nothing to the numerator, inflate `member_channels`, and consume discovery quota.

## The sharpest finding: confidence is inverted

`uploads_per_week`'s confidence is `adequacy × coverage × relevance_coverage`
(`nh/features/supply.py:54`). On this run **`known == members` for all eleven clusters**,
so coverage = 1.0, and adequacy saturates at 104–347 channels. Confidence therefore
reduces exactly to `relevance_coverage = (on-niche + noise) / total`. Verified on all
eleven to three decimals — philosophy-of-science 4.3 + 77.7 = **82.0%** against a stored
confidence of **0.820**; esoterism 12.8 + 69.5 = 82.3% against 0.823; trading
43.9 + 30.3 = 74.2% against 0.743.

The consequence: **confidently rejecting a video raises confidence in a volume metric that
the video does not contribute to.**

| cluster | uploads/wk | confidence | never-on-niche channels |
|---|---|---|---|
| esoterism-spirituality | 42.5 | **0.823** | 40.4% |
| philosophy-of-science | 28.6 | **0.820** | **60.9%** |
| macro-economy | 150.3 | 0.806 | 29.8% |
| history-of-ideas | 21.9 | 0.803 | 55.9% |
| … | | | |
| trading | 299.6 | 0.743 | 14.0% |
| ai-and-software | 185.9 | 0.730 | 15.1% |
| geopolitics | 205.2 | 0.727 | 19.1% |

Spearman between value and confidence: **ρ = −0.346**. philosophy-of-science reports the
second-lowest supply at the second-highest confidence, on a cluster where three fifths of
the channels have never produced an on-niche video.

This is defensible for a *share* metric like `on_niche_share`, where a decided negative is
genuine information. For a *volume* metric it is backwards. The docstring's stated intent —
"a niche which genuinely published nothing this window reports a confident zero rather than
a doubtful one" — is reasonable, and this is the case it did not anticipate: a niche whose
members publish plenty, none of it on-niche, is not the same thing as a niche that
published nothing, but the confidence term cannot tell them apart.

## What this does not show

- **It does not show the lexicon is wrong.** The score distribution is equally consistent
  with a mis-specified lexicon confidently rejecting genuine philosophy-of-science content,
  and with membership assigning broad channels to a narrow niche. Nothing measured here
  separates those, and — as ADR-0041 argues for the exposition axis — no machine test can:
  the labels and the lexicon come from the same model family, and agreement between two
  raters of that family cannot detect a bias they share. Only human labels settle it.
- **It does not license a change to any scorecard.** `value`, `sustainability` and
  `opportunity` remain NULL behind Gate E's 2026-08-28 null. Nothing here is evidence
  about that gate, which was measured at niche grain on a different corpus.
- **It does not touch ADR-0041.** The corpus has grown considerably since the 99-row
  exposition sample was drawn on 08-29 — all eleven domains now hold on-niche videos, 184
  to 1,917, against "19 of 120 across 4 of 11" in the deferral register. That is an
  observation and **not** an argument to redraw. Pre-registration means the sample is not
  resampled because the data improved; changing it requires a new ADR and a re-label.
- **ρ = 0.66 and ρ = −0.35 are eleven-point rank correlations** and should not be quoted as
  precise. They are reported to separate "reorders the ranking" from "does not", which at
  ρ = 1.000 versus ρ = 0.664 is not a close call, and not to size an effect.

## What would settle it, cheapest first

1. **Bound `_observed_weeks`.** A one-week floor is arithmetically free and changes no
   ranking. Do it as a robustness guard, not as a fix to a live error.
2. **Report `channels_span_censored` over contributing channels**, or add a second counter
   that does, so data rule 9's attribution marker means what the rule says it means.
3. **Decide whether a never-on-niche channel should stay a cluster member.** This is a
   clustering question, not a metric question, and it is worth an ADR: 61% of one
   cluster's channels currently contribute nothing but denominator and quota.
4. **Separate the two confidence roles.** A volume metric and a share metric should not
   take the same `relevance_coverage` term with the same sign.

Items 1, 2 and 4 are code changes and none has been made. Item 3 is a decision.

## Other observations from the same run, not pursued here

- **`wiki_weekly_views_event` is NULL on all eleven** — `"no wikipedia article mapped to
  this cluster"`, `inputs_n = 0`, `confidence = 0`. The other five `wiki_*` metrics are
  healthy (confidence 0.989–1.0, 51–1,098 inputs). This is an *event*-shaped metric inherited
  from the disaster niches; the eleven are evergreen domains, so it is structurally
  inapplicable to the new grain rather than merely missing data.
- **`money.*` rests on 162 keyword rows total** (96 US, 66 GB) across all clusters — 4.5–6
  inputs per niche, and 35 of 96 US rows have a NULL bid. `median_bid_high` is backed by as
  few as **2 keywords** in places. Confidence (0.148–0.200) reports this honestly.
- **27% of videos are unenriched** (18,372 of 68,106; the same count is NULL on `is_short`
  and `duration_s`). Every long-form metric silently excludes them, as
  `uploads_per_week`'s own note states. This run backfilled 25,000; that is what remains.
- **Relevance decisions corpus-wide:** 60.7% noise, 17.5% on-niche, 17.0% undecided, 4.9%
  unscorable. 22% of videos are in neither numerator nor denominator, by design
  (`on_niche_join`), which caps every relevance-dependent confidence.
- **The 7 retired clusters** still hold 97–272 channels each and keep compounding via RSS
  while producing zero features — features follow `niche_seeds.active`. That matches
  ADR-0040's intent and is noted only so it is not mistaken for a scoring failure.

---

# Addendum, 2026-08-30: sizing the `_latin_share` defect

The plan that came out of this audit made one thing a prerequisite before any
language-gate fix could be proposed: **the defect's size was not established**,
because 43% of noise videos carry a NULL `audio_lang`. It is established now, and
the answer is narrower and sharper than "non-English content is mis-scored".

## The NULL rate has two causes, and only one is a limit

| | videos | NULL `audio_lang` |
|---|---|---|
| unenriched | 17,689 | **100%** — never fetched |
| enriched | 47,980 | 18.9% — YouTube does not always report it |

So 81% of enriched cluster videos carry a known language. That is the base
everything below is measured on.

## "Non-English" is the wrong population

Among enriched videos with a known language, non-English content is decided noise
at **56.1%** against English's **58.8%** — indistinguishable — and 15% of it still
scores on-niche. The gate is working where it can see: 15.2% of non-English videos
are marked unscorable against 0.4% of English ones.

Per language, on-niche share **among scorable videos**:

| lang | n | unscorable | on-niche of scorable |
|---|---|---|---|
| ta | 246 | 34 | 37.7% |
| en-US | 7,010 | 7 | 28.2% |
| hi | 6,583 | 709 | 21.8% |
| en | 16,913 | 25 | 20.2% |
| ur | 877 | 17 | 16.3% |
| mr | 320 | 214 | 4.7% |
| **fr** | **171** | **0** | **1.2%** |
| **es** | **226** | **0** | **0.9%** |
| ko | 208 | 203 | 0.0% |

Two different things are visible here and they must not be confused. Korean and
Marathi score near zero because the gate **caught** them (203 of 208, 214 of 320
unscorable) — that is the design working: unreadable is recorded as unknown, not
as off-niche. Hindi, Urdu and Tamil score like English because their titles are
romanized or already carry English domain vocabulary, so the lexicon reads them.

## The real population: Latin-script European languages

| lang | n | unscorable | decided noise | on-niche |
|---|---|---|---|---|
| es | 226 | 0 | 223 | 2 |
| fr | 171 | 0 | 144 | 2 |
| pt-BR | 140 | 0 | 138 | 0 |
| es-419 | 115 | 0 | 103 | 2 |
| de | 89 | 0 | 69 | 2 |
| pt | 49 | 0 | 49 | 0 |
| it | 33 | 0 | 22 | 0 |
| es-ES | 31 | 0 | 28 | 1 |
| **total** | **854** | **0** | **776** | **9 (1.1%)** |

**Not one of 854 is caught.** `_latin_share` tests the share of *Latin letters*, and
a Spanish or German title is ~100% Latin, so it passes; the English lexicon then
matches nothing, the score is exactly 0.0, and `is_noise = value <= RELEVANCE_LOW`
with `RELEVANCE_LOW = 0.0` files it as **decided** off-niche. That is precisely the
outcome the gate's own comment forbids — "An English lexicon cannot read this.
Scoring it 0 would call it off-niche."

1.1% on-niche against English's 20.2% is an 18x gap. At the English rate, ~172 of
these would be on-niche; 9 are. So roughly **163 videos are wrongly excluded from
every supply numerator, and 776 are wrongly counted as decided** in
`relevance_coverage`.

It lands where the Fable taxonomy predicted its K4 kind would:

| cluster | affected | on-niche |
|---|---|---|
| metaphysical-battles | 179 | 0 |
| philosophy-of-science | 133 | 2 |
| esoterism-spirituality | 121 | 2 |
| geopolitics | 66 | 0 |
| history-of-ideas | 63 | 2 |

These are three of the four worst-precision domains in the main report, and the
one with the single lowest supply score.

## What this does and does not license

**854 is a floor, not the population.** It counts only enriched videos with a
reported language; the 17,689 unenriched ones have no language at all, so the true
figure is larger by an unknown factor.

**It is still a `score()` change and still hard-blocked** behind the 99-row
labelling, for the reason in the main report: changing the scorer would leave those
labels measuring a configuration no longer running.

**It does not explain the precision spread on its own.** 854 videos cannot account
for philosophy-of-science's 4,405 off-niche rows. The ballast finding stands as the
larger mechanism; this is a second, independent, and much cheaper-to-fix one.

**The fix is not more lexicon terms.** It is a language signal the gate can act on
— `videos.audio_lang` already exists and is populated for 81% of enriched rows,
which is why this was worth measuring before proposing anything. A video whose
language the lexicon does not cover should be **unscorable**, exactly like Korean,
not decided. That keeps it out of numerator and denominator alike and lowers
confidence honestly, instead of counting a rejection nobody made.
