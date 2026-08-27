"""Supply metrics: the volume and reach of content already in the niche."""

from __future__ import annotations

from datetime import timedelta

from nh.features.supply import median_views, uploads_per_week
from tests.conftest_features import CLUSTER, DAY, add_channel, make_cluster, session_for


def test_uploads_per_week_divides_the_window_not_the_channel_count(engine):
    """A cluster total: supply is the volume a newcomer competes against."""
    make_cluster(engine)
    add_channel(engine, "a", videos=4, age_days=1)
    add_channel(engine, "b", videos=4, age_days=1)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == 2.0  # 8 over 4 weeks


def test_uploads_outside_the_window_are_not_counted(engine):
    make_cluster(engine)
    add_channel(engine, "recent", videos=4, age_days=1)
    add_channel(engine, "stale", videos=40, age_days=200)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == 1.0


def test_a_niche_that_published_nothing_is_a_confident_zero_not_null(engine):
    """The distinction the whole NULL discipline exists for: we looked, and the
    answer was zero. That is a finding about the niche, not missing data."""
    make_cluster(engine)
    add_channel(engine, "dormant", videos=3, age_days=300)
    result = uploads_per_week(session_for(engine), CLUSTER, DAY)
    assert result.value == 0.0
    assert result.confidence > 0


def test_a_cluster_with_no_channels_is_null_not_zero(engine):
    make_cluster(engine)
    result = uploads_per_week(session_for(engine), CLUSTER, DAY)
    assert result.value is None
    assert result.confidence == 0.0


def test_unknown_format_videos_are_excluded_from_supply(engine):
    make_cluster(engine)
    add_channel(engine, "unenriched", videos=8, age_days=1, is_short=None)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == 0.0


def test_shorts_are_excluded_from_supply(engine):
    make_cluster(engine)
    add_channel(engine, "shorts", videos=8, age_days=1, is_short=True)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == 0.0


def test_median_views_pools_across_channels(engine):
    """Pooled, not median-of-medians: a 500-sub channel should not weigh as much
    as a 30M one when measuring the field you compete against."""
    make_cluster(engine)
    add_channel(engine, "small", videos=1, views=[10])
    add_channel(engine, "big", videos=3, views=[1_000, 2_000, 3_000])
    # pool is [10, 1000, 2000, 3000]; the small channel is one vote, not half the weight
    assert median_views(session_for(engine), CLUSTER, DAY).value == 1_500


def test_videos_younger_than_the_age_floor_are_excluded(engine):
    """Views on a very fresh upload have not settled; comparing one against an
    older video measures age rather than performance."""
    make_cluster(engine)
    add_channel(engine, "fresh", videos=3, views=[1, 2, 3], age_days=2)
    result = median_views(session_for(engine), CLUSTER, DAY)
    assert result.value is None
    assert "age" in result.detail["reason"] or "eligible" in result.detail["reason"]


def test_only_snapshots_up_to_the_day_are_read(engine):
    """The anti-leakage property Slice 6's backtest depends on: a feature must
    never see a row that did not exist at the decision date."""
    make_cluster(engine)
    add_channel(engine, "a", videos=1, views=[500])
    past = median_views(session_for(engine), CLUSTER, DAY - timedelta(days=1))
    assert past.value is None  # the snapshot is dated DAY, so a day earlier sees nothing


def test_confidence_falls_when_the_metric_sees_little_of_the_niche(engine):
    """74 contributing channels of 197 must not report full confidence just
    because 74 clears the adequacy bar."""
    make_cluster(engine)
    add_channel(engine, "contributes", videos=5, views=100)
    for i in range(9):
        add_channel(engine, f"silent{i}", videos=0)
    result = median_views(session_for(engine), CLUSTER, DAY)
    assert result.confidence < 0.2  # 1 of 10 channels, and 1 is far below n=30
