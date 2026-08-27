"""The blind sample that turns the relevance rule into a measured claim.

Without labels, a threshold is a number chosen because the output looked reasonable,
and `supply.median_views` would rest on it. docs/METRICS.md already carries this
warning for `winner_age_years` — "3 was chosen because it maximised spread across
five niches. Do not reintroduce a cutoff" — and the same trap is available here in a
larger size, because a relevance filter can manufacture almost any ranking you tune
it toward.

**What "blind" can and cannot mean.** The plan said to hide the niche as well as the
score. That is not possible: the question *is* "is this video about this niche", so
the niche has to be on screen or there is nothing to answer. What is hidden is the
scorer's output and its decision, and the sample is interleaved across niches in
randomised order so the labeller cannot fall into judging one niche at a time and
drifting. Those are the mitigations that actually apply; the report says so rather
than claiming a blindness it does not have.

Export/import rather than a terminal prompt: labelling a few hundred items is
editor work, the file is reviewable and diffable, and an interactive loop would be
the one part of this pipeline with no test.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.db.models import Cluster, ClusterMember, RelevanceLabel, Video
from nh.db.session import session_scope
from nh.db.upsert import upsert

#: Characters of description shown. Enough to judge, short enough to read.
DESCRIPTION_CHARS = 600


@dataclass(slots=True)
class SampleResult:
    written: int
    path: Path
    per_cluster: dict[str, int]


def stratified_sample(engine: Engine | None, n_per_cluster: int, seed: int) -> list[dict]:
    """`n_per_cluster` videos from each active cluster, interleaved and shuffled.

    Stratified because a proportional sample would give court-cases 16% of the rows
    and measure precision mostly on the largest niche. Seeded because a sample you
    cannot reproduce is not evidence.
    """
    rng = random.Random(seed)
    picked: list[dict] = []
    with session_scope(engine) as session:
        clusters = list(
            session.scalars(
                sa.select(Cluster.cluster_id).where(Cluster.active).order_by(Cluster.cluster_id)
            )
        )
        labels = dict(session.execute(sa.select(Cluster.cluster_id, Cluster.label)).all())
        for cluster_id in clusters:
            rows = session.execute(
                sa.select(Video.video_id, Video.title, Video.description)
                .join(
                    ClusterMember,
                    sa.and_(
                        ClusterMember.item_id == Video.channel_id,
                        ClusterMember.item_type == "channel",
                        ClusterMember.cluster_id == cluster_id,
                    ),
                )
                .order_by(Video.video_id)
            ).all()
            for video_id, title, description in rng.sample(rows, min(n_per_cluster, len(rows))):
                picked.append(
                    {
                        "video_id": video_id,
                        "niche": labels.get(cluster_id) or cluster_id,
                        "cluster_id": cluster_id,
                        "title": title,
                        "description": (description or "")[:DESCRIPTION_CHARS],
                        # The labeller fills this in: true, false, or null to skip.
                        "label": None,
                    }
                )
    rng.shuffle(picked)
    return picked


def export_sample(path: Path, engine: Engine | None = None, *, per_cluster: int, seed: int):
    """Write the blind sample as JSONL, one video per line."""
    rows = stratified_sample(engine, per_cluster, seed)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    per: dict[str, int] = {}
    for row in rows:
        per[row["cluster_id"]] = per.get(row["cluster_id"], 0) + 1
    return SampleResult(len(rows), path, per)


def import_labels(path: Path, engine: Engine | None = None, *, labeller: str) -> int:
    """Read a labelled JSONL back. `label: null` means skipped, and is not stored.

    There is no "unsure" state on purpose: a judgement that cannot be made is left
    unwritten rather than recorded as a third value that every later calculation
    would then have to decide how to treat.
    """
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("label") is None:
            continue
        rows.append(
            {
                "video_id": record["video_id"],
                "cluster_id": record["cluster_id"],
                "label": bool(record["label"]),
                "labeller": labeller,
                "notes": record.get("notes"),
            }
        )
    if not rows:
        return 0
    with session_scope(engine) as session:
        return upsert(
            session,
            RelevanceLabel,
            rows,
            conflict_on=["video_id"],
            update=["cluster_id", "label", "labeller", "notes"],
        )
