"""What the nightly job knows how to run.

Specs are declarative and importable without pulling in optional dependencies
(trendspy, praw, google-ads), so `nh nightly --dry-run` works on a bare install.
The class is only imported when a collector actually runs.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True, slots=True)
class CollectorSpec:
    source: str
    dotted: str
    cadence: str
    prototype: str
    ported: bool
    notes: str

    def load(self) -> type:
        module_path, _, cls_name = self.dotted.partition(":")
        return getattr(import_module(module_path), cls_name)


#: Order matters — the nightly job runs these top to bottom. Discovery feeds
#: enrichment feeds RSS; Trends and Reddit expand the seed set for tomorrow.
#: youtube_api leads because only it can produce a channel list: on day 1 RSS
#: would otherwise poll nothing, and every later night a freshly discovered
#: channel would wait 24h for its first velocity reading (ADR-0007).
REGISTRY: tuple[CollectorSpec, ...] = (
    CollectorSpec(
        source="youtube_api",
        dotted="nh.collectors.youtube_api:YouTubeApiCollector",
        cadence="nightly",
        prototype="legacy/niche_hunter_yt.py",
        ported=True,
        notes="10k units/day. search.list costs 100; everything else 1 per 50 ids. Discovery + enrichment only in S1.",
    ),
    CollectorSpec(
        source="youtube_rss",
        dotted="nh.collectors.youtube_rss:YouTubeRssCollector",
        cadence="nightly + hourly for hot channels",
        prototype="legacy/niche_hunter_rss.py",
        ported=True,
        notes="Zero quota. The one series that cannot be backfilled — never let it lapse.",
    ),
    CollectorSpec(
        source="trends",
        dotted="nh.collectors.trends:TrendsCollector",
        cadence="nightly",
        prototype="legacy/niche_hunter_trends.py",
        ported=False,
        notes="Unofficial endpoint. Anchor-scale every batch or the numbers do not compare.",
    ),
    CollectorSpec(
        source="reddit",
        dotted="nh.collectors.reddit:RedditCollector",
        cadence="nightly",
        prototype="legacy/niche_hunter_reddit.py",
        ported=False,
        notes="Blocked on Responsible Builder Policy approval; skipped until credentials exist.",
    ),
    CollectorSpec(
        source="keyword_planner",
        dotted="nh.collectors.keyword_planner:KeywordPlannerCollector",
        cadence="weekly (cached 7 days)",
        prototype="legacy/niche_hunter_kp.py",
        ported=False,
        notes="Needs Google Ads Basic access. UI CSV export is the fallback path.",
    ),
)

_BY_SOURCE = {spec.source: spec for spec in REGISTRY}


def iter_specs(only: list[str] | None = None) -> Iterator[CollectorSpec]:
    if not only:
        yield from REGISTRY
        return
    unknown = set(only) - set(_BY_SOURCE)
    if unknown:
        raise KeyError(f"unknown collector(s): {', '.join(sorted(unknown))}")
    yield from (spec for spec in REGISTRY if spec.source in only)


def get_collector(source: str) -> type:
    return _BY_SOURCE[source].load()
