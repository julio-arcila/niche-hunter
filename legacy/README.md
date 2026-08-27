# legacy/ — frozen prototypes

The five scripts this project started from, unchanged. They are the reference
for what the domain logic does; do not edit them (ruff skips them and
`.claude/settings.json` denies edits). Delete one only when its collector is
ported, tested against a recorded fixture, and running in a nightly.

| File | Port target | Status |
|---|---|---|
| `niche_hunter_rss.py` | `nh/collectors/youtube_rss.py` | not ported |
| `niche_hunter_yt.py` | `nh/collectors/youtube_api.py` | not ported |
| `niche_hunter_trends.py` | `nh/collectors/trends.py` | not ported |
| `niche_hunter_reddit.py` | `nh/collectors/reddit.py` | not ported |
| `niche_hunter_kp.py` | `nh/collectors/keyword_planner.py` | not ported |

## How to port one

Split the file along these seams (`.claude/skills/new-collector` has the full
checklist):

```
HTTP client + retries        ->  Collector.fetch()
row shaping / dict building  ->  Collector.normalize()
pure analysis functions      ->  nh/features/*.py, essentially unchanged
SCHEMA + INSERT statements   ->  delete — nh/db/models.py owns the schema
run() / __main__             ->  delete — nh/jobs/nightly.py owns orchestration
```

The pure analysis functions are the valuable part and should move over close to
verbatim: `channel_baseline`, `video_velocity`, `channel_breakthroughs`,
`trend_features`, `anchor_scaled_interest`, `geo_tier1_share`, `supply_signals`,
`question_clusters`, `niche_features`, `cpc_geo_spread`.

## What must change during a port

These are prototype-grade shortcuts that the base class now handles, or that
violate `.claude/rules/data.md`:

1. **`KEY = os.environ["YT_API_KEY"]` at module scope** — raises on import,
   making the module unimportable and untestable. Read through `nh.config`.
2. **`INSERT OR REPLACE`** — deletes and re-inserts, nulling any column the new
   payload omits. Use `nh.db.upsert.upsert`.
3. **Non-idempotent snapshot inserts** — plain `INSERT INTO snapshots` /
   `discoveries` duplicates rows on a re-run. Use `insert_ignore`, keyed on
   `(entity, observed_date, source)`.
4. **`int(st.get("viewCount", 0))`** — a hidden or missing count becomes a real
   0, indistinguishable from a genuine flop and poisonous to every median and
   z-score downstream. Use `nh.collectors.parse.as_int`.
5. **Module-level `Q = Quota()`** — cannot be reset per run, shared, or written
   to `job_runs`. Use `self.quota` on the collector instance.
6. **Per-script `SCHEMA` strings and `sqlite3.connect`** — the schema lives in
   `nh/db/models.py` and moves through Alembic.
7. **No niche/cluster identity** — every script keys on raw keyword strings and
   nothing joins. Collected items need a `seed_id` now and a `cluster_id` at
   Phase 2.
8. **No tests, no fixtures** — record one real response per endpoint into
   `tests/fixtures/<source>/`.

## One detail worth not losing

`niche_hunter_yt.py` issues discovery twice per query: `order="date"` for an
unbiased pool including flops, and `order="viewCount"` for the winners. That is
the denominator and the numerator of the breakthrough rate. The `discoveries`
table keeps `order_by` for exactly this reason — a port that collapses the two
orders silently destroys the openness metric.
