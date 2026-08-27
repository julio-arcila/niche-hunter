"""Trivial clustering: one cluster per seed, channels resolved to exactly one.

The unique constraint on (item_type, item_id) is what makes cluster_id a
partition, and every aggregate above assumes a partition (ADR-0013). These tests
pin the resolution rule that makes the constraint satisfiable.
"""

from __future__ import annotations

from datetime import date
from functools import partial

import sqlalchemy as sa

from nh.clustering.trivial import assign, dominant_seed
from nh.db.models import Cluster, ClusterMember, Discovery, NicheSeed, Video
from nh.db.provenance import stamp
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.seeds import apply_seeds

DAY = date(2026, 8, 27)


def _mark():
    return partial(stamp, source="clustering", run_id="test", at=utcnow())


def _discovered(engine, channel_id: str, seed_slug: str, order_by: str, n: int = 1) -> None:
    with session_scope(engine) as s:
        seed_id = s.scalar(sa.select(NicheSeed.id).where(NicheSeed.slug == seed_slug))
        for i in range(n):
            vid = f"{channel_id}-{seed_slug}-{order_by}-{i}"
            s.add(Video(video_id=vid, channel_id=channel_id, source="t", run_id="t"))
            s.add(
                Discovery(
                    video_id=vid,
                    seed_id=seed_id,
                    query="q",
                    order_by=order_by,
                    observed_date=DAY,
                    source="youtube_api",
                    run_id="t",
                )
            )


# -- the resolution rule, pure ----------------------------------------------


def test_more_date_discovered_videos_wins():
    """order=date is evidence the channel produces this niche's content."""
    resolved = dominant_seed([("ch", 1, 6, 6), ("ch", 2, 1, 9)])
    assert resolved["ch"][0] == 1


def test_viewcount_volume_does_not_override_date_evidence():
    """order=viewCount selects on success and must not decide what a channel is
    about — otherwise one viral video reassigns the channel's whole identity."""
    resolved = dominant_seed([("ch", 1, 3, 3), ("ch", 2, 0, 50)])
    assert resolved["ch"][0] == 1


def test_a_full_tie_resolves_to_the_lowest_seed_id():
    """Arbitrary but deterministic: re-running must never reshuffle memberships."""
    assert dominant_seed([("ch", 7, 2, 2), ("ch", 3, 2, 2)])["ch"][0] == 3


def test_confidence_is_the_winning_seeds_share(engine=None):
    resolved = dominant_seed([("ch", 1, 3, 3), ("ch", 2, 1, 1)])
    assert resolved["ch"][1] == 0.75


def test_an_unambiguous_channel_scores_full_confidence():
    assert dominant_seed([("ch", 1, 5, 5)])["ch"][1] == 1.0


# -- the writer --------------------------------------------------------------


def test_one_cluster_per_active_seed_even_with_no_members(engine):
    apply_seeds(engine)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        assert s.scalar(sa.select(sa.func.count()).select_from(Cluster)) == 5


def test_every_discovered_channel_lands_in_exactly_one_cluster(engine):
    apply_seeds(engine)
    _discovered(engine, "ch1", "aviation-disasters", "date", 3)
    _discovered(engine, "ch1", "maritime-disasters", "date", 1)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        rows = s.scalars(sa.select(ClusterMember.cluster_id)).all()
    assert rows == ["aviation-disasters"]


def test_rerunning_moves_a_channel_rather_than_violating_the_unique_key(engine):
    apply_seeds(engine)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
    _discovered(engine, "ch1", "maritime-disasters", "date", 5)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        rows = s.scalars(sa.select(ClusterMember.cluster_id)).all()
    assert rows == ["maritime-disasters"]  # moved, not duplicated


def test_membership_carries_provenance(engine):
    apply_seeds(engine)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        row = s.scalars(sa.select(ClusterMember)).one()
    assert row.source == "clustering"
    assert row.run_id == "test"
