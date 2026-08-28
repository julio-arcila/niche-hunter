# Python rules

- Python 3.12, `uv` for env and deps, ruff-formatted (the PostToolUse hook runs
  it on every write). Line length 100.
- Type hints on every function signature. `from __future__ import annotations`
  at the top of every module.
- Functions under 60 lines. If a collector's `normalize()` is longer, the
  analysis inside it belongs in `nh/features/`.
- Prefer `raise` over returning `None` on error — **except at a collection or
  phase boundary**, where one bad item or one dead source must not kill the
  nightly job.
- No bare `except:`. A broad `except Exception` is permitted only at those
  boundaries, and only with a comment saying which boundary and why. There are
  currently **five**: `Collector.run()` (a whole source), `trends.py:147` and
  `wikipedia.py:155` and `youtube_rss.py:144` (one item within a source), and
  `jobs/phases.py:80` (one phase). An earlier version of this rule said the
  exception was implemented "once, in `Collector.run()`, and nowhere else", and
  `youtube_rss.py` called itself "the second of only two" — both were false as
  written. A rule that miscounts its own exceptions has lost its force, so the
  count is stated here and is expected to be corrected rather than quietly
  outgrown.
- No I/O, clock reads or network in `normalize()`. It takes a `Raw` and returns
  a `Batch`; that purity is what makes it testable from a recorded fixture.
- Credentials are read through `nh.config.Settings` only. Never
  `os.environ[...]` at module scope — it makes the module unimportable and
  therefore untestable when the source is not yet provisioned.
