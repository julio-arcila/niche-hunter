# RPM disclosure pass — result: a complete null, and why

Executed against `rpm_disclosure_preregistration_2026-08-28.md`, committed before the
first query ran. Nine measurement units, 108 registered queries (6 primary + 6 secondary
per unit, every unit falling below n=5 on primaries and so triggering its secondary).

## Result

```
unit           recorded   included
philosophy           10          0
geopolitics           7          0
history               7          0
ai-tech               6          0
economics             6          0
occult                5          0
trading               5          0
biohacking            3          0
anthropology          1          0
                     50          0
```

**Fifty observations recorded, zero qualifying. Every unit returns "insufficient
disclosures (n=0)".** No medians, no ranges. F1, F2 and F3 are all non-evaluable —
median comparison requires n≥5 on both sides, and no side reached it.

Per the pre-registration, n<5 after the full query budget **is the finding**, and it
"confounds small creator base, non-disclosing culture, and descriptors that missed how
creators self-describe" — this pass cannot separate those. But it can say something
sharper about the instrument, below.

## What the fifty rows actually were

Three classes, and none of them is a creator disclosure:

- **Third-party algorithmic estimators** (~20 rows) — `youtubers.me`, `vidIQ`,
  `HypeAuditor`, `SPEAKRJ`. These name a channel and *invent* the figure. The giveaway
  is decisive and was caught **independently by three of the four agents**: the identical
  `$1.21 per 1,000 views` appears for unrelated channels across different units. That is
  a site default, not a measurement.
- **Aggregator category ranges with no named creator** (~15 rows) — "$4–6 RPM ancient
  philosophy", "Education and Tutorials $2–8". SEO content, two instances mirrored on
  hijacked domains.
- **Real but unusable** — revenue without views, inaccessible pages (403), undatable
  containers.

The exclusion rule that did the most work was the one the protocol registered against
estimators: an aggregator *quoting* a creator's disclosure counts; an aggregator
*computing* one does not. Three agents reached that call independently on the same
evidence.

## The instrument failed, and the failure is diagnosable without reference to the results

This matters for whether a v2 is repair or fishing. All four defects below are visible
from the tool's behaviour alone:

1. **Registered depth was unattainable.** The protocol says "first 20 results of each
   query"; the search tool returns **7–10, with no pagination**. Every unit ran at roughly
   half the registered depth. Uniform, so comparability survives — but absolute n is
   mechanically depressed.
2. **The source layer was never reached.** Creator RPM disclosures live inside **YouTube
   videos and Reddit threads**. A web search surfaces the SEO stratum sitting on top of
   them. Concretely: the `q2` template is `{D} youtube channel rpm reddit`, and across all
   108 queries **not one Reddit thread surfaced**; Quora returned 403.
3. **Filters calibrated for an abundant source, applied to a scarce one.** Two genuine
   first-person disclosures were found and excluded by registered rules:
   - `eddyjoemd` — $795.35 per 100k views (≈$7.95 RPM), a real creator stating real
     numbers, **excluded solely by the 2023-09-01 date floor** (published 2020-12-12).
   - `TLDR News` — its own transparency reports "likely qualify", but reaching them was
     search → Wikipedia → report, and **the one-hop limit forbade the second hop**.
   A 36-month window and a single hop are reasonable against a dense source. Against a
   thin one they remove the only real hits.
4. **"Every qualifying hit recorded" was under-specified.** The dominant result class in
   all 108 queries — generic RPM explainers and earnings calculators carrying no
   channel-attributable figure — is neither clearly qualifying nor clearly excluded. Every
   agent applied the conservative reading and recorded nothing, which is why 50 rows sit
   under ~1,000 scanned results. The next version must say so explicitly.

## F2: not triggered, but the premise it tested took a soft hit

F2 asked whether philosophy content is ad-monetized despite `philosophy-of-science`
having **zero priced keywords** in either market — the finding on which its elimination
rests.

**The test did not fire**: philosophy reached n=0, so no median exists and the registered
condition is unevaluable. **The elimination stands procedurally.**

But the direction of the scraps is worth recording, carefully and without inflating it.
Every philosophy-adjacent figure encountered — $4–6 RPM, $6, $7.13, and one first-party
$1.5k/month AdSense claim — is **consistent with ordinary educational-niche
monetization**, and nothing found suggests ads fail to serve on philosophy content. The
rows are aggregator-heavy and skewed toward stoicism-and-self-help rather than the unit's
actual member niches, so this is far below the protocol's own evidentiary bar.

The honest statement: **not a pass, not a trigger — but the inference "zero priced search
keywords ⇒ no ad monetization" is weaker after this pass than before it.** The n=0 for
philosophy is better explained by a small, non-disclosing creator base than by
demonetization. Anyone re-opening that elimination now has a reason to look; nobody has
evidence to act on.

## What this changes for the niche decision

Nothing, and that is the point worth being clear about. The operator's value evidence
remains exactly what it was before this pass: **Keyword Planner search bids, a proxy from
a different auction, at power-of-ten resolution.** The RPM cross-check was supposed to
either corroborate or contradict the tier structure, and it did neither.

So the tier structure stands **unchallenged and unconfirmed**, and the decision procedure's
weighting of it should not change on the strength of a pass that produced no evidence.

## Whether to run a v2

The four defects above are repairable — search Reddit and YouTube directly through the
browser rather than through a web index, widen the date floor, allow two hops, and define
the generic-explainer case. That is instrument repair, and it is justified by diagnosis
made independently of the results.

**But it must be registered before it runs, and this null must stand in the record
whatever it finds.** Changing the instrument after a null is legitimate only when the
instrument's failure can be shown without reference to the numbers — which is why the four
defects are listed above with the evidence for each. A v2 that quietly replaced this
document would be the same act with the opposite integrity.
