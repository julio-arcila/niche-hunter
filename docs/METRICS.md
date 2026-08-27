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
Confidence   : how computed, e.g. min(cohort_n / 30, 1)
Failure mode : what makes this metric lie; what it returns when inputs are sparse
Feeds        : which composite score, if any
```

## Inventory — already implemented in the prototypes, not yet defined here

These formulas exist as working code in `legacy/`. Porting one means writing its
entry here first (the `add-metric` skill covers the sequence), then moving the
function into `nh/features/` essentially unchanged — the analysis is sound, it
is only the I/O around it that needs replacing.

| Group | Metric | Prototype source | Defined |
|---|---|---|---|
| supply | `uploads_per_week` | `niche_hunter_yt.py` `channel_baseline` (cadence) | no |
| supply | `upload_interval_days` | `niche_hunter_yt.py` `channel_baseline` | no |
| supply | `median_views`, `p90_views` | `niche_hunter_yt.py` `channel_baseline` | no |
| openness | `breakthrough_rate_cohort` | `niche_hunter_yt.py` `channel_baseline.breakthroughs` (≥5× median, or ≥10× subs) | no |
| openness | `views_per_sub` | `niche_hunter_yt.py` `channel_baseline` | no |
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
