"""`outcome.growth_180d` — what actually happened.

Defined in docs/METRICS.md before this code existed, so it could not be chosen
after seeing results. These tests pin the parts of that definition that are easy
to get subtly wrong: log not ratio, median not mean, membership as of the decision
date, and an honest account of how late the snapshot actually was.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from nh.backtest.outcome import growth
from nh.db.models import ChannelSnapshot
from nh.db.session import session_scope
from tests.conftest_features import CLUSTER, RUN, add_channel, make_cluster, session_for

T = date(2018, 6, 1)


def _subs(engine, channel_id, when, subs):
    with session_scope(engine) as s:
        s.add(
            ChannelSnapshot(
                channel_id=channel_id,
                observed_date=when,
                subs=subs,
                source="youniverse",
                run_id=RUN,
            )
        )


def _member(engine, channel_id, before, after, *, horizon=180, lag=0):
    add_channel(engine, channel_id, subs=None, videos=0, day=T - timedelta(days=30))
    _subs(engine, channel_id, T, before)
    _subs(engine, channel_id, T + timedelta(days=horizon + lag), after)


def test_growth_is_logarithmic(engine):
    """A channel going 1k->2k and one going 100k->200k did the same thing. A plain
    ratio would agree; a difference would not, and a mean of differences would be
    dominated by the largest channel."""
    make_cluster(engine)
    _member(engine, "UCsmall", 1_000, 2_000)
    _member(engine, "UCbig", 100_000, 200_000)

    result = growth(session_for(engine), CLUSTER, T)

    assert result.value == math.log(2)
    assert result.contributing == 2


def test_it_takes_the_median_not_the_mean(engine):
    """One viral channel must not define a niche's outcome."""
    make_cluster(engine)
    _member(engine, "UCa", 1_000, 1_100)
    _member(engine, "UCb", 1_000, 1_200)
    _member(engine, "UCviral", 1_000, 1_000_000)

    result = growth(session_for(engine), CLUSTER, T)

    assert result.value == math.log(1.2)


def test_membership_is_taken_as_of_the_decision_date(engine):
    """A channel that joined the niche later did not exist to be chosen at `t`.
    Including it is the same leak the feature layer was audited for."""
    make_cluster(engine)
    _member(engine, "UCthen", 1_000, 2_000)
    # First seen a year after the decision date.
    add_channel(engine, "UClater", subs=None, videos=0, day=T + timedelta(days=365))
    _subs(engine, "UClater", T, 1_000)
    _subs(engine, "UClater", T + timedelta(days=180), 50_000)

    result = growth(session_for(engine), CLUSTER, T)

    assert result.contributing == 1
    assert result.value == math.log(2)


def test_a_channel_missing_either_endpoint_is_excluded(engine):
    make_cluster(engine)
    _member(engine, "UCok", 1_000, 2_000)
    add_channel(engine, "UChalf", subs=None, videos=0, day=T - timedelta(days=30))
    _subs(engine, "UChalf", T, 1_000)  # no later reading

    result = growth(session_for(engine), CLUSTER, T)

    assert result.contributing == 1
    assert result.channels == 2
    assert result.confidence == 0.5


def test_the_lag_to_the_snapshot_actually_used_is_reported(engine):
    """YouNiverse is weekly with gaps, so "growth at 180 days" is really "growth at
    the nearest reading after it". Reporting the lag keeps that visible instead of
    implying an exactness the data does not have."""
    make_cluster(engine)
    _member(engine, "UCa", 1_000, 2_000, lag=5)

    result = growth(session_for(engine), CLUSTER, T)

    assert result.mean_lag == 5


def test_a_channel_that_went_dark_is_not_scored_as_flat(engine):
    """The bug this file was written to catch. An open-ended "latest reading before
    the horizon" hands back the channel's own *starting* reading when its series
    stops, and log(1) = 0 reads as "grew not at all" rather than "we do not know" —
    data rule 9, in the outcome variable the whole gate depends on."""
    make_cluster(engine)
    _member(engine, "UCalive", 1_000, 2_000)
    add_channel(engine, "UCdark", subs=None, videos=0, day=T - timedelta(days=30))
    _subs(engine, "UCdark", T, 5_000)  # last reading of its life

    result = growth(session_for(engine), CLUSTER, T)

    assert result.contributing == 1
    assert result.value == math.log(2)


def test_the_start_reading_may_not_come_from_after_the_decision_date(engine):
    """The leak that would be invisible in the correlation: a start taken after `t`
    is information the decision could not have had."""
    make_cluster(engine)
    add_channel(engine, "UCa", subs=None, videos=0, day=T - timedelta(days=30))
    _subs(engine, "UCa", T + timedelta(days=1), 1_000)
    _subs(engine, "UCa", T + timedelta(days=180), 2_000)

    result = growth(session_for(engine), CLUSTER, T)

    assert result.contributing == 0
    assert result.value is None


def test_a_stale_start_reading_is_refused(engine):
    """A six-month-old subscriber count is not "the value at t"."""
    make_cluster(engine)
    add_channel(engine, "UCa", subs=None, videos=0, day=T - timedelta(days=400))
    _subs(engine, "UCa", T - timedelta(days=180), 1_000)
    _subs(engine, "UCa", T + timedelta(days=180), 2_000)

    result = growth(session_for(engine), CLUSTER, T)

    assert result.contributing == 0


def test_it_is_empty_when_the_niche_had_no_members_then(engine):
    make_cluster(engine)
    result = growth(session_for(engine), CLUSTER, T)
    assert result.value is None
    assert "no member channel" in result.reason
