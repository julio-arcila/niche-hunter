---
name: new-collector
description: Scaffold a new source collector behind base.Collector, with migration, fixtures, docs and registry entry. Use when adding a data source or porting one of the legacy/ prototypes.
---

# Add a collector

Run `source-researcher` first if this source is new. Skip it when porting a
`legacy/` prototype — the constraints are already in its module docstring.

1. **Document the source.** Add or update the row in `docs/SOURCES.md` and the
   quota/etiquette row in `.claude/rules/sources.md`. Auth, quota, endpoints,
   fields, join keys, caveats. Do this before writing code.

2. **Schema, if the source needs new tables.** Add models to `nh/db/models.py`.
   A time series inherits `AppendOnly` and declares
   `UniqueConstraint(entity, "observed_date", "source")`. Measures are nullable.
   Then `uv run alembic revision --autogenerate -m "<source> tables"` and check
   the generated `downgrade()` actually reverses it.

3. **Implement.** In `nh/collectors/<source>.py`, subclass `Collector`:
   - `fetch()` — all network, yields `Raw(kind, key, payload)` with the payload
     untouched. Charge `self.quota.spend(cost, endpoint)` only after a success.
   - `normalize(raw)` — pure. No I/O, no clock, no network. Returns a `Batch`
     of `Upsert` and `Snapshot`. Use `nh.collectors.parse` helpers so absent
     values stay NULL.
   - Set `source`, `description`, `quota_budget`.
   Pure analysis (medians, slopes, ratios) does **not** belong here — it goes in
   `nh/features/` where it can be tested against a fixture database.

4. **Record fixtures.** One real call per endpoint, saved to
   `tests/fixtures/<source>/`. Strip credentials from the recorded payload.

5. **Test.** Against the fixture, mirroring `tests/test_base_collector.py`:
   provenance present, re-run is idempotent, snapshots do not duplicate, absent
   fields land as NULL, a simulated outage produces `status="failed"` rather
   than an exception.

6. **Register.** Flip `ported=True` in `nh/collectors/registry.py` and place the
   spec in the right nightly order — anything that feeds another collector runs
   before it.

7. **Verify.** `uv run pytest -q`, then `uv run nh nightly --dry-run` shows the
   source as ready, then `uv run nh nightly --only <source>` and run `data-qa`.
