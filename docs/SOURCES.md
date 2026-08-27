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
- **Join key**: `video_id`, `channel_id`.

## trends — ported ✅ (partially) `nh/collectors/trends.py`

*Reviewed 2026-08-27. **Shape only** — one term per request, no anchor (ADR-0015).*

**Measured, live:** `interest_over_time`, `interest_by_region` and `trending_now`
work. `related_queries` and `related_topics` return `TrendsQuotaExceededError`,
and the documented referer workaround also fails — so `expand_seeds()` and
topic-mid resolution are unavailable, which removes the prototype's own
prescribed fix for low-volume terms. `trendspy` was last released 2024-12-25.

Our niche phrases mostly read literal **zero**: Trends normalises 0–100 per
request against the batch maximum, so a small term beside a large one rounds
away. `aviation disasters documentary` is NaN even queried alone. Hence broad
proxy terms in `seed_terms`, and level coming from Wikipedia instead.

## trends — original notes

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

## keyword_planner — `legacy/niche_hunter_kp.py` → `nh/collectors/keyword_planner.py`

- **Auth**: Google Ads account (zero-spend is fine) + Manager (MCC) account +
  developer token. Test-account-only until Basic access is approved.
- **Quota**: 15,000 ops/day on Basic access. Cache 7 days.
- **Gives**: absolute monthly search volume, top-of-page bid low/high, average
  CPC, competition index 0–100, 12 months of monthly volumes, per-country runs.
- **Fallback**: UI export — Keyword Planner → "Get search volume and forecasts"
  → paste up to 10k keywords → Historical metrics → CSV. No approval needed.
- **Caveats**: this is Google **Search** data; YouTube search behaves
  differently — use CPC as an advertiser-value proxy, never as a YouTube RPM
  number. Metrics are grouped by close variants, so plurals and misspellings
  collapse. Long-tail terms often have no bid data; aggregate at niche level,
  never per keyword. The API returns numeric volumes where the UI shows ranges.
- **Join key**: `keyword+geo+lang`.

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

## Planned

`wikipedia` (pageviews + wikidata, join on `wikidata_qid`), `wayback`
(CDX → historical subscriber counts), and `primary/` sources for cost_risk
density (`ntsb`, `edgar`, `courtlistener`, …).
