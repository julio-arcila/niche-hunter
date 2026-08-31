# What source would actually measure each metric — an audit

Prompted by a day in which three of this project's numbers turned out to be proxies
standing in for things nobody had measured: `bid_high` is a search-ad bid, not RPM
(`rpm_disclosure_result_2026-08-28.md`, n=0 across nine units); `gap` does not predict
growth (`backtest_2026-08-28.md`, a powered null); and the four sources measure four
different populations (ADR-0035). The question this answers: **for each metric, what
source would measure the claim accurately, and is it obtainable?**

Every external claim below carries a URL. Inferences are labelled.

## The headline: sources are not why Gate E failed

Demand alone scored **+0.049**, supply alone **−0.073**. Neither input carried signal
*before* they were combined, the score varied, the outcome varied, and the test was
powered. ADR-0035's retraction closed the last instrument-shaped escape. A better Trends
level, un-bucketed volumes, or perfect relevance labels would have produced **a cleaner
ranking of the same wrong question** — relative growth among channels that had already
succeeded. Zero of 4,517 niche-dates negative is not measurement error; it is the corpus.

**No obtainable source rewrites that verdict.** The only instrument that could re-open the
predictive claim is a panel containing failures, and every obtainable version is
**prospective**: the small channels this pipeline discovers today, snapshotted nightly,
yield unbiased 90/180-day outcomes by early 2027. Free, already running, and requiring
only that discovery keep both sort orders and that a fresh pre-registration be written on
the new grain *before* outcomes accrue. No retrospective purchase substitutes — Social
Blade covers channels people looked up, Wayback covers pages people archived, and both are
conditioned on attention, which is the outcome being predicted.

## Three free applications, ranked by impact on decisions actually being made

**1. Google Ads API Basic access** — free, 15,000 ops/day, reportedly 24–48h approval
([access levels](https://developers.google.com/google-ads/api/docs/api-policy/access-levels)).
Buys four things the CSV cannot: numeric `avg_monthly_searches` instead of power-of-ten
buckets — and the `geo_value` correction traced **5-position rank swings to the bucketing
alone**, on the ranking the pivot decision rests on; the 12 monthly columns that are
**0/360 empty** in the export and are the entire input of `kp_trend_last3_vs_first3`;
per-geo runs without manual exports, dissolving Slice 9's 96/162 join problem into a
loader argument; and `ReachPlanService`
([docs](https://developers.google.com/google-ads/api/docs/reach-forecasting)), which
forecasts CPM for **YouTube video campaigns** — the same auction that funds RPM, one step
closer than a search bid.
*Caveats:* needs a payment method on file (no spend). Practitioner reports say zero-spend
accounts may still get ranges ([get-ryze](https://www.get-ryze.ai/blog/google-ads-api-keyword-planner-claude))
— testable in an afternoon once the token clears, and it decides whether the upgrade
delivers everything or only three of four. Reach Planner targets audiences, **not content
topics**, so it prices reaching people on YouTube, not ads on this niche's videos.

**2. Reddit Data API** — free, application-gated, already runbooked in `SOURCES.md`. Feeds
all four `voice.*` metrics *and* the RPM v2, whose diagnosed defect was that disclosures
live in Reddit threads the web index doesn't surface. Post-Gate-E this is the one
reachable source measured on **demand rather than on incumbent content** — the structural
blind spot the null exposed. Costs a form.
*Do not* bridge the wait with Arctic Shift bulk dumps: unlicensed bulk redistribution is
what the Responsible Builder Policy polices, and the approval is worth more than a backfill.

**3. Google Trends API (alpha)** — free, application, **invite-only**
([announcement](https://developers.google.com/search/blog/2025/07/trends-api),
[access](https://developers.google.com/search/apis/trends)). Consistently scaled interest
across requests — precisely the property whose absence forced ADR-0015's level-from-
Wikipedia decision, and plausibly the fix for the quantization floor that blocks sub-niche
demand (`bridge collapse`: 201/262 zeros). Whether a narrow term still quantizes to zero
is **inferred, not documented** — it is the thing to test in week one of access. Ranked
third only because acceptance is not in the operator's control.

**Also free and worth taking:** **SponsorBlock** dumps
([database](https://sponsor.ajay.app/database), CC BY-NC-SA) turn `sponsor_signal_rate`
from lexical guesswork into observed sponsor segments. Coverage skews to videos popular
with extension users (inferred), so it is a cross-check on the detector, not a replacement.
The NC clause matters if this ever commercializes.

## The honest negatives — six ceilings, to be recorded so nobody re-searches them

1. **YouTube RPM by niche.** Realized RPM exists only in the YouTube Analytics API under
   `yt-analytics-monetary.readonly`, **for the channel owner or MCN**
   ([metrics](https://developers.google.com/youtube/analytics/metrics)). Every third-party
   figure is an estimator — the disclosure pass caught an identical `$1.21` default across
   unrelated channels — and creator disclosures returned n=0. The ceiling is search bids,
   optionally Reach Planner CPM, and eventually **N=1 ground truth from the operator's own
   channel**, which will be the only real RPM number this project ever holds.
2. **Audience geography.** Owner-only. `channels.country` is self-reported creator
   domicile, absent for 236/955, and is *not* audience location — the conflation that cost
   a retracted claim in ADR-0035.
3. **Historical emergence outcomes.** A 2015–2019 panel including failures does not exist
   at any price. Channels that stayed small were never crawled by anyone.
4. **Brand-safety enforcement.** Per-video demonetization is owner-only. A static lexicon
   is a prior, not a measurement, and should say so.
5. **True YouTube search volume.** No official source. Keyword Planner is Google *Search*;
   vidIQ and Ahrefs are undisclosed models — the estimator class the RPM pass rejected on
   principle.
6. **Niche membership completeness.** `search.list` caps ~500 results and nothing
   enumerates a topic's channels. Every supply metric is "among discovered channels"
   forever. The confidence legs already encode this — keep them.

## Adequate as sourced — do not manufacture gaps here

`format_mix`, `midroll_eligible_share`, `winner_age_years` inputs, the four Wikipedia
*shape* metrics (a scale-free ratio cancels the population bias to first order), every
RSS-velocity metric, and the `cost_risk` primary sources for domains that have an
institution. Several defects flagged elsewhere — `median_views`' lifetime-views stopgap,
`top10_concentration`'s ranking bias, `uploads_per_week`'s RSS censoring — are fixed by
**own snapshot depth plus time**, not by any purchase.

## The cheapest accuracy purchase in the audit

**Human relevance labels.** 60–100 rows sampled above the 0.55 threshold — the open item
from the interrater audit. An afternoon of operator time, or ~$30–100 on a labelling
marketplace. Every `supply.*` number passes through the instrument it validates, and the
topic-domain axis currently rests entirely on machine labels.

## One thing to re-test before trusting it

`nh/seeds.py` records a live test on **2026-08-27**: *"CourtListener's REST API works
unauthenticated and carries `dateFiled`."* But Free Law Project moved full API access into
memberships on **2026-05-07**, with free accounts at 5/min, 50/hour, **125/day**
([announcement](https://free.law/2026/05/07/api-included-in-memberships/),
[limits](https://wiki.free.law/c/courtlistener/help/api/rest/v4/api-usage)). The repo's
test postdates the change, so one of the two is wrong. Re-test before any `cost_risk`
work depends on it; `SOURCES.md` needs the rate limits either way.
