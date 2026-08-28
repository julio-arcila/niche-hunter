# Data rules — non-negotiable

The snapshot history is the compounding asset. Every other artifact in this repo
can be recomputed; a night of missing or corrupted `*_snapshots` cannot, because
no source serves history. These rules exist to protect that.

1. **Provenance on every write.** Every row carries `source`, `run_id` and `at`
   (UTC, timezone-aware). `Collector._stamp()` injects all three, so a collector
   physically cannot omit them — do not write rows outside a Collector without
   supplying them yourself.
2. **Raw before normalized.** The payload lands in `raw_records` exactly as the
   source returned it, before any interpretation. Re-normalizing a week of
   history must be a query, never a re-fetch.
3. **Idempotent upserts.** Entity writes use `nh.db.upsert.upsert`
   (`ON CONFLICT DO UPDATE` on the real key, touching only supplied columns).
   Never `INSERT OR REPLACE` — it deletes the row and re-inserts, nulling every
   column the new payload happened to omit.
4. **Snapshots are append-only, and never pruned.** Retention exists for bulk
   `raw_records` payloads only (`nh prune`, ADR-0010) — a replay convenience
   whose value decays. Snapshots are the asset: they cannot be re-fetched, so
   no retention path may ever reach them.
5. **Snapshot writes are append-only.** Written with `insert_ignore`
   (`ON CONFLICT DO NOTHING`) keyed on `(entity, observed_date, source)`. Never
   UPDATE or DELETE one. `nh.db.session` raises `AppendOnlyViolation` at flush
   time if you try. Re-running a day is a no-op; the first reading of the day is
   the one that survives.
6. **Confidence on every feature.** Each `features_daily` row stores `inputs_n`
   and `confidence`. A metric computed from 3 rows must not read like one from
   300.
7. **Absent is NULL, never 0.** Use `nh.collectors.parse.as_int` /
   `as_float` / `as_bool` — they return `None` for missing input. A hidden
   subscriber count is unknown, not zero; writing 0 poisons every median,
   z-score and views-per-sub ratio downstream and is undetectable afterwards.
8. **No live network in tests.** `tests/conftest.py` blocks sockets in every
   test. Record a fixture into `tests/fixtures/<source>/` and replay it with
   `responses`.
9. **Never count events over a fixed window using RSS-sourced rows.** A feed
   returns at most 15 entries, so a count over any window the data cannot fill
   censors at the cap: measured, 708 of 892 channels hold every video they have
   inside 90 days, and a 90-day upload count lands on 1.17/wk for *every* niche
   (1.1x spread) against 2.2x for the same quantity computed as a rate over the
   observed span. Rate-from-observed-span is the pattern **for any new count over
   a window the feed cannot fill.** Note what ships today: `uploads_per_week` is
   still a fixed-window count, with the censoring documented in its own failure
   mode rather than fixed -- an earlier version of this rule and of
   `median_top_video_age`'s docstring both said the metric "was redefined as a
   rate over an observed span", which was never true of the shipped code. More
   generally: a metric that normalises away the dimension you are comparing on
   comes out flat, and flat reads as a finding rather than as a bug.
10. **No destructive SQL.** `DROP` / `TRUNCATE` / unscoped `DELETE FROM` are
   blocked by `scripts/hooks/block_dangerous_sql.sh`. Schema changes go through
   an Alembic migration with a working `downgrade()`.
