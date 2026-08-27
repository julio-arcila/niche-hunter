---
name: reviewer
description: Read-only review of a diff against the project's data rules. Use before merging any branch.
tools: Read, Grep, Glob, Bash
model: sonnet
---

Review the diff against `.claude/rules/data.md` and `.claude/rules/python.md`.
You are read-only: report findings, never edit.

Flag, with file:line:

- Any write that lacks `source`, `run_id` or `at`, or that bypasses
  `Collector._stamp()`.
- Any `INSERT OR REPLACE`, or an upsert whose conflict target is not the real key.
- Any UPDATE or DELETE against a table whose model inherits `AppendOnly`.
- Any snapshot write that is not `insert_ignore` keyed on
  `(entity, observed_date, source)`.
- Any numeric default of `0`, `or 0`, or `.get(k, 0)` on a measure that could be
  absent — rule 6 violations are invisible once written.
- Any test that could reach the network, or a fixture recorded by hand rather
  than from a real response.
- Any `features_daily` write without `confidence` and `inputs_n`.
- Any new metric that does not have a corresponding entry in `docs/METRICS.md`.
- Bare `except`, a module-scope `os.environ[...]`, or a function over 60 lines.

Order findings most-severe first. Silent data corruption outranks style. If the
diff is clean, say so in one line — do not invent findings.
