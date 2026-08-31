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
  boundaries, and only with a comment saying which boundary and why.

  **The rule is about catches that SWALLOW.** That scope line is new, and it is what
  the count kept getting wrong: a catch that re-raises hides nothing and is not what
  this rule guards against. There are **five** swallowing catches, and they are:

  | site | boundary |
  |---|---|
  | `collectors/base.py:230` (`Collector.run`) | a whole source |
  | `collectors/trends.py:159` | one item within a source |
  | `collectors/wikipedia.py:155` | one item within a source |
  | `collectors/youtube_rss.py:144` | one item within a source |
  | `jobs/phases.py:93` | one phase |

  Three further `except Exception` sites exist and are deliberately **not** in that
  count, named here so the next audit does not have to re-derive the distinction:
  `db/session.py:82` and `jobs/backfill.py:124` both **re-raise** after cleanup, and
  `db/upsert.py:59` is a driver-capability probe whose fallback is the conservative
  path. `grep -rn "except Exception" nh/` returns **eight**; five is the count of the
  ones this rule is about.

  History, because the count has now been wrong twice and that is the point. An
  earlier version said the exception was implemented "once, in `Collector.run()`, and
  nowhere else", and `youtube_rss.py` called itself "the second of only two" — both
  false as written. The correction then said "five" and named line numbers that
  drifted (`trends.py:147`, `phases.py:80`) while three uncounted sites appeared, so
  an independent sweep on 2026-08-31 found the corrected rule miscounting again. **A
  rule that miscounts its own exceptions has lost its force**, so the scope is stated,
  the members are tabulated, and the near-misses are named. Expected to be corrected
  rather than quietly outgrown — and `youtube_rss.py`'s own comment now points here
  instead of restating a count, because a number kept in two places is a number that
  will disagree with itself.
- No I/O, clock reads or network in `normalize()`. It takes a `Raw` and returns
  a `Batch`; that purity is what makes it testable from a recorded fixture.
- Credentials are read through `nh.config.Settings` only. Never
  `os.environ[...]` at module scope — it makes the module unimportable and
  therefore untestable when the source is not yet provisioned.
