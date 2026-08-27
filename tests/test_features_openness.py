"""Openness metrics.

The cohort definition IS the metric. Measured on live data, the same breakthrough
formula computed over all channels is flat across five niches (2 percentage
points); over the cohort it spreads 40. Each of these tests pins one filter.
"""

from __future__ import annotations

import sqlalchemy as sa

from nh.db.models import ClusterMember
from nh.db.session import session_scope
from nh.features.openness import breakthrough_rate_cohort, views_per_sub, winner_age_years
from tests.conftest_features import CLUSTER, DAY, add_channel, make_cluster, session_for


def _cohort_channel(engine, name, views, subs=1_000, **kw):
    """A channel that qualifies: small, date-discovered, 5 long-form videos."""
    return add_channel(engine, name, subs=subs, videos=5, views=views, **kw)


def test_the_rate_counts_channels_not_videos(engine):
    """A prolific channel with three breakouts must not outweigh three channels
    with one each — the question is whether a typical entrant breaks through."""
    make_cluster(engine)
    _cohort_channel(engine, "many", [100, 100, 100, 5_000, 5_000])  # 2 breakouts, 1 channel
    _cohort_channel(engine, "none", [100, 100, 100, 100, 100])
    result = breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY)
    assert result.value == 0.5  # one of two channels, not two of ten videos
    assert result.inputs_n == 2


def test_a_viewcount_only_channel_is_excluded_from_the_cohort(engine):
    """It is in the sample BECAUSE it had a winner; counting it in the denominator
    inflates the rate by construction. This is what Discovery.order_by is for."""
    make_cluster(engine)
    _cohort_channel(engine, "dated", [100] * 5, date_lineage=True)
    _cohort_channel(engine, "viewcount-only", [100] * 5, date_lineage=False)
    assert breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY).inputs_n == 1


def test_a_large_channel_is_excluded(engine):
    """Above 10k subs, views-per-sub measures retention, not openness."""
    make_cluster(engine)
    _cohort_channel(engine, "small", [100] * 5, subs=9_000)
    _cohort_channel(engine, "large", [100] * 5, subs=50_000)
    assert breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY).inputs_n == 1


def test_a_channel_with_too_few_videos_is_excluded(engine):
    """Below five uploads there is no stable median to compare a breakout against."""
    make_cluster(engine)
    _cohort_channel(engine, "enough", [100] * 5)
    add_channel(engine, "sparse", subs=1_000, videos=4, views=100)
    assert breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY).inputs_n == 1


def test_a_hidden_subscriber_count_excludes_rather_than_reads_as_zero(engine):
    make_cluster(engine)
    _cohort_channel(engine, "visible", [100] * 5)
    add_channel(engine, "hidden", subs=None, videos=5, views=100)
    assert breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY).inputs_n == 1


def test_unknown_format_videos_do_not_count_as_long_form(engine):
    """An unenriched RSS video has is_short NULL. Treating NULL as False is the
    trap that would let Shorts into a long-form baseline."""
    make_cluster(engine)
    add_channel(engine, "unenriched", subs=1_000, videos=5, views=100, is_short=None)
    result = breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY)
    assert result.value is None
    assert result.inputs_n == 0


def test_the_ten_times_subs_rule_fires_without_a_median_breakout(engine):
    """A channel whose whole catalogue is small but which reached far past its
    audience: no video is 5x the median, but one is 10x the subscriber count."""
    make_cluster(engine)
    _cohort_channel(engine, "reached", [1_000, 1_100, 1_200, 1_300, 1_400], subs=100)
    assert breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY).value == 1.0


def test_an_empty_cohort_is_null_not_zero(engine):
    """Zero would say 'no channel here breaks through', which is a finding.
    NULL says we could not look, which is the truth."""
    make_cluster(engine)
    result = breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY)
    assert result.value is None
    assert result.confidence == 0.0
    assert "cohort empty" in result.detail["reason"]


def test_confidence_rises_with_cohort_size(engine):
    make_cluster(engine)
    for i in range(15):
        _cohort_channel(engine, f"c{i}", [100] * 5)
    result = breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY)
    assert result.confidence == 0.5  # 15 of the 30 needed


def test_views_per_sub_is_the_unweighted_median_across_the_cohort(engine):
    make_cluster(engine)
    _cohort_channel(engine, "a", [100] * 5, subs=100)  # ratio 1.0
    _cohort_channel(engine, "b", [400] * 5, subs=100)  # ratio 4.0
    _cohort_channel(engine, "c", [900] * 5, subs=100)  # ratio 9.0
    assert views_per_sub(session_for(engine), CLUSTER, DAY).value == 4.0


def test_detail_names_the_channels_that_broke_through(engine):
    make_cluster(engine)
    _cohort_channel(engine, "winner", [100, 100, 100, 100, 9_000])
    detail = breakthrough_rate_cohort(session_for(engine), CLUSTER, DAY).detail
    assert detail["breakout_channel_ids"] == ["winner"]


# -- Slice 4 regression: openness must NOT follow supply onto the on-niche pool --


def test_openness_uses_the_whole_catalogue_not_the_on_niche_pool(engine):
    """Breakthrough asks whether a video beat *its own channel's* baseline, and that
    baseline must be the channel's whole output. Supply asks what a newcomer
    competes against *in this niche*. Two questions, two pools — merging them back
    together would shrink every cohort by ~80% and make openness universally NULL,
    which is a self-inflicted Gate D on a metric group that was not the problem.
    """
    make_cluster(engine)
    add_channel(
        engine,
        "UCa",
        subs=1_000,
        videos=6,
        views=[100] * 5 + [10_000],
        relevant=[True] + [False] * 5,
    )

    with session_scope(engine) as s:
        result = breakthrough_rate_cohort(s, CLUSTER, DAY)

    # All six videos count toward the baseline, even though five are off-niche.
    assert result.inputs_n == 1
    assert result.value is not None


def test_marking_every_video_off_niche_does_not_empty_the_cohort(engine):
    """The sharpest form of the same guarantee: relevance must not reach openness
    at all."""
    make_cluster(engine)
    add_channel(engine, "UCa", subs=1_000, videos=6, relevant=False)
    add_channel(engine, "UCb", subs=2_000, videos=6, relevant=False)

    with session_scope(engine) as s:
        breakthrough = breakthrough_rate_cohort(s, CLUSTER, DAY)
        per_sub = views_per_sub(s, CLUSTER, DAY)

    assert breakthrough.inputs_n == 2
    assert per_sub.inputs_n == 2


def test_openness_values_are_identical_whatever_the_relevance(engine):
    """Same world twice, differing only in the relevance decisions. If openness
    moved, something has quietly joined it to the video-grain membership."""
    make_cluster(engine)
    add_channel(engine, "UCa", subs=1_000, videos=6, views=[100] * 5 + [9_000], relevant=True)
    with session_scope(engine) as s:
        all_relevant = breakthrough_rate_cohort(s, CLUSTER, DAY).value
    with session_scope(engine) as s:
        s.execute(
            sa.update(ClusterMember)
            .where(ClusterMember.item_type == "video")
            .values(relevance=0.0, is_noise=True)
        )
        s.commit()
        none_relevant = breakthrough_rate_cohort(s, CLUSTER, DAY).value

    assert all_relevant == none_relevant


# -- winner_age_years --------------------------------------------------------


def _dated_channel(engine, channel_id, created, views, *, relevant=True, n=1):
    """A channel with a known creation date and `n` videos at `views`."""
    from datetime import timedelta

    from nh.db.models import Channel
    from nh.db.types import utcnow

    add_channel(engine, channel_id, videos=n, views=views, relevant=relevant)
    with session_scope(engine) as s:
        s.execute(
            sa.update(Channel)
            .where(Channel.channel_id == channel_id)
            .values(created_at=utcnow() - timedelta(days=int(created * 365.25)))
        )
        s.commit()


def test_winner_age_is_the_median_age_behind_the_top_videos(engine):
    make_cluster(engine)
    _dated_channel(engine, "UCyoung", created=1.0, views=1_000)
    _dated_channel(engine, "UCmid", created=5.0, views=900)
    _dated_channel(engine, "UCold", created=9.0, views=800)

    with session_scope(engine) as s:
        result = winner_age_years(s, CLUSTER, DAY)

    assert 4.5 < result.value < 5.5  # the middle channel
    assert result.inputs_n == 3


def test_it_ranks_on_views_so_a_big_old_channel_pulls_the_median_up(engine):
    """The documented bias: lifetime views favour older videos, so this
    UNDER-states openness rather than over-stating it."""
    make_cluster(engine)
    _dated_channel(engine, "UCold", created=10.0, views=1_000_000, n=3)
    _dated_channel(engine, "UCyoung", created=1.0, views=10)

    with session_scope(engine) as s:
        result = winner_age_years(s, CLUSTER, DAY)

    assert result.value > 5.0


def test_confidence_is_distinct_channels_not_videos(engine):
    """If the top-N comes from few prolific channels the median describes those
    channels, not the niche — which is exactly what confidence must say."""
    make_cluster(engine)
    _dated_channel(engine, "UConly", created=4.0, views=1_000, n=10)

    with session_scope(engine) as s:
        result = winner_age_years(s, CLUSTER, DAY)

    assert result.inputs_n == 10
    assert result.confidence == 1 / 100  # one channel, however many videos
    assert result.detail["distinct_channels"] == 1


def test_off_niche_videos_do_not_decide_who_wins(engine):
    """ "Who wins in this niche" is a question about the niche's content."""
    make_cluster(engine)
    _dated_channel(engine, "UConniche", created=2.0, views=100)
    _dated_channel(engine, "UCoffniche", created=12.0, views=5_000_000, relevant=False)

    with session_scope(engine) as s:
        result = winner_age_years(s, CLUSTER, DAY)

    assert result.value < 3.0
    assert result.detail["distinct_channels"] == 1


def test_it_survives_an_empty_cohort(engine):
    """The reason this metric earns its place: it needs no subscriber counts and no
    discovery lineage, so it reports where the cohort metrics cannot."""
    make_cluster(engine)
    _dated_channel(engine, "UChidden", created=3.0, views=500)
    with session_scope(engine) as s:
        s.execute(sa.text("DELETE FROM channel_snapshots"))
        s.execute(sa.text("DELETE FROM discoveries"))
        s.commit()
        assert breakthrough_rate_cohort(s, CLUSTER, DAY).value is None
        assert winner_age_years(s, CLUSTER, DAY).value is not None


def test_a_channel_with_no_creation_date_is_excluded_not_zeroed(engine):
    make_cluster(engine)
    _dated_channel(engine, "UCdated", created=6.0, views=100)
    add_channel(engine, "UCundated", videos=1, views=999_999)  # created_at stays NULL

    with session_scope(engine) as s:
        result = winner_age_years(s, CLUSTER, DAY)

    assert result.detail["distinct_channels"] == 1
    assert 5.5 < result.value < 6.5


def test_it_is_empty_when_nothing_qualifies(engine):
    make_cluster(engine)
    with session_scope(engine) as s:
        result = winner_age_years(s, CLUSTER, DAY)
    assert result.value is None
    assert result.confidence == 0.0
    assert "no on-niche video" in result.detail["reason"]
