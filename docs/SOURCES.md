# Sources

Update this file whenever you learn something about a source — that is what it
is for. Quota and etiquette specifics live in `.claude/rules/sources.md`.

## youtube_rss — ported ✅ `nh/collectors/youtube_rss.py`

*Reviewed 2026-08-27. Fixtures hand-built to the documented shape; replace with
a real capture via `scripts/record_fixtures.py`.*

- **URL**: `https://www.youtube.com/feeds/videos.xml?channel_id=UC...`
  (also accepts `playlist_id=` for `UU`/`UULF`/`UUSH` playlists).
- **Auth**: none. **Quota**: none.
- **Gives**: `videoId`, `channelId`, `title`, `published`, `updated`,
  `description`, thumbnail URL, `media:statistics/@views`,
  `media:starRating/@count` (≈ likes, since dislikes were hidden).
- **Does NOT give**: duration, comment count, subscriber count, tags, category,
  Shorts flag. Enrich new ids once through `youtube_api` (1 unit per 50).
- **Caveats**: last 15 entries only, no pagination — a channel that uploads more
  than 15 times between polls loses the overflow permanently. Unofficial endpoint.
- **Measured 2026-08-27: `media:description` is served but truncated.** Present on
  13,312 of 14,355 feed-sourced videos, median 1,052 characters and capped at
  5,000; `youtube_api` returns the untruncated text. It is ~20x the title and is
  the relevance scorer's main input, so both collectors now store it in
  `videos.description` — before Slice 4 it survived only inside `raw_records` and
  the nightly prune was on course to delete it (ADR-0017).
- **The 15-entry cap makes descriptions unbackfillable too.** A video that has
  fallen out of its channel's window cannot be re-fetched, so the text is
  recoverable only while the stored payload lives. 1,873 of 14,899 were already
  past that window on 2026-08-27.
- **Measured 2026-08-27: the feeds return NO cache validators.** No `ETag`, no
  `Last-Modified` — only `cache-control: max-age=900` and `expires`. Across 955
  channels: 0 ETags, 0 Last-Modified, 0 responses of 304, all 200. Conditional
  GET is therefore structurally impossible and the `If-None-Match` /
  `If-Modified-Since` machinery is inert. It is kept (tested, free, and YouTube
  may add validators) but do not expect a 304 and do not treat `feed_state.etag`
  staying NULL as a bug.
- **Consequence**: every poll transfers the whole feed. `requests` negotiates
  gzip by default, so it is ~7 KB on the wire per feed (~7 MB a night for 955
  channels) against ~64 KB decoded. Transfer is fine; *storage* was not — hence
  compression and retention in ADR-0010.
- The `fail_count` circuit breaker lives in `feed_state`.
- **Join key**: `video_id`, `channel_id`.
- **Why it matters most**: this is the zero-cost view-velocity series, and it
  cannot be backfilled.

## youtube_api — ported ✅ `nh/collectors/youtube_api.py`

*Reviewed 2026-08-27. Slice 1 scope is discovery + enrichment only — channel
baselines and comment sampling deferred as quota-expensive and not needed to
start the snapshot clock.*

- **Auth**: API key only for public data; no OAuth.
- **Quota**: 10,000 units/day, resets midnight Pacific. Budget 9,500.
- **Endpoints & cost**: `search.list` 100 · `videos.list` 1/50 ids ·
  `channels.list` 1/50 ids · `playlistItems.list` 1/50 items ·
  `commentThreads.list` 1/100 comments.
- **Caveats**: `search.list` returns ~500 results max per query regardless of
  paging. `hiddenSubscriberCount` means subs are unknown — write NULL, not 0.
  The uploads playlist is derivable as `"UU" + channel_id[2:]`, which saves a
  call. `commentsDisabled` comes back as a 403 and must not be treated as an
  error.
- **Load-bearing detail**: discovery must issue **both** sort orders per query.
  `order=date` is the unbiased pool including flops (the denominator for
  breakthrough rate); `order=viewCount` is what is winning now (the numerator).
  Dropping either silently breaks the openness metric.
- **`regionCode` is sent per seed (ADR-0037, 2026-08-29).** Omitting it was
  never neutral: the API serves a region-less query with a **US default**
  (documented on the response's `regionCode` property), from whatever IP the
  cron runs on. Discovery now sends `niche_seeds.geo` when the seed states a
  market and records what was sent in the raw `search_hit` payload
  (`region`, None = server default). It is a viewpoint parameter — results
  viewable in and ranked for that market — not a filter on creator geography;
  `supply.geo_concentration` still measures the divergence.
- **Join key**: `video_id`, `channel_id`.

## trends — ported ✅ (partially) `nh/collectors/trends.py`

*Collector reviewed 2026-08-27. **Source re-probed live 2026-08-28, and two of the
2026-08-27 findings below no longer hold.** Still shape-only: one term per request,
no anchor (ADR-0015).*

### Endpoint status, re-measured 2026-08-28

| Endpoint | State | Note |
|---|---|---|
| `interest_over_time` | works | the collector's only call |
| `interest_by_region`, `trending_now` | works | 2026-08-27, unchanged |
| `related_queries`, `related_topics` | **works via the referer header** | rate-limited, not blocked |

The bare call still raises `TrendsQuotaExceededError`. Passing the library's own
documented header — `headers={"referer": "https://www.google.com/"}` — **succeeds**.
That reverses the previous note in this file and the matching bullet in ADR-0015,
both of which recorded the referer workaround as failing.
`related_queries("shipwreck")` returns 25 top and 25 rising; `related_topics`
returns 17 top and 12 rising, each row carrying `mid`, `title`, `type`, `value`. So
**topic mids resolve** and `expand_seeds()` is reachable.

It is **rate-limited, not quota-blocked**: at a 3 s gap the third consecutive call
failed; at 6–8 s gaps every call succeeded. `interest_over_time` keeps working from
the same address in the same session while `related_*` is refused, so the limit is
per-endpoint, not our IP's reputation. Budget **≥6 s between `related_*` calls** —
well above the 2.5 s in `.claude/rules/sources.md`, which was set for
`interest_over_time`. The proxy suggestion in the error text is untested, and the
per-endpoint evidence argues against needing it. `trendspy` is 0.1.6 (2024-12-25).

### Can Trends resolve sub-niches? Vocabulary yes, level no

Now that `related_*` is reachable this is a live question. The three capabilities
give three different answers, and only one of them is good news.

**Level — no, and it is structural.** Measured 2026-08-28 over the seven live
`seed_terms`, 5-year weekly, each queried alone, so each is normalised against **its
own peak** rather than a sibling's:

| term | median | p90 | zeros | max ÷ median |
|---|---|---|---|---|
| court case | 48 | 82 | 0/262 | 2.1x |
| shipwreck | 28 | 49 | 0/262 | 3.6x |
| supreme court | 23 | 54 | 0/262 | 4.3x |
| murder trial | 20 | 44 | 0/262 | 5.0x |
| corporate fraud | 11 | 52 | 0/262 | 9.1x |
| plane crash | 3 | 5 | 0/262 | 33.3x |
| bridge collapse | **0** | **1** | **201/262** | ∞ |

`bridge collapse` is not *small* — its max is 100, like every row here. It is
**spiky**: one event owns the scale and the whole baseline quantises to 0, leaving a
series with two distinct values that cannot express momentum at all.

That is the mechanism that decides the sub-niche question. Normalisation is against
the term's own peak, so narrowing a term never lowers its ceiling — it concentrates
the term's traffic into the events that define it, lifting the peak against a
baseline that then rounds away. **Sub-niches are narrower by construction, so
resolution degrades in exactly the direction sub-niche work travels.** Ordered by
that last column the table is also ordered by breadth.

Strength of the claim: breadth here is a judgement, not a measured quantity, and
only `shipwreck` appears in both this set and the Keyword Planner export, so
absolute volume cannot be regressed against the ratio (n=1).

**Topic mids do not rescue it.** The prototype named mid resolution as *the* fix for
low-volume terms. Measured both ways:

| query | mean | median | max ÷ median |
|---|---|---|---|
| string `shipwreck` | 32.71 | 28.0 | 3.6x |
| mid `/m/01nzyt` *Shipwreck* | 8.25 | 7.0 | **14.3x — worse** |
| string `murder trial` | 24.13 | 19.5 | 5.1x |
| mid `/m/051_y` *Murder* | 52.45 | 51.0 | **2.0x — better** |

Opposite results, one explanation: `/m/051_y` is *Murder*, far broader than "murder
trial", whereas `/m/01nzyt` is *Shipwreck*, no broader than its own string — and
that string's apparent advantage is contamination, since `related_topics` shows part
of its traffic is *Old School RuneScape*. A mid helps when it **broadens** and hurts
when it disambiguates steady off-topic traffic away. Mids are a breadth knob on the
same axis, not an escape from it: buying resolution with a mid means measuring
something broader than the sub-niche you asked about.

**Vocabulary — yes, with two defects.** `related_*` is the only Trends capability
that actually *discovers* sub-niches, and it returns real material. But `top` mixes
broadenings in with narrowings (`ship`, `the trial`), and `rising` is dominated by
news-cycle ephemera (`murder trial` → named current trials) and by homonym drift
(`shipwreck` → the first six rising queries are all RuneScape). `related_topics.type`
is the disambiguator — filter to `Topic` and `Online game` drops out — which is the
reason to prefer `related_topics` over `related_queries` for seed expansion.

**Shape — unchanged, and still the right use.** ADR-0015's *decision* does not move:
level from Wikipedia, shape from Trends. Nothing above touches the normalisation and
anchor-chain argument the ADR rests on; `related_*` availability was cited there as
supporting evidence, not as the reason. What is now settled is that its loss cost us
nothing measurable — the fix it removed is not a fix.

### Enabling `related_*` — what it buys, what it costs

Cheap: at a 6 s gap, seed expansion for 11 domains × ~6 terms is ~66 calls ≈ 7
minutes, once, cached. It needs no auth and no approval.

Scope it to **vocabulary for clustering** — candidate sub-niche terms, then priced
against absolute volume by the Keyword Planner export. It must not be sold as
sub-niche demand measurement: per the table above, Trends cannot supply a level for
a narrow term, and the Keyword Planner export quantises volume to four buckets
(50 / 500 / 5000 / 50000), so order-of-magnitude is the best level any current
source gives a sub-niche.

Re-check triggers are evidence-shaped, not dated:

- **Drop the referer workaround** when a bare `related_queries("shipwreck")` returns
  rows — the header is a workaround, not a contract.
- **Revisit the ≥6 s gap** if `TrendsQuotaExceededError` appears at that spacing.
- **Revisit mids-as-fix** only with a measurement on a *narrow* term; the two above
  are mid-breadth, and `bridge collapse` — the case that matters — hit the rate
  limit before it could be tested.

## trends — original notes

*Kept as the prototype's own record. Two claims here are superseded by the
2026-08-28 measurements above: "low-volume terms return all zeros" attributes to
volume what is actually spikiness, and "prefer topic mids" is not supported —
mids helped one term and hurt another, tracking breadth rather than representation.*

- **Library**: `trendspy`. **Auth**: none. Unofficial endpoint.
- **Gives**: interest over time, interest by region, related/rising queries and
  topics, trending now.
- **Caveats**: values are normalized **0–100 per request** — two requests are
  never comparable unless both contain the same anchor keyword. Max 5 terms per
  request (1 anchor + 4 targets). No absolute volumes. Sampled: re-running
  jitters ±5 points. Low-volume terms return all zeros. Prefer topic mids
  (`/m/0abc`) over raw strings — they aggregate spellings and languages.
- **Join key**: `keyword+geo+lang`, then `cluster_id` after embedding.

## reddit — `legacy/niche_hunter_reddit.py` → `nh/collectors/reddit.py`

- **Library**: `praw`. **Auth**: OAuth client credentials, read-only.
- **Access reality (2026)**: the Responsible Builder Policy requires approval
  **before** any API access; self-service registration closed in late 2025.
  Grandfathered credentials still work. Until credentials exist,
  `Settings.configured("reddit")` is False and the nightly job records the
  source as skipped.
- **Quota**: ~100 queries/min per client, averaged over 10 minutes. Watch
  `reddit.auth.limits` — the header is the truth.
- **Gives**: subreddit ecosystem and size, question posts, "recommend a channel"
  threads, YouTube links shared in the wild, RPM/CPM disclosures in creator
  subs, comment text for language/geo proxying.
- **Caveats**: listings cap around 1000 items; vary `sort` and `time_filter` to
  widen coverage. `replace_more(limit=0)` — each expansion costs a request.
- **Join key**: `cluster_id` after embedding; shared video ids join on `video_id`.

### Access re-checked 2026-08-28 — the blocker holds

Re-checked the same day the Trends "wall" turned out to be false, because the two
claims came from the same research pass and one of them was wrong. **This one holds.**
Self-service registration did close in late 2025; every new OAuth client, free or paid,
goes through a manual approval ticket. Reported queues run two to four weeks, with a
pattern of silent rejections for vague or trivial use cases.

*Evidence quality:* the **closure is measured** — the app-creation form was tried on
2026-08-28 and refused (see the runbook below). The surrounding detail (queue lengths,
rejection patterns, the $0.24/1k commercial rate) is still only corroborated from
secondary write-ups: Reddit's own Data API wiki and the Responsible Builder Policy
article both return **403** to an unauthenticated fetch. Keep the two apart.

The **free tier is intact**: 100 queries/min per OAuth client, non-commercial — which
covers this project (read-only, a few hundred queries/night). Commercial is $0.24/1k
calls and a hand-reviewed contract; we do not want that tier.

ADR-0021 still stands and is the point: *"blocked on approval" describes a policy, not a
queue position.* No application has ever been filed. The clock starts when one is.

### Enablement runbook — the human half

Steps 1–4 cannot be done by the assistant: they create an app under a personal identity.

**Approval comes before app creation.** An earlier version of this runbook had the
order backwards. Confirmed empirically 2026-08-28: `old.reddit.com/prefs/apps/` refuses
to create anything and returns the Responsible Builder Policy link instead. That makes
the closure **measured**, not merely corroborated — the one claim in this section that
is now first-hand.

**`developers.reddit.com` is the wrong product.** It is Devvit, the Developer Platform,
for apps that run *inside* the Reddit experience — interactive posts, games, mod tools.
This project pulls data *out* into an external pipeline, which Devvit does not cover. A
Devvit account is harmless but unlocks nothing here; do not mistake it for progress.

1. Use an **established** Reddit account (verified email, some history) — new accounts
   draw rejections.
2. Open the **Reddit Data API Wiki** (`support.reddithelp.com/hc/en-us/articles/`
   `16160319875092-Reddit-Data-API-Wiki`) and follow its *contact us* link. The form
   asks for a category — **developer**, researcher, or moderator — and a use case. The
   page 403s automated fetches, so it must be opened in a browser.
3. **File once.** The policy prohibits registering multiple accounts or submitting
   multiple requests for the same use case, so a retry after silence is a rejection
   trigger rather than a nudge. State plainly: **non-commercial**, research/analytics,
   **no redistribution of Reddit content**, low volume. Silent rejections skew toward
   vague use cases, and our real profile genuinely is modest.
4. **Category depends on a question only the operator can answer.** The free tier is
   non-commercial. Applying as *developer* for a commercial use is a documented
   rejection trigger, and the policy forbids misrepresenting why the data is accessed.
   A personal research tool is honestly *developer*/*researcher*; anything feeding a
   revenue-generating operation belongs on the commercial route ($0.24/1k, contract)
   however much harder that is. Do not split the difference in the wording.
5. **Only on approval** does `reddit.com/prefs/apps` create a **`script`** app
   (server-side, no redirect flow — the right shape for a nightly job). Its `redirect
   uri` field is required but inert for script apps; `http://localhost:8080` is the PRAW
   convention and is editable later. `about url` may be blank. The `client_id` is the
   short string under the app name, *not* the name and not the secret — confusing the
   two surfaces later as an opaque 401.
6. Fill `.env` (already scaffolded, `.env.example:44-49`):

   ```
   NH_REDDIT_CLIENT_ID=
   NH_REDDIT_CLIENT_SECRET=
   NH_REDDIT_USER_AGENT=python:niche-hunter:0.1.0 (by u/yourusername)
   ```

   The UA format `<platform>:<app_id>:<version> (by u/<username>)` is **mandatory and
   enforced**. A generic UA causes throttling that reads like a code bug.

**Do not set `NH_REDDIT_CLIENT_ID` to a placeholder.** `nh/jobs/deferrals.py:124` uses
`NH_REDDIT_CLIENT_ID is set` as its trigger, so a dummy value fires the deferral falsely.
`praw>=7.7` is already declared as the `reddit` extra — nothing needs installing first.

### Why it is worth the wait, post-Gate E

Gate E's failure analysis found **zero of 4,517 niche-dates with negative growth**: the
corpus contained no failures, so it measured relative growth among channels that had
already succeeded and could not express emergence at all.

Reddit is one of the few reachable sources that can express **demand which is not
already served** — the port target names *"recommend a channel" threads that got no
YouTube link back* as the sharpest single signal in the source: a supply gap with a real
person attached. Every signal now in the scorecard is measured on content that already
exists, which is structurally why the gap metric could not see emergence. This is the
most plausible available fix for what Gate E actually exposed, which is the argument for
filing rather than deferring again.

Design constraint on the eventual port (ADR-0021, roadmap risk #4): Reddit inputs are
**optional with a confidence penalty, never required**, so an outage or a revoked
approval cannot take features down.

**Re-check trigger** — evidence-shaped, not dated: re-open this section when an
application has actually been filed and either approved or refused. Nothing about the
policy changes what we do; only filing does.

## keyword_planner — `legacy/niche_hunter_kp.py` → `nh/collectors/keyword_planner.py`

- **Auth**: Google Ads account (zero-spend is fine) + Manager (MCC) account +
  developer token + **Basic access** — planning services are closed below Basic;
  see the runbook below.
- **Quota**: 15,000 ops/day on Basic access. Cache 7 days.
- **Gives**: absolute monthly search volume, top-of-page bid low/high, average
  CPC, competition index 0–100, 12 months of monthly volumes, per-country runs.
- **Fallback**: UI export — Keyword Planner → "Get search volume and forecasts"
  → paste up to 10k keywords → Historical metrics → CSV. No approval needed.
- **Caveats**: this is Google **Search** data; YouTube search behaves
  differently — use CPC as an advertiser-value proxy, never as a YouTube RPM
  number. Metrics are grouped by close variants, so plurals and misspellings
  collapse. Long-tail terms often have no bid data; aggregate at niche level,
  never per keyword. ~~The API returns numeric volumes where the UI shows
  ranges~~ — **unverified for a zero-spend account**; see the API-access runbook
  below.
- **Join key**: `keyword+geo+lang`.

### API access runbook — verified against Google's own docs, 2026-08-29

The operator's account is a **regular** Ads account and no manager account
exists, so the sequence below has not started. Every step is from
developers.google.com (get-started/dev-token, api-policy/access-levels) unless
labelled otherwise.

1. **Create a manager (MCC) account.** Required, not optional: the developer
   token lives only in a manager account's API Center, and "it cannot be a
   Google Ads test manager account". Creation is free and self-service
   (ads.google.com → tools → manager accounts) but wants an email address **not
   previously associated with Google Ads**. The existing regular account is then
   *linked under* the manager — it is not converted, and its zero-spend history
   is untouched.
2. **Get the developer token** from the manager account's API Center by
   completing the API access form: accurate company details and a functioning
   website URL are required. The token is granted immediately, at **Explorer**
   access by default (occasionally Test-Account-only instead).
3. **Explorer access does not open Keyword Planner.** This is the step
   practitioner write-ups skip. Explorer allows production calls at 2,880
   ops/day, but its restriction list *names the planning services*:
   `KeywordPlanIdeaService`, `KeywordPlanService`, `ReachPlanService`,
   `AudienceInsightsService` are all excluded. A token in hand generates no
   keyword data until Basic clears.
4. **Apply for Basic access** in the API Center: drop-down next to *Access
   level* → *Apply for Basic Access*. Prerequisites Google states: a valid,
   monitored API contact email, and all active Ads accounts linked under the
   manager. Review is "typically 5 business days" — the "24–48h" in
   `reports/source_audit_2026-08-28.md` was a practitioner report, and Google's
   own figure is the one to plan on. Basic gives 15,000 ops/day,
   test + production.
5. **Plumbing besides the token** (implementation, same docs): OAuth2
   credentials from a Google Cloud project, `login_customer_id` set to the
   manager account id, requests issued against the linked regular account's
   customer id. `GenerateKeywordHistoricalMetrics` requires a keyword plan
   object per request (confirmed by the API team on the support forum).

**Does Basic access return numeric volumes for a zero-spend account? UNRESOLVED
— and it is the deciding uncertainty, so the honest state is recorded rather
than a side picked.** Google's reference defines `avg_monthly_searches` as an
int64 twelve-month average and documents no spend gate on the API; but the UI's
"limited data view" for low-spend accounts (bucketed ranges) *is* documented,
and practitioner reports disagree on whether the API is behind the same gate.
Our own measured evidence points the wrong way for optimism: this zero-spend
account's UI CSV export already returns power-of-ten bucket midpoints (50 / 500
/ 5,000 / 50,000 / 500,000) rather than ranges, i.e. the bucketing follows the
**account**, not the surface — inference: the API on this account plausibly
returns the same bucket values, just typed as integers. The test is one
`GenerateKeywordHistoricalMetrics` call on day one of Basic access, compared
against the stored CSV buckets for the same keywords. **What the API buys even
if volumes stay bucketed** — and it is a lot: the twelve monthly columns
(0/360 empty in every CSV export, the whole input of `kp_trend_last3_vs_first3`),
per-geo runs as a request parameter instead of a manual export each, and
`ReachPlanService` CPM forecasts. So the application is worth filing on either
branch of the uncertainty; only the `geo_value` bucketing-noise problem waits on
the test.

`reports/geo_value_2026-08-28.md` flagged `inflation` and `humanism` sharing an
identical US `bid_high` of 64,083 COP and guessed close-variant collapse.
Checked against all 162 stored `keyword_metrics` rows (96 US + 66 GB,
2026-07-31 period; 107 rows carry a `bid_high`):

- **The shared value is not a pair, it is a sentinel.** 64,083.40 COP appears on
  **five** rows — `human impact on the environment`, `humanism`, `inflation`,
  `philosophy of mind` (US) and `epistemology` (GB) — and its exact tenth,
  6,408.34 COP, on two more (`scientific method` US, `occult` GB `bid_high`;
  also `humanism` GB `bid_low`). At one implied rate of 4,005.2125 COP/USD those
  are exactly **US$16.00 and US$1.60**; none of the other 100 priced rows is a
  round dollar figure at that rate. One row is fully degenerate:
  `human impact on the environment` (US) has `bid_low = bid_high = 64,083.40`.
- **Close-variant grouping is disproven.** The five sharers are semantically
  unrelated, and their volumes (5,000 vs 500,000), `bid_low`s (94.61 vs
  5,742.30) and competition indexes all differ — a close-variant collapse merges
  whole metric rows, not one column. This is an **estimator default**: Google
  emits a fixed round-dollar bid estimate when a keyword lacks auction depth,
  converted to the account currency at a fixed rate. Same failure shape as the
  identical `$1.21` RPM default the disclosure pass caught.
- **So the collision is systematic but bounded and detectable**: 7 of 107 priced
  rows (6.5%), across both geos and both bid columns, always one of two exact
  values. Inference, labelled as such: other exports may carry other round-dollar
  defaults; the durable test is exact cross-keyword equality (or exact roundness
  in USD at the account's implied rate), not the two literals.
- **Consequences.** (1) `history-of-ideas`' US value is 70% `humanism`, which
  carries the $16 sentinel — the figure stays unquotable, now with a measured
  reason. (2) Any Slice 9 money metric over `bid_high`/`bid_low`
  (`median_bid_high`, `vw_cpc`) must treat sentinel-valued bids as **unpriced
  (NULL), never as a price** — at 1–6 priced keywords per niche, one imputed $16
  dominates a median. (3) `bid_high` remains usable for tiering and for
  cross-niche comparison *after* sentinel rows are excluded; 100 of 107 priced
  rows look like real, distinct auction estimates.

## wikipedia — ported ✅ `nh/collectors/wikipedia.py`

*New in Slice 3; no legacy prototype. The primary demand signal (ADR-0015).*

- **Endpoint**: `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/
  en.wikipedia/all-access/user/{article}/daily/{start}/{end}`
- **Auth**: none. **Quota**: none. Wikimedia's policy asks for a descriptive
  User-Agent with contact details — `NH_WIKI_USER_AGENT`.
- **Gives**: absolute daily pageviews, back to **2015-07-01**. Measured: 16,404
  rows across 15 articles covering 1,095 days, fetched in under a minute.
- **`agent=user` is mandatory.** Bot and spider traffic is **19–54% of raw
  counts and is not uniform across articles** (Corporate_scandal 54%, Aviation
  19%), so `all-agents` systematically inflates small niches relative to large
  ones. Measured: filtering widens the cross-niche spread from 295× to 590×.
- **Counts mature over 24–48h.** Snapshots are first-write-wins, so nothing
  closer than `NH_WIKI_LAG_DAYS` (2) is ever requested — an early fetch would
  freeze an undercount permanently.
- **Caveats**: measures encyclopedic curiosity, not intent to watch a video.
  Reference-heavy articles carry school-calendar traffic. News events spike
  attention without durable video demand. The article mapping is curation and
  nothing in the data detects a bad one.
- **Join key**: `seed_terms.term`, and `wikidata_qid` when populated.

## courtlistener — not ported; access re-measured 2026-08-29

- **The 2026-08-27 finding "works unauthenticated" does not reproduce.** Measured
  2026-08-29 03:30 UTC, one unauthenticated GET to
  `https://www.courtlistener.com/api/rest/v4/dockets/?page_size=1` returns
  **HTTP 401** `{"detail": "Authentication credentials were not provided."}` with
  `WWW-Authenticate: Bearer realm="api"`. The repo's `nh/seeds.py` recorded a
  successful unauthenticated live test dated 2026-08-27; that test postdated the
  policy change below, so either it hit a not-yet-enforced path or the claim was
  wrong. Either way the measurement is what stands, and `nh/seeds.py` now says so.
- **Access moved into memberships on 2026-05-07** (Free Law Project announcement,
  https://free.law/2026/05/07/api-included-in-memberships/). Free accounts:
  **5 req/min, 50/hour, 125/day**; higher tiers come with paid memberships.
  Registration is free and self-service; auth is a token in the
  `Authorization` header.
- **What it still gives, when authenticated**: REST v4 over opinions, dockets,
  courts; `dateFiled` on dockets, so filing cadence is a real series. 125/day is
  plenty for a nightly per-niche cadence count and nothing like enough for a bulk
  crawl — their bulk data files are the sanctioned path for that.
- **Consequence**: any future `cost_risk` collector for this source needs a
  credential in `.env` via `Settings` (never at module scope), and its quota row
  must count against 125/day. Until someone registers an account, the source is
  *obtainable, unregistered* — the ADR-0021 distinction applies.

## Planned

`wikipedia` (pageviews + wikidata, join on `wikidata_qid`), `wayback`
(CDX → historical subscriber counts), and `primary/` sources for cost_risk
density (`ntsb`, `edgar`, `courtlistener`, …).
