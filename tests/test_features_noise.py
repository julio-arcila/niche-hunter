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

from nh.db.session import session_scope
from nh.features import money, openness, supply
from nh.features.inputs import (
    cohort,
    date_discovered_channels,
    eligible_videos,
    latest_subs,
    member_channels,
)
from tests.conftest_features import CLUSTER, DAY, add_channel, make_cluster


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
    assert result.value == 1.0  # 4 uploads over 28 days, noise channel's 4 ignored


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
