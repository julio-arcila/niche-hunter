# Runbook

Operating the nightly pipeline. Slice 1 scope.

## Day 1

```bash
cp .env.example .env          # then fill NH_YT_API_KEY, NH_HEALTHCHECK_URL, NH_NTFY_TOPIC
uv run alembic upgrade head
uv run nh seed                # 5 niches, prints the nightly quota cost
uv run python scripts/record_fixtures.py   # ~102 units, once
uv run nh nightly             # watch the quota number
uv run nh status              # what got collected
```

Record the observed `quota_used` here the first time — the plan's ~3,000 is
arithmetic, and the real number is what the budget conversation should use:

    day 1 quota_used: 3,041 of 9,500  (measured 2026-08-27)

Predicted 3,040, measured 3,041 — 3,000 of search.list plus 41 of enrichment.
The arithmetic holds, so `NH_YT_SEARCH_PAGES=2` (~6,082, 64%) is affordable
once you want deeper discovery. A run yields ~870-950 channels and ~13k videos.

If it overruns, cut `NH_YT_SEARCH_PAGES` first, then keywords per seed. Never cut
a seed: dropping one means that niche's history never starts, and history is the
one thing that cannot be recovered later.

## Cron

Append to `crontab -e`, matching the `PATH=` block style already in that file.
Log paths are absolute so a failed `cd` cannot spray output somewhere unwatched.

```cron
# ── Niche Hunter ──
NH=/Users/mac/Projects/youtube/niche-hunter
0  9 * * *  $NH/scripts/run_nightly.sh >> $NH/logs/nightly.log 2>&1
30 9 * * *  $NH/scripts/backup_db.sh   >> $NH/logs/backup.log  2>&1
```

09:00 local is deliberate. This Mac has `sleep 1`, `powernap 0`, `womp 0` and no
`pmset repeat` wake, so a 03:00 job silently never fires. 09:00 local = 07:00
Pacific, inside a fresh YouTube quota day. Snapshots key on `observed_date`, so
the hour is irrelevant — only that it happens once per 24h.

**While you are in there, delete the four `auto-helpdesk` entries.** That project
no longer exists; those jobs have been failing silently into a directory that is
also gone. They are the reason the dead-man switch below is not optional.

## Alerting: two layers

| Layer | Catches | How |
|---|---|---|
| healthchecks.io | the run never happened — Mac off, stale cron line, dead host | ping on success; the service alerts when a ping does not arrive |
| ntfy.sh | the run happened and something in it failed | `alert()` in `scripts/_common.sh` |

Create one check: period 1 day, grace 6 hours, notification channel pointed at
the same ntfy topic. Put the ping URL in `.env` as `NH_HEALTHCHECK_URL`.

`run_nightly.sh` pings success only when **both** `nh nightly` and
`nh status --check` pass. That distinction matters: `nh nightly` exits 0 when a
ported source is skipped for missing credentials, so gating on it alone would
report green while collecting nothing.

## Drill: kill the cron (do this in week 1)

An untested dead-man switch is not a dead-man switch.

1. Comment out the nightly crontab line before 09:00.
2. Confirm the healthchecks "down" alert arrives by ~15:00 (period 1d + grace 6h).
3. Uncomment it; confirm the next run turns the check green again.
4. Record the date performed: **alert routing verified 2026-08-27** (`/fail` ping → healthchecks → ntfy, all HTTP 200). The *timing* half —
   confirming a missed ping is detected after the grace window — has not
   been run; it needs a real skipped day. Do it in week 1.

## Drill: restore from backup (do this in week 1)

```bash
./scripts/restore_check.sh
```

Restores the newest backup to a scratch path, runs `PRAGMA integrity_check`, then
`nh doctor` and `nh status` against the restored copy. Expect `14/14 tables
present`. Record the date performed: **passed 2026-08-27** — restored a real
25 MB iCloud backup, 14/14 tables, 14,270 snapshots intact.

Note on verification: `integrity_check` alone is **not** sufficient — it returns
`ok` for a valid but empty database. `backup_db.sh` therefore also compares table
and snapshot counts against the source, because an unset `NH_DATABASE_URL` once
produced a "successful" 113-byte backup of nothing.

## Reading the state

```bash
uv run nh prune --dry-run     # storage per kind/codec; what retention would drop
uv run nh backfill descriptions --dry-run   # re-derive stored columns from raw
uv run nh status              # last 7 days: runs, quota, snapshots per day
uv run nh status --check      # the gate; exit 1 if the last night collected nothing
uv run nh sources             # ported / configured / quota per source
uv run nh doctor              # database reachable, schema present
```

Then run the `data-qa` agent against the newest `run_id` on nights 1, 2 and 7 at
minimum — it checks NULL rates, snapshot monotonicity, duplicates and orphans.

## Storage

Raw feed payloads are gzipped and pruned after `NH_RAW_RETENTION_DAYS` (14),
because YouTube's feeds carry no cache validators and every poll stores the
whole document (ADR-0010). `scripts/run_nightly.sh` prunes after each run,
non-fatally. Expect a steady state near **~95 MB of feed payloads** rather than
unbounded growth; `nh prune --dry-run` shows the current split.

SQLite does not return freed pages to the filesystem on its own. After a large
prune: `/usr/bin/sqlite3 data/niche_hunter.db "VACUUM;"`. Snapshots are never
pruned — they are the asset.

### If the prune refuses

```
refused: pruning would destroy the last copy of N video description(s)
```

The delete set holds text that is not yet in a typed column (ADR-0017). Fix it,
do not force it:

```bash
uv run nh backfill descriptions      # extracts from raw_records; no network, no quota
uv run nh prune                      # now proceeds
```

`--force` exists for the case where you have decided the text is not worth
keeping. It prunes anyway and reports how many descriptions it cost. Feeds serve
15 entries and no history, so for any video that has fallen out of its channel's
window that text does not come back.

Because `scripts/run_nightly.sh` prunes non-fatally, a refusal shows up in
`logs/prune.log` rather than failing the night — check it if `videos.description`
coverage stops rising.

## Exit criteria for Slice 1

- [ ] 7 consecutive days, no manual intervention
- [ ] `video_snapshots` grew every one of those days
- [ ] `quota_used` under 9,500 every day
- [~] kill-the-cron: alert routing verified; missed-ping detection still to do
- [x] restore drill performed against a real backup (2026-08-27)

## Gate E: running the backtest (Slice 6)

Everything below is **operator time, not design** — the code is built, tested and
committed. Five steps, two of which are long waits that can overlap.

**The one rule.** Every command in this section runs against `data/backtest.db`.
Never the live corpus: the load writes ~30 fake clusters and millions of 2019 rows,
and `nh nightly` would then RSS-poll channels that stopped uploading in 2019 and rank
live niches against phantom ones. `nh/backtest/load.py::refuse_live` enforces it by
requiring "backtest" in the URL, so a slip raises rather than corrupts. Export it once
per shell:

```bash
export NH_DATABASE_URL="sqlite:///data/backtest.db"
```

If a command errors with `RefusingLiveDatabase`, that export is missing. That is the
guard working, not a bug.

### Step 1 — the database exists and is seeded ✅ done 2026-08-28

```bash
uv run alembic upgrade head          # 18 tables
uv run nh backtest seed              # 36 niches, 108 topic articles
uv run nh doctor                     # confirms schema
```

### Step 2 — Wikipedia demand backfill 🔄 running

```bash
NH_WIKI_BACKFILL_DAYS=4400 uv run nh nightly --only wikipedia
```

4,400 days reaches past 2014-08, so `wiki_yoy` is computable at the first 2015-07
decision date. Quota-free; roughly 1.6 hours for 108 articles. **Independent of the
download** — that is why it starts first.

Check progress, and check it again when it finishes:

```bash
uv run python -c "
import sqlalchemy as sa
from nh.db.session import get_engine
with get_engine().connect() as c:
    print(c.execute(sa.text('select count(*) from demand_snapshots')).scalar())"
```

**Before trusting the result, check coverage per niche.** The log emits
`no data for <article> in <range>` when an article did not exist yet or is a redirect
— `Cryptocurrency_exchange` has no pageviews before 2017. A niche whose three topic
articles are all empty early has no demand at early decision dates, and its `gap` will
be NULL there rather than wrong. Count the niches that survive:

```bash
uv run python -c "
import sqlalchemy as sa
from nh.db.session import get_engine
q='''select s.slug, count(distinct d.term), min(d.observed_date), sum(d.value)
     from niche_seeds s join seed_terms t on t.seed_id=s.id
     left join demand_snapshots d on d.term=t.term
     group by s.slug order by 4 nulls first'''
with get_engine().connect() as c:
    for r in c.execute(sa.text(q)): print(r)"
```

Niches with no demand at all cannot enter the correlation. **Record how many, and
report the number in `reports/backtest_<date>.md` — do not quietly drop them.**

**Measured 2026-08-28: `min(observed_date)` is 2015-07-01 for every article.** That is
the Wikimedia pageviews API floor, not a gap in the backfill — the API serves nothing
earlier, which is why the replay window starts there. Two consequences:

- `NH_WIKI_BACKFILL_DAYS=4400` asks for more than exists. Harmless, and cheaper than
  discovering mid-run that it asked for too little.
- **`demand.wiki_yoy` needs a year of prior data, so it is NULL until 2016-07-01**, and
  `scorecards.stage` is therefore UNKNOWN for the first year of decision dates. This
  does not affect the primary result — `gap` needs `wiki_weekly_views` and supply, not
  momentum — but a reader looking at early `stage` values needs to know why they are
  empty rather than assuming the classifier failed.

### Step 3 — finish the download, then scan ⏳ blocked on the download

`data/youniverse/yt_metadata_en.jsonl.gz` is 13.64 GB. Nothing else waits on it.

```bash
ls -la data/youniverse/yt_metadata_en.jsonl.gz   # 13.64 GB when complete
uv run nh backtest scan --limit 50000            # smoke test first, ~10 seconds
uv run nh backtest scan                          # the real pass, ~5.2 hours
```

Run the `--limit` pass first. It exercises the same code on the same file and tells
you within seconds whether the prefilter, the lexicons and the writer all work — a
failure four hours into the full pass costs the afternoon.

The scan streams the gzip once and keeps almost none of it: it writes
`data/backtest/hits.jsonl.gz` (video, niche, date, relevance) and
`data/backtest/selection.json` (which channels belong to which niche).

**Measured on the real file, 2026-08-28: 3,894 videos/second, so ~5.2 hours for
72.9M videos.** Decompression and JSON parsing are only ~3% of that — the cost is
scoring, and it was 7.4 hours before `_singular` and `normalise` were memoized. Of
the videos read, 9.9% clear the prefilter and get scored.

**Read `selection.json` before Step 4.** It is sorted and indented so it diffs, and it
is the last point at which the assignment is reviewable before millions of rows are
materialised on it. The scan prints the summary too:

- **niches kept** — the number that cleared `MIN_MEMBER_CHANNELS = 15`. This is the N
  the whole gate rests on. Below 20 the run is underpowered and `report.verdict` will
  say INCONCLUSIVE rather than FAIL.
- **dropped** — niches and their member counts. Report them; **never revive, edit or
  substitute one.** That is selection on the outcome and it voids the
  pre-registration.
- **contested** — channels that qualified for more than one niche.

### Step 4 — load, then replay

```bash
uv run nh backtest load
uv run nh backtest replay --start 2015-07-01 --end 2019-03-01
```

The window ends 2019-03 because that is the last decision date with a full 180-day
outcome inside the data. Weekly dates, ~195 of them.

The load prints channels, channel-weeks, videos and memberships. A line saying
`no metadata for N selected channel(s)` means YouNiverse's channel file does not
describe some channel its video file contains — counted, not silently dropped.

### Step 5 — score and read the verdict

```bash
uv run nh backtest score --start 2015-07-01 --end 2019-03-01
```

Writes `reports/backtest_<date>.md` and prints the verdict. Four possible outcomes,
and the difference between the last two matters more than anything else in this file:

| verdict | meaning | what to do |
|---|---|---|
| **PASS** | positive rho, p < 0.05, survives the size control | Slice 7. `opportunity`'s weights are now derivable. |
| **FAIL** | null, negative, or explained by niche size | Do not build the dashboard. Either return to Slice 5's feature work with the failure analysis, or narrow the claim to "surfaces evidence for a human to judge". |
| **INCONCLUSIVE — UNDERPOWERED** | fewer than 20 niches survived | **Not a null.** The test could not have detected an effect worth having. Do not retire the thesis on it. |
| **INCONCLUSIVE** | the primary could not be computed | Something upstream is empty. Check demand coverage (Step 2) and `selection.json` (Step 3). |

Then **write the failure-analysis paragraph by hand** — `render()` leaves it as
`_Not yet written._` and it is the part of the report that has to be thought about
rather than computed.

### What is fixed in advance and must not move

`reports/backtest_preregistration_2026-08-27.md` fixes the primary result, the verdict
rule, the permutation scheme, the tune/validate split and the power table. It has an
amendment log; a change made after seeing a result voids it.

Not tunable, under any result: the relevance thresholds (METRICS.md forbids it — the
three-threshold run is robustness, not a search), the lexicon contents, and the niche
set. The only tuning surface is `lifecycle.Thresholds`, which is frozen and versioned.

If the primary fails and a secondary variant succeeds, that is a hypothesis for a
later slice with a fresh validation window. It is **not** this gate's verdict, and
`report.render` will label it secondary no matter how good it looks.

### Deferred, and due right after this

- The human relevance spot-check (50 rows, `reports/spotcheck_50.jsonl`) — deferred to
  before Slice 7, with the threshold-sensitivity run as its stand-in.
- The `nh deferrals` cron ping.
- The **event** demand stratum. `nh backtest seed` writes the topic stratum only; the
  event stratum needs `scripts/select_demand_articles.py` to resolve each niche's pool
  against Wikidata first. Topic is the pre-registered primary, so the gate can run
  without it — but the two strata invert the demand ranking end to end (ADR-0022), and
  the stratum comparison is a pre-registered secondary that stays uncomputed until
  this lands.
