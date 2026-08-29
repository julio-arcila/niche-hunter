# RPM disclosure pass — pre-registration

**Registered before the first query is run.** Every rule below is fixed in advance;
the point of committing this first is that a later reader can check the protocol was not
shaped by its results. Registered against ROADMAP risk #7 (n≥5, always a range, never a
point) and METRICS.md's `rpm_disclosure_calibration`.

## Why this pass exists

`bid_high` from Keyword Planner is an advertiser's **search-ad** bid — a different
auction, different inventory, different market from YouTube's. It is the tier proxy this
project has; it is not RPM. Creator disclosures are the actual quantity from the actual
auction. They are badly biased, and the protocol's job is to make the bias **uniform
across niches** so comparisons survive even though levels do not.

## Resolution warning, stated first

Creators do not self-describe at this repo's niche granularity. Evidence resolves to
**nine measurement units, coarser than the eleven niches** — the four philosophy niches
collapse into one. Results attach to the unit and are inherited by its members, stated as
such. **This instrument cannot rank metaphysical-battles against logic-linguistics.**

| Unit | Covers | Primary descriptor | Secondary |
|---|---|---|---|
| philosophy | philosophy-of-science, metaphysical-battles, logic-linguistics-gnoseology | `philosophy` | `educational philosophy` |
| history | history-of-ideas | `history` | `history of philosophy` |
| occult | esoterism-spirituality | `occult` | `spirituality` |
| anthropology | anthropocene-anthropology | `anthropology` | `archaeology` |
| economics | macro-economy | `economics` | `macroeconomics` |
| trading | trading | `trading` | `day trading` |
| ai-tech | ai-and-software | `AI` | `tech` |
| biohacking | biohacking | `biohacking` | `health` |
| geopolitics | geopolitics | `geopolitics` | `news and politics` |

Where a secondary broadens the population (biohacking→health), n bought by broadening is
labelled as broader.

## The query set — fixed templates, identical for every niche

Uniformity is what makes cross-niche comparison survive the bias. Six per descriptor,
`{D}` = descriptor, run in this order:

1. `{D} youtube rpm`
2. `{D} youtube channel rpm reddit`
3. `"{D}" youtube creator "my rpm" OR "rpm is"`
4. `{D} youtube channel how much earn per 1000 views`
5. `{D} youtube revenue "per 1,000 views" OR "per million views"`
6. `{D} youtube channel income report monetization`

**First 20 results of each, no cherry-picking**; every qualifying hit recorded. Dedup
within a unit. One outbound hop allowed (a thread linking a creator's own disclosure);
no second hop. English queries — **void and re-register in Spanish if the operator
publishes in Spanish.**

## Inclusion, and every edge case decided now

**Qualifies:** a figure attributable to an identifiable channel, stating RPM *or* revenue
plus views, datable to **2023-09-01 or later**, for a channel matching the unit.

- **RPM vs CPM:** record the creator's word verbatim. A CPM figure with no revenue/views
  to divide is recorded but **excluded** — converting CPM→RPM needs a monetized-view-rate
  assumption, i.e. the invented exchange rate data rule 6 forbids. Revenue + views given →
  derive RPM regardless of their vocabulary.
- **Revenue without views:** recorded, excluded.
- **"$X per million views":** same quantity ÷ 1,000, included.
- **Undated:** a disclosure cannot postdate its container, so the container's publish date
  is an upper bound. In window → include, `date_quality=container_only`. No datable
  container → exclude.
- **Aggregators quoting unnamed creators:** recorded, excluded from primary n. Quoting a
  **named, linkable** creator: included; a duplicate of that creator's own disclosure adds
  no n. Medians reported with and without aggregator rows as a sensitivity line.
- **Adjacent channels:** check the last 20 upload titles; ≥11/20 inside the unit → counts.
  Otherwise recorded, excluded, reported separately, with the judgment evidence in the row
  so a later reader can dispute it.
- **Non-USD:** record currency and stated value; convert at the period's approximate rate;
  both values in the row.

## Recording schema — one JSONL line per observation, included or not

```json
{"unit":"trading","descriptor":"trading","query_id":"q3","query_rank":7,
 "found_at":"2026-08-29","url":"https://...",
 "source_type":"creator_video|creator_post|forum_named|aggregator_named|aggregator_unnamed",
 "channel_name":"...","channel_url":"...","channel_subs_stated":12000,
 "niche_match":"core|adjacent|off","niche_match_evidence":"last 20 uploads: 17/20 day-trading",
 "metric_as_stated":"RPM","value_stated":"verbatim quote of the figure and its sentence",
 "rpm_low_usd":8.0,"rpm_high_usd":12.0,
 "period_stated":"2025-Q4","date_quality":"explicit|container_only",
 "geo_stated":"unstated","currency_original":"USD",
 "included":true,"exclude_reason":null,"notes":""}
```

Excluded rows are written too. The audit trail is the point. Files:
`reports/rpm_disclosures_2026-08/<unit>.jsonl`.

## The bias that cannot be removed

Disclosure is itself a content genre — "how much YouTube paid me" is a monetizable video —
so the sample is creators successful enough for that video to be interesting, skewed
toward extremes, with aggregators inflating on top. **Levels from this protocol are not
the niche's RPM and must never be quoted as such.** What keeps comparison alive is that
the bias operates through the same mechanism everywhere and the protocol holds constant
everything that modulates it: identical templates, result depth, window, inclusion rules,
effort cap. One residual asymmetry is checked rather than assumed — `channel_subs_stated`
is recorded, so if one unit's disclosers are 10x larger than another's, the comparison is
flagged size-confounded instead of silently standing.

## Analysis rules

- Primary n = included core rows after dedup. **n≥5 before any figure appears.**
- Report **min–median–max**, never a point.
- **Comparisons:** medians only, both units at n≥5. **≥3x is evidence; 2–3x is reported
  and decides nothing; <2x is indistinguishable.**
- **Different n:** medians comparable at n≥5 both; min/max spreads are **not** comparable
  across different n, since range widens mechanically with n.
- **n<5:** "insufficient disclosures (n=k)", rows attached, no range, no median. Scarcity
  confounds small creator base / non-disclosing culture / a descriptor that missed how
  creators self-describe, and this protocol cannot separate those.

## Pre-registered falsifications

Tier table under test (post-correction): A {ai-and-software, logic-linguistics,
macro-economy, trading} > B {biohacking, metaphysical-battles, esoterism, anthropocene} >
? {history-of-ideas, geopolitics}; philosophy-of-science unpriced.

- **F1 — tiers contradicted.** Any B median ≥3x any A median, both n≥5 → `bid_high` does
  not proxy YouTube RPM for that pair. The tier table is dropped from the value reasoning;
  "at least one Tier-A pick" survives only as diversification, not evidence.
- **F2 — the strongest finding contradicted.** The philosophy unit reaches n≥5 with a
  median within 2x of the lowest A median → the leap from "zero priced search keywords" to
  "absent ad monetization" fails, because advertisers who don't bid on search terms may
  still pay on watch time. **philosophy-of-science's elimination must be re-opened.**
- **F3 — corroboration.** Every A median ≥3x every B median → tiers corroborated at the
  RPM level. This still says nothing about views (Gate E's null stands).
- Any middle outcome **decides nothing**, and the report must say so rather than grading it.
- history-of-ideas and geopolitics are `?` in KP, so no falsification is possible for them;
  this pass is their **first** value evidence, provisional and single-instrument.

## Stopping rule

Per unit: 6 primary-descriptor queries × top 20, hard cap **45 minutes**, whichever ends
first. If n<5: 6 secondary-descriptor queries, same rules, total cap **75 minutes**. Then
stop regardless of n — **n<5 after 75 minutes is the finding.** No third descriptor, no
page two, no extra hops.

## Which units to run

Every unit containing a survivor of the operator's veto pass, **plus the philosophy unit
unconditionally** — it is the F2 probe against this repo's single strongest robust
finding, worth the time even if all its member niches are vetoed. A later un-vetoed niche
is collected under this same protocol version, with the collection-date gap noted;
cross-date medians are a flagged comparison, not a clean one.
