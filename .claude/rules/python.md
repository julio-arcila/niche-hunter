# Python rules

- Python 3.12, `uv` for env and deps, ruff-formatted (the PostToolUse hook runs
  it on every write). Line length 100.
- Type hints on every function signature. `from __future__ import annotations`
  at the top of every module.
- Functions under 60 lines. If a collector's `normalize()` is longer, the
  analysis inside it belongs in `nh/features/`.
- Prefer `raise` over returning `None` on error — **except inside collectors**,
  where a source outage must not kill the nightly job. That exception is
  implemented once, in `Collector.run()`, and nowhere else.
- No bare `except:`. The one broad `except Exception` in `Collector.run()` is
  deliberate, commented, and records the failure to `job_runs`.
- No I/O, clock reads or network in `normalize()`. It takes a `Raw` and returns
  a `Batch`; that purity is what makes it testable from a recorded fixture.
- Credentials are read through `nh.config.Settings` only. Never
  `os.environ[...]` at module scope — it makes the module unimportable and
  therefore untestable when the source is not yet provisioned.
