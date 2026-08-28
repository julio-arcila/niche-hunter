"""Supply metrics: the volume and reach of content already in the niche."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa

from nh.db.session import session_scope
from nh.features.supply import geo_concentration, median_views, uploads_per_week
from tests.conftest_features import CLUSTER, DAY, RUN, add_channel, make_cluster, session_for


def test_uploads_per_week_divides_the_window_not_the_channel_count(engine):
    """A cluster total: supply is the volume a newcomer competes against."""
    make_cluster(engine)
    add_channel(engine, "a", videos=4, age_days=20)
    add_channel(engine, "b", videos=4, age_days=20)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == 2.0  # 8 over 4 weeks


def test_uploads_outside_the_window_are_not_counted(engine):
    make_cluster(engine)
    add_channel(engine, "recent", videos=4, age_days=20)
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
