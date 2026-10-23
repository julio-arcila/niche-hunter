# Features phase profile — 2026-10-07

Stage 1 of the plan. Read-only against the live corpus
(`sqlite:///file:data/niche_hunter.db?mode=ro&uri=true`), `scripts/profile_features.py`,
`--day 2026-10-04 --reps 1`, run at ~22:10 local so it could not contaminate a nightly.
Nothing was written. `features.run.compute` was never called — the metric callables were
invoked directly and their results discarded, because `compute` upserts into
`features_daily` (`nh/features/run.py:143`).

**Total: 2,550.2 s (42.5 min)** for 10 active clusters × 23 metrics. Process:
`real 2551.72 / user 1028.33 / sys 984.64`, max RSS 72 MB, 145,165 page reclaims.

## Per metric (top, by wall)

| metric | wall s | cpu% |
|---|---|---|
| `median_views` | 512.4 | 62 |
| `winner_age_years` | 476.5 | 70 |
| `breakthrough_rate_cohort` | 467.1 | 71 |
| `views_per_sub` | 461.0 | 66 |
| `top10_concentration` | 452.2 | 76 |
| `trimmed_mean_views` | 429.7 | 70 |
| `uploads_per_week` | 218.0 | 45 |
| `midroll_eligible_share` | 86.7 | 62 |
| `format_mix` | 38.2 | 85 |
| `on_niche_share` | 4.6 | 94 |
| everything else | < 1 each | — |

The six metrics predicted to reach the whole-table aggregate **are** the top six, at
~2,800 s. The seventh is less than half the smallest of them.

## Per input function

| function | calls | wall s | cpu% | distinct (cluster, day) | calls/distinct |
|---|---|---|---|---|---|
| `inputs.eligible_videos` | 40 | 1571.2 | 75 | 10 | **4.0** |
| `supply._top_videos` | 10 | 337.4 | 95 | 10 | 1.0 |
| `inputs.date_discovered_channels` | 20 | 13.0 | 55 | 10 | 2.0 |
| `inputs.latest_subs` | 20 | 2.5 | 55 | 10 | 2.0 |

`calls/distinct` is the ceiling on what memoisation can buy, stated before any code
changed. `eligible_videos` at 4.0 is the firmest number in this profile.

## Per statement

| statement | wall s | share | executions |
|---|---|---|---|
| `eligible_videos`' (`SELECT anon_1.channel_id, anon_1.video_id, …`) | **1454.6** | **57%** | 40 |
| `winner_age_years`' (`SELECT videos.channel_id, channels.created_…`) | 414.3 | 16% | 10 |
| `_top_videos`' (`SELECT videos.video_id, anon_1.views, …`) | 337.3 | 13% | 10 |
| `uploads_per_week`' count | 64.3 | 3% | 10 |
| remaining 8 | < 50 each | — | — |

**Three whole-table `max(views)` aggregates are 86.5% of the entire phase.**

## Working set (`dbstat`, cache-independent)

| btree on `video_snapshots` | MB | pages |
|---|---|---|
| table | **611** | 156,560 |
| `ix_video_snapshots_run_id` | 218 | 55,816 |
| `sqlite_autoindex_video_snapshots_1` (video_id, observed_date, source) | 209 | 53,584 |
| `ix_video_snapshots_channel_id` | 166 | 42,621 |
| `ix_video_snapshots_series` (video_id, observed_date) | 149 | 38,245 |
| `ix_video_snapshots_source` | 98 | 25,264 |
| `ix_video_snapshots_video_id` | 96 | 24,586 |

The current plan (`SCAN video_snapshots USING INDEX ix_video_snapshots_video_id`, unchanged
by the 2026-10-06 `ANALYZE`) walks the 96 MB index in `video_id` order, then probes the
611 MB table per row for `views`, scattered because each video's snapshots arrived on
different nights. **707 MB, 4.5M random probes.** A covering index on
`(video_id, observed_date, views)` would be ~175 MB, scanned in order.

## Verdict against the gate — it does not fire as written

The gate said: do the covering index if the aggregate statement is **≥60%** of warm wall at
**cpu% < 50**. Measured: **57%** (just under) at **75% CPU on `eligible_videos`** (well
over). Process-level, ~40% user compute and ~39% kernel — the `pread` and page-fault path —
with ~21% waiting.

So this is **not** the clean I/O-bound picture that the bare aggregate's 31-38% CPU
suggested. The difference is that the real statement also carries the join to
`videos`/`channels`/`cluster_members` and a `row_number()` window, which a covering index
cannot remove. The index is still expected to help the kernel half; it is not the 5-8x the
plan hoped.

**What the evidence recommends instead: invert the order, memo first.**

- `eligible_videos` is **40 executions for 10 distinct arguments**. That is duplicated work,
  not an access-path inference, and removing it is index-independent: 1,454 s → ~364 s,
  about **43% of the whole phase**.
- `winner_age_years` and `_top_videos` are **1.0** — a memo buys them nothing. Only an index
  can help those two, and together they are 29%.

So: Stage 2b first, re-profile, then decide Stage 2a on the remainder. Both are probably
justified; the order the plan assumed was predicated on the CPU share, and that half did not
hold.

## Harness defect, disclosed

The per-statement `cpu%` column reads 0% for every row: `statement_timer` accumulates wall
only and never populates `cpu`. The column is meaningless, not a finding. The CPU evidence
in this report comes from the per-metric and per-input tables (which do measure
`process_time`) and from the process totals. Fix before the re-profile, or drop the column.

## Not established

Why 2026-10-01 (156.6 min) and 2026-10-06 (177.0 min) were 6x the median remains
unexplained. ρ(clustering, features) = 0.836 across 2026-09-22..10-06 while clustering never
reads `video_snapshots`, which points at machine-wide I/O contention rather than anything in
this profile. **Nothing in Stage 2 should be claimed to fix those nights.**
