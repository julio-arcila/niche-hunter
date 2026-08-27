# Metrics

**A metric starts as an entry here — formula, inputs, join key, confidence —
then code, then a test.** A definition that lives only inside a Python function
cannot be reviewed, backtested, or compared across a schema change.

Every `features_daily` row stores `value`, `confidence` and `inputs_n`. Absent
inputs produce NULL, never 0.

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

Five metrics, three groups. Each was verified to **vary across the five live
niches** before implementation — a metric that is flat across the units it
compares is not a comparator, however plausible its formula.

### supply.uploads_per_week
```
Formula      : count of videos with published_at in (day-28d, day], is_short IS FALSE,
               belonging to the cluster's member channels, divided by 4.0. A cluster
               TOTAL, not a per-channel average: supply is the volume of competing
               long-form content entering the niche. Per-channel median cadence is
               recorded in detail.per_channel_median for reference.
Inputs       : videos(published_at, is_short, channel_id); cluster_members
               (item_type='channel'); window (day-28d, day].
Join key     : cluster_id, via videos.channel_id -> cluster_members.item_id
Confidence   : min(known_n / 30, 1) * (publishing_n / member_n) -- sample adequacy
               TIMES coverage. Adequacy alone saturates: 74 contributing channels
               of 197 scores 1.00 while the metric sees 38% of the niche, and
               those 74 are the enriched, discovery-biased ones. Coverage alone
               would under-report a small but fully observed cluster. Measured
               live: adequacy-only gave 1.00 for every niche; the product gives
               0.38 for aviation-disasters, which is the true picture.
Failure mode : RSS feeds cap at 15 entries, so a channel uploading >15 times in 28
               days is undercounted. MUST NOT be computed as a count over a fixed
               window using RSS rows -- measured, that censors at the cap and every
               niche converges on 1.17/wk (1.1x spread) against 2.2x for the
               span-based form. Unknown-format videos are excluded, biasing low
               until the enrichment backfill completes. No member channels -> NULL.
Feeds        : scorecards.supply; gap from Slice 3
Measured     : 2.2x spread across the five seeds (2.31 to 5.01 /wk)
```

### supply.median_views
```
Formula      : median of current views over the pooled eligible videos of all member
               channels. Eligible: is_short IS FALSE, published_at <= day-14d, within
               the channel's 15 most recent known uploads (uniform per-channel cap =
               RSS feed depth, so API-discovered channels get no deeper window).
               Views from the video's latest video_snapshots row with observed_date
               <= day. Pooled, not median-of-medians: supply is the field you compete
               against, and a 500-sub channel should not weigh the same as a 30M one.
Inputs       : videos; video_snapshots(observed_date, views, source); cluster_members
Join key     : cluster_id
Confidence   : min(contributing_channels / 30, 1). Channels, not videos: views are
               correlated within a channel, so channels are the effective sample.
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
Measured     : 33x spread (330 to 10,832 views)
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
Failure mode : depends entirely on the enrichment backfill. Before it runs the
               denominator is the 1,242 API-discovered videos only -- a
               discovery-biased subset. Deleted videos leave unknown durations; if
               deletions skew short, the share biases up. Zero known -> NULL.
Feeds        : money composite in Slice 5; display-only in Slice 2
```

## Composite stubs (Slice 2)

Explicitly stubs, replaced by real composites in Slice 5. Named here because they
render on `scorecards` and a number on screen invites being trusted.

- `scorecards.openness` = `breakthrough_rate_cohort.value`, unmodified. Already 0-1;
  no weighting is invented.
- `scorecards.supply` = percentile rank of `supply.median_views` among the clusters
  scored that day. Relative by design. A NULL median_views gives NULL supply, never
  a default rank.
- `gap`, `value`, `sustainability`, `opportunity`, `ci_low`, `ci_high`, `stage`
  stay NULL until their inputs exist. There is no demand side until Slice 3, and a
  placeholder that looks like a score is how an uncalibrated number gets believed.

## Defined but not implemented

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
Status       : designed and measured (6.4x spread: maritime 1.8y to corporate 11.6y,
               stable at the extremes across N=50/100/200) but NOT implemented. It
               was built to replace breakthrough_rate_cohort, which turned out not to
               need replacing. Candidate for Slice 5 as a second openness signal.
```

---

## Inventory — already implemented in the prototypes, not yet defined here

These formulas exist as working code in `legacy/`. Porting one means writing its
entry here first (the `add-metric` skill covers the sequence), then moving the
function into `nh/features/` essentially unchanged — the analysis is sound, it
is only the I/O around it that needs replacing.

| Group | Metric | Prototype source | Defined |
|---|---|---|---|
| supply | `uploads_per_week` | `niche_hunter_yt.py` `channel_baseline` (cadence) | **yes** |
| supply | `upload_interval_days` | `niche_hunter_yt.py` `channel_baseline` | no |
| supply | `median_views`, `p90_views` | `niche_hunter_yt.py` `channel_baseline` | **yes** |
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
| demand | `total_monthly_searches` | `niche_hunter_kp.py` `niche_features` | no |
| demand | `kp_trend_last3_vs_first3` | `niche_hunter_kp.py` `niche_features` | no |
| voice | `question_rate` | `niche_hunter_reddit.py` `question_clusters` | no |
| voice | `unanswered_rate` | `niche_hunter_reddit.py` `supply_signals` | no |
| voice | `recommendation_threads` | `niche_hunter_reddit.py` `supply_signals` | no |
| voice | `top_shared_video_ids` | `niche_hunter_reddit.py` `supply_signals` | no |
| money | `vw_cpc` | `niche_hunter_kp.py` `niche_features` (volume-weighted) | no |
| money | `priced_share` | `niche_hunter_kp.py` `niche_features` | no |
| money | `median_bid_high` | `niche_hunter_kp.py` `niche_features` | no |
| money | `competition_index_mean` | `niche_hunter_kp.py` `niche_features` | no |
| money | `tier1_cpc_ratio` | `niche_hunter_kp.py` `cpc_geo_spread` | no |
| money | `tier1_share` (search geo) | `niche_hunter_trends.py` `geo_tier1_share` | no |
| money | `rpm_disclosure_calibration` | `niche_hunter_reddit.py` `rpm_disclosures` (needs n≥5) | no |
| money | `sponsor_signal_rate` | `niche_hunter_yt.py` `enrich_videos.sponsor_signal` | no |
| money | `midroll_eligible_share` | `niche_hunter_yt.py` `enrich_videos.midroll_eligible` | no |

Two known definitional gaps to resolve when writing these up:

- **`tier1_share` is computed twice**, from Trends region interest and from
  Keyword Planner geo runs, by different methods. Decide which is authoritative
  for the RPM model, or define how they combine — do not let both feed the
  scorecard silently.
- **`geo_tier1_share` uses hard-coded internet-population weights** (see the `w`
  dict in the Trends prototype). Those numbers need a citation or a replacement
  before any dollar figure derived from them is shown.

## Not yet implemented anywhere

`supply.top10_concentration`, `supply.median_top_video_age`,
`supply.format_mix`, `openness.newcomer_share`, `demand.wikipedia_pageviews`,
`cost_risk.*` (primary-source density and cadence, PD asset density, evergreen
score, brand-safety lexicon, enforcement trend).
