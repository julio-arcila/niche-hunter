# Verification and extraction-repair pass — 2026-08-29

Slice 11 branch (`slice-11-eleven-domain-pivot`). Three claims verified by doing,
three extraction defects repaired. Every number below was measured this session
unless labelled inference; commits are one logical unit each.

## A1 — CourtListener: the repo's live test does not reproduce

**Measured 2026-08-29 03:30 UTC**, one unauthenticated GET to
`/api/rest/v4/dockets/?page_size=1`: **HTTP 401**,
`{"detail": "Authentication credentials were not provided."}`,
`WWW-Authenticate: Bearer realm="api"`.

The repo (`nh/seeds.py`) recorded a successful unauthenticated live test dated
2026-08-27 — *after* Free Law Project moved API access into memberships
(2026-05-07; free accounts 5/min, 50/hour, 125/day). The two could not both be
true and the measurement wins: either the 08-27 test hit a not-yet-enforced path
or it was wrong. Corrected in `nh/seeds.py` (both `primary_sources` entries and
the module docstring), the `cost_risk` deferral blocker in `nh/jobs/deferrals.py`,
and a new dated section in `docs/SOURCES.md`. The source is now
*obtainable-unregistered* in ADR-0021's sense: registration is free, `dateFiled`
still exists behind auth, and 125/day fits a nightly cadence count but not a
crawl.

## A2 — The `inflation`/`humanism` bid collision: a sentinel, not close variants

Checked against all 162 stored `keyword_metrics` rows (96 US + 66 GB, period
ending 2026-07-31; 107 rows carry `bid_high`), raw CSVs cross-checked to rule out
a parser artifact.

- 64,083.40 COP appears on **five** rows — `human impact on the environment`,
  `humanism`, `inflation`, `philosophy of mind` (US) and `epistemology` (GB) —
  and its exact tenth, 6,408.34, on two more (`scientific method` US, `occult`
  GB), plus once as a `bid_low` (`humanism` GB).
- At one implied rate, 4,005.2125 COP/USD, those two values are exactly
  **US$16.00 and US$1.60**. None of the other 100 priced rows is a round dollar
  at that rate. One row is degenerate: `human impact on the environment` (US)
  has `bid_low = bid_high = 64,083.40`.
- **Close-variant grouping is disproven**: the sharers are semantically unrelated
  and their volumes (5,000 vs 500,000), `bid_low`s (94.61 vs 5,742.30) and
  competition indexes all differ. Close variants merge whole rows, not one
  column.

**Verdict: systematic but bounded and detectable** — 7 of 107 priced rows
(6.5%), across both geos and both bid columns, always one of two exact values.
This is an estimator default emitted when a keyword lacks auction depth — the
same failure shape as the identical `$1.21` RPM default the disclosure pass
caught. Inference, labelled: other exports may carry other round-dollar
defaults; the durable detector is exact cross-keyword equality (or exact USD
roundness at the account's implied rate), not the two literals.

**Implication for `bid_high`**: usable after sentinel exclusion (100/107 rows
look like real, distinct estimates), but any niche aggregate over 1–6 priced
keywords is dominated by one imputed $16, so Slice 9's `median_bid_high` and
`vw_cpc` must treat sentinel bids as **unpriced (NULL)**. `history-of-ideas`
stays unquotable — 70% of its value sits on the sentinel — now with a measured
reason. Recorded in `docs/SOURCES.md`, a dated addendum to
`reports/geo_value_2026-08-28.md`, and the Slice 9 constraints in ROADMAP.

## A3 — Google Ads API: the sequence, from Google's own docs

Written into `docs/SOURCES.md` as a numbered runbook. The load-bearing findings:

1. **Manager (MCC) account first** — the developer token lives only in a manager
   account's API Center; creation is free, wants a fresh email, and the existing
   regular account is *linked*, not converted.
2. **A new token arrives at Explorer access, and Explorer excludes keyword
   planning.** The access-levels page's restriction list names
   `KeywordPlanIdeaService`, `KeywordPlanService`, `ReachPlanService`,
   `AudienceInsightsService`. A token in hand generates no keyword data — this is
   the step practitioner write-ups skip.
3. **Basic access is an application** (API Center → Apply for Basic Access;
   valid contact email; accounts linked), reviewed "typically 5 business days" —
   the source audit's "24–48h" was a practitioner report and is corrected.
   Basic: 15,000 ops/day.
4. **Numeric volumes for a zero-spend account: UNRESOLVED**, deliberately
   recorded as such rather than a side picked. Google documents the UI's
   limited-data-view spend gate and does not document one for the API;
   practitioner reports disagree. Our own account's evidence leans pessimistic:
   the zero-spend UI CSV already returns power-of-ten bucket midpoints
   (50/500/5,000/50,000/500,000) rather than ranges, i.e. bucketing follows the
   *account* (inference). The day-one test is one
   `GenerateKeywordHistoricalMetrics` call against the stored CSV buckets. The
   application is worth filing on either branch: the 12 monthly columns (0/360
   empty in every CSV), per-geo runs as a parameter, and Reach Planner CPM come
   regardless.

## B4 — `regionCode`: the premise was wrong, and the decision followed from that

The task assumed discovery was "language-biased and geo-unscoped". **Measured
from the API reference: a `search.list` request without `regionCode` is served
with a US default** (the response's `regionCode` property: "The default value is
US"), from whatever IP the cron runs on — this one is Colombian. So the real
choice was "basis stated by us" vs "basis inferred by a server default, free to
drift", and ADR-0035's recorded-not-inferred rule decides it alone.

**Decision (ADR-0037): send it, sourced per-seed from `niche_seeds.geo`;** a seed
stating no geo sends nothing. A constant re-buries curation; a run argument forks
the corpus per invocation invisibly; per-seed is the only shape a many-market
catalogue (ADR-0036) needs, and it makes ADR-0035's deferred per-market
instantiation free when it arrives. The raw `search_hit` payload now records the
`region` sent. This is *not* the supply-narrowing ADR-0035 rule 4 rejected:
`regionCode` is a viewpoint parameter (results viewable in and ranked for the
market), not a creator filter — global English supply stays in the pool and
`geo_concentration` keeps measuring the divergence.

All five live seeds state US == the documented default, so the expected series
change is **zero — inferred from docs, not measured**; the ADR names a step
change in `discoveries` volume as the thing to watch, and the payload stamp
makes the boundary attributable either way. Two tests pin the parameter and the
omission case.

## B5 — `uploads_per_week`: the span rate finally shipped (v3-span-rate-on-niche)

The shipped code divided a fixed 28-day count by 4.0 weeks while rule 9, the
metric's own failure-mode text, and two doc passages variously forbade that or
falsely claimed it was already fixed. Now: per-channel uploads in the window
divided by the channel's **observed span** in weeks
(`max(window start, oldest known video of any kind)` .. day, inclusive civil
days), summed across channels. Identical to `count/4` where observation covers
the whole window; a rate over what was seen where the RSS 15-entry cap truncated
it. The span marker is any-video deliberately — an on-niche marker would turn a
channel with one on-niche upload into a one-day span at 7/wk.

**Measured on the live corpus at day 2026-08-28** (first computation, read-only):

```
cluster                 span form   fixed form   censored/known
aviation-disasters         174.8       100.0        122/241
corporate-collapse         131.4        83.8        100/280
engineering-failures        96.6        62.3        102/222
maritime-disasters          81.1        47.8         84/196
true-crime-trials          328.1       158.5         42/ 99
```

17–52% of each cluster's known channels are span-censored and the fixed form
underread every niche by 1.6x–2.1x, worst where cadence is highest — a
size-correlated bias sitting under `scorecards.supply`. New regression test pins
14 uploads over a 14-day observed span at 7.0/wk (old code: 3.5); three tests
that had pinned the censored arithmetic were updated with the span arithmetic
spelled out. `detail` gains `channels_span_censored` and a new definition tag so
the stored-series step is attributable. METRICS.md, rule 9, and
`median_top_video_age`'s docstring now date the redefinition instead of claiming
it early. Honest residue, recorded in the failure mode: the span form
extrapolates a censored channel's cadence (no damping floor — zero tuned
constants), and feed *overflow* (>15 uploads between polls) is still lost.

## B6 — `seed_terms.geo`: option (b), implemented and migrated (ADR-0038)

A seed term asserts "this niche cares about this keyword" — geo-independent
curation. `keyword_metrics.geo` records which export a number came from — a
property of the observation. Stamping `geo="US"` onto KP seed terms conflated
the two and made the GB export match 96/162. Option (a) (seed rows per geo) was
rejected: 66×N duplicated curation that misses every new market until re-seeded.

Shipped: the 96 KP seed terms return to `geo=''` (meaning "curation, no market");
`nh kp ingest`'s match report keys on `(keyword, lang)` — the join the features
will actually use — with per-geo coverage lines; ROADMAP Slice 9's loader
contract now reads `keyword_planner_rows(session, cluster_id, day, geo)` with
**no default geo** (a defaulted geo silently picks a market, and `geo_value`
measured market choice as a real reordering). Data migration via `nh seed`, the
documented path. **Measured after the re-seed: 162/162 stored rows match a seed
term (US 96/96, GB 66/66).** No schema change was needed — the unique key never
included geo.

## What contradicted an expectation

1. **CourtListener**: the repo's own dated live test was wrong; the policy
   change was real. (The task anticipated this one.)
2. **The bid collision is not close-variant grouping** — the geo_value
   correction's guessed mechanism is disproven; it is an imputed estimator
   default, wider than the flagged pair (7 rows, both geos) but exactly
   detectable.
3. **YouTube discovery was never geo-unscoped** — it has been implicitly
   US-scoped by a server default since Slice 1. The "should we send regionCode"
   question dissolved into "should the basis be recorded", which was already
   answered by ADR-0035.
4. **Google Ads approval is 5 business days per Google**, not the audit's
   24–48h; and an Explorer-level token — the default grant — cannot call any
   planning service at all.
5. **The fixed-window uploads bias was larger than documented**: not only flat
   spread at the cap (the Slice 2 finding) but a 1.6x–2.1x underread on today's
   corpus, scaling with cadence.

## Not settled, and why

- **Numeric vs bucketed volumes under Basic access, zero-spend** — needs the
  developer token that needs the manager account. One API call decides it.
- **Whether explicit `regionCode=US` is byte-identical to the server default** —
  inferred from documentation; verifying would spend un-ledgered search quota,
  and tonight's nightly plus the payload stamp answers it for free. Watch
  `discoveries` volume.
- **Whether other KP exports carry other sentinel bid values** — two literals
  measured; the detection rule (exact cross-keyword equality / USD roundness at
  the implied rate) is recorded for the next export.

## Now blocked on the operator, not on code

1. **Google Ads**: create the manager account, obtain the token, apply for Basic
   (runbook in SOURCES.md). Everything Slice 9 wants beyond CSV buckets waits
   here.
2. **CourtListener**: register a free account if `cost_risk` work is wanted;
   125 req/day is enough for cadence counts.
3. **Reddit**: the application remains unfiled (ADR-0021 — unchanged, noted for
   completeness).
4. **Next KP export** (monthly cadence) and the **human relevance labels**
   (60–100 rows above threshold) — both pre-existing, both unmoved by this pass.

## Live-database writes made this session

`nh seed` was re-run once (B6): `seed_terms.geo` US→'' for 96 keyword_planner
rows, and the two CourtListener `primary_sources` entries updated on their
seeds. Everything else was read-only against `data/niche_hunter.db`; one
unauthenticated HTTP request went to CourtListener (A1), and no quota-bearing
call was made anywhere.
