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
