"""Every metric must exclude a noise member. One test per metric, on purpose.

Nothing writes `is_noise=True` yet, so today these all pass trivially — which is
exactly why they are worth having now. Membership resolution was hand-copied at six
join sites and four of them had silently dropped the `is_noise` filter; the bug was
invisible precisely because no noise existed. It would have become a live corruption
the moment Slice 4 wrote the first noise row, and the corrupted number would have
been `confidence`, which is what bounds trust in every other number.

`nh.features.inputs.member_join` is the structural fix. These are the test that
notices if a seventh join site is written by hand.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from nh.db.models import ClusterMember, Video
from nh.db.session import session_scope
from nh.features import money, openness, supply
from nh.features.inputs import (
    BALLAST_DECIDED,
    _ballast_channels,
    cohort,
    date_discovered_channels,
    eligible_videos,
    latest_subs,
    member_channels,
    numerator_coverage,
    relevance_coverage,
)
from tests.conftest_features import CLUSTER, DAY, _at, add_channel, make_cluster


def _world(engine):
    """One real member and one noise member, identical in every other respect.

    Identical on purpose: any metric that counts the noise channel produces a
    different number from one that does not, so a leak cannot hide in rounding.
    """
    make_cluster(engine)
    add_channel(engine, "UCreal", subs=1_000, videos=6, views=1_000)
    add_channel(engine, "UCnoise", subs=1_000, videos=6, views=1_000_000, noise=True)


# -- the shared resolvers ----------------------------------------------------


def test_member_channels_excludes_noise(engine):
    _world(engine)
    with session_scope(engine) as s:
        assert member_channels(s, CLUSTER) == ["UCreal"]


def test_eligible_videos_excludes_noise(engine):
    _world(engine)
    with session_scope(engine) as s:
        assert set(eligible_videos(s, CLUSTER, DAY)) == {"UCreal"}


def test_latest_subs_excludes_noise(engine):
    _world(engine)
    with session_scope(engine) as s:
        assert set(latest_subs(s, CLUSTER, DAY)) == {"UCreal"}


def test_date_discovered_channels_excludes_noise(engine):
    _world(engine)
    with session_scope(engine) as s:
        assert date_discovered_channels(s, CLUSTER) == {"UCreal"}


def test_cohort_excludes_noise(engine):
    _world(engine)
    with session_scope(engine) as s:
        assert set(cohort(s, CLUSTER, DAY)) == {"UCreal"}


# -- the metrics -------------------------------------------------------------


def test_uploads_per_week_excludes_noise(engine):
    """Recent uploads, so they land inside the 28-day window."""
    make_cluster(engine)
    add_channel(engine, "UCreal", videos=4, age_days=1)
    add_channel(engine, "UCnoise", videos=4, age_days=1, noise=True)
    with session_scope(engine) as s:
        result = supply.uploads_per_week(s, CLUSTER, DAY)
    # UCreal alone: 4 uploads over its 5-day observed span = 4/(5/7). The noise
    # channel's 4 are ignored — included, the value would double.
    assert result.value == pytest.approx(5.6)


def test_median_views_excludes_noise(engine):
    _world(engine)
    with session_scope(engine) as s:
        result = supply.median_views(s, CLUSTER, DAY)
    assert result.value == 1_000  # not pulled toward the noise channel's 1,000,000


def test_midroll_eligible_share_excludes_noise(engine):
    make_cluster(engine)
    add_channel(engine, "UCreal", videos=4, age_days=1, is_short=False)
    add_channel(engine, "UCnoise", videos=4, age_days=1, is_short=True, noise=True)
    with session_scope(engine) as s:
        result = money.midroll_eligible_share(s, CLUSTER, DAY)
    assert result.value == 1.0  # all four real videos are long-form


def test_openness_metrics_exclude_noise(engine):
    _world(engine)
    with session_scope(engine) as s:
        assert openness.breakthrough_rate_cohort(s, CLUSTER, DAY).inputs_n == 1
        assert openness.views_per_sub(s, CLUSTER, DAY).inputs_n == 1


# -- the property the clamp protects -----------------------------------------


def test_supply_confidence_never_exceeds_one(engine):
    """Coverage is `contributing / universe`. Both sides must exclude noise, or a
    noise channel counts in the numerator and not the denominator."""
    _world(engine)
    with session_scope(engine) as s:
        for result in (
            supply.uploads_per_week(s, CLUSTER, DAY),
            supply.median_views(s, CLUSTER, DAY),
        ):
            assert 0.0 <= result.confidence <= 1.0


# -- ballast: members that publish nothing the niche can read (ADR-0047) -------


def _ballast_world(engine, *, decided: int, on_niche: int = 0, unscorable: int = 0, age_days=60):
    """A keeper channel plus one channel with a controlled mix of decided / on-niche /
    unscorable rows, so each edge of the rule can be tested on its own."""
    make_cluster(engine)
    add_channel(engine, "keeper", videos=3, relevant=True)
    add_channel(engine, "suspect", videos=0)
    with session_scope(engine) as s:
        for i in range(decided + unscorable):
            vid = f"sv{i}"
            s.add(
                Video(
                    video_id=vid,
                    channel_id="suspect",
                    is_short=False,
                    published_at=_at(DAY - timedelta(days=age_days)),
                    first_seen=_at(DAY),
                    enriched=True,
                    source="t",
                    run_id="t",
                )
            )
            if i < unscorable:
                relevance, noise = None, False
            elif i < unscorable + on_niche:
                relevance, noise = 0.9, False
            else:
                relevance, noise = 0.0, True
            s.add(
                ClusterMember(
                    cluster_id=CLUSTER,
                    item_type="video",
                    item_id=vid,
                    relevance=relevance,
                    is_noise=noise,
                    source="t",
                    run_id="t",
                )
            )
        s.commit()


def _is_ballast(engine, channel="suspect") -> bool:
    with session_scope(engine) as s:
        return channel in set(s.scalars(_ballast_channels(CLUSTER, DAY)))


def test_ten_decided_and_none_on_niche_is_ballast(engine):
    _ballast_world(engine, decided=10)
    assert _is_ballast(engine)


def test_nine_decided_is_not_enough_evidence(engine):
    """Below the bar, "never on-niche" is absence rather than evidence."""
    _ballast_world(engine, decided=9)
    assert not _is_ballast(engine)


def test_one_on_niche_video_is_enough_to_stay(engine):
    """Zero, not a small share. 342 live channels sit at exactly one on-niche video,
    and any tolerance above zero takes them -- removing real on-niche rows from
    numerators. Zero is what makes this denominator-only."""
    _ballast_world(engine, decided=20, on_niche=1)
    assert not _is_ballast(engine)


def test_an_unreadable_catalogue_is_not_ballast(engine):
    """decided = on-niche + decided-noise; unscorable rows are not judgements and must
    not count as evidence against a channel (data rule 7 at channel grain). Live, 43
    channels have an all-unscorable catalogue after ADR-0046's language gate -- they
    stay members and drag relevance_coverage down as unscorable instead."""
    _ballast_world(engine, decided=0, unscorable=20)
    assert not _is_ballast(engine)


def test_ballast_is_bounded_by_the_decision_date(engine):
    """The reason this is a read-time query and not a stored flag.

    A stored `is_noise` is an aggregate as of the RUN date, so it leaks post-`day`
    information into day-bounded reads -- measured on the live corpus, 114 pre-2026
    video rows vanished from a replay at a 2025 decision date, and five of the nine
    BACKTEST_METRICS route through these predicates. `inputs.py`'s own docstring
    promises the opposite. Computed per read, the set can only contain evidence that
    existed then."""
    _ballast_world(engine, decided=12, age_days=10)
    with session_scope(engine) as s:
        recent = set(s.scalars(_ballast_channels(CLUSTER, DAY)))
        earlier = set(s.scalars(_ballast_channels(CLUSTER, DAY - timedelta(days=30))))
    assert "suspect" in recent
    assert "suspect" not in earlier, "ballast leaked evidence from after the decision date"


def test_ballast_leaves_every_coverage_denominator(engine):
    """Marking a channel and stopping there would have been cosmetic: coverage and
    numerator queries count VIDEO rows and none carried a channel condition. Measured
    live: history-of-ideas coverage 2608/3246 -> 870/1384, share 0.076 -> 0.226."""
    _ballast_world(engine, decided=10)
    with session_scope(engine) as s:
        decided, total = relevance_coverage(s, CLUSTER, DAY)
        on_niche, _, _ = numerator_coverage(s, CLUSTER, DAY)
    assert total == 3, "the ballast channel's videos are still in the denominator"
    assert decided == 3
    assert on_niche == 3


def test_ballast_can_never_change_a_numerator(engine):
    """The safety property the rule rests on, and it holds at every N and every day:
    the predicate requires ZERO on-niche videos, so a ballast channel contributes
    nothing above the threshold. Verified live -- 0 counterexamples across all 503."""
    _ballast_world(engine, decided=12)
    with session_scope(engine) as s:
        share = supply.on_niche_share(s, CLUSTER, DAY)
    assert share.detail["on_niche"] == 3  # the keeper's, unchanged
    assert share.value == 1.0  # and the ballast videos left the denominator entirely


def test_ballast_leaves_the_member_universe_too(engine):
    """`supply._confidence` takes `universe` from `member_channels` and `contributing`
    from a `member_join` query, and its clamp comment says coverage above 1.0 means
    those populations have drifted apart. One predicate, both sides."""
    _ballast_world(engine, decided=10)
    with session_scope(engine) as s:
        assert member_channels(s, CLUSTER, DAY) == ["keeper"]


def test_openness_deliberately_keeps_ballast_channels(engine):
    """The other half of ADR-0047's decision, and the only thing pinning it.

    Ballast leaves the SUPPLY denominators and the member universe. It deliberately
    stays in the openness pool, because openness asks whether a video beat its OWN
    channel's baseline over that channel's whole output -- "two different questions,
    so two different pools", which this repo already documents under
    supply.median_views. A ballast channel is a real channel with real reach
    dynamics; whether its uploads are on-niche says nothing about whether a newcomer
    can get traction on it.

    Without this test the decision is unenforced: pushing the ballast filter into
    `member_join` moves breakthrough_rate_cohort and views_per_sub across every
    cluster, and the rest of the suite still passes."""
    from nh.features.inputs import eligible_videos

    make_cluster(engine)
    add_channel(engine, "keeper", videos=3, relevant=True)
    add_channel(engine, "suspect", videos=BALLAST_DECIDED, relevant=False)
    with session_scope(engine) as s:
        assert "suspect" in set(s.scalars(_ballast_channels(CLUSTER, DAY)))
        assert member_channels(s, CLUSTER, DAY) == ["keeper"]  # supply universe: gone
        assert "suspect" in eligible_videos(s, CLUSTER, DAY)  # openness pool: kept
