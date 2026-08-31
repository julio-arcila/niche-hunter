"""Supply metrics: the volume and reach of content already in the niche."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa

from nh.db.session import session_scope
from nh.features.inputs import BALLAST_DECIDED, numerator_coverage
from nh.features.supply import (
    geo_concentration,
    median_views,
    uploads_per_week,
    views_per_new_video,
)
from tests.conftest_features import CLUSTER, DAY, RUN, add_channel, make_cluster, session_for


def test_uploads_per_week_sums_channel_rates_not_a_channel_average(engine):
    """A cluster total: supply is the volume a newcomer competes against.

    Each channel's oldest known video is 23 days old, so each is a rate over its
    24-day observed span (data rule 9): 4 / (24/7) = 7/6 per channel. The total is
    the sum, 7/3 — a per-channel average would halve it.
    """
    make_cluster(engine)
    add_channel(engine, "a", videos=4, age_days=20)
    add_channel(engine, "b", videos=4, age_days=20)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == pytest.approx(7 / 3)


def test_uploads_outside_the_window_are_not_counted(engine):
    make_cluster(engine)
    add_channel(engine, "recent", videos=4, age_days=20)  # observed span 24d -> 4/(24/7)
    add_channel(engine, "stale", videos=40, age_days=200)  # all outside; contributes 0
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == pytest.approx(7 / 6)


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


# -- geo_concentration -------------------------------------------------------


def _seeded_cluster(engine, geo="US"):
    from nh.db.models import Cluster, NicheSeed

    with session_scope(engine) as s:
        s.add(NicheSeed(id=1, slug=CLUSTER, label="Aviation", keywords=[], geo=geo))
        s.flush()
        s.add(Cluster(cluster_id=CLUSTER, seed_id=1, source="clustering", run_id=RUN))


def _country(engine, channel_id, country):
    from nh.db.models import Channel

    with session_scope(engine) as s:
        s.execute(
            sa.update(Channel).where(Channel.channel_id == channel_id).values(country=country)
        )
        s.commit()


def test_geo_concentration_is_the_share_from_the_stated_market(engine):
    _seeded_cluster(engine, geo="US")
    for name, country in (("UCa", "US"), ("UCb", "US"), ("UCc", "IN"), ("UCd", "GB")):
        add_channel(engine, name, videos=1)
        _country(engine, name, country)

    with session_scope(engine) as s:
        result = geo_concentration(s, CLUSTER, DAY)

    assert result.value == 0.5
    assert result.detail["seed_geo"] == "US"


def test_an_unknown_country_lowers_confidence_rather_than_counting_as_foreign(engine):
    """Data rule 7. 236 of 955 real channels report no country; treating them as
    "not local" would understate every niche by a quarter."""
    _seeded_cluster(engine, geo="US")
    add_channel(engine, "UCknown", videos=1)
    _country(engine, "UCknown", "US")
    add_channel(engine, "UCunknown", videos=1)  # country stays NULL

    with session_scope(engine) as s:
        result = geo_concentration(s, CLUSTER, DAY)

    assert result.value == 1.0  # the one channel we can place is local
    assert result.confidence == 0.5  # but we could only place half of them
    assert result.inputs_n == 1


def test_a_seed_with_no_stated_geo_has_nothing_to_diverge_from(engine):
    _seeded_cluster(engine, geo=None)
    add_channel(engine, "UCa", videos=1)
    _country(engine, "UCa", "US")

    with session_scope(engine) as s:
        result = geo_concentration(s, CLUSTER, DAY)

    assert result.value is None
    assert "states no geo" in result.detail["reason"]


def test_it_reports_where_the_supply_actually_is(engine):
    """The detail is the point: a low value is only actionable if you can see which
    market the supply came from instead."""
    _seeded_cluster(engine, geo="US")
    for name, country in (("UCa", "IN"), ("UCb", "IN"), ("UCc", "IN"), ("UCd", "US")):
        add_channel(engine, name, videos=1)
        _country(engine, name, country)

    with session_scope(engine) as s:
        result = geo_concentration(s, CLUSTER, DAY)

    assert result.value == 0.25
    assert result.detail["top_countries"][0] == ("IN", 3)


# -- pressure_index ----------------------------------------------------------


def test_pressure_index_is_the_mean_of_two_ranks_not_a_weighted_blend(engine):
    """Mean of ranks invents no weights. Any coefficient on "how big are the
    winners" versus "how much arrives" would be a fabricated constant with nothing
    to calibrate it against until Gate E."""
    from functools import partial

    from nh.db.provenance import stamp
    from nh.db.types import utcnow
    from nh.features.run import compute

    make_cluster(engine, "a")
    make_cluster(engine, "b")
    # `a` wins on median_views, `b` wins on uploads — the ranks should cancel.
    add_channel(engine, "UCa", cluster_id="a", videos=6, views=10_000, age_days=20)
    add_channel(engine, "UCb1", cluster_id="b", videos=6, views=10, age_days=20)
    add_channel(engine, "UCb2", cluster_id="b", videos=6, views=10, age_days=20)

    mark = partial(stamp, source="features", run_id="t", at=utcnow())
    with session_scope(engine) as s:
        compute(s, DAY, mark)
        rows = dict(
            s.execute(
                sa.text("SELECT cluster_id, value FROM features_daily WHERE name='pressure_index'")
            ).all()
        )
    assert set(rows) == {"a", "b"}
    # Two clusters, opposite ranks on the two components -> both land at 0.5.
    assert rows["a"] == pytest.approx(0.5)
    assert rows["b"] == pytest.approx(0.5)


def test_pressure_index_records_its_components_and_population(engine):
    """A rank is only meaningful against the set it was taken over, so the set is
    part of the row."""
    from functools import partial

    from nh.db.provenance import stamp
    from nh.db.types import utcnow
    from nh.features.run import compute

    make_cluster(engine, "a")
    make_cluster(engine, "b")
    add_channel(engine, "UCa", cluster_id="a", videos=6, views=10_000, age_days=20)
    add_channel(engine, "UCb", cluster_id="b", videos=6, views=10, age_days=20)

    mark = partial(stamp, source="features", run_id="t", at=utcnow())
    with session_scope(engine) as s:
        compute(s, DAY, mark)
        detail = s.execute(
            sa.text(
                "SELECT detail FROM features_daily WHERE name='pressure_index' AND cluster_id='a'"
            )
        ).scalar()
    import json

    detail = json.loads(detail) if isinstance(detail, str) else detail
    assert set(detail["components"]) == {"median_views", "uploads_per_week"}
    assert detail["ranked_over"] == ["a", "b"]


# -- views_per_new_video: the replayable supply analogue ---------------------


def _weekly(engine, channel_id, points, *, start=DAY):
    """`points` is [(total_views, video_count), ...], one per week going back."""
    from datetime import timedelta

    from nh.db.models import ChannelSnapshot

    with session_scope(engine) as s:
        for i, (views, videos) in enumerate(reversed(points)):
            s.add(
                ChannelSnapshot(
                    channel_id=channel_id,
                    observed_date=start - timedelta(days=7 * i),
                    subs=1_000,
                    total_views=views,
                    video_count=videos,
                    source="youniverse",
                    run_id=RUN,
                )
            )


def test_views_per_new_video_differences_the_stocks(engine):
    """10,000 new views over 2 new videos is 5,000 per video."""
    make_cluster(engine)
    add_channel(engine, "UCa", videos=1, age_days=40)
    _weekly(engine, "UCa", [(100_000, 10), (105_000, 11), (110_000, 12)])

    with session_scope(engine) as s:
        result = views_per_new_video(s, CLUSTER, DAY)

    assert result.value == 5_000
    assert result.detail["contributing_channels"] == 1


def test_a_channel_that_published_nothing_is_excluded_not_zeroed(engine):
    """A week with no upload says nothing about reach per upload (data rule 7).
    Counting it as zero would drag every niche's median toward zero in proportion
    to how quiet its channels are."""
    make_cluster(engine)
    add_channel(engine, "UCquiet", videos=1, age_days=40)
    add_channel(engine, "UCbusy", videos=1, age_days=40)
    _weekly(engine, "UCquiet", [(500_000, 40), (500_900, 40)])  # views, no new video
    _weekly(engine, "UCbusy", [(10_000, 5), (14_000, 7)])  # 4,000 over 2 -> 2,000

    with session_scope(engine) as s:
        result = views_per_new_video(s, CLUSTER, DAY)

    assert result.value == 2_000
    assert result.inputs_n == 1
    assert result.confidence == 0.5  # one of two members could contribute


def test_it_reads_nothing_after_the_decision_date(engine):
    """The property that makes it usable in a replay at all."""
    from datetime import timedelta

    make_cluster(engine)
    add_channel(engine, "UCa", videos=1, age_days=40)
    _weekly(engine, "UCa", [(100_000, 10), (110_000, 12)])
    _weekly(engine, "UCa", [(900_000, 13)], start=DAY + timedelta(days=7))

    with session_scope(engine) as s:
        assert views_per_new_video(s, CLUSTER, DAY).value == 5_000


def test_it_is_empty_when_nothing_can_be_differenced(engine):
    make_cluster(engine)
    add_channel(engine, "UCa", videos=1, age_days=40)
    _weekly(engine, "UCa", [(100_000, 10)])  # a single snapshot has no delta

    with session_scope(engine) as s:
        result = views_per_new_video(s, CLUSTER, DAY)

    assert result.value is None
    assert "between two snapshots" in result.detail["reason"]


# -- numerator decisiveness: what bounds trust in a VOLUME ---------------------
# The inversion these protect against shipped untested: on run a6d35aee,
# Spearman(value, confidence) across the eleven live clusters was -0.346, because
# `known == members` everywhere made confidence reduce exactly to
# `relevance_coverage` and a confidently REJECTED video therefore raised
# confidence in a volume it contributes nothing to.
# See reports/supply_audit_2026-08-30.md.


def test_numerator_coverage_counts_the_three_undecided_states_together(engine):
    """`judgeable` is everything not decided off-niche, so it must hold the
    on-niche, the undecided-NULL and the mid-band alike — the three states are not
    two, exactly as `on_niche_join` insists when it excludes them."""
    make_cluster(engine)
    add_channel(engine, "a", videos=2, relevant=True)
    add_channel(engine, "b", videos=3, relevant=False)
    add_channel(engine, "c", videos=4, relevant=None)
    on_niche, judgeable, total = numerator_coverage(session_for(engine), CLUSTER, DAY)
    assert (on_niche, judgeable, total) == (2, 6, 9)


def test_rejecting_a_video_does_not_raise_confidence_in_a_volume(engine):
    """The whole point. Two clusters with the SAME on-niche numerator, differing
    only in how many off-niche videos the scorer confidently rejected.

    Both clusters hold two channels, two on-niche videos and two unscorable ones,
    so adequacy and coverage are identical by construction and only the third leg
    can move. The second cluster adds eight videos the scorer confidently rejected.

    Under the old `decided/total` leg those eight lifted it from 0.5 to 10/12 = 0.833,
    because rejection counted as knowledge. A rejected video is not in this volume
    and cannot make it more certain, so the two must now agree exactly.

    Eight and not forty: at ten decided with no on-niche the channel becomes ballast
    (ADR-0047) and leaves the cluster entirely, which would confound this test by
    changing the adequacy leg as well. The two rules interact and the fixture has to
    stay on one side of it."""
    make_cluster(engine)
    add_channel(engine, "a", videos=2, relevant=True)
    add_channel(engine, "b", videos=2, relevant=None)
    lean = uploads_per_week(session_for(engine), CLUSTER, DAY).confidence

    make_cluster(engine, "other")
    add_channel(engine, "c", videos=2, cluster_id="other", relevant=True)
    rejected = [False] * (BALLAST_DECIDED - 2)  # derived: must stay below the ballast bar
    add_channel(
        engine, "d", videos=2 + len(rejected), cluster_id="other", relevant=[None, None, *rejected]
    )
    padded = uploads_per_week(session_for(engine), "other", DAY).confidence

    assert padded == pytest.approx(lean)


def test_deciding_a_cluster_off_niche_beats_being_unable_to_read_it(engine):
    """The case the coverage leg's own comment defends, arriving through the new
    leg. Both clusters have one channel, five videos and a zero volume, so adequacy
    and coverage are identical and only the third leg can move.

    Every video DECIDED off-niche is full decisiveness — the zero is earned. Every
    video UNSCORABLE is the opposite: nothing was judged, so the same zero is worth
    nothing. `is_noise` records only the decided case, and that distinction is the
    whole reason the three relevance states are not two."""
    make_cluster(engine)
    add_channel(engine, "a", videos=5, relevant=False)
    decided = uploads_per_week(session_for(engine), CLUSTER, DAY)

    make_cluster(engine, "unreadable")
    add_channel(engine, "b", videos=5, cluster_id="unreadable", relevant=None)
    unreadable = uploads_per_week(session_for(engine), "unreadable", DAY)

    assert decided.value == unreadable.value == 0.0
    assert decided.confidence > unreadable.confidence
    assert unreadable.confidence == 0.0


def test_a_cluster_with_no_videos_at_all_is_not_confident(engine):
    """Distinct from the case above and must not collapse into it: there was
    nothing to be decisive about, so 0/0 reads 0.0 rather than 1.0."""
    make_cluster(engine)
    add_channel(engine, "a", videos=0)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).confidence == 0.0


def test_censoring_is_reported_over_the_channels_that_reach_the_value(engine):
    """Data rule 9 names this counter as the attribution marker for the span-rate
    bump, so it has to range over the population the value is summed from. The
    older `channels_span_censored` ranges over every known channel and is kept
    beside it, unchanged, so rows on both sides of 2026-08-30 stay readable."""
    make_cluster(engine)
    add_channel(engine, "publisher", videos=3, age_days=5)
    add_channel(engine, "quiet", videos=2, age_days=200)
    detail = uploads_per_week(session_for(engine), CLUSTER, DAY).detail
    assert detail["contributing_span_censored"] == 1
    assert detail["channels_span_censored"] == 1
    assert detail["contributing_span_censored"] <= detail["channels_publishing_in_window"]
