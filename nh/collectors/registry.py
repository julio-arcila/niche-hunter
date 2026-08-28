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
    #: A source a human imports by hand rather than one the nightly can run. It is
    #: ported (the code exists and works) but has no network fetch to schedule, so
    #: `nh nightly` must neither run it nor count its absence as a failure. Keyword
    #: Planner is the first: its data arrives as a CSV someone downloads (ADR-0030).
    manual: bool = False
    #: The exact command that imports a manual source, printed by `nh nightly
    #: --dry-run`. Stated rather than derived from `source`, because a reason line
    #: telling the operator to run a command that does not exist is worse than no
    #: reason at all.
    manual_cmd: str = ""

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
        source="wikipedia",
        dotted="nh.collectors.wikipedia:WikipediaCollector",
        cadence="nightly",
        prototype="(none — new in Slice 3)",
        ported=True,
        notes="Primary demand signal. Absolute counts, agent=user, 2-day maturation lag, "
        "backfills to 2015 on first run.",
    ),
    CollectorSpec(
        source="trends",
        dotted="nh.collectors.trends:TrendsCollector",
        cadence="nightly",
        prototype="legacy/niche_hunter_trends.py",
        ported=True,
        notes="Shape only — one term per request, no anchor (ADR-0015). related_queries/topics are reachable via the referer header but unused: vocabulary, not level (ADR-0032).",
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
        cadence="manual (UI CSV export)",
        prototype="legacy/niche_hunter_kp.py",
        ported=True,
        manual=True,
        manual_cmd="nh kp ingest <csv>",
        notes=(
            "UI CSV export — no API, no token, no application (ADR-0029/0030). "
            "Run `nh kp ingest <csv>`. Measured 2026-08-28: the export carries exact "
            "values where the UI shows only ranges."
        ),
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
