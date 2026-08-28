"""Window *length*, which no other test covered.

`tests/test_features_leakage.py` proves a metric cannot read past its decision date.
That is a different property from spanning the right number of days, and the gap
between the two let a real defect ship: `uploads_per_week` computed
`day - WINDOW_DAYS` with a `time.max` upper bound, which is 29 civil days, and then
divided by 4.0 weeks. Measured on the live corpus 2026-08-28 it counted 69 and 80
videos for corporate-collapse and court-cases where 28 days give 67 and 76 — every
published "per week" figure inflated ~3.6%.

The whole 632-test suite stayed green when that was fixed. A guard that only checks
one side of a window is not a guard on the window.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from nh.db.models import ClusterMember, Video
from nh.db.session import session_scope
from nh.features import money, supply
from nh.features.inputs import _day_end, window_start
from tests.conftest_features import CLUSTER, RUN, add_channel, make_cluster, session_for

DAY = date(2026, 8, 27)
CHANNEL = "UCwindow"

#: (module, function, WINDOW_DAYS) for every metric that counts over a fixed window.
WINDOWED = [
    pytest.param(supply.uploads_per_week, supply.WINDOW_DAYS, id="uploads_per_week"),
    pytest.param(money.midroll_eligible_share, money.WINDOW_DAYS, id="midroll_eligible_share"),
]


def _plant(engine, offsets: list[int]) -> None:
    """One on-niche video per offset, `offset` days before DAY at midday."""
    with session_scope(engine) as s:
        for off in offsets:
            vid = f"v{off:+04d}"
            s.add(
                Video(
                    video_id=vid,
                    channel_id=CHANNEL,
                    title="crash investigation",
                    published_at=datetime.combine(
                        DAY - timedelta(days=off), time(12, 0), tzinfo=UTC
                    ),
                    is_short=False,
                    midroll_eligible=True,
                    duration_s=900,
                    first_seen=datetime.combine(DAY - timedelta(days=off), time.min, tzinfo=UTC),
                    source="test",
                    run_id=RUN,
                )
            )
            s.add(
                ClusterMember(
                    cluster_id=CLUSTER,
                    item_type="video",
                    item_id=vid,
                    relevance=0.9,
                    is_noise=False,
                    source="test",
                    run_id=RUN,
                )
            )


# --------------------------------------------------------------------------
# The convention itself
# --------------------------------------------------------------------------


def test_window_start_spans_exactly_the_days_asked_for():
    """`day - window_days` paired with a whole-day upper bound is off by one: both
    endpoints become whole days, so the span is `window_days + 1`."""
    start = window_start(DAY, 28)
    end = _day_end(DAY)

    assert start.date() == DAY - timedelta(days=27)
    assert (end.date() - start.date()).days + 1 == 28
    assert start.time() == time.min


def test_a_same_day_publish_is_inside_the_window():
    assert _day_end(DAY) > datetime.combine(DAY, time(23, 59), tzinfo=UTC)


# --------------------------------------------------------------------------
# The metrics
# --------------------------------------------------------------------------


@pytest.mark.parametrize("metric,window", WINDOWED)
def test_the_window_holds_exactly_window_days_of_publishes(engine, metric, window):
    """Plant one video on every day of the window and one on each side of it.

    The two sentinels are the whole test: `window` days before DAY is the first day
    OUTSIDE a window of length `window`, and one day after DAY is the future. A
    metric that counts either has the wrong span.
    """
    make_cluster(engine)
    add_channel(engine, CHANNEL, videos=0, day=DAY - timedelta(days=400))
    inside = list(range(0, window))  # DAY back to DAY-(window-1)
    _plant(engine, [*inside, window, -1])

    result = metric(session_for(engine), CLUSTER, DAY)

    assert result.inputs_n == window, (
        f"{result.name} saw {result.inputs_n} of {window} planted days — "
        "the sentinel at the boundary or the future leaked in"
    )


@pytest.mark.parametrize("metric,window", WINDOWED)
def test_the_day_before_the_window_is_excluded(engine, metric, window):
    make_cluster(engine)
    add_channel(engine, CHANNEL, videos=0, day=DAY - timedelta(days=400))
    _plant(engine, [window])  # exactly one day too old

    result = metric(session_for(engine), CLUSTER, DAY)

    assert not result.inputs_n


@pytest.mark.parametrize("metric,window", WINDOWED)
def test_the_oldest_day_inside_the_window_is_included(engine, metric, window):
    make_cluster(engine)
    add_channel(engine, CHANNEL, videos=0, day=DAY - timedelta(days=400))
    _plant(engine, [window - 1])

    result = metric(session_for(engine), CLUSTER, DAY)

    assert result.inputs_n == 1


def test_uploads_per_week_divides_by_the_span_it_actually_counted(engine):
    """The rate is the point: 28 planted days over 4.0 weeks must read 7.0/wk. The
    shipped bug counted 29 days against the same divisor."""
    make_cluster(engine)
    add_channel(engine, CHANNEL, videos=0, day=DAY - timedelta(days=400))
    _plant(engine, list(range(0, supply.WINDOW_DAYS)))

    result = supply.uploads_per_week(session_for(engine), CLUSTER, DAY)

    assert result.inputs_n == 28
    assert result.value == pytest.approx(7.0)
