"""The ranked channel list (ADR-0060 H1's licence): the gate, the ordering, the exclusions.

The first ranked surface in this project, so the tests are mostly about what it refuses to
show and what it refuses to become.
"""

from __future__ import annotations

import pytest

from nh.api import gates
from nh.db.models import FeedState
from nh.db.session import session_scope
from nh.jobs import channels, niche
from tests.conftest_features import CLUSTER, DAY, add_channel, make_cluster


@pytest.fixture
def validated(monkeypatch):
    """A world where a person has recorded H1's verdict."""
    monkeypatch.setattr(gates, "CHANNEL_REACH_H1_VALIDATED", True)


def _world(engine):
    make_cluster(engine)
    # views are newest-first per `add_channel`; medians are 100, 1_000 and 20.
    add_channel(engine, "UClow", subs=1_000, videos=3, views=[100, 100, 100], age_days=30, day=DAY)
    add_channel(engine, "UChigh", subs=500, videos=3, views=[1_000] * 3, age_days=30, day=DAY)
    add_channel(engine, "UCtiny", subs=5_000, videos=3, views=[20] * 3, age_days=30, day=DAY)


def test_the_list_is_withheld_until_a_person_records_the_verdict(engine):
    """Default-withheld, so forgetting the argument fails safe — ADR-0052's shape. H1
    PASSED; what is missing is a human having looked."""
    _world(engine)
    view = channels.load(CLUSTER, DAY, engine)
    assert view.withheld
    assert view.rows == ()
    assert "recorded by a person" in view.verdict.reason
    assert "CHANNEL_REACH_H1_VALIDATED" in view.verdict.reason


def test_a_declined_verdict_reads_differently_from_an_unrecorded_one(engine, monkeypatch):
    """`None` is "nobody looked"; `False` is "somebody looked and said no". Collapsing them
    would lose the operator's own decision."""
    _world(engine)
    monkeypatch.setattr(gates, "CHANNEL_REACH_H1_VALIDATED", False)
    assert "declined" in channels.load(CLUSTER, DAY, engine).verdict.reason
    monkeypatch.setattr(gates, "CHANNEL_REACH_H1_VALIDATED", None)
    assert "unrecorded" in channels.load(CLUSTER, DAY, engine).verdict.reason


def test_a_human_asking_once_sees_it(engine):
    """`include_unvalidated` records nothing and is not the stored setting ADR-0050
    forbids — the same distinction `jobs.niche.load` draws."""
    _world(engine)
    view = channels.load(CLUSTER, DAY, engine, include_unvalidated=True)
    assert not view.withheld or view.rows
    assert len(view.rows) == 3


def test_the_order_is_raw_views_per_sub_descending(engine, validated):
    """Raw, not residualised: the registered lift was computed on the top decile of the RAW
    predictor, so raw is the quantity H1 validated. A reader reads from the top."""
    _world(engine)
    view = channels.load(CLUSTER, DAY, engine)
    assert [r.channel_id for r in view.rows] == ["UChigh", "UClow", "UCtiny"]
    assert view.rows[0].views_per_sub == pytest.approx(2.0)  # 1000 / 500
    assert view.rows[1].views_per_sub == pytest.approx(0.1)  # 100 / 1000
    assert [r.rank for r in view.rows] == [1, 2, 3]


def test_a_dead_feed_is_excluded_and_counted(engine, validated):
    """Terminated channels stay in the supply METRICS by decision — the first-404 date is
    not stored, so excluding them from a replay would leak information from after the day.
    A RECOMMENDATION is different: telling someone to study a channel that no longer exists
    is simply wrong. So the surface filters them and says how many."""
    _world(engine)
    with session_scope(engine) as s:
        s.add(FeedState(channel_id="UChigh", fail_count=5, last_status=404, etag=None))
    view = channels.load(CLUSTER, DAY, engine)
    assert [r.channel_id for r in view.rows] == ["UClow", "UCtiny"]
    assert view.dead_excluded == 1


def test_a_feed_capped_for_some_other_reason_is_not_excluded(engine, validated):
    """A DNS outage charges `fail_count` too — measured, 385 feeds in one night on
    2026-09-20, all of which reset on their next healthy poll. Only a 404 means gone."""
    _world(engine)
    with session_scope(engine) as s:
        s.add(FeedState(channel_id="UChigh", fail_count=5, last_status=500, etag=None))
    view = channels.load(CLUSTER, DAY, engine)
    assert "UChigh" in [r.channel_id for r in view.rows]
    assert view.dead_excluded == 0


def test_a_hidden_subscriber_count_is_not_a_zero_denominator(engine, validated):
    """Rule 7: `subs=None` is unknown, and `views/0` would be either a crash or an
    infinity at the top of the list."""
    make_cluster(engine)
    add_channel(engine, "UChidden", subs=None, videos=3, views=[1_000] * 3, age_days=30, day=DAY)
    view = channels.load(CLUSTER, DAY, engine)
    assert view.rows == ()


def test_an_unknown_cluster_raises_rather_than_returning_an_empty_list(engine, validated):
    """An empty list and a typo must not look identical."""
    _world(engine)
    with pytest.raises(niche.UnknownCluster):
        channels.load("not-a-cluster", DAY, engine)


def test_the_licence_travels_with_the_list(engine, validated):
    """Kept in one constant so two surfaces cannot drift into two different claims, and it
    states the negative explicitly because that is the over-read to expect."""
    _world(engine)
    view = channels.load(CLUSTER, DAY, engine)
    assert "H1 PASS" in view.licence and "+0.470" in view.licence
    assert "NOTHING about any niche" in view.licence
    assert view.licence == channels.LICENCE


def test_no_field_is_called_a_score_and_none_is_a_scorecard_field(engine, validated):
    """The rank is the rank. A `score` column would invite exactly the aggregation
    ADR-0068 ruled out, and a scorecard field here would walk through the Gate E wall."""
    _world(engine)
    row = channels.load(CLUSTER, DAY, engine).rows[0]
    fields = set(type(row).__dataclass_fields__)
    assert not fields & {"score", "value", "opportunity", "sustainability", "gap"}
    assert not fields & gates.SCORECARD_FIELDS if hasattr(gates, "SCORECARD_FIELDS") else True


def test_the_list_is_per_cluster_and_offers_no_cross_cluster_shape(engine, validated):
    """`load` takes exactly one cluster_id and returns one cluster's rows. ADR-0068
    measured the cross-cluster aggregate as undetectable at ten clusters, so there must be
    no convenient path to building one from this module."""
    import inspect

    sig = inspect.signature(channels.load)
    assert "cluster_id" in sig.parameters
    assert not any(p in sig.parameters for p in ("cluster_ids", "clusters", "all_clusters"))
    exported = {n for n in dir(channels) if not n.startswith("_")}
    assert not exported & {"load_all", "rank_clusters", "best_clusters"}
