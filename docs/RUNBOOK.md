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

## Scheduling — two mechanisms, on purpose

**The nightly runs from launchd. The backup and the disk check run from cron.**
Each job has exactly one scheduler; two would mean two runs in one Pacific quota
day, which is the collision `.skip-once` exists to prevent.

| job | scheduler | when | why there |
|---|---|---|---|
| `run_nightly.sh` | launchd | 09:10 | cron cannot survive a sleeping Mac |
| `backup_db.sh` | cron | 09:40 | launchd agent has no Full Disk Access to iCloud |
| `restore_check.sh --offsite` | launchd | 09:55, 1st of the month | downloads from B2 into a temp dir — **never touches iCloud**, so the FDA constraint on the row above does not apply here |
| disk check | cron | every 6h | a monitor, not a data job; skips cost nothing |

**Why the drill is launchd when the backup is cron**, since the two rows look
contradictory. Full Disk Access is granted per *responsible process*: cron holds it on
this machine and a launchd agent does not, which is why the backup — writing to
TCC-protected iCloud Drive — stays on cron. The drill's `--offsite` arm downloads from
B2 into a `mktemp` scratch and never opens `~/Library/Mobile Documents`, so that
constraint is simply absent. And for a *monthly* job cron is the worse choice:
`pmset -g custom` shows `sleep 1` on battery, so the 09:05 wake, the nightly and the
backup finish around 09:45, the Mac re-sleeps, and a cron fire after that is silently
skipped and never retried — the mechanism that lost 2026-08-30. launchd replays a
`StartCalendarInterval` it slept through.

```bash
cp scripts/launchd/com.niche-hunter.restore-drill.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.niche-hunter.restore-drill.plist
launchctl kickstart -p gui/$UID/com.niche-hunter.restore-drill    # this IS the verification
```

That kickstart appends a dated pass to `logs/restore.log`, which `nh criteria` counts —
so installing it correctly and evidencing criterion 3 are the same act.

**The drill is watched, which is the point.** `c3_recoverable` requires two dated passes
**and** a newest one inside `DRILL_STALE_DAYS` (45). Without that clause two drills in
2026 would have kept C3 green in 2027, and a scheduled drill would have had a success and
a failure equally invisible to the grader — a job whose death nobody notices, which is the
pattern the four dead auto-helpdesk jobs on this machine already demonstrated. A failing
drill also pushes through `alert()`.

### The scheduled wake — the thing that replaced a cloud deploy

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 09:05:00     # silent on success
pmset -g sched                                       # confirm: "wakepoweron at 9:05AM every day"
```

Installed **2026-09-01**, five minutes before the 09:10 nightly.

launchd already replays a fire the Mac slept *through* on wake, which is why the nightly
moved off cron. The case it does not cover is a Mac asleep **all day** — nobody opens the
lid, nothing wakes it, and the day is simply gone. That is exactly how 2026-08-30 was lost,
and it is the only realised failure mode this system has had.

**This is what Slice 8 shipped instead of deploying to a cloud** (ADR-0055). One command
against a migration whose principal risk was to the one artifact that cannot be re-collected.

Two caveats, because they decide whether it actually fires:

- **A closed laptop wakes only on AC power.** On battery with the lid shut, macOS will not
  honour the scheduled wake. If the machine lives closed, it needs to live plugged in.
- `wakeorpoweron` also powers the machine on if it is fully shut down, which `wake` alone
  does not. That is the intent — "off overnight" is the same lost day as "asleep overnight".

What is still uncovered, and is now written down rather than assumed: the Mac being *away*
— travelling, or off for days. That costs one day-column of `video_snapshots` and
`channel_snapshots` per missed day. Wikipedia backfills itself on the next run
(`_resume_from`, history to 2015), Trends is shape-only, and RSS survives short gaps inside
its 15-entry window. So an absence costs the supply series and nothing else.

### The nightly, and why launchd

```
~/Library/LaunchAgents/com.niche-hunter.nightly.plist
source of truth: scripts/launchd/ — edit there and re-copy, never edit in place
```

```sh
cp scripts/launchd/com.niche-hunter.nightly.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.niche-hunter.nightly.plist
launchctl print gui/$UID/com.niche-hunter.nightly | grep -E '"Hour"|"Minute"'
launchctl bootout gui/$UID/com.niche-hunter.nightly     # to remove
```

09:10 local = 07:10 Pacific, inside a fresh YouTube quota day, offset from the
09:00 Opencode job so they do not contend. Snapshots key on `observed_date`, so
the hour is irrelevant — only that it happens once per 24h.

**This section used to say 09:00 was safe because "this Mac has `sleep 1`,
`powernap 0`, `womp 0` and no `pmset repeat` wake, so a 03:00 job silently never
fires."** The reasoning was right and the conclusion was wrong: a 09:00 job does
not fire either if the Mac happens to be asleep at 09:00. **Measured 2026-08-30**
— the machine entered Maintenance Sleep at 09:05:10 for 722s and woke at
09:17:12, cron skipped the fire and never retried, and that day's snapshots are
gone for good because no source serves history. The backup was lost the same
morning; two silent jobs on one day is what identified the scheduler rather than
the pipeline.

launchd fixes exactly this: a missed `StartCalendarInterval` job runs **once when
the system next wakes**. Note the one caveat — a wake after 19:00 local puts the
catch-up run past the UTC `observed_date` boundary, so it collects for *tomorrow*.
Still better than nothing, but do not read a late run as having filled the gap.

### Two backup destinations, and why the second one exists

The iCloud copy and the database it protects are **one Apple ID apart**. A locked or
compromised account takes both, and the snapshot history is the one artifact that cannot be
re-collected. So there is a second, weekly copy to Backblaze B2 — different provider,
different credential, different failure domain.

```bash
# configure once, in .env (see .env.example for the full block)
NH_B2_BUCKET="niche-hunter"
NH_B2_ENDPOINT="s3.us-east-005.backblazeb2.com"
NH_B2_KEY_ID="..."      # an application key scoped to that bucket, not the master key
NH_B2_APP_KEY="..."

NH_B2_FORCE=1 scripts/backup_db.sh     # test it now instead of waiting for Sunday
```

**Set the bucket's File Lifecycle to "Keep only the last version."** The B2 default is "Keep
all versions", which retains every deleted object as a hidden version that still counts
against the 10 GB free tier — the prune would appear to work while storage climbed.

Deliberate choices, so they are not re-litigated:

- **Weekly, four deep.** This is disaster recovery, not point-in-time recovery; the daily
  series stays in iCloud. Four Sundays is ~1.2 GB against a 10 GB free tier.
- **`aws`, not rclone or the b2 CLI.** It is already on the machine and B2 is
  S3-compatible. Credentials are scoped to each command rather than exported, so they
  cannot collide with a real AWS profile.
- **Non-fatal.** An offsite failure logs and pushes but does not redden the night — the
  primary backup is already written and verified by then. Same judgement as the retention
  sweep and `nh prune`.
- **Silent when unconfigured**, like `alert()` and `ping_hc()`.

The local window dropped **30 days → 14** at the same time. Thirty was set when a backup was
26 MB; at 2026-09-01 it is 266 MB growing ~58 MB/day, which trends to ~32 GB of iCloud.
Fourteen matches `nh prune`'s raw-payload retention, so the two windows move together — and
most of that growth is `raw_records` backfill that flattens once prune starts rotating feed
payloads out at day 15.

### The backup, and why it is NOT on launchd

The plist is written and correct (`scripts/launchd/com.niche-hunter.backup.plist`)
and installing it today would **break the backup**. Measured 2026-08-30: the agent
could not open its own output file — `Operation not permitted`, exit 1. The
destination is iCloud Drive, which is TCC-protected, and macOS grants Full Disk
Access per *responsible process*: cron holds that grant here, a launchd agent is a
different process holding nothing. So the agent fails harder than the missed fire
it would have fixed.

To finish the move: grant the agent Full Disk Access in System Settings > Privacy
& Security, bootstrap it, `launchctl kickstart -p`, and confirm `logs/backup.log`
says `backup ok` **before** removing the cron line. The plist header carries the
same instructions.

Known, unfixed, and separate: under cron the retention `find` cannot traverse
iCloud either, so the rolling 30-day sweep never runs and backups accumulate
(26 → 90 → 150 → 214MB across four days). It is non-fatal since 2026-08-30 and
says so in the log; granting Full Disk Access fixes both this and the paragraph
above.

**The four `auto-helpdesk` entries are gone** — verified absent from `crontab -l`
on 2026-08-30. That project no longer exists and those jobs had been failing
silently into a directory that was also gone. They remain the reason the dead-man
switch below is not optional.

### Skipping one night

```sh
echo "why" > .skip-once     # consumed by the next scheduled fire, then gone
rm .skip-once               # changed your mind before it fired
```

`run_nightly.sh` consumes the sentinel and exits 0 *before* collecting, pinging
healthchecks as a success — a deliberate skip is not a failure and must not page
anyone. It cannot become a habit, because skipping is what deletes it.

**Do not disable the scheduled job instead** — neither by commenting out a
crontab line nor by `launchctl bootout`. Nothing in the system ever
reminds anyone to put it back, and a pipeline that quietly stopped looks exactly
like a pipeline that is running. ADR-0039 is this repo's standing example: a
retirement written in code that never reached the database, and spent 3,000
units a night for a day while everyone believed otherwise.

**When you actually need this**: to skip a fire deliberately, with the reason
recorded in the file, rather than by unloading the agent and forgetting to put it
back. **Not** to avoid a quota collision — this paragraph said
"`QuotaLedger`'s budget is per-**run**, not per-day" until 2026-09-01, and that was
false since Slice 1: `YouTubeApiCollector.__init__` seeds its ledger with
`budget - _spent_today()`, summed across every run_id since midnight Pacific, and
`test_todays_earlier_spend_is_deducted_from_this_runs_budget` has covered it from
the start. A manual `nh nightly` and the 09:10 fire do not each believe they have
9,500; the second is told what is left.

What is real: the ledger stops per *query*, so a day can exceed the 9,500 self-budget
by up to one call — measured 9,624 across seven development runs on 2026-08-27, which
is 124 over, well inside Google's actual 10,000. And spend reaches `job_runs` only when
a run finishes, so two runs genuinely overlapping in time would each seed from a stale
sum. `nh status` now prints the day's headroom, and `nh status --check` warns above 85%.

The quota day resets at midnight Pacific, which is 02:00 local.

## Alerting: two layers

| Layer | Catches | How |
|---|---|---|
| healthchecks.io | the run never happened — Mac off, unloaded agent, dead host | ping on success; the service alerts when a ping does not arrive |
| ntfy.sh | the run happened and something in it failed | `alert()` in `scripts/_common.sh` |

Create one check: period 1 day, grace 6 hours, notification channel pointed at
the same ntfy topic. Put the ping URL in `.env` as `NH_HEALTHCHECK_URL`.

`run_nightly.sh` pings success only when **both** `nh nightly` and
`nh status --check` pass. That distinction matters: `nh nightly` exits 0 when a
ported source is skipped for missing credentials, so gating on it alone would
report green while collecting nothing.

## Drill: kill the scheduler (do this in week 1)

An untested dead-man switch is not a dead-man switch.

1. `launchctl bootout gui/$UID/com.niche-hunter.nightly` before 09:10. (This
   drill is the one sanctioned exception to the rule just above — put it back in
   step 3.)
2. Confirm the healthchecks "down" alert arrives by ~15:00 (period 1d + grace 6h).
3. Bootstrap it again; confirm the next run turns the check green again, and
   that `launchctl list | grep niche-hunter` shows it loaded.
4. Record the date performed: **alert routing verified 2026-08-27** (`/fail` ping → healthchecks → ntfy, all HTTP 200). The *timing* half —
   confirming a missed ping is detected after the grace window — has not
   been run; it needs a real skipped day. Do it in week 1.

## Drill: restore from backup (do this in week 1)

```bash
scripts/restore_check.sh              # newest local (iCloud) copy
scripts/restore_check.sh --offsite    # newest B2 object, downloaded first
```

**Performed 2026-09-01 from B2**: downloaded `weekly/niche_hunter_2026-09-01.db.gz`,
decompressed, `integrity_check` ok, 20 tables and 208,444 snapshots — matching source. That
is the third dated drill and the first from the offsite copy.

**The `--offsite` arm is the one that proves something new.** A local restore tests gzip and
SQLite. It does not test that the remote object exists, is complete, is readable with the key
we actually hold, or that the endpoint and bucket in `.env` are where data is really going —
and those are precisely the failure modes a second destination exists to cover. A bucket can
accept 266 MB every Sunday for a year and still be unopenable on the day it matters.

Both arms now assert **contents**, not just openability: ≥20 tables and a non-zero
`video_snapshots` count. `PRAGMA integrity_check` returns `ok` for a perfectly valid *empty*
database — the same trap `backup_db.sh` documents — so a drill that proves only "it opens"
proves the one thing that was never in doubt.



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

## The evidence surface

```bash
uv sync --extra web          # once; kept optional so the nightly never needs it
uv run nh web                # http://127.0.0.1:8501
uv run nh niche show <slug>  # the same numbers, in a terminal
uv run nh niche trace <slug> <metric>   # the rows behind one number
```

Loopback-only and telemetry-off by default (`.streamlit/config.toml`). There is no
authentication and the page shows an unvalidated scorer's inputs, so do not bind it
to a LAN.

**What it will not show you, and why that is the point.** A metric the relevance
scorer decided is withheld for a cluster whose axis has no human labels — that is
every active cluster today — and so is the whole `scorecards` row. What appears
instead is the reason and the command that lifts it. Demand, Keyword Planner and
two of the three openness metrics are unaffected: the scorer never touches them.

`--unvalidated` on `nh niche show` reveals them for one invocation. It records
nothing, which is what makes it different from a setting: a stored flag standing
in for a human's verdict is what ADR-0050 forbids.

The input rows behind a gated metric **are** shown, deliberately — the aggregate
claim is withheld, the evidence needed to check it is not. But they carry
per-video `relevance`, so do not browse them before labelling a sample.

## Labelling the two validation samples

Both are drawn, unlabelled, and waiting on a person. **A model must not label
either** — the whole objection is that the existing evidence is machine labels
from one family, and two raters of that family cannot detect a bias they share.

```bash
uv run python scripts/label_exposition.py                  # ADR-0041's precision sample
uv run python scripts/label_exposition.py --sample recall  # ADR-0050's recall sample
uv run python scripts/label_exposition.py --status         # progress, either one
```

One criterion covers both (ADR-0042, unchanged): pass A asks whether the video is
**about** the named domain, pass B whether it **explains, analyses, teaches or
argues**. Each pass runs over the whole sample; `y` / `n` / `?` / `s` skip / `b`
back / `q` quit, resumable, saved after every keystroke. You see domain, title and
description and nothing else — not the score, not the terms that fired.

| | `--sample exposition` | `--sample recall` |
|---|---|---|
| file | `reports/exposition_labelling_2026-08-31.jsonl` | `reports/recall_labelling_2026-08-31.jsonl` |
| stratum | above the 0.55 threshold | decided-noise rows on ballast channels |
| measures | precision | false negative rate |
| bar | Wilson **lower** bound >= 0.70 (**79 of 100**) | Wilson **upper** bound <= 0.10 (**at most 4 of 100**) |
| a "hit" is | a row correctly kept | a row wrongly excluded |
| if unlabelled | nothing happens; it blocks nothing (ADR-0045) | **ballast reverts to v2 on 2026-09-14** |

The two bars point in opposite directions because the samples do: above the
threshold you want most rows right, below it you want almost none wrong. Roughly
60–90 minutes for both; the recall rows are mostly obvious negatives and go
faster. `nh deferrals` carries the dated one and is the thing that will remind you.

**On the result**, for either: compute the interval, write
`reports/<name>_result_<date>.md`, and record it in the ADR that pre-registered
it. For the recall sample also set `nh.features.inputs.BALLAST_VALIDATED` in that
same commit — it is a human's verdict about the bar, deliberately not a file the
code reads, because completing the labels and passing the bar are different
events.

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

### Running it unattended

Steps 3–5 are one chain with two long waits in it, so it is worth driving rather than
babysitting. `scripts/gate_e.sh` (2026-08-28) waits for the download, verifies it,
then runs scan → load → replay → score, and **aborts the chain on any failure**: a
backtest built on a truncated corpus or a half-loaded database still produces a
number, and a number is worse than nothing here because it will be believed.

Three things in it are worth keeping in any re-run:

- **Wait on the byte count, not on the downloader exiting.** curl runs with `-C -`,
  so a dropped connection exits non-zero with a short file that looks finished. The
  expected size and md5 come from the Zenodo record
  (`13636127630` bytes, `md5:0514b2ee52ffaa2c9c27c539038feb60`) — check them there
  rather than hard-coding a guess.
- **Verify the md5 before scanning.** Five minutes of hashing against 5.2 hours of
  scanning a corrupt file.
- **A FAIL verdict is not a script failure.** `nh backtest score` exits 0 and prints
  the verdict; only an uncomputable primary exits non-zero. The driver must not
  conflate "the gate said no" with "the run broke".

Check on it:

```bash
tail -f scratchpad/gate_e.log            # the driver's own progress (log path)
tail -5 scratchpad/gate_e_scan.log       # or _load / _replay / _score
pgrep -f gate_e.sh || echo "driver finished or died"
```

Run it detached (`nohup`) rather than in a foreground shell: it outlives the terminal,
which a seven-hour chain needs.

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


## Known defects

Real, reproduced, and unfixed. Distinct from `nh deferrals`, which lists work *blocked
on a trigger* — everything here is unblocked and simply not done. Ordered by what would
mislead someone soonest.

### A test's verdict depends on live collection state

`tests/test_deferrals.py::test_no_deferral_is_silently_unblocked_today` evaluates
`fires()`, and `fires()` with `kind="query"` runs against **the live database** when no
engine is passed. Reproduced 2026-08-28: the nightly fired mid-suite, added 1,317 RSS
videos whose format is unknown until enrichment, moved `is_short` coverage from 0.7685
to 0.7209, and flipped `supply.format_mix` — a red suite from collection, not from code.
It passed again minutes later.

This is nondeterministic by construction and will recur whenever the suite overlaps a
nightly. It also violates the spirit of the no-network rule: the test reads mutable
outside state that no fixture controls. The fix is to give the test a seeded fixture
database and assert against known counts, keeping a *separate* operator check —
`nh deferrals` already is one — for the live question.

### `relevance_labels` cannot hold an inter-rater study

`relevance_labels.video_id` carries a UNIQUE constraint, so the table stores exactly one
label per video. The project's own documented top risk is single-labeller bias, and the
`labeller` column exists to distinguish raters — but the key makes a second rater
impossible. Hit on 2026-08-28 trying to store a cross-family pass; the insert was
refused and the labels live in `reports/spotcheck_50_fable.jsonl` instead. Fix: an
Alembic migration moving the unique key to `(video_id, labeller)`.

### Snapshots are append-only against the ORM only

A Core-level `session.execute(sa.update(VideoSnapshot)...)` bypasses the `before_flush`
listener and mutates a snapshot silently. Confirmed by probe 2026-08-28; ADR-0010
predicts it for the retention prune's own mechanism. The guarantee is therefore against
*ORM misuse*, not against all writes, and any future Core write path re-opens it. Fix:
an engine-level `before_execute` listener refusing UPDATE/DELETE on `AppendOnly` tables,
with a greppable escape hatch so an override is a visible decision.

### Two backtest metrics could never compute

`replay.BACKTEST_METRICS` lists `winner_age_years` and `top10_concentration`, both of
which need `video_snapshots` — which `load.py` deliberately leaves empty, as its own
docstring states. Both returned NULL for all 5,568 cluster-days of the Gate E run, so
openness never entered the backtest, and roughly a fifth of the replay's compute
produced nothing. Neither feeds `gap`, so the verdict stands. Fix: drop them from the
list, or load a view-count source if openness is ever wanted in a replay.

### `_bootstrap_ci` percentile indices are asymmetric

`nh/backtest/stats.py` uses `int(tail·n) − 1` for the low bound and `int((1−tail)·n)`
for the high one — about one rank of extra width at 10,000 draws. Cosmetic, and not a
verdict input, but the interval is published in `reports/backtest_*.md`.

### The recorded RSS fixture is not wired into the collector tests

`tests/test_youtube_rss.py` runs on a hand-built `feed.xml` while a real capture
(`feed_real.xml`) sits beside it, used only by `test_backfill.py`. The standing rule is
that fixtures are recorded from real responses. Fix: parametrize the collector tests
over both — the real one proves the documented shape is the served shape, the synthetic
one keeps encoding edge cases a single feed may not exhibit. Budget for the real capture
failing an assertion written to the synthetic shape; that failure is the finding.
