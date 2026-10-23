# Step 0 corrections for the niche choice — 2026-10-22

`reports/niche_choice_procedure_2026-08-28.md` opens with Step 0: *"Corrections: the humanism
row, the language answer, re-file geopolitics and history-of-ideas as value unknown."* This
document discharges the **measurable** half of that step, 55 days later, so Steps 2–5 — the
vetoes, the RPM disclosures, the supply eyeball, the portfolio rules — land on checked
numbers. The language answer and everything from Step 2 on remain the operator's and are
untouched here.

**The procedure's governing constraint is unchanged and is now stronger, not weaker:** this
tool cannot rank these niches by profitability. ADR-0068 (2026-10-22) established that it
cannot rank them by anything — a cross-sectional niche-grain test needs an observed rho above
0.636 at ten clusters, and no effect this corpus admits comes close. The tier table below is
**elimination evidence and texture**, never an ordering. Nothing in it may be used to choose
between two niches of similar value; that was the procedure's rule on 08-28 and it is
arithmetic now.

## Correction 1 — the `humanism` row: suspicion confirmed, and wider than suspected

The procedure flagged that `history-of-ideas` was "70% `humanism`, whose US bid is
byte-identical to `inflation` (64,083 COP — suspected close-variant collapse)".

**Confirmed, and it is not a pair.** US `bid_high` = 64,083.40 is shared by **four
semantically unrelated keywords**:

```
human impact on the environment · humanism · inflation · philosophy of mind
```

Four unrelated terms carrying one byte-identical bid is a quantisation artifact in the export,
not four coincidences. `bid_low` for the same rows differs wildly (humanism 94.61 against
inflation 5,742.30) and monthly searches differ tenfold, so only the `bid_high` field
collapses — which is the field the tiering used.

**Treatment: 64,083.40 is excluded as a value reading wherever it appears.** It affects one
term each in `anthropocene-anthropology`, `history-of-ideas`, `macro-economy` and
`metaphysical-battles`.

## Correction 2 — the value table as of today, artifact excluded

Source: the single Keyword Planner reading of **2026-07-31**, US market, read through the
curated `seed_terms` with `source='keyword_planner'` (six per niche) — *not* `niche_seeds.
keywords`, which are YouTube search phrases and are explicitly not KP inputs.

| niche | usable priced terms | median usable `bid_high` (COP) | total monthly US searches |
|---|---|---|---|
| ai-and-software | 6 of 6 | **33,834** | 5,700,000 |
| trading | 5 of 6 | **31,503** | 610,000 |
| logic-linguistics-gnoseology | 5 of 6 | 25,658 | 1,600,500 |
| macro-economy | 5 of 6 | 20,046 | 750,000 |
| metaphysical-battles | 4 of 6 | 19,385 | 1,155,000 |
| anthropocene-anthropology | 4 of 6 | 19,246 | 1,110,000 |
| history-of-ideas | 3 of 6 | 19,042 | 160,500 |
| geopolitics | 4 of 6 | 14,811 | 660,000 |
| biohacking | 6 of 6 | 11,950 | 1,200,000 |
| esoterism-spirituality | 5 of 6 | 8,130 | 1,150,500 |

**What survives the procedure's own ≥2–3× rule.** Only a 2–3× median gap between
identically-sampled niches counts as evidence. On that rule there is exactly one
defensible statement: **ai-and-software (33,834) and trading (31,503) against
esoterism-spirituality (8,130) is a 4.2x and 3.9x gap.** Everything between 14,811 and
25,658 is one undifferentiated band — seven niches inside a 1.7x spread, on a single
83-day-old reading with 3–6 priced terms each. **Do not order within that band.**

## Correction 3 — the `?` tier empties, and the A/B/? table is stale

Both members of the unknown tier now have usable readings, so the 08-28 structure no longer
describes the evidence:

- **`history-of-ideas`: no longer unknown, but thin.** Three usable terms, median 19,042 —
  mid-band. Its old placement rested on the artifact keyword, which is now gone; what is
  left is `enlightenment` 19,042, `history of philosophy` 27,277, `postmodernism` 6,019,
  with `intellectual history` and `scholasticism` unpriced. Note its demand side is the
  **smallest of the ten at 160,500 searches** — an order of magnitude under ai-and-software.
- **`geopolitics`: no longer resting on one keyword.** Four usable terms, median 14,811. But
  read the composition before using it: `deterrence` 47,421 against `sovereignty` 273 on
  500,000 searches, i.e. its highest-volume term is nearly unpriced. A median over four terms
  this dispersed is a weak summary.
- **`philosophy-of-science`** was retired 2026-08-31 as an editorial choice (ADR-0044), which
  executed the procedure's Step 1 by a different route. The procedure's strongest robust
  finding — zero priced keywords in either market against 565,500 searches — was *not* the
  stated reason, and should not be retro-fitted as one.

## What remains unanswerable, and is not a gap in this document

- **Actual per-niche RPM.** These are Google *search-ad* bids in COP. The procedure's Step 3
  — creator disclosures, every qualifying hit in the top 20, n ≥ 5, reported min–median–max —
  is the only route to the real quantity, and is ~30–45 min per surviving candidate of the
  operator's time.
- **Any prediction of views.** Gate E's null stands and ADR-0068 closes the re-test.
- **The publish-language question.** If the channel publishes in Spanish, this entire US table
  describes a market it will not serve and a `geo=CO/MX/ES` export must precede any use of it.
  **Unanswered as of today.**
- **Production cost.** Never measured anywhere in this repo.

## Staleness, stated plainly

One reading, **2026-07-31, now 83 days old**. ADR-0058 decays its confidence with age —
`freshness = min(1, 30/age_days)` puts it at **~0.36** — and only a manual UI CSV export
(`nh kp ingest`) refreshes it. If this choice is going to turn on the value column at all,
re-export first; if it is going to turn on the vetoes, it does not matter.

## What this document does not do

It does not pick, rank, score, weight or recommend. It does not eliminate anything. The
procedure forbids a composite score and forbids choosing between same-tier niches on these
numbers, and both prohibitions are respected here. Steps 2 through 5 — the three vetoes (the
25-title test, episode 1 vs episode 20, the video-#30 question), the RPM disclosures, the
uniform supply eyeball, the portfolio rules and the Step-5 residue paragraphs — are the
operator's, unchanged.

## Provenance

Measured read-only against `data/niche_hunter.db` on 2026-10-22 by the queries recorded in
this session: the four-way artifact collision, the per-niche usable-term counts and medians,
the per-term detail for the two `?`-tier niches, and the search totals. **One correction to my
own working, recorded because it nearly shipped:** a first pass reported "zero priced keywords
for all ten niches", having queried `niche_seeds.keywords` instead of the curated
`seed_terms`. The result was implausible enough to re-check, which is a weaker safeguard than
reading the docstring that says those fields are not interchangeable
(`inputs.demand_terms`, "deliberately does NOT fall back to `niche_seeds.keywords`").

---

## Addendum 2026-10-23 — Step 3 attempted and NOT completable by me

Step 3 of the procedure is creator RPM disclosures: *"~30–45 min per surviving candidate —
the actual quantity from the actual auction, unlike `bid_high`. Registered queries, **every**
qualifying hit in the top 20 (no cherry-picking), n ≥ 5, report min–median–max, never a
point."*

I attempted it and **obtained zero qualifying disclosures.** The reason is structural, not
effort:

- **Web search returns content farms, not disclosures.** The top results for RPM queries are
  SEO marketing blogs quoting ranges like "$12–$18" and "$8–$20" for the same category,
  unsourced and mutually inconsistent. A "qualifying hit" under this procedure is a creator
  stating their own measured RPM; an aggregator asserting a band is not that, and averaging
  bands would manufacture precisely the fabricated exchange rate data rule 6 forbids.
- **The venues where real disclosures live are closed to me.** They are Reddit threads,
  in-video analytics screenshares, and podcast audio. `reddit.com` refuses this user agent
  outright; a video's on-screen analytics cannot be read from a search snippet; podcast
  figures are spoken, not indexed.

**Per the procedure's own rule — "Fewer than 5 disclosures is itself information" — this is
recorded as n = 0, not as an absence of data.** What it says is narrower than it looks: it
says *this method is not executable by a web-search agent*, not that the disclosures do not
exist. The operator can watch a video's analytics overlay, read a Reddit thread and hear a
podcast number; I cannot do any of the three.

**So the one surviving value statement remains uncorroborated.** The 4.2x / 3.9x gap between
ai-and-software and trading on one side and esoterism-spirituality on the other rests
entirely on Google *search-ad* bids in COP from a single 2026-07-31 export — which is a
proxy the procedure explicitly says is not RPM. Step 3 exists because that proxy is not
trusted, and Step 3 has not been run.

**Nothing has been added to the value column by this attempt**, deliberately. A table of
marketing-blog ranges in this repository would read as evidence at a glance and would be
worse than the blank it replaces.
