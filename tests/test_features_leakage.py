"""Every metric must answer as of the day it is asked about, and nothing later.

This is the test that did not exist, and its absence is why two metrics shipped
day-blind. Slice 4's `supply.on_niche_share` accepts `day` and never references it;
Slice 5's `supply.geo_concentration` uses it only to write `detail["as_of"]`, which
is worse — the row *looks* replayed. Verified against the live database before this
file was written:

    day=2019-01-01   on_niche_share 0.3367   geo_concentration 0.4324  as_of=2019-01-01
    day=2026-08-27   on_niche_share 0.3367   geo_concentration 0.4324  as_of=2026-08-27

Every existing feature test builds ONE world and asserts ONE number, which cannot
catch this. These are differential: two worlds, or two days, and the metric must
respond correctly to the difference.

All three are parametrised over `nh.features.run.METRICS`, so they cover every
registered metric and every metric added later — stated without a count, because the
count went stale twice. That is the property worth having — a leak is
invisible from the site where it is introduced.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from nh.features.run import METRICS
from tests.conftest_features import (
    CLUSTER,
    DAY,
    KP_BASKET,
    RUN,
    _at,
    add_channel,
    add_keyword_metrics,
    make_cluster,
    session_for,
)

#: Far enough back that no fixture row can legitimately be in scope.
LONG_AGO = DAY - timedelta(days=3650)


def _set_country(engine, countries: dict[str, str]) -> None:
    """`supply.geo_concentration` needs a country to divide by, or it reports
    `empty()` and passes every leakage test without being exercised."""
    import sqlalchemy as sa

    from nh.db.models import Channel
    from nh.db.session import session_scope

    with session_scope(engine) as s:
        for channel_id, country in countries.items():
            s.execute(
                sa.update(Channel).where(Channel.channel_id == channel_id).values(country=country)
            )
        s.commit()


def _add_future_videos(engine, channel_id: str, *, n: int, views: int) -> None:
    """Videos published after DAY, on a channel that already existed.

    Not `add_channel`, which would insert the channel a second time. This is the
    case that isolates the video-level bound from the channel-level one — with the
    channel present in both worlds, only the videos differ.
    """
    from datetime import timedelta as _td

    from nh.db.models import ClusterMember, Video, VideoSnapshot
    from nh.db.session import session_scope
    from nh.db.types import utcnow

    later = DAY + _td(days=40)
    with session_scope(engine) as s:
        for i in range(n):
            vid = f"{channel_id}-future-{i}"
            s.add(
                Video(
                    video_id=vid,
                    channel_id=channel_id,
                    title=vid,
                    published_at=_at(later),
                    is_short=False,
                    midroll_eligible=True,
                    source="test",
                    run_id=RUN,
                    at=utcnow(),
                )
            )
            s.add(
                VideoSnapshot(
                    video_id=vid,
                    channel_id=channel_id,
                    observed_date=later,
                    views=views,
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
                    source="clustering",
                    run_id=RUN,
                )
            )


def _world(engine, *, include_future: bool) -> None:
    """A cluster with history, optionally plus rows dated after DAY.

    The future rows have to exercise every dating column a metric might read —
    `published_at`, snapshot `observed_date`, discovery lineage — because a leak
    hides in whichever column nobody thought to test.
    """
    make_cluster(engine)
    add_channel(engine, "UCa", subs=1_000, videos=6, views=1_000, age_days=40)
    add_channel(engine, "UCb", subs=5_000, videos=6, views=9_000, age_days=40)
    # Exists in BOTH worlds — it was around on DAY. Only its videos differ, which
    # is the case that isolates the video-level bound from the channel-level one.
    add_channel(engine, "UCold", subs=2_000, videos=0, age_days=0, day=DAY)
    _set_country(engine, {"UCa": "US", "UCb": "IN", "UCold": "US"})
    # Keyword Planner rows in BOTH worlds. Without them the five KP metrics return
    # empty() everywhere and their fifteen cases below pass without testing anything —
    # the same vacuity that let a day-blind metric ship twice here.
    add_keyword_metrics(engine)
    if include_future:
        # Published after DAY, snapshotted after DAY, discovered after DAY.
        add_channel(
            engine,
            "UCfuture",
            subs=90_000,
            videos=6,
            views=5_000_000,
            age_days=-30,
            day=DAY + timedelta(days=60),
        )
        _set_country(engine, {"UCfuture": "US"})
        # The video-level case: a channel that existed BEFORE the decision date,
        # publishing AFTER it. Without this the channel-level bound hides the
        # video-level one — measured, removing `on_niche_join`'s `published_at`
        # clause caused zero failures until this was added.
        _add_future_videos(engine, "UCold", n=6, views=4_000_000)
        # A re-export dated after DAY, with every number changed. `keyword_metrics` is
        # append-only, so this does not overwrite the readable row — it sits beside it,
        # and a metric that takes the newest row without bounding on `day` will read it
        # and disagree with world A.
        add_keyword_metrics(
            engine,
            observed_offset_days=-60,
            basket=tuple(
                (kw, (v or 0) * 10 + 1, (i or 0) + 7, (lo or 0) + 5, (hi or 0) + 5)
                for kw, v, i, lo, hi in KP_BASKET
            ),
        )


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.__name__)
def test_future_rows_cannot_change_a_past_answer(engine, engine_b, metric):
    """The core anti-leakage property. Two worlds identical up to DAY; one also
    holds rows dated after it. Every metric must return the same answer at DAY.

    Asserts confidence and inputs_n as well as value, deliberately: several of the
    leaks found in the Slice 6 audit move only a confidence — `uploads_per_week`'s
    `known` denominator and `relevance_coverage` both feed confidences and neither
    is bounded. A value-only assertion would pass while the number lied about how
    much it was standing on.
    """
    _world(engine, include_future=False)
    _world(engine_b, include_future=True)

    without = metric(session_for(engine), CLUSTER, DAY)
    with_future = metric(session_for(engine_b), CLUSTER, DAY)

    assert (without.value, without.confidence, without.inputs_n) == (
        with_future.value,
        with_future.confidence,
        with_future.inputs_n,
    ), f"{metric.__name__} changed when rows dated after {DAY} were added"


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.__name__)
def test_the_day_parameter_is_load_bearing(engine, metric):
    """A metric that accepts `day` and never reads it is not replayable.

    Ten years before the fixture's data, every metric must be NULL — there was
    nothing to measure. Returning a non-NULL value there means the metric is
    reading present-day state through an unbounded entity join, which is exactly
    how `on_niche_share` and `geo_concentration` behaved.
    """
    _world(engine, include_future=False)

    long_ago = metric(session_for(engine), CLUSTER, LONG_AGO)

    assert long_ago.value is None, (
        f"{metric.__name__} returned {long_ago.value} for {LONG_AGO}, "
        "which is before any row in the fixture existed"
    )


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.__name__)
def test_an_uncomputable_metric_is_null_not_a_confident_zero(engine, metric):
    """`uploads_per_week` returned 0.0 at confidence 0.871 for 2019 against the live
    database, because its `known` denominator counted all 197 present-day channels.

    A confident zero is the failure data rule 9 names — "flat reads as a finding
    rather than as a bug" — and it is worse than a NULL because a backtest would
    consume it as data.
    """
    _world(engine, include_future=False)

    long_ago = metric(session_for(engine), CLUSTER, LONG_AGO)

    assert long_ago.confidence == 0.0, (
        f"{metric.__name__} reports confidence {long_ago.confidence} for a day "
        "on which it had nothing to measure"
    )
