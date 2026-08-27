"""Measure the relevance rule against the hand labels.

The numbers in `reports/relevance_*.md` come from here, so the report can be
regenerated rather than trusted. Pure enough to test: it takes a session and
returns dataclasses, and prints nothing.

The split is `sha256(video_id) % 2`, deliberately not a random seed: the halves
must not move when the scorer changes, or "measured on held-out data" stops being
true the second time it is run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.clustering.lexicon import event_weights, weights
from nh.clustering.relevance import RELEVANCE_HIGH, score
from nh.db.models import RelevanceLabel, Video


@dataclass(slots=True)
class Band:
    name: str
    n: int = 0
    positive: int = 0

    @property
    def rate(self) -> float | None:
        return self.positive / self.n if self.n else None


@dataclass(slots=True)
class Half:
    name: str
    n: int = 0
    positive: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    bands: list[Band] = field(default_factory=list)

    @property
    def base_rate(self) -> float | None:
        return self.positive / self.n if self.n else None

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None


def _half(video_id: str) -> int:
    return int(hashlib.sha256(video_id.encode()).hexdigest(), 16) % 2


def evaluate(session: Session, threshold: float = RELEVANCE_HIGH) -> tuple[Half, Half, int, int]:
    """`(tuning, held_out, unscorable, unscorable_positive)`."""
    domain, event = weights(), event_weights()
    rows = session.execute(
        sa.select(
            RelevanceLabel.video_id,
            RelevanceLabel.cluster_id,
            RelevanceLabel.label,
            Video.title,
            Video.description,
        ).join(Video, Video.video_id == RelevanceLabel.video_id)
    ).all()
    halves = (Half("tuning"), Half("held-out"))
    for half in halves:
        half.bands = [Band("on-niche"), Band("undecided"), Band("noise")]
    unscorable = unscorable_positive = 0
    for video_id, cluster_id, label, title, description in rows:
        if cluster_id not in domain:
            continue
        result = score(title, description, domain[cluster_id], event)
        if result.value is None:
            unscorable += 1
            unscorable_positive += bool(label)
            continue
        half = halves[_half(video_id)]
        half.n += 1
        half.positive += bool(label)
        if result.value >= threshold:
            half.tp += bool(label)
            half.fp += not label
            band = half.bands[0]
        else:
            half.fn += bool(label)
            band = half.bands[1] if result.value > 0 else half.bands[2]
        band.n += 1
        band.positive += bool(label)
    return halves[0], halves[1], unscorable, unscorable_positive
