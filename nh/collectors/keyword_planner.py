"""Google Ads Keyword Planner — demand scale and advertiser value.

Port target for `legacy/niche_hunter_kp.py`. Not implemented yet — `nh nightly` reports this
source as not-ported and moves on.

What this adds that nothing else free does: absolute monthly search volume
(Trends gives only shape), top-of-page bids as the best free RPM proxy, and
per-country runs for the tier-1 CPC ratio.

Caveats to keep in docs/METRICS.md: this is Google SEARCH data, not YouTube;
close variants collapse plurals and misspellings; long-tail terms often have no
bid data, so aggregate at niche level, never per keyword. Cache 7 days.
"""

from __future__ import annotations

from collections.abc import Iterable

from nh.collectors.base import Batch, Collector, NotPorted, Raw


class KeywordPlannerCollector(Collector):
    source = "keyword_planner"
    description = "Google Ads Keyword Planner — demand scale and advertiser value."
    quota_budget = None

    def fetch(self) -> Iterable[Raw]:
        raise NotPorted("port legacy/niche_hunter_kp.py into fetch(); see nh/collectors/base.py")

    def normalize(self, raw: Raw) -> Batch:
        raise NotPorted(
            "port legacy/niche_hunter_kp.py into normalize(); see nh/collectors/base.py"
        )
