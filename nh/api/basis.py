"""Which population each metric measures (ADR-0035).

The four sources are **not** scoped to the same people, and a reader must not have to know
that `en.wikipedia` is a language while `geo=US` is a country in order to avoid comparing
them. METRICS.md records the mapping in prose; this is the same mapping as data, so a
renderer cannot show two numbers side by side with nothing saying they count different
people.

**This discharges the render half of the `geo_basis` deferral**, whose trigger — "it becomes
arithmetically live the day a `geo=US` level ships" — fired when Slice 9 landed
`demand.total_monthly_searches`. The deferral warned that the cost was "larger than it
looks... `cli.py::_provenance` renders a FIXED list of named keys, so an unrendered key
repeats ADR-0031's `currency` bug exactly". That is why the basis is resolved here from the
metric's identity rather than from a `detail` key someone has to remember to stamp: a
stamped key that no renderer reads is the bug, not the fix.

Keyed on the SOURCE a metric reads, because that is where the population is decided.
`detail.geo`, where a metric stamps it, wins — a Keyword Planner number knows which export
it came from and that is more specific than anything this table can say.
"""

from __future__ import annotations

from typing import Any

#: Population per source, verbatim from docs/METRICS.md's table. Not paraphrased: the two
#: must be diffable by eye, because a renderer quietly drifting from the doc is how a
#: reader ends up comparing English readers to US searchers again.
POPULATIONS: dict[str, str] = {
    "wikipedia": "English readers globally (en.wikipedia)",
    "trends": "Worldwide",
    "keyword_planner": "United States",
    "youtube": "YouTube search as served for the seed's market (US), English relevance",
    "derived": "a rank across the day's clusters, not a population",
}

#: Metric → the source whose population it inherits. Exhaustive over
#: `features.run.METRICS` by test, so a metric added later cannot render with no basis.
SOURCE_OF: dict[str, str] = {
    # demand
    "wiki_weekly_views": "wikipedia",
    "wiki_weekly_views_event": "wikipedia",
    "wiki_momentum_28d": "wikipedia",
    "wiki_yoy": "wikipedia",
    "wiki_volatility_365d": "wikipedia",
    "wiki_seasonality": "wikipedia",
    "trends_momentum_13w": "trends",
    "total_monthly_searches": "keyword_planner",
    # supply — the corpus is what discovery returned for the seed's market
    "uploads_per_week": "youtube",
    "median_views": "youtube",
    "on_niche_share": "youtube",
    "geo_concentration": "youtube",
    "format_mix": "youtube",
    "top10_concentration": "youtube",
    "median_top_video_age": "youtube",
    "pressure_index": "derived",
    # openness
    "breakthrough_rate_cohort": "youtube",
    "views_per_sub": "youtube",
    "winner_age_years": "youtube",
    # money
    "midroll_eligible_share": "youtube",
    "priced_share": "keyword_planner",
    "competition_index_mean": "keyword_planner",
    "vw_cpc": "keyword_planner",
    "median_bid_high": "keyword_planner",
}

UNKNOWN = "population not recorded — see docs/METRICS.md"


def source_of(name: str) -> str | None:
    return SOURCE_OF.get(name)


def basis(name: str, detail: dict[str, Any] | None = None) -> str:
    """The population `name` measured, preferring what the row itself recorded.

    A metric that stamps `detail.geo` knows which export or market its number came from,
    which beats a static table — that is the ADR-0037 case, where discovery began sending
    the seed's geo explicitly and stamping it rather than relying on an inferred US default.
    """
    if detail and (geo := detail.get("geo")) is not None:
        return f"geo {geo}" if geo else "worldwide"
    source = SOURCE_OF.get(name)
    return POPULATIONS[source] if source else UNKNOWN


def comparable(a: str, b: str) -> bool:
    """Do two metrics count the same people?

    The question `scorecards.gap` raises and does not answer. It is exposed so a renderer
    can mark a comparison rather than let a reader assume one; METRICS.md measured that
    mixing populations does not currently move `gap`, because it is a difference of
    within-day percentile RANKS rather than a ratio — but "does not currently" is a
    measurement about five niches in August 2026, not a property.
    """
    return SOURCE_OF.get(a) == SOURCE_OF.get(b) and a in SOURCE_OF
