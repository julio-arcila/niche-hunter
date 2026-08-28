"""The clustering phase: channel identity, then per-video topicality.

Two questions, deliberately kept apart and answered by different code:

* **Identity** — which niche does a *channel* belong to? Resolved from discovery
  lineage, unchanged since ADR-0013, in `nh/clustering/trivial.py`.
* **Topicality** — is a given *video* actually about that niche? Asked for the
  first time in Slice 4, by `nh/clustering/relevance.py`.

Before this, videos inherited their channel's cluster and the second question was
never asked, which silently answered it "yes" for everything. Measured on
2026-08-27 that answer was wrong for 80% of the corpus, and every `supply.*` and
`money.*` number was computed over the result.

The phase name stays `"clustering"`: it is the `job_runs.source` value on every
historical row and `nh/jobs/status.py` gates the nightly on it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.clustering.lexicon import LEXICON_VERSION, event_weights, weights
from nh.clustering.relevance import RELEVANCE_HIGH, RELEVANCE_LOW, score
from nh.clustering.trivial import assign_channels
from nh.db.models import Cluster, ClusterMember, NicheSeed, Video
from nh.db.provenance import Stamp
from nh.db.upsert import upsert

log = logging.getLogger(__name__)


def lexicon_gaps(session: Session) -> tuple[list[str], list[str]]:
    """`(active seeds with no lexicon, lexicons with no active seed)`.

    The first list is the dangerous one and it is not hypothetical: ADR-0024 split
    `court-cases` into `landmark-court-cases` and `true-crime-trials`, both seeds were
    activated, and **neither ever got a lexicon**. `assign_videos` skips a cluster it
    cannot score, so their videos were never scored, their relevance stayed NULL,
    `on_niche_join` excluded them, and `retire_empty` retired both clusters on their
    creation day. Nothing anywhere said why. Measured 2026-08-28, the two were still
    spending 600 YouTube search units a night -- 6.3% of the budget -- on niches that
    could not produce a single scored video.

    The second list is harmless (a retired niche keeping its terms) and is reported
    only so the pair reads as one question rather than two.
    """
    slugs = set(session.scalars(sa.select(NicheSeed.slug).where(NicheSeed.active)))
    known = set(weights())
    return sorted(slugs - known), sorted(known - slugs)


#: Videos scored per write. The corpus is ~15k rows and grows with the channel
#: set, so it is streamed rather than assembled in one list.
CHUNK = 2_000


def assign(session: Session, day: date, mark: Stamp) -> int:
    """Channels, then videos, then the per-cluster tallies."""
    written = assign_channels(session, day, mark)
    written += assign_videos(session, mark)
    retire_empty(session, day)
    return written


def _video_rows(session: Session) -> Iterator[tuple[str, str, str | None, str | None]]:
    """`(cluster_id, video_id, title, description)` for every video of a member channel.

    Joined through channel membership rather than through `videos.channel_id` alone,
    so a video whose channel was never resolved to a niche gets no row at all —
    absent rather than guessed.
    """
    yield from session.execute(
        sa.select(ClusterMember.cluster_id, Video.video_id, Video.title, Video.description)
        .join(ClusterMember, ClusterMember.item_id == Video.channel_id)
        .where(ClusterMember.item_type == "channel", ClusterMember.is_noise.is_(False))
        .order_by(Video.video_id)
    ).yield_per(CHUNK)


def assign_videos(session: Session, mark: Stamp) -> int:
    """One membership row per video, carrying its relevance and the evidence for it.

    `is_noise` records only the *decided* off-niche case. An unscorable video keeps
    `relevance = NULL` and `is_noise = False`, because "we could not read this" and
    "this is not about the niche" are different claims and only one of them is a
    finding (data rule 7). The on-niche cut lives at read time in
    `nh/features/inputs.py`, so moving a threshold is a query rather than a rewrite
    of every stored row.
    """
    domain, event = weights(), event_weights()
    # Loud, once per run, before any row is written. The skip below is correct --
    # there is nothing to score a video against -- but silently skipping an ACTIVE
    # niche is how two of them sat inert for a day while still spending quota.
    unscorable, _ = lexicon_gaps(session)
    for slug in unscorable:
        log.warning(
            "active seed %r has no lexicon: its videos cannot be scored, its cluster "
            "will be retired as empty, and its discovery quota is being spent for "
            "nothing. Add it to nh/clustering/lexicon.py::LEXICONS or deactivate the "
            "seed.",
            slug,
        )
    rows, written = [], 0
    skipped: set[str] = set()
    for cluster_id, video_id, title, description in _video_rows(session):
        if cluster_id not in domain:
            skipped.add(cluster_id)
            continue
        result = score(title, description, domain[cluster_id], event)
        rows.append(
            mark(
                ClusterMember,
                {
                    "cluster_id": cluster_id,
                    "item_type": "video",
                    "item_id": video_id,
                    "relevance": result.value,
                    "is_noise": result.value is not None and result.value <= RELEVANCE_LOW,
                    "detail": _detail(result),
                },
            )
        )
        if len(rows) >= CHUNK:
            written += _flush(session, rows)
            rows = []
    if skipped:
        log.warning("skipped %d cluster(s) with no lexicon: %s", len(skipped), sorted(skipped))
    return written + _flush(session, rows)


def _detail(result) -> dict:
    """The evidence, small enough to store on every row.

    Only the strongest few matches: this lands on ~15k rows a night, and the point
    is that a reviewer can see *why* a video was included, not that the row carries
    a complete audit of a bag-of-words match.
    """
    detail = {"lexicon": LEXICON_VERSION, **result.detail}
    if result.reason:
        detail["reason"] = result.reason
    if result.matched:
        top = sorted(result.matched.items(), key=lambda kv: -kv[1])[:6]
        detail["matched"] = [term for term, _ in top]
    return detail


def _flush(session: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    return upsert(
        session,
        ClusterMember,
        rows,
        conflict_on=("item_type", "item_id"),
        update=["cluster_id", "relevance", "detail", "is_noise", "source", "run_id", "at"],
    )


def retire_empty(session: Session, day: date) -> None:
    """Retire clusters whose seed was switched off, or that hold no on-niche video.

    Two reasons a cluster stops being live, and the seed one is not optional: when a
    seed is deactivated — or split into two, as `court-cases` was in Slice 5 —
    `assign_channels` simply stops upserting its cluster, which leaves the old row
    `active=True` and still generating a `features_daily` row and a percentile rank
    every night, forever. `apply_seeds` deliberately never deactivates a seed it no
    longer sees, because a typo in the literal would otherwise silently kill a
    niche; so the seed is switched off by hand and this is what notices.

    Reactivation matters too — a niche that goes quiet for a week must come back on
    its own, not need a hand.

    Retirement rather than deletion: `features_daily` and `scorecards` keep rows
    keyed on `cluster_id`, and deleting the cluster would orphan history that is
    the only thing making a past score readable. Reactivation matters too — a niche
    that goes quiet for a week must come back on its own, not need a hand.
    """
    live = set(
        session.scalars(
            sa.select(ClusterMember.cluster_id).where(
                ClusterMember.item_type == "video",
                ClusterMember.relevance >= RELEVANCE_HIGH,
            )
        )
    )
    seeded = set(
        session.scalars(
            sa.select(Cluster.cluster_id)
            .join(NicheSeed, NicheSeed.id == Cluster.seed_id)
            .where(NicheSeed.active)
        )
    )
    for cluster_id, active in session.execute(sa.select(Cluster.cluster_id, Cluster.active)).all():
        wanted = cluster_id in live and cluster_id in seeded
        if wanted != active:
            session.execute(
                sa.update(Cluster)
                .where(Cluster.cluster_id == cluster_id)
                .values(active=wanted, retired_on=None if wanted else day)
            )
    session.commit()
