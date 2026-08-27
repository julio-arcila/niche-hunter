"""Openness metrics.

The cohort definition IS the metric. Measured on live data, the same breakthrough
formula computed over all channels is flat across five niches (2 percentage
points); over the cohort it spreads 40. Each of these tests pins one filter.
"""

from __future__ import annotations

from nh.features.openness import breakthrough_rate_cohort, views_per_sub
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
