"""Reddit via PRAW — unmet demand, supply gaps, RPM disclosures.

Port target for `legacy/niche_hunter_reddit.py`. Not implemented yet — `nh nightly` reports this
source as not-ported and moves on.

ACCESS REALITY (2026): the Responsible Builder Policy requires approval BEFORE
any API access; self-service registration closed in late 2025. Until credentials
exist, Settings.configured('reddit') is False and the nightly job records this
source as skipped.

What Reddit contributes that YouTube and Trends cannot:
  * Question mining — unmet demand phrased as questions, upvote-weighted.
  * 'Recommend a channel' threads that got NO YouTube link back: a documented
    supply gap with a real person attached. This is supply_signals() in the
    prototype and it is the sharpest single signal in the whole source.
  * RPM/CPM disclosures in creator subs — calibration points for the money model.
"""

from __future__ import annotations

from collections.abc import Iterable

from nh.collectors.base import Batch, Collector, NotPorted, Raw


class RedditCollector(Collector):
    source = "reddit"
    description = "Reddit via PRAW — unmet demand, supply gaps, RPM disclosures."
    quota_budget = None

    def fetch(self) -> Iterable[Raw]:
        raise NotPorted(
            "port legacy/niche_hunter_reddit.py into fetch(); see nh/collectors/base.py"
        )

    def normalize(self, raw: Raw) -> Batch:
        raise NotPorted(
            "port legacy/niche_hunter_reddit.py into normalize(); see nh/collectors/base.py"
        )
