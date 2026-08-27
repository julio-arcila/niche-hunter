# Source etiquette and quota budgets

Exceeding a quota costs a day of collection. Getting blocked costs the source.

| Source | Budget / limit | Etiquette |
|---|---|---|
| `youtube_api` | 10,000 units/day, resets midnight Pacific. Reserve 500 → budget 9,500. | `search.list` costs **100**; `videos.list`/`channels.list`/`playlistItems.list` cost **1 per 50 ids**; `commentThreads.list` **1 per 100**. Batch to 50. Charge quota only on HTTP 200. |
| `youtube_rss` | No quota, no auth. | 8 workers max, 0.2–0.8s jitter. Always send `If-None-Match`/`If-Modified-Since`. Real contact address in the User-Agent. Circuit-break a channel at `fail_count >= 5`. Feeds are unofficial — politeness *is* the rate limit. |
| `trends` | Unofficial endpoint, no published limit. | 2.5s minimum gap plus jitter, exponential backoff on 429, cache every response 24h. Max 5 terms per request (1 anchor + 4 targets). Above a few hundred calls/day, use a proxy pool. |
| `reddit` | ~100 queries/min per OAuth client once approved, averaged over 10 minutes. | Approval under the Responsible Builder Policy is required *before* any access. Watch `reddit.auth.limits` remaining/reset — the header is the truth. Mandatory UA format: `<platform>:<app_id>:<version> (by u/<username>)`. |
| `keyword_planner` | 15,000 ops/day on Basic access. | ≤20 seeds per `generateKeywordIdeas`. Cache results 7 days — volumes are monthly, so a daily refresh buys nothing. UI CSV export is the no-approval fallback. |

Every run writes its spend to `job_runs.quota_used`. If a collector cannot count
its own quota, it reports `None` — never a guess.
