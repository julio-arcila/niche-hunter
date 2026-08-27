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
