"""Google Trends via trendspy — demand shape, seed expansion.

Port target for `legacy/niche_hunter_trends.py`. Not implemented yet — `nh nightly` reports this
source as not-ported and moves on.

Hard constraints of the source — design around them, do not fight them:
  * Values are normalized 0-100 PER REQUEST. Two requests are never comparable
    unless both contain the same anchor keyword. anchor_scaled_interest() in the
    prototype is the fix; it belongs in nh/features/demand.py, not here.
  * Max 5 terms per request -> 1 anchor + 4 targets per batch.
  * No absolute volumes — that is what keyword_planner is for.
  * Sampled: re-running jitters +/-5 points. Smooth, do not overfit.
  * Prefer topic mids (/m/0abc) over raw strings; they aggregate spellings.
  * Unofficial endpoint: expect 429s. Cache everything, 2.5s minimum gap.
"""

from __future__ import annotations

from collections.abc import Iterable

from nh.collectors.base import Batch, Collector, NotPorted, Raw


class TrendsCollector(Collector):
    source = "trends"
    description = "Google Trends via trendspy — demand shape, seed expansion."
    quota_budget = None

    def fetch(self) -> Iterable[Raw]:
        raise NotPorted(
            "port legacy/niche_hunter_trends.py into fetch(); see nh/collectors/base.py"
        )

    def normalize(self, raw: Raw) -> Batch:
        raise NotPorted(
            "port legacy/niche_hunter_trends.py into normalize(); see nh/collectors/base.py"
        )
