"""Money metrics."""

from __future__ import annotations

from nh.features.money import midroll_eligible_share
from tests.conftest_features import CLUSTER, DAY, add_channel, make_cluster, session_for


def test_share_of_long_form_videos_over_the_midroll_threshold(engine):
    make_cluster(engine)
    add_channel(engine, "long", videos=3, age_days=1, is_short=False)
    add_channel(engine, "short", videos=1, age_days=1, is_short=True)
    assert midroll_eligible_share(session_for(engine), CLUSTER, DAY).value == 0.75


def test_unknown_durations_are_excluded_from_both_sides(engine):
    """Counting them ineligible would be the NULL-as-False trap: before the
    enrichment backfill, 91% of videos have no duration, and treating those as
    'no mid-roll' would report a confident near-zero for every niche."""
    make_cluster(engine)
    add_channel(engine, "known", videos=2, age_days=1, is_short=False)
    add_channel(engine, "unenriched", videos=98, age_days=1, is_short=None)
    result = midroll_eligible_share(session_for(engine), CLUSTER, DAY)
    assert result.value == 1.0
    assert result.inputs_n == 2  # the 98 unknowns are absent, not counted as zero


def test_all_unknown_durations_is_null_not_zero(engine):
    make_cluster(engine)
    add_channel(engine, "unenriched", videos=10, age_days=1, is_short=None)
    result = midroll_eligible_share(session_for(engine), CLUSTER, DAY)
    assert result.value is None
    assert "backfill" in result.detail["reason"]
