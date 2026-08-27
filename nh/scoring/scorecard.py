"""One scorecard per cluster per day.

Slice 2 fills in what is real and leaves the rest NULL. There is no demand side
until Slice 3, so `gap = demand - supply` is not computable, and a placeholder
number that looks like a score is how an uncalibrated figure gets believed — the
exact failure Slice 6's gate exists to prevent.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import FeatureDaily, Scorecard
from nh.db.provenance import Stamp
from nh.db.upsert import upsert

#: Both are stubs, replaced by real composites in Slice 5. Named in
#: docs/METRICS.md under "Composite stubs" so nobody mistakes them for findings.
OPENNESS_FROM = "breakthrough_rate_cohort"
SUPPLY_FROM = "median_views"
DEMAND_FROM = "wiki_weekly_views"


def percentile_rank(values: dict[str, float]) -> dict[str, float]:
    """Rank each cluster's value among the others, 0-1.

    Relative by construction: with five clusters this says "more supply than three
    of the others", not "a lot of supply". A single cluster ranks 0.5 — the middle
    — because with nothing to compare against, any other answer would be inventing
    information.
    """
    if not values:
        return {}
    if len(values) == 1:
        return {next(iter(values)): 0.5}
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    return {cid: i / (len(ordered) - 1) for i, (cid, _) in enumerate(ordered)}


def build(session: Session, day: date, mark: Stamp) -> int:
    rows = session.execute(
        sa.select(
            FeatureDaily.cluster_id,
            FeatureDaily.name,
            FeatureDaily.value,
            FeatureDaily.confidence,
        ).where(
            FeatureDaily.day == day,
            FeatureDaily.name.in_((OPENNESS_FROM, SUPPLY_FROM, DEMAND_FROM)),
        )
    ).all()
    if not rows:
        return 0

    openness = {cid: v for cid, name, v, _ in rows if name == OPENNESS_FROM}
    medians = {cid: v for cid, name, v, _ in rows if name == SUPPLY_FROM and v is not None}
    levels = {cid: v for cid, name, v, _ in rows if name == DEMAND_FROM and v is not None}
    supply = percentile_rank(medians)
    demand = percentile_rank(levels)
    confidences = {(cid, name): c for cid, name, _, c in rows}
    # Every cluster that had features computed gets a card, even if every score on
    # it is NULL. A missing card and an all-NULL card say different things — the
    # first that scoring never ran, the second that it ran and nothing was
    # computable — and only the second is a fact about the niche.
    scored = {cid for cid, _, _, _ in rows}

    def gap(cluster_id: str) -> float | None:
        """Demand rank minus supply rank, in [-1, 1].

        Ranks rather than raw units because pageviews and video views share no
        currency: any exchange rate between them would be a fabricated constant,
        exactly what data rule 6 forbids. What this measures is relative position
        within the day's cluster set — positive means the niche ranks higher on
        audience attention than on incumbent content performance.
        """
        d, s_ = demand.get(cluster_id), supply.get(cluster_id)
        return None if d is None or s_ is None else d - s_

    def gap_confidence(cluster_id: str) -> float | None:
        """The weaker leg bounds the chain."""
        if gap(cluster_id) is None:
            return None
        return min(
            confidences.get((cluster_id, DEMAND_FROM)) or 0.0,
            confidences.get((cluster_id, SUPPLY_FROM)) or 0.0,
        )

    cards = [
        mark(
            Scorecard,
            {
                "cluster_id": cluster_id,
                "day": day,
                # Already 0-1, so it is carried through unmodified rather than
                # rescaled into a number nobody can trace back to the metric.
                "openness": openness.get(cluster_id),
                "supply": supply.get(cluster_id),
                "demand": demand.get(cluster_id),
                "gap": gap(cluster_id),
                "gap_confidence": gap_confidence(cluster_id),
                # NULL until their inputs exist.
                "value": None,
                "sustainability": None,
                "opportunity": None,
                "ci_low": None,
                "ci_high": None,
                "stage": None,
            },
        )
        for cluster_id in sorted(scored)
    ]
    return upsert(session, Scorecard, cards, conflict_on=("cluster_id", "day"))
