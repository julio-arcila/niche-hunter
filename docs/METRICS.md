# Metrics

**2026-08-28 — lexicon family membership changed (ADR-0028).** `court-cases` out,
`true-crime-trials` in; `LEXICON_VERSION` is `2026-08-28.1`. The family is still five,
so every "one of five lexicons" statement below stays literally true. The four
continuing niches' weights were measured unchanged (the retired entry was term-disjoint
with all of them) and that is now a standing test rather than a one-off check. The new
lexicon's held-out precision is **unmeasured** — 0.781 belongs to the old family — so
every `supply.*` number for `true-crime-trials` carries that caveat until the pre-Slice-7
human spot-check covers it.

**Every `Measured:` line carries a date.** A measured number is a fact about a
corpus on a day, not a property of the metric, and this file is read as if its
numbers are current. Two undated claims here went stale unnoticed and were caught
only by an audit re-running them (2026-08-28); every dated claim in the same sample
verified. A number without a date cannot be told from a number that is wrong.

**A metric starts as an entry here — formula, inputs, join key, confidence —
then code, then a test.** A definition that lives only inside a Python function
cannot be reviewed, backtested, or compared across a schema change.

Every `features_daily` row stores `value`, `confidence` and `inputs_n`. Absent
inputs produce NULL, never 0.


## Geo basis — which population each source measures

Recorded because the four sources are **not** scoped to the same people (ADR-0035), and
a reader must not have to know that `en.wikipedia` is a language while `geo=US` is a
country in order to avoid comparing them.

| Source | Population | Set by |
|---|---|---|
| `keyword_planner` | United States | `--geo` per export |
| `trends` | Worldwide | `geo=""`, per ADR-0024 |
| `wikipedia` | English readers globally (`en.wikipedia`) | `PROJECT` constant |
| `youtube_api` | Search as served for the seed's stated market (US today), English relevance | `regionCode` from `niche_seeds.geo` + `relevanceLanguage: "en"` (ADR-0037) |

The `youtube_api` row previously read "Unfiltered, English-relevance only", which
was never true: a `search.list` request without `regionCode` is served with a
**US default** (documented on the response's `regionCode` property), so the basis
was inferred rather than recorded. Since ADR-0037 (2026-08-29) discovery sends the
seed's stated geo explicitly and stamps it into the raw payload; all live seeds
state US, so no behavioural change is expected — see the ADR for the caveat.

So a composite mixing them mixes populations. **This does not currently move
`scorecards.gap`**, which is `demand_rank − supply_rank` — a difference of within-day
percentile ranks, not a ratio. Measured 2026-08-28: restricting supply to US-domiciled
channels moves the medians substantially and leaves the ranking of all five niches
**identical**, so the composition cannot move a rank difference. Consistent with the
`median_views` entry below, where a 0.42x–3.37x value change also left ranks unmoved.

It becomes live in **Slice 9**, the first time a `geo=US` demand level (Keyword Planner)
sits beside global-English supply. Note also that `geo_concentration` counts *channels*
while supply weighs *videos*, so it is not a supply-composition measurement — do not
reuse its numbers as one (ADR-0035's retracted claim did exactly that).

## Entry template

```
### <group>.<name>
Formula      : written out, including normalization (z-scored within which
               universe? anchor-scaled against what?)
Inputs       : tables and columns, and the time window
Join key     : usually cluster_id
Confidence   : how computed, and WHAT n IS. Pick an n whose scarcity is what
               makes this metric lie, and check it actually varies across
               clusters -- a confidence pinned at 1.00 everywhere proves nothing
Failure mode : what makes this metric lie; what it returns when inputs are sparse
Feeds        : which composite score, if any
```

---

## Defined

Twenty-three metrics across four of the six groups (`voice` and `cost_risk` are still
empty). Twenty-two are registered in `nh/features/run.py::METRICS`; `supply.pressure_index`
is computed cross-cluster after them and `supply.views_per_new_video` is backtest-only. Each was verified to **vary across the five live niches** before
implementation — a metric that is flat across the units it
compares is not a comparator, however plausible its formula.

### supply.uploads_per_week
```
Formula      : sum over member channels of (on-niche long-form uploads with
               published_at in the 28-day window ending on day) divided by the
               channel's OBSERVED span in weeks, where the span runs from
               max(window start, the channel's oldest known video of any kind)
               through day, inclusive in civil days. A cluster TOTAL, not a
               per-channel average: supply is the volume of competing long-form
               content entering the niche. For a channel observed across the whole
               window this is exactly count/4.0; for a channel whose known history
               starts inside the window — the RSS 15-entry cap discards everything
               older — it reads as a rate over what was actually seen instead of
               censoring at the cap (data rule 9).
               CHANGED 2026-08-29 (definition "v3-span-rate-on-niche"): until then
               the shipped code divided a fixed-window count by 4.0, despite rule 9
               and this entry's own failure mode saying it must not — and despite
               two doc passages claiming the rate form had already shipped. Values
               rise wherever detail.channels_span_censored > 0; not comparable
               across 2026-08-29.
               The span marker is the oldest known video of ANY kind, not the
               oldest on-niche one: observation coverage is a property of the feed,
               and an on-niche marker would turn a channel with one on-niche upload
               into a one-day span at 7/wk.
Inputs       : videos(published_at, is_short, channel_id); cluster_members
               (item_type='channel'); window (day-28d, day].
Join key     : cluster_id, via videos.channel_id -> cluster_members.item_id, AND
               videos.video_id -> cluster_members(item_type='video').relevance
Confidence   : min(known_n / 30, 1) * (known_n / member_n) * numerator_decisiveness
               -- sample adequacy TIMES coverage TIMES how decisively the numerator
               was filled. Adequacy alone saturates: 74 contributing channels
               of 197 scores 1.00 while the metric sees 38% of the niche, and those
               74 are the enriched, discovery-biased ones. Coverage alone would
               under-report a small but fully observed cluster.
               numerator_decisiveness = on_niche / (on_niche + undecided +
               unscorable) -- "of the videos that could have entered my numerator,
               how many did I decide into it". When nothing is unjudged and nothing
               is on-niche the ratio is 0/0 and is defined as 1.0: a niche whose
               members' output was entirely DECIDED, none of it on-niche, has
               earned a confident low volume. When the cluster holds no videos at
               all it is 0.0 -- there is nothing to have been decisive about.
               CORRECTED 2026-08-28: this block previously specified
               `publishing_n / member_n` -- channels that published IN THE WINDOW --
               and claimed "the product gives 0.38 for aviation-disasters, which is
               the true picture". The shipped code has always used `known_n`,
               channels we can see at all, and the audit that found the divergence
               concluded the CODE is right: a channel we observe publishing nothing
               is a MEASUREMENT, not missing data, and dividing by publishers would
               mark a genuinely quiet niche as unknown -- collapsing rule 7's
               absent-is-not-zero from the other side. Measured 2026-08-28 on
               aviation-disasters: known=197, publishing=63, members=197, so the old
               spec computes 0.278 against the shipped 0.871. The spec was changed
               to the code, not the reverse, and no stored value moved.
CHANGED 2026-08-27 (Slice 4, definition "v2-on-niche"): the numerator counts only
               videos judged on-niche, and confidence gained a relevance_coverage
               leg. Values fell 15-30% for every cluster. Not comparable across
               2026-08-27.
CHANGED 2026-08-30: the third leg moved from relevance_coverage
               (decided/total) to numerator_decisiveness. VALUES DO NOT MOVE; only
               confidence does. Measured on run a6d35aee: because known_n ==
               member_n for all eleven clusters, the two other legs were both 1.0
               and confidence reduced EXACTLY to relevance_coverage -- verified to
               three decimals (philosophy-of-science 4.3% on-niche + 77.7% noise =
               82.0% against a stored 0.820). That made confident REJECTION raise
               confidence in a volume the rejected videos contribute nothing to:
               Spearman(value, confidence) across the eleven was -0.346, most
               confident where supply was lowest. A decided negative is real
               information about that video and belongs in a SHARE metric's
               denominator, which is why supply.on_niche_share keeps the old form
               unchanged; it does not belong in a VOLUME metric's confidence.
               Expected effect: philosophy-of-science ~0.19 (from 0.820), trading
               ~0.63 (from 0.743). Series are not comparable across 2026-08-30.
               Neither form prices the scorer's own held-out precision of 0.781,
               which pushes share and volume symmetrically.
               See reports/supply_audit_2026-08-30.md.
Failure mode : the span form assumes a censored channel's cadence was constant
               across the window -- an extrapolation, honest about rate but not a
               realized count. A channel observed for a single day contributes a
               noisy rate (n*7 per upload); no floor constant is added to damp it,
               by the ADR-0023 zero-tuned-constants argument, so a very young
               corpus is volatile at the channel level and detail records
               channels_span_censored for exactly that reading.
               CAVEAT on that counter, and the reason detail gained a second one on
               2026-08-30: channels_span_censored counts censored channels among ALL
               KNOWN member channels, while the value sums only CONTRIBUTING ones,
               so it cannot say how much of a stored value is affected. Measured on
               run a6d35aee: history-of-ideas stores 68 but only 13 of its 34
               contributing channels are censored; philosophy-of-science stores 87
               against 22 of 51. detail.contributing_span_censored (and
               detail.channels_publishing_in_window as its denominator) is the pair
               data rule 9's attribution marker actually needs. The old counter is
               kept, unchanged, so rows on both sides stay readable. A channel uploading
               >15 times BETWEEN polls still loses the overflow permanently -- the
               span form fixes censoring of the window, not feed overflow. Unknown-
               format videos are excluded, biasing low until the enrichment
               backfill completes. No member channels -> NULL.
Feeds        : scorecards.supply; gap from Slice 3
Measured     : 2026-08-29, span form vs fixed-window form on the live corpus at
               day 2026-08-28: 17-52% of each cluster's known channels are
               span-censored, and the span form reads 1.6x-2.1x the fixed count
               (aviation-disasters 174.8 vs 100.0/wk; true-crime-trials 328.1 vs
               158.5/wk) -- the fixed form was underreading every niche's cadence,
               worst where cadence is highest. Spread across the five active
               niches: 81.1-328.1/wk (4.0x). The Slice 2 measurement that forced
               rule 9: a 90-day fixed count landed EVERY niche on 1.17/wk (1.1x
               spread) against 2.2x for the span form.
```

### supply.median_views
```
Formula      : median of current views over the pooled eligible ON-NICHE videos of
               all member channels. Eligible: is_short IS FALSE, published_at <= day-14d, within
               the channel's 15 most recent known uploads (uniform per-channel cap =
               RSS feed depth, so API-discovered channels get no deeper window).
               Views from the video's latest video_snapshots row with observed_date
               <= day. Pooled, not median-of-medians: supply is the field you compete
               against, and a 500-sub channel should not weigh the same as a 30M one.
               The relevance filter is applied AFTER the 15-video cap, never before:
               filtering first would let an on-niche-sparse channel reach further
               back in time and silently destroy the comparability the cap exists
               to create (data rule 9).
Inputs       : videos; video_snapshots(observed_date, views, source); cluster_members
               (item_type='channel' for the pool, item_type='video' for relevance)
Join key     : cluster_id
Confidence   : min(contributing_channels / 30, 1) * coverage *
               numerator_decisiveness. Channels, not videos, for the first leg:
               views are correlated within a channel, so channels are the effective
               sample. numerator_decisiveness is on_niche / (on_niche + undecided +
               unscorable) -- the pooled median is taken over on-niche videos, so
               what bounds trust in it is how much of the pool it COULD have drawn
               from was actually decided into it. A video decided off-niche never
               had a place in this pool and must not raise confidence in it.
CHANGED 2026-08-30: third leg moved from relevance_coverage
               (decided/total) for the reason above; shares the change with
               supply.uploads_per_week, whose entry carries the measurement.
               VALUES DO NOT MOVE, only confidence. Not comparable across
               2026-08-30. See reports/supply_audit_2026-08-30.md.

CHANGED 2026-08-27 (Slice 4, definition "v2-on-niche"): the pool moved from every
               eligible video to eligible videos judged on-niche. Values moved
               0.42x-3.37x; supply RANKS did not change, and `gap` is unchanged for
               all five clusters. Confidence fell (0.35-0.47 -> 0.16-0.27), which is
               the honest half: the numbers now rest on a filter whose held-out
               precision is 0.781. Series spanning this date are not comparable
               across it -- detail.definition says which side a row is on.
               NOT comparable to openness.*, which deliberately keeps the whole
               catalogue: supply asks what a newcomer competes against IN THIS NICHE,
               openness asks whether a video beat ITS OWN CHANNEL's baseline, and
               that baseline must be the channel's whole output. Do not merge the
               two pools back together -- it would shrink every cohort by ~80% and
               make openness universally NULL.
Failure mode : current views are LIFETIME views -- a five-year-old hit counts the
               same as last month's, overstating what new content earns today. The
               14-day floor is below view settlement. relevanceLanguage=en skews the
               pool. No eligible videos -> NULL, never 0.
Stopgap      : replaces the prototype's 30-180 day age window, which the RSS 15-entry
               feed makes unusable -- an active channel's whole feed is under 30 days
               old, collapsing usable channels from ~890 to 221. Replace with
               age-normalised views-at-day-30 once the snapshot series is >=30 days
               deep. Until then these levels drift upward as today's very young video
               population (10,853 of 13,725 under 30 days) ages in; do not trend them.
Feeds        : scorecards.supply; gap from Slice 3
Measured     : 2026-08-28 -- 417x spread (979.5 to 408,594 views) across the five
               clusters, or 214x (979.5 to 209,845) across the four that are not
               retired. An earlier undated line here read "33x spread (330 to
               10,832)"; it is superseded, and the reason it went stale unnoticed
               is that it carried no date -- see the dating rule at the head of
               this file.
```

### openness.breakthrough_rate_cohort
```
Formula      : share of COHORT CHANNELS with >=1 breakthrough among their eligible
               videos. Breakthrough, ported unchanged from channel_baseline:
                 views >= 5 x channel median of eligible views, OR
                 (subs visible AND views >= 10 x subs).
               Cohort = member channels where (a) latest channel_snapshots.subs
               <= 10,000 and not hidden, (b) >= 5 eligible videos, (c) >= 1 distinct
               video discovered under discoveries.order_by='date'.
               A rate OF CHANNELS, not of videos: the question is whether a typical
               small entrant can break through, and a per-video rate is dominated by
               prolific channels.
Inputs       : cluster_members; channel_snapshots(subs); videos; video_snapshots;
               discoveries(order_by)
Join key     : cluster_id
Confidence   : min(cohort_n / 30, 1); inputs_n = cohort_n. Live cohorts are 15-49,
               so this genuinely varies (0.50 to 1.00). Binomial SE at n=30 is ~0.09.
Failure mode : Filter (c) is the whole metric. A channel that entered the sample only
               via order=viewCount is there BECAUSE it had a winner; counting it in
               the denominator inflates the rate by construction. Measured: without
               the cohort restrictions the metric is FLAT -- 2 percentage points
               across five niches -- and looks like a finding. With them, 40 points.
               This is the unbiased-denominator purpose of Discovery.order_by, and
               dropping either sort order in discovery destroys it silently.
               Also: one day of snapshots means "views now", not views-at-fixed-age.
               The >=5-video floor censors the newest channels -- the ones openness
               is most about. Empty cohort -> NULL, confidence 0, inputs_n 0.
Feeds        : scorecards.openness (used directly; already 0-1)
Measured     : 40 percentage points (47% court-cases to 87% engineering-failures)
```

### openness.views_per_sub
```
Formula      : median over cohort channels (same cohort as breakthrough_rate_cohort)
               of channel_median_eligible_views / latest_visible_subs. Unweighted
               median: a mean is destroyed by tiny-sub channels with one viral video,
               and sub-weighting answers "where do the views go" rather than "what
               does a typical entrant get". Capped at 10k subs because for a 1M+
               channel this ratio measures retention, not openness.
Inputs       : as breakthrough_rate_cohort
Join key     : cluster_id
Confidence   : min(cohort_n / 30, 1); inputs_n = cohort_n
Failure mode : subs measured today against views accrued over months biases the ratio
               up for fast growers. A hidden subscriber count excludes the channel
               entirely -- never read as 0 (rule 7); if hiding correlates with size
               the cohort skews. Deliberately does NOT normalise per channel: that is
               what makes it vary where the naive breakthrough rate does not.
Feeds        : openness composite from Slice 5
Measured     : 5.3x spread cohort-restricted (0.43 to 2.26); 3.8x unrestricted
```

### supply.format_mix
```
Formula      : among on-niche member-channel videos with published_at in
               (day-28d, day] and is_short IS NOT NULL, the share with
               is_short IS TRUE. Unknown is_short is excluded from numerator AND
               denominator -- never counted as long-form.
Inputs       : videos(is_short, published_at, channel_id); cluster_members
Join key     : cluster_id
Confidence   : min(known_format_videos / 30, 1) x relevance coverage. Videos are the
               honest n because is_short is a per-video property; 30 is the supply
               group's constant, not money's 100, because the 28-day supply window is
               far thinner than money's 90-day one.
Failure mode : Shorts skew toward off-niche filler, so computing this over a channel's
               whole output rather than its on-niche output would measure the channel's
               posting habits instead of the niche's supply. On-niche only for that
               reason. A cluster the enrichment has not reached returns NULL, not 0.0.
Registered   : 2026-08-28, when its deferral trigger fired (is_short known for 99.6%
               of videos against a 92%-NULL blocker). Consumer is a future supply
               composite; nothing ranked uses it while ADR-0029 stands.
```

### money.midroll_eligible_share
```
Formula      : among member-channel videos with published_at in (day-90d, day] and
               midroll_eligible IS NOT NULL, the share with midroll_eligible IS TRUE
               (duration_s >= 480, set at enrichment). Unknown durations are excluded
               from numerator AND denominator -- never counted as ineligible.
Inputs       : videos(midroll_eligible, published_at, channel_id); cluster_members
Join key     : cluster_id
Confidence   : min(known_duration_videos / 100, 1). A per-video property measured
               exactly, so videos are the honest n; 100 because the window is
               video-rich and 30 videos can be two channels' output.
CHANGED 2026-08-27 (Slice 4, definition "v2-on-niche"): numerator and denominator
               both restrict to on-niche videos, and confidence gained a
               relevance_coverage leg. Values ROSE for every cluster (0.25-0.54 ->
               0.31-0.69) because off-niche shorts were dragging the share down;
               confidence fell from 1.00 to 0.74-0.87, which was the number that had
               been wrong. Not comparable across 2026-08-27.
Failure mode : depends entirely on the enrichment backfill. Before it runs the
               denominator is the 1,242 API-discovered videos only -- a
               discovery-biased subset. Deleted videos leave unknown durations; if
               deletions skew short, the share biases up. Zero known -> NULL.
Feeds        : money composite in Slice 5; display-only in Slice 2
```

### money.priced_share
```
Formula      : among the cluster's curated keyword_planner terms with a
               keyword_metrics reading in `geo` and observed_date <= day, the share
               carrying at least one REAL bid cell. A bid cell is real when it is
               non-NULL and not one of the two imputed sentinels (see below).
Inputs       : keyword_metrics(bid_low, bid_high, geo, observed_date); seed_terms
Join key     : cluster_id, then (lower(term), lang) against keyword_metrics
Confidence   : curation coverage x sample adequacy =
               min(observed/curated, 1) x min(n/30, 1). Coverage is the
               relevance_coverage analogue for a source with no videos: what we can
               fail to see is a curated keyword. 30 = KP_ADEQUATE_KEYWORDS, the
               first export's basket size. NOT money.CONFIDENCE_N, which is
               documented per-video and would pin this near 0.30 forever.
               At today's 6-keyword baskets this caps near 0.20 BY CONSTRUCTION.
Failure mode : zero is a MEASUREMENT here, not an absence — keywords observed, none
               bid on. That is honest only because the denominator is day-bounded;
               before any export exists the metric returns NULL instead. The two
               cases are pinned by a matching pair of tests.
Feeds        : nothing. scorecards.value stays deferred behind ADR-0029.
```

### money.competition_index_mean
```
Formula      : mean of competition_index (0-100, verbatim from the export) over the
               cluster's observed keywords in `geo` as of day. Keywords without an
               index are excluded from both sides.
Inputs       : keyword_metrics(competition_index, geo, observed_date); seed_terms
Join key     : cluster_id, then (lower(term), lang)
Confidence   : as priced_share.
Failure mode : this is advertiser competition for SEARCH ads. It says nothing about
               how much video already exists in the niche — that is supply.*, a
               different auction in a different market. A reader who conflates them
               will think a cheap niche is an empty one.
Feeds        : nothing yet.
```

### money.vw_cpc
```
Formula      : volume-weighted mean bid, sum(v*p)/sum(v), where v is
               avg_monthly_searches and p is the mean of whichever of (bid_low,
               bid_high) are real for that keyword. A keyword missing either a real
               price or a volume is excluded from BOTH sides, never counted as zero.
Inputs       : keyword_metrics(avg_monthly_searches, bid_low, bid_high, currency);
               seed_terms
Join key     : cluster_id, then (lower(term), lang)
Confidence   : as priced_share, with n = keywords contributing to the weighting.
Failure mode : the weights are power-of-ten bucket MIDPOINTS (measured: six distinct
               values across 152 priced rows), so the weighting is order-of-magnitude
               at best. Value is in the ACCOUNT's currency, stored verbatim — COP on
               every row today — and no exchange rate is applied (ADR-0031). Rows
               spanning more than one currency return NULL rather than an average.
Feeds        : nothing yet.
```

### money.median_bid_high
```
Formula      : median of REAL top-of-page high bids across the cluster's observed
               keywords in `geo` as of day.
Inputs       : keyword_metrics(bid_high, currency, geo, observed_date); seed_terms
Join key     : cluster_id, then (lower(term), lang)
Confidence   : as priced_share, with n = keywords carrying a real high bid.
Failure mode : an advertiser's SEARCH-ad bid, NOT YouTube RPM — a different auction
               with different inventory and different bidders. The RPM disclosure
               pass of 2026-08-28 returned n=0 across nine measurement units, so this
               proxy is what exists; treat it as a tier signal, never as a price.
Registered   : 2026-08-29. SENTINEL BIDS: two values, 64,083.40 and 6,408.34 COP,
               are imputed estimator defaults rather than measurements — exactly
               US$16.00 and US$1.60 at one implied rate, on eight unrelated keywords
               across both markets (10 cells of 107 priced rows) while every other
               priced cell is non-round. They are excluded PER CELL, not per row:
               `humanism` GB carries a sentinel low beside a real 47,045.50 high, and
               a per-row rule would discard a genuine measurement. Detection is two
               exact literals in money.SENTINEL_BIDS and deliberately NOT a roundness
               heuristic, which would silently drop real round bids.
Feeds        : nothing yet.
```

### demand.wiki_weekly_views
```
Formula      : sum of daily Wikipedia pageviews over the cluster's mapped articles,
               window (day-30d, day-2d] (28 days), divided by 4.0 -> a weekly rate.
               project=en.wikipedia, access=all-access, AGENT=USER — bots and
               spiders excluded at the API. ABSOLUTE units, comparable across
               niches with no anchor and no rescaling; that is the whole reason
               this source leads the demand side (ADR-0015). Articles are summed,
               not averaged: a niche's attention is the total across its topics.
Inputs       : demand_snapshots(term, observed_date, value, source='wikipedia');
               seed_terms(source='wikipedia', active) via clusters.seed_id
Join key     : cluster_id -> clusters.seed_id -> seed_terms.seed_id
Confidence   : coverage x volume adequacy
               = (points_present / (28 * n_articles)) * min(window_views/10000, 1)
               Coverage alone pins at 1.00 for every niche once the backfill
               completes and would prove nothing. What makes this metric lie at
               the bottom of the range is COUNT SCARCITY: Corporate_scandal draws
               ~3 views/day, where relative sampling noise ~1/sqrt(N) is ~10% and
               any momentum built on it is noise. 10,000 window views puts that
               at ~1%. inputs_n = daily points present.
Failure mode : measures encyclopedic curiosity, NOT intent to watch a video. A
               reference-heavy article (List_of_landmark_court_decisions) carries
               school-calendar traffic. News events spike attention without
               durable video demand — the January 2024 aviation incidents are
               plainly visible in the series. The article MAPPING is curation and
               can misrepresent the niche; nothing in the data detects a bad
               mapping. Counts younger than 2 days are immature at the API and are
               excluded by the window, because first-write-wins would freeze an
               undercount forever. No mapped article, or no points -> NULL.
Feeds        : scorecards.demand (percentile rank) -> scorecards.gap
Measured     : 590x spread across the five seeds with agent=user. NOTE: an earlier
               measurement using all-agents gave 295x and was wrong — bot share
               runs 19-54% and is NOT uniform across niches (Corporate_scandal 54%,
               Aviation 19%), so bots were inflating small niches relative to large.
```

### demand.wiki_momentum_28d
```
Formula      : (views over (day-30d, day-2d]) / (views over (day-58d, day-30d]) - 1,
               pooled over the cluster's mapped articles. A ratio of adjacent
               28-day windows, so it is scale-free and the 590x level spread does
               not leak into it.
Inputs       : as wiki_weekly_views; window (day-58d, day-2d]
Join key     : as wiki_weekly_views
Confidence   : min over the two windows of (coverage * min(window_views/10000, 1)).
               A momentum figure is only as good as its worse window, and the
               prior window is the one a newly mapped article's backfill may not
               yet cover. inputs_n = daily points across both windows.
Failure mode : a single news spike in either window swamps the ratio — detail
               records both window sums so a spike is visible on inspection.
               School-calendar seasonality reads as momentum: court-cases measured
               -31% month-over-month in late August, which is plausibly term
               structure rather than decay. Do not read this as trend until a year
               of history supports seasonal adjustment (Slice 5). A prior-window
               sum of 0 -> NULL, never an infinity.
Feeds        : none yet — display in Slice 3, demand composite in Slice 5
Measured     : -36% to +1% across the five seeds
```

### demand.wiki_yoy
```
Formula      : views in (day-lag-28d, day-lag] divided by views in the same 28-day
               window 365 days earlier, minus 1. Summed across the cluster's
               wikipedia articles.
Inputs       : demand_snapshots(term, observed_date, value, source='wikipedia');
               seed_terms; clusters
Join key     : cluster_id -> clusters.seed_id -> seed_terms.seed_id
Confidence   : min over the two windows of (coverage x volume adequacy), as
               wiki_momentum_28d. The weaker window bounds the ratio.
Failure mode : a single news event in EITHER window moves it, and the two are a
               year apart so they cannot cancel. Immune to annual seasonality by
               construction, which is the whole reason it exists; not immune to a
               one-off. Check demand.wiki_volatility_365d before acting on it.
Why not wiki_momentum_28d: that metric's own entry records court-cases at -31%
               month-over-month in late August and warns it "is plausibly term
               structure rather than decay". Measured in Slice 5: three of four
               niches peak in SEPTEMBER (demand.wiki_seasonality), so a
               month-over-month reading in August is measuring the school calendar.
               A year-apart comparison cannot be.
Feeds        : scorecards.stage — the momentum axis. wiki_momentum_28d stays as
               evidence in detail and is NOT a decision input.
Measured     : 2026-08-27 -- ALL FOUR active niches negative: maritime -13.5%,
               engineering -21.5%, aviation -21.8%, corporate -24.8%. English
               Wikipedia overall was measured at -6% YoY in Slice 3, so these are
               real declines and not only platform drift. Note the consequence for
               `stage`: with every niche negative the momentum axis does not
               currently discriminate, which is a fact about the portfolio rather
               than a defect in the metric.
```

### demand.wiki_volatility_365d
```
Formula      : standard deviation of week-over-week log change in cluster-total
               daily views, over the last 365 days. Weeks with a zero on either
               side are dropped rather than treated as an infinite change.
Inputs       : demand_snapshots; seed_terms; clusters
Join key     : as wiki_yoy
Confidence   : usable weekly changes / 51 -- the full year the metric claims.
Failure mode : log changes are undefined at zero, so a niche that goes dark for a
               week is quietly excluded rather than recorded as maximally volatile.
               Weekly aggregation hides intra-week spikes by design; that is the
               point, since Wikipedia has a strong day-of-week cycle that would
               otherwise dominate and measure the calendar.
Why weekly, why log: log makes it scale-free, so a 300-views/day niche and a
               30,000-views/day niche are comparable -- raw variance would rank
               them by size. Weekly removes the day-of-week cycle.
Feeds        : INSIGHT_RULES Rule 7's false-positive check ("demand that is a
               single news event rather than a standing interest"). A spike in a
               volatile series is a Tuesday; in a quiet one it is news.
Measured     : 2026-08-27 -- 3.8x spread. corporate 0.071 (steadiest), maritime
               0.140, aviation 0.154, engineering 0.268 (jumpiest). Event-driven
               niches score higher, which is what the metric is for.
```

### demand.wiki_seasonality
```
Formula      : each calendar month gets an index (its mean daily cluster-total
               views over all observed years / the overall mean daily views); the
               metric is the standard deviation of those twelve. Scale-free, and
               reads as "typical monthly deviation from the annual average".
Inputs       : demand_snapshots; seed_terms; clusters
Join key     : as wiki_yoy
Confidence   : observed days / 365.25 / 3, capped at 1. CYCLES, not rows: one cycle
               cannot separate season from trend and two cannot tell a repeating
               pattern from a coincidence. A row-count confidence would report 1.00
               from eight months of data for a number about a year.
Failure mode : three cycles is the bare minimum and a single large news event in
               one month of one year still shifts that month's index. It cannot
               separate a genuine season from an annually recurring news cycle --
               an anniversary looks exactly like a season.
Feeds        : INSIGHT_RULES Rule 4's false-positive check ("a seasonal upload
               spike with no real change in openness"). Returns NULL, never 0.0,
               until all twelve calendar months are observed.
Measured     : 2026-08-27, 3.0 cycles for every niche -- aviation 0.218 peaking in
               FEBRUARY, engineering 0.162, corporate 0.073 and maritime 0.051 all
               peaking in SEPTEMBER. Three of four peaking together in September is
               the school calendar, and it is the measured basis for reading
               wiki_momentum_28d as term structure rather than decay.
```

### demand.trends_momentum_13w
```
Formula      : from the newest demand_series observation with observed_date <= day
               for the cluster's Trends term (ONE TERM PER REQUEST, no anchor —
               ADR-0015): mean of the last 13 weekly values / mean of the previous
               13, minus 1. Scale-invariant, so the per-request 0-100
               normalisation that makes Trends LEVELS incomparable across requests
               is harmless here — this metric never compares two requests, only
               two windows inside one.
Inputs       : demand_series(term, geo, timeframe, points, observed_date,
               source='trends'); seed_terms(source='trends', active). Points dated
               after `day` are excluded even when present in the row.
Join key     : cluster_id -> clusters.seed_id -> seed_terms.seed_id
Confidence   : share of the 26 window values that are non-zero. Trends quantises
               to integers on a 0-100 scale normalised to the term's own 5-year
               peak, so a mostly-zero series sits at the quantisation floor and its
               ratio is noise. Measured 2026-08-28 on the single stored series
               (id 1, observed 2026-08-27): `bridge collapse` has mean 0.828 with
               86 of 262 points non-zero -- low against `court case` (52.97, all
               non-zero) and `shipwreck` (32.60), so it does sit near the
               quantisation floor and scores low here, which is the honest report.
               An earlier line claimed "mean 0.1"; that number is not reproducible
               from any held series and is withdrawn. inputs_n = 26.
Failure mode : +/-5 point sampling jitter between fetches moves the ratio; the
               series is one observation, not ground truth. A term whose peak is a
               single news event compresses the rest of the series toward the
               floor, since normalisation is to peak. Fewer than 26 weekly points,
               or an all-zero prior window -> NULL with confidence 0. A dead term
               (aviation disasters documentary = NaN) must be replaced in
               seed_terms, never padded here.
Feeds        : none yet — corroboration display in Slice 3
```

### demand.total_monthly_searches
```
Formula      : sum of avg_monthly_searches over the cluster's curated
               keyword_planner terms with a reading in `geo` and observed_date <=
               day, taking the newest reading per term. Keywords the export carried
               no volume for are EXCLUDED, never counted as zero.
Inputs       : keyword_metrics(avg_monthly_searches, geo, observed_date); seed_terms
Join key     : cluster_id, then (lower(term), lang) — geo resolves on the
               observation, never on the seed (ADR-0038)
Confidence   : curation coverage x min(n/30, 1), as the money KP metrics.
Failure mode : every value is a power-of-ten bucket MIDPOINT, not a count — measured
               2026-08-28, a zero-spend export takes only six distinct values (50,
               500, 5k, 50k, 500k, 5M) across 152 priced rows. This is
               order-of-magnitude arithmetic and NOTHING downstream may de-bucket it.
               It is also GOOGLE SEARCH volume, not YouTube search volume, which no
               source publishes; and it is scoped to a COUNTRY while every other
               demand metric here is scoped to a LANGUAGE (ADR-0035). 10 of 162 live
               rows carry no volume at all; treating those as zero would understate a
               niche for the crime of being unmeasured (data rule 7).
Registered   : 2026-08-29, US only. 66 GB rows are ingested and loader-readable but
               unregistered — ADR-0035 rule 3, and the deferral register carries why.
Feeds        : nothing. Corroborates the Wikipedia demand level; does not replace it.
```

### supply.views_per_new_video
```
Formula      : median across a cluster's member channels of
               (delta_views / delta_videos) over the trailing 4 weekly snapshots —
               views accruing per newly published video. Channel-weeks with
               delta_videos = 0 are excluded, not treated as zero: a week with no
               upload says nothing about reach per upload.
Inputs       : channel_snapshots(observed_date, total_views, video_count) — the
               weekly stocks; the flows are differenced at read time from
               consecutive rows.
Join key     : cluster_id, via channel membership
Confidence   : member channels contributing a usable pair / member channels.
Failure mode : delta_views counts views on the WHOLE back catalogue, not only on
               the new video, so it OVERSTATES new-video reach for channels with
               large catalogues and does so unevenly -- an old channel publishing
               once looks like a hit. docs/METRICS.md already flags this
               contamination for outcome.growth_180d, which is why that metric uses
               subscribers rather than views.
Why it exists: supply.median_views is NOT REPLAYABLE. YouNiverse holds per-video
               view counts only as of its 2019-10-27 crawl, which is after every
               decision date in the backtest window, so eligible_videos correctly
               excludes all of it and median_views is NULL for every historical
               date -- taking scorecards.supply, gap and stage down with it. This
               is the analogue that lets the backtest compute anything at all.
NOT the same : the backtested `gap` built on this is NOT the `gap` the live
               pipeline computes. reports/backtest_*.md must say so. Slice 6 also
               reports a second definition (uploads_per_week alone, faithfully
               replayable but volume without reach) so the choice is visible rather
               than assumed.
Feeds        : scorecards.supply in the backtest only, via
               scorecard.build(..., supply_from=...). The live default is unchanged.
```

### supply.pressure_index
```
Formula      : mean of the within-day percentile ranks of supply.median_views and
               supply.uploads_per_week, over the clusters scored that day.
Inputs       : features_daily (the same day's rows for those two metrics)
Join key     : cluster_id
Confidence   : min of the two components' confidences. Ranks carry no confidence of
               their own, so the weaker input bounds it.
Failure mode : a rank, so NOT comparable across days on which the cluster set
               changed -- same limitation as scorecards.supply and gap, and the
               population it was ranked over is recorded in detail.ranked_over so a
               later reader can tell. Both components are themselves on-niche-only
               (definition v2-on-niche), so it inherits relevance precision 0.781.
Why a MEAN OF RANKS: it invents no weights. Any coefficient on "how big are the
               winners" versus "how much arrives" would be a fabricated constant,
               and there is nothing to calibrate one against until Gate E.
Why it exists: docs/METRICS.md's composite-stub note names this as the fix for gap
               compression -- scorecards.supply ranks median_views alone, which
               correlates with niche size, and so does demand, so gap is a mismatch
               of two ranks that share a driver and comes out narrower than either.
Feeds        : nothing yet. It ships BESIDE scorecards.supply rather than replacing
               it, so the stored series survives and Slice 6 backtests both -- the
               same treatment the two demand strata get.
Measured     : 2026-08-27 -- aviation 1.00, engineering 0.67, corporate 0.17,
               maritime 0.17. The tie is the metric working: those two hold
               opposite ranks on the two components and the mean cancels them.
```

### supply.top10_concentration
```
Formula      : share of the top-100 on-niche videos' views held by their top 10.
               HIGHER IS MORE CONCENTRATED. A ratio WITHIN the top 100, not a share
               of all cluster views, because that denominator moves with how many
               videos we happen to have collected -- a coverage artefact would read
               as a change in concentration.
Inputs       : cluster_members(item_type='video'); videos; video_snapshots
Join key     : cluster_id, via on-niche video membership
Confidence   : videos ranked / 100. A top drawn from 25 videos describes a niche's
               shape more weakly than one drawn from 100.
Failure mode : ranks on LIFETIME views, so older videos place higher and the
               measured shape leans toward whatever has had time to accumulate.
               Returns NULL below 20 videos: a "top 10 share" of a pool of 12 is
               arithmetic, not a measurement.
Why it exists: a newcomer competes against the SHAPE of a niche's attention, not
               only its volume. Ten videos holding most of it means settled
               winners; a flat distribution means there is still room.
Measured     : 2026-08-27 -- maritime 0.71 (most concentrated), engineering 0.69,
               corporate 0.54, aviation 0.45 (most spread).
```

### supply.on_niche_share
```
Formula      : videos judged on-niche / videos judged at all, per cluster. Judged
               means relevance >= RELEVANCE_HIGH (on-niche) or is_noise (off-niche);
               undecided and unscorable videos are excluded from BOTH sides rather
               than counted against, the same treatment midroll_eligible_share gives
               an unknown duration.
Inputs       : cluster_members(item_type='video', relevance, is_noise)
Join key     : cluster_id
Confidence   : decided / total. Coverage only -- there is no sample-adequacy leg
               because this is a census of the cluster, not a sample of it.
Failure mode : it measures our LEXICON as much as the corpus. A lexicon edit moves
               it with no change in the world, which is why cluster_members.detail
               records LEXICON_VERSION per row. Held-out precision on the underlying
               judgement is 0.781 and recall 0.694 against a 28.6% base rate
               (reports/relevance_2026-08-27.md), so this is an estimate with a
               known error rate, not a count. English-only: 10.5% of titles are
               non-Latin script and are unscorable by construction.
Measured     : 2026-08-27 -- aviation 33.7%, court 26.5%, corporate 21.2%,
               maritime 20.8%, engineering 19.6%. The spread tracks how specific
               each seed's keywords are.
```

### supply.geo_concentration
```
Formula      : share of the cluster's member channels whose channels.country equals
               the seed's stated niche_seeds.geo. Channels with no reported country
               are excluded from BOTH sides and lower confidence -- 236 of 955 have
               none, and counting them as "not local" would understate every niche
               by a quarter (data rule 7).
Inputs       : cluster_members(item_type='channel'); channels.country; clusters.seed_id;
               niche_seeds.geo
Join key     : cluster_id -> clusters.seed_id -> niche_seeds.geo
Confidence   : channels with a known country / member channels. Coverage only --
               this is a census of the cluster, not a sample of it.
Failure mode : NOT a quality score, and the most likely way it is misread. A low
               value can mean the seed's stated geo is wrong, or that the niche is
               genuinely global. Both are findings; neither is a defect.
Why it exists: demand is read off English Wikipedia, which is global and US-leaning,
               while supply is whatever relevanceLanguage=en discovery returns.
               `gap` subtracts one rank from the other and cannot see the mismatch.
               This makes it a number rather than letting the gap absorb it.
Measured     : 2026-08-27, against a stated geo of US -- corporate-collapse 0.33,
               engineering 0.37, maritime 0.43, aviation 0.43. So 57-67% of every
               niche's supply sits outside the market its seed claims. Separately,
               234 of 719 channels reporting a country are Indian against 290 US.
Feeds        : nothing yet. A confound to report beside `gap`, not an input to it --
               folding it into a composite would be inventing an exchange rate
               between "how local is this" and "how big is the gap".
```

### openness.winner_age_years
```
Formula      : rank the cluster's videos by latest-snapshot views descending, take
               the top 100, return the median of (day - channels.created_at) in years
               for the channels behind them. LOWER IS MORE OPEN.
Inputs       : video_snapshots(views); channels.created_at (100% coverage); cluster_members
Join key     : cluster_id
Confidence   : distinct_channels_in_top_100 / 100
Failure mode : if the top-100 comes from few prolific channels the median describes
               those channels, not the niche -- which is what the confidence measures.
               Ranking on latest-snapshot views favours older videos, biasing toward
               established channels, so it UNDER-states openness. Threshold-free on
               purpose: an earlier draft used "share of top videos from channels
               younger than 3 years" and 3 was chosen because it maximised spread
               across five niches. Do not reintroduce a cutoff.
Feeds        : none yet -- a second openness signal beside breakthrough_rate_cohort,
               which it does not replace. It needs no subscriber counts and no
               discovery lineage, so it reports where the cohort metrics cannot --
               and today the cohort is empty for four of five clusters.
Measured     : Slice 5, on-niche videos only -- 4.9x spread, maritime 1.58y (most
               open) to court-cases 7.73y (most closed), confidence 0.31-0.48.
               An earlier pass over ALL member-channel videos gave 6.4x with
               corporate at 11.6y; restricting to on-niche moved corporate to 3.2y.
               The pool matters as much as the formula.
```

---

## Relevance -- the rule every supply number now depends on

Not a metric, but `supply.*` and `money.*` are all computed over the videos it
selects, so it is defined here rather than only in code.

A video is scored against its cluster on two axes, and relevance is their geometric
mean, so either at zero means zero:

- **domain** -- terms from the niche's own vocabulary, weighted by how many of the
  five lexicons contain them (unique 1.00, two 0.50, all five 0.00). The zero row is
  deliberate: *documentary*, *investigation*, *analysis*, *explained* are what these
  niches share, not what separates them.
- **event** -- failure and case markers (crash, collapsed, sank, fraud, verdict).
  These carry no power to tell one niche from another and decisive power to tell a
  failure from a tutorial.

The second axis exists because measurement demanded it. A domain-only scorer reached
precision 0.62 and every false positive had one shape: on-domain, off-niche --
"Changi Airport Plane Spotting", "Why Concrete Needs Steel Reinforcement",
"Settlement vs Adjudication". The niche is domain AND event.

Three states, cut at read time so a threshold change is a query and not a rewrite:

| state | rule | held-out share truly on-niche |
|---|---|---|
| on-niche | `relevance >= 0.55` | 78.1% |
| undecided | `0 < relevance < 0.55` | 37.5% |
| noise | `relevance == 0` | 6.4% |
| unscorable | `relevance IS NULL` | excluded; 0 of 10 labelled were on-niche |

Base rate 28.6%. **Held-out precision 0.781, recall 0.694 -- the 0.90 target in the
plan was not met**, and every metric above says so. It still ships because the
status quo is no filter, which is a filter with precision 0.286.

Weights are a pure function of the frozen lexicon, never of the corpus. Corpus IDF
was rejected: it drifts as the corpus grows, so the same video would score
differently on two days and Slice 6 could not replay a historical decision.

Do not re-tune the thresholds against a metric. They were chosen against hand labels
on a held-out split, and moving them until a ranking looks right is exactly the trap
this file already warns about for `winner_age_years`.

## Outcome variables — what "it worked" means

Gate E compares a score at date *t* to what happened afterwards, and until Slice 5
nothing in this repo said what *happened* means. Defined here before any replay
code exists, so it cannot be chosen after seeing results.

### outcome.growth_180d
```
Formula      : log(channel subscribers at t+180d / channel subscribers at t),
               aggregated to the niche as the MEDIAN across its member channels.
               Log because growth is multiplicative; median because one viral
               channel must not define a niche's outcome.
Inputs       : YouNiverse df_timeseries_en (weekly subs per channel, 2015-01 to
               2019-09). Not collected by this pipeline; loaded for the backtest.
Join key     : channel_id -> cluster_id, via the relevance scorer over YouNiverse
               video titles and descriptions.
Window       : t from 2015-07 (first Wikipedia pageview data) to 2019-03 (last t
               with a 180-day outcome inside the data).
Confidence   : member channels with subs at both t and t+180d / member channels.
Failure mode : SURVIVORSHIP, and it is not a caveat but the defining limitation.
               YouNiverse is "all channels with >10k subscribers and >10 videos" as
               of 2019-10-27, so every channel in it succeeded. A channel that was
               small in 2016 and stayed small was never crawled. This therefore
               measures RELATIVE GROWTH AMONG SUCCESSES, never emergence, and no
               sampling recovers the missing negative class.
               Consequence: a binary "emerging" precision on this population has a
               base rate near 1 and is uninterpretable. Gate E must use rank
               correlation instead -- see reports/gate_e_feasibility_2026-08-27.md.
Why subs, not views: `delta_views` is contaminated by a channel's back catalogue,
               and subscriber growth is closer to what a creator choosing a niche
               is actually deciding about.
```


## Composite stubs (Slice 2)

Explicitly stubs, replaced by real composites in Slice 5. Named here because they
render on `scorecards` and a number on screen invites being trusted.

- `scorecards.openness` = `breakthrough_rate_cohort.value`, unmodified. Already 0-1;
  no weighting is invented.
- `scorecards.supply` = percentile rank of `supply.median_views` among the clusters
  scored that day. Relative by design. A NULL median_views gives NULL supply, never
  a default rank. Ties share the average rank (Slice 4): without that, equal values
  got distinct ranks resolved by row order, so two clusters could swap between two
  runs of the same day and `gap` is a difference of these ranks.
- `scorecards.demand` = percentile rank of `demand.wiki_weekly_views` among the
  clusters scored that day, same construction as `supply`. NULL level -> NULL rank.
- `scorecards.gap` = demand - supply, both ranks, range [-1, 1]. A gap OF RELATIVE
  POSITION within the day's cluster set: positive means the niche ranks higher on
  audience attention than on incumbent content performance. Ranks rather than units
  because pageviews and video views share no currency, and any exchange rate between
  them would be a fabricated constant of exactly the kind data rule 6 forbids.
  Deliberately NOT comparable across days on which the cluster set changed — it is a
  within-day comparator, and Slice 6 backtests it as one (rank correlation with
  90/180-day outcomes, replayed against each day's own cluster set).
  KNOWN COMPRESSION: `supply` ranks median_views, which correlates with niche size,
  and so does demand — so gap is a mismatch of ranks that share a driver and its
  spread will be narrower than either input's. The Slice 5 composite, which brings
  uploads_per_week into supply, is the fix. A narrow gap spread is expected, not a bug.
- `scorecards.gap_confidence` = min(confidence(wiki_weekly_views),
  confidence(median_views)) — a chain is as strong as its weaker leg.
- `value`, `sustainability`, `opportunity`, `ci_low`, `ci_high`, `stage` stay NULL
  until their inputs exist. A placeholder that looks like a score is how an
  uncalibrated number gets believed.

## Defined but not implemented

*(empty — `openness.winner_age_years` was implemented in Slice 5.)*

## Inventory — already implemented in the prototypes, not yet defined here

These formulas exist as working code in `legacy/`. Porting one means writing its
entry here first (the `add-metric` skill covers the sequence), then moving the
function into `nh/features/` essentially unchanged — the analysis is sound, it
is only the I/O around it that needs replacing.

| Group | Metric | Prototype source | Defined |
|---|---|---|---|
| supply | `uploads_per_week` | `niche_hunter_yt.py` `channel_baseline` (cadence) | **yes** |
| supply | `upload_interval_days` | `niche_hunter_yt.py` `channel_baseline` | no |
| supply | `median_views` | `niche_hunter_yt.py` `channel_baseline` | **yes** |
| supply | `p90_views` | `niche_hunter_yt.py` `channel_baseline` | detail-only |
| openness | `breakthrough_rate_cohort` | `niche_hunter_yt.py` `channel_baseline.breakthroughs` (≥5× median, or ≥10× subs) | **yes** |
| openness | `views_per_sub` | `niche_hunter_yt.py` `channel_baseline` | **yes** |
| openness | `channel_breakthroughs` (feed-only) | `niche_hunter_rss.py` `channel_breakthroughs` | no |
| openness | `rss_acceleration` | `niche_hunter_rss.py` `video_velocity.acceleration` | no |
| openness | `views_per_day_24h` / `_observed` / `_lifetime` | `niche_hunter_rss.py` `video_velocity` | no |
| demand | `anchor_relative_level` | `niche_hunter_trends.py` `anchor_scaled_interest` + `trend_features.level` | no |
| demand | `slope_log_per_period` | `niche_hunter_trends.py` `trend_features` | no |
| demand | `momentum_13p` | `niche_hunter_trends.py` `trend_features` | no |
| demand | `yoy` | `niche_hunter_trends.py` `trend_features` | no |
| demand | `season_strength`, `season_index`, `peak_month` | `niche_hunter_trends.py` `trend_features` | no |
| demand | `breakout_z`, `breakout` | `niche_hunter_trends.py` `trend_features` (z > 2.5) | no |
| demand | `volatility` | `niche_hunter_trends.py` `trend_features` | no |
| demand | `total_monthly_searches` | `niche_hunter_kp.py` `niche_features` | **yes** |
| demand | `kp_trend_last3_vs_first3` | `niche_hunter_kp.py` `niche_features` | no |
| voice | `question_rate` | `niche_hunter_reddit.py` `question_clusters` | no |
| voice | `unanswered_rate` | `niche_hunter_reddit.py` `supply_signals` | no |
| voice | `recommendation_threads` | `niche_hunter_reddit.py` `supply_signals` | no |
| voice | `top_shared_video_ids` | `niche_hunter_reddit.py` `supply_signals` | no |
| money | `vw_cpc` | `niche_hunter_kp.py` `niche_features` (volume-weighted) | **yes** |
| money | `priced_share` | `niche_hunter_kp.py` `niche_features` | **yes** |
| money | `median_bid_high` | `niche_hunter_kp.py` `niche_features` | **yes** |
| money | `competition_index_mean` | `niche_hunter_kp.py` `niche_features` | **yes** |
| money | `tier1_cpc_ratio` | `niche_hunter_kp.py` `cpc_geo_spread` | no |
| money | `tier1_share` (search geo) | `niche_hunter_trends.py` `geo_tier1_share` | no |
| money | `rpm_disclosure_calibration` | `niche_hunter_reddit.py` `rpm_disclosures` (needs n≥5) | no |
| money | `sponsor_signal_rate` | `niche_hunter_yt.py` `enrich_videos.sponsor_signal` | no |
| money | `midroll_eligible_share` | `niche_hunter_yt.py` `enrich_videos.midroll_eligible` | no |

Two known definitional gaps to resolve when writing these up:

- **`tier1_share` — RESOLVED (ADR-0016).** Keyword Planner's `cpc_geo_spread` is
  authoritative for anything feeding a dollar figure; the Trends region share is
  display-only and may never feed a composite. `geo_tier1_share` is not ported until
  its weight dict is cited. Original note follows.
- ~~**`tier1_share` is computed twice**~~, from Trends region interest and from
  Keyword Planner geo runs, by different methods. Decide which is authoritative
  for the RPM model, or define how they combine — do not let both feed the
  scorecard silently.
- **`geo_tier1_share` uses hard-coded internet-population weights** (see the `w`
  dict in the Trends prototype). Those numbers need a citation or a replacement
  before any dollar figure derived from them is shown.

## Not yet implemented anywhere

`supply.top10_concentration`, `supply.median_top_video_age`,
`supply.format_mix`, `cost_risk.*` (primary-source density and cadence, PD asset
density, evergreen score, brand-safety lexicon, enforcement trend).

**`supply.median_top_video_age` — implemented, measured, and deliberately NOT
registered.** It is structurally censored by how the corpus is collected, and the
censoring is invisible in the output. Measured 2026-08-27: 2,859 of 2,977 on-niche
videos are under 90 days old, because an RSS feed returns a channel's newest 15
entries and the corpus is one day of collection. The metric returned 29-61 days for
every niche against a corpus whose mean age is 27 days -- it was reporting the
collection window and would have read as "every niche is a news treadmill".

That is data rule 9 in a new place: *"a metric that normalises away the dimension
you are comparing on comes out flat, and flat reads as a finding rather than as a
bug."* `uploads_per_week` became a rate over an observed span on **2026-08-29** —
this sentence claimed that redefinition a day before it existed, which rule 9 and
the metric's own entry record; the claim is true of the code only from that date.
The code stays; `nh deferrals` carries the trigger that would register
it (a fifth of on-niche videos older than a year).

Two names removed from this list rather than implemented:

- `demand.wikipedia_pageviews` — **superseded**, not pending. `demand.wiki_weekly_views`
  is that metric, shipped in Slice 3.
- `openness.newcomer_share` — **superseded by `openness.winner_age_years`**, not
  blocked. Its natural form is "share of top videos from channels younger than T
  years", and T is exactly the cutoff `winner_age_years` was deliberately built
  without. Implementing it would reintroduce the thing that entry tells you not to.
