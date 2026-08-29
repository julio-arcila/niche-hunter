"""Trivial clustering: one cluster per seed, channels resolved to exactly one.

The unique constraint on (item_type, item_id) is what makes cluster_id a
partition, and every aggregate above assumes a partition (ADR-0013). These tests
pin the resolution rule that makes the constraint satisfiable.
"""

from __future__ import annotations

from datetime import date
from functools import partial

import sqlalchemy as sa

from nh.clustering.phase import assign
from nh.clustering.trivial import assign_channels, dominant_seed
from nh.db.models import Cluster, ClusterMember, Discovery, NicheSeed, Video
from nh.db.provenance import stamp
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.seeds import SEEDS, apply_seeds

DAY = date(2026, 8, 27)

#: The clustering tests own their seed set instead of reading production's.
#:
#: They used to filter `SEEDS` by `active`, which coupled them to an operational
#: decision they have no stake in — and that coupling broke them three times: when
#: `landmark-court-cases` was retired (ADR-0028), when the eleven-domain pivot landed
#: (ADR-0033), and again when discovery was retired for the five disaster niches
#: (ADR-0039), which left ZERO active seeds and so zero clusters to build.
#:
#: What these tests actually need is two niches that have a lexicon, are active in the
#: test database, and are stable across whatever production is doing tonight. Slugs
#: still come from the real set because `LEXICONS` is keyed on them and relevance
#: scoring is real here — but `active` is forced True locally, which is the bit that
#: was never any of production's business.
#: The two the rest of this file names in its fixtures and scoring titles — an
#: aviation title must score against the aviation lexicon for the assertions to mean
#: anything, so the slugs are not interchangeable.
_PRIMARY, _SECONDARY = "aviation-disasters", "maritime-disasters"
LIVE_SEEDS = tuple(
    {**seed, "active": True} for seed in SEEDS if seed["slug"] in (_PRIMARY, _SECONDARY)
)


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


def _channels():
    """Channel membership only. Slice 4 added `item_type='video'` rows to the same
    table, so a bare select over it is no longer a select over channels."""
    return sa.select(ClusterMember.cluster_id).where(ClusterMember.item_type == "channel")


def test_one_cluster_per_active_seed_even_with_no_members(engine):
    apply_seeds(engine, LIVE_SEEDS)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        assert s.scalar(sa.select(sa.func.count()).select_from(Cluster)) == len(LIVE_SEEDS)


def test_every_discovered_channel_lands_in_exactly_one_cluster(engine):
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 3)
    _discovered(engine, "ch1", "maritime-disasters", "date", 1)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        rows = s.scalars(_channels()).all()
    assert rows == ["aviation-disasters"]


def test_rerunning_moves_a_channel_rather_than_violating_the_unique_key(engine):
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
    _discovered(engine, "ch1", "maritime-disasters", "date", 5)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        rows = s.scalars(_channels()).all()
    assert rows == ["maritime-disasters"]  # moved, not duplicated


def test_membership_carries_provenance(engine):
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        row = s.scalars(sa.select(ClusterMember).where(ClusterMember.item_type == "channel")).one()
    assert row.source == "clustering"
    assert row.run_id == "test"


# -- video membership (Slice 4) ----------------------------------------------


def _video(engine, video_id, channel_id, title, description=None):
    from nh.db.models import Video
    from nh.db.types import utcnow

    with session_scope(engine) as s:
        s.add(
            Video(
                video_id=video_id,
                channel_id=channel_id,
                title=title,
                description=description,
                source="youtube_rss",
                run_id="test",
                at=utcnow(),
            )
        )


def _relevance(engine, video_id):
    with session_scope(engine) as s:
        return s.scalars(
            sa.select(ClusterMember).where(
                ClusterMember.item_type == "video", ClusterMember.item_id == video_id
            )
        ).one()


def test_every_video_of_a_member_channel_gets_a_decision(engine):
    """Slice 4's exit criterion: a cluster_id or an explicit reason, never silence."""
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    _video(engine, "v1", "ch1", "Plane crashed on the runway")
    _video(engine, "v2", "ch1", "Maruti Grand Vitara maintenance cost")
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        rows = s.scalars(sa.select(ClusterMember).where(ClusterMember.item_type == "video")).all()
    # `_discovered` also creates a video, so this is a superset check by design.
    assert {"v1", "v2"} <= {r.item_id for r in rows}
    assert all(r.cluster_id == "aviation-disasters" for r in rows)


def test_an_on_niche_video_scores_and_is_not_noise(engine):
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    _video(engine, "v1", "ch1", "Plane crashed on the runway after engine failure")
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
    row = _relevance(engine, "v1")
    assert row.relevance is not None and row.relevance >= 0.55
    assert row.is_noise is False


def test_an_off_niche_video_is_marked_noise(engine):
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    _video(engine, "v1", "ch1", "Maruti Grand Vitara maintenance cost review")
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
    row = _relevance(engine, "v1")
    assert row.relevance == 0.0
    assert row.is_noise is True


def test_an_unscorable_video_is_null_not_noise(engine):
    """ "We could not read this" and "this is not about the niche" are different
    claims, and only one of them is a finding (data rule 7)."""
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    _video(engine, "v1", "ch1", "क्या पंखा आपको और ज्यादा गरमी का एहसास कराता है")
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
    row = _relevance(engine, "v1")
    assert row.relevance is None
    assert row.is_noise is False
    assert "unscorable" in row.detail["reason"]


def test_the_decision_carries_its_evidence(engine):
    """Production criterion 5: a displayed number reaches its input rows."""
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    _video(engine, "v1", "ch1", "Plane crashed on the runway")
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
    detail = _relevance(engine, "v1").detail
    assert detail["lexicon"]
    assert detail["domain"] > 0 and detail["event"] > 0
    assert "crash" in " ".join(detail["matched"])


def test_a_cluster_with_no_on_niche_video_is_retired_not_deleted(engine):
    """features_daily is keyed on cluster_id; deleting the cluster would orphan the
    history that makes a past score readable."""
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    _video(engine, "v1", "ch1", "Maruti Grand Vitara maintenance cost review")
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        clusters = dict(s.execute(sa.select(Cluster.cluster_id, Cluster.active)).all())
    assert clusters["aviation-disasters"] is False
    assert len(clusters) == len(LIVE_SEEDS)  # retired, still present


def test_a_cluster_reactivates_when_it_gains_an_on_niche_video(engine):
    """A niche that goes quiet for a week must come back on its own."""
    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    _video(engine, "v1", "ch1", "Maruti Grand Vitara maintenance cost review")
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
    _video(engine, "v2", "ch1", "Plane crashed on the runway after engine failure")
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        active = s.scalar(
            sa.select(Cluster.active).where(Cluster.cluster_id == "aviation-disasters")
        )
    assert active is True


def test_a_cluster_whose_seed_was_switched_off_is_retired(engine):
    """`apply_seeds` never deactivates a seed it stops seeing — a typo in the
    literal would otherwise silently kill a niche — so a seed is switched off by
    hand, and this is what notices. Without it the old cluster keeps producing a
    features_daily row and a percentile rank every night, forever."""
    from nh.db.models import NicheSeed

    apply_seeds(engine, LIVE_SEEDS)
    _discovered(engine, "ch1", "aviation-disasters", "date", 1)
    _video(engine, "v1", "ch1", "Plane crashed on the runway after engine failure")
    with session_scope(engine) as s:
        assign(s, DAY, _mark())
        assert (
            s.scalar(sa.select(Cluster.active).where(Cluster.cluster_id == "aviation-disasters"))
            is True
        )

        s.execute(
            sa.update(NicheSeed).where(NicheSeed.slug == "aviation-disasters").values(active=False)
        )
        s.commit()
        assign(s, DAY, _mark())
        row = s.execute(
            sa.select(Cluster.active, Cluster.retired_on).where(
                Cluster.cluster_id == "aviation-disasters"
            )
        ).one()
    assert row.active is False
    assert row.retired_on == DAY


# --------------------------------------------------------------------------
# Seed / lexicon coupling
# --------------------------------------------------------------------------


def test_an_active_seed_without_a_lexicon_is_reported(engine):
    """The court-cases regression, as a guard.

    ADR-0024 split a seed in two, both successors were activated, and neither got a
    lexicon. `assign_videos` skips a cluster it cannot score, so both sat inert --
    videos unscored, clusters retired as empty, 600 YouTube search units a night
    spent on nothing -- and the pipeline said not one word about it for a day.
    """
    from nh.clustering.phase import lexicon_gaps
    from nh.db.session import get_sessionmaker

    with session_scope(engine) as s:
        s.add(NicheSeed(slug="no-lexicon-here", label="Orphan", keywords=[], active=True))

    unscorable, _ = lexicon_gaps(get_sessionmaker(engine)())

    assert "no-lexicon-here" in unscorable


def test_a_deactivated_seed_keeps_its_lexicon_harmlessly(engine):
    """The inverse mismatch is not an error. Measured 2026-08-28: removing the
    retired `court-cases` lexicon changes the weights of the other four niches by
    nothing at all, because the lexicons are term-disjoint -- so a retired niche
    keeping its terms costs no accuracy elsewhere."""
    from nh.clustering.phase import lexicon_gaps
    from nh.db.session import get_sessionmaker

    unscorable, orphaned = lexicon_gaps(get_sessionmaker(engine)())

    assert unscorable == []
    assert "aviation-disasters" in orphaned  # this fixture defines no seeds


def test_inactive_seed_lineage_does_not_shadow_an_active_one(engine):
    """The freeze that kept 110 channels in a retired cluster.

    Dominance used to rank over every seed's lineage and discard the winner
    afterwards if it was inactive — so a channel whose majority history came from a
    deactivated seed was dropped from the loop and kept its stale membership row
    forever, however much lineage an active seed accumulated. Here the dead seed
    out-numbers the live one five to one; the live one must still win.
    """
    with session_scope(engine) as s:
        s.add(NicheSeed(id=1, slug="dead-niche", label="Dead", keywords=[], active=False))
        s.add(NicheSeed(id=2, slug="live-niche", label="Live", keywords=[], active=True))
    _discovered(engine, "UCa", "dead-niche", "date", n=5)
    _discovered(engine, "UCa", "live-niche", "date", n=1)

    with session_scope(engine) as s:
        assign_channels(s, DAY, _mark())

    with session_scope(engine) as s:
        cluster_id = s.scalar(
            sa.select(ClusterMember.cluster_id).where(ClusterMember.item_type == "channel")
        )
    assert cluster_id == "live-niche"


def test_a_channel_with_only_dead_lineage_gets_no_membership(engine):
    """The other side: no active seed claims it, so nothing is invented. It keeps
    whatever membership it already had, and `lexicon_gaps` / `retire_empty` describe
    that state honestly rather than a guess being written over it."""
    with session_scope(engine) as s:
        s.add(NicheSeed(id=1, slug="dead-niche", label="Dead", keywords=[], active=False))
        s.add(NicheSeed(id=2, slug="live-niche", label="Live", keywords=[], active=True))
    _discovered(engine, "UCa", "dead-niche", "date", n=3)

    with session_scope(engine) as s:
        assign_channels(s, DAY, _mark())

    with session_scope(engine) as s:
        rows = list(s.scalars(sa.select(ClusterMember.item_id)))
    assert rows == []
