# Niche Hunter

A nightly research pipeline that measures **content-niche opportunity** — the gap
between what people search for and what already exists to answer them — using free,
public data sources.

It is a personal research tool. It collects data into a local database to inform
decisions about what topics are worth covering. It is **not** a product, a service,
or a bot that acts on any platform.

## What it does

Collectors pull from public sources on a nightly schedule, land raw payloads
verbatim, normalise them into typed tables, and append daily snapshots. Features are
computed per topic cluster per day, each carrying an explicit `confidence` and
`inputs_n`. Nothing is inferred that was not measured.

| Source | Access | Use |
|---|---|---|
| YouTube Data API | official, keyed | supply side: what already exists |
| YouTube RSS | public feeds | upload cadence |
| Wikipedia pageviews | official, no auth | demand level, absolute units |
| Google Trends | unofficial | demand *shape* only — see `docs/SOURCES.md` |
| Google Ads Keyword Planner | manual CSV export | absolute search volume |
| Reddit | **not implemented** — see below | unmet demand, supply gaps |

## Operating principles

These are enforced in code and tests, not just documented:

- **Read-only.** Nothing here posts, comments, votes, or messages on any platform.
- **No redistribution.** Collected content stays in a local database. Nothing is
  republished, resold, or exposed through any public interface.
- **Absent is NULL, never 0.** A missing value is unknown, not zero — writing zero
  would poison every median and ratio downstream, undetectably.
- **Snapshots are append-only.** History is the compounding asset and cannot be
  re-fetched, so no code path may update or delete a snapshot.
- **Rate limits are budgets, not targets.** Every source has a documented per-run
  quota in `.claude/rules/sources.md`, and every run records what it spent.
- **No live network in tests.** Sockets are blocked in the whole suite; sources are
  replayed from recorded fixtures.

## Planned Reddit use

Not yet implemented — `nh/collectors/reddit.py` is a stub, and access requires
approval under Reddit's Responsible Builder Policy. The intended use is read-only
collection via PRAW from a fixed list of topic-relevant subreddits, to identify:

1. **Question-shaped posts** — what an audience actually asks, which is demand that
   existing content may not answer.
2. **"Recommend a channel" threads that got no useful answer** — a documented supply
   gap with a real person attached.

Expected volume is a few hundred requests per night, far below the 100 queries/minute
limit. No user profiling, no storage of personal data, no redistribution of content.
Design constraint: Reddit inputs are **optional with a confidence penalty, never
required**, so an outage cannot take the pipeline down.

## Honest status

The core hypothesis **has not been validated.** A pre-registered test (Gate E) of
whether the demand–supply gap predicts subsequent channel growth returned a null:
rho 0.091, permutation p 0.4988, across 29 niches with a detectable rho of 0.378.
That is a powered null, not an underpowered run, and the failure analysis in
`reports/backtest_2026-08-28.md` rejects the easy explanations — the inputs are not
flat, and nothing hides under niche size.

Consequently **no ranking ships**: `scorecards.opportunity` stays NULL and the
dashboard is not built until a new pre-registered test passes. The reasoning is in
`docs/DECISIONS.md` as numbered ADRs, including the ones that record being wrong.

## Layout

```
nh/collectors/   one module per source; fetch() does I/O, normalize() is pure
nh/features/     one row per cluster per day, with confidence and inputs_n
nh/scoring/      scorecards and alerts
docs/            SOURCES, METRICS, DECISIONS (ADRs), ROADMAP, RUNBOOK
reports/         pre-registered analyses and their verdicts
legacy/          the original prototypes, frozen; ported one file at a time
```

Python 3.12, SQLAlchemy 2.0, Alembic, Typer, pytest. 667 tests, no network.

```bash
uv run pytest -q          # must be green
uv run nh sources         # ported / configured / quota per source
uv run nh nightly --dry-run
```
