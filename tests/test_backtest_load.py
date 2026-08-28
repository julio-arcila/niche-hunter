"""The YouNiverse readers and the loader.

Two classes of bug live here and neither shows up as an exception. The first is a
silent NULL — the source stores counts as floats and the project's integer parser
refuses those, so an 18.9M-row file loads as all-NULL and the backtest reports "no
data" instead of "bug". The second is contamination: writing 2019 rows and thirty
fake clusters into the live corpus, which no test downstream would notice and no
`nh nightly` run would survive cleanly.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from nh.backtest.load import RefusingLiveDatabase, load
from nh.backtest.select import Selection
from nh.backtest.youniverse import channels, weeks
from nh.db.models import Channel, ChannelSnapshot, Cluster, ClusterMember, Video
from nh.db.session import session_scope

RUN = "backtest-test"
AT = datetime(2026, 8, 27, tzinfo=UTC)
SLUG = "nuclear-accidents"

CHANNELS_HEADER = "category_cc\tjoin_date\tchannel\tname_cc\tsubscribers_cc\tvideos_cc\tsubscriber_rank_sb\tweights\n"
WEEKS_HEADER = "channel\tcategory\tdatetime\tviews\tdelta_views\tsubs\tdelta_subs\tvideos\tdelta_videos\tactivity\n"


def _gz(path: Path, text: str) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(text)
    return path


def _channels_file(tmp_path, *rows: str) -> Path:
    return _gz(tmp_path / "df_channels_en.tsv.gz", CHANNELS_HEADER + "".join(rows))


def _weeks_file(tmp_path, *rows: str) -> Path:
    return _gz(tmp_path / "df_timeseries_en.tsv.gz", WEEKS_HEADER + "".join(rows))


def _hits_file(tmp_path, *hits: dict) -> Path:
    return _gz(tmp_path / "hits.jsonl.gz", "".join(json.dumps(h) + "\n" for h in hits))


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------


def test_weekly_counts_are_floats_and_must_not_load_as_null(tmp_path):
    """The bug this file exists for. YouNiverse smooths across its crawl cadence, so
    `subs` is `650.2222222222222`, and `parse.as_int` correctly refuses that — it
    exists to stop an API returning "3.7" where an integer was promised. Reusing it
    here turned every numeric column into NULL with no error anywhere."""
    path = _weeks_file(
        tmp_path,
        "UCa\tGaming\t2017-07-03 00:00:00\t202494.5555555556\t0.0\t650.2222222222222\t0.0\t5\t0\t3\n",
    )

    row = next(iter(weeks(path)))

    assert row.subs == 650
    assert row.views == 202495
    assert row.week_ending == date(2017, 7, 3)


def test_a_missing_count_stays_null(tmp_path):
    """A week with no reading is not a week with no growth — data rule 7."""
    path = _weeks_file(tmp_path, "UCa\tGaming\t2017-07-03 00:00:00\t100.0\t\t\t\t5\t0\t3\n")

    row = next(iter(weeks(path)))

    assert row.subs is None
    assert row.delta_views is None
    assert row.views == 100


def test_channel_rows_parse(tmp_path):
    path = _channels_file(
        tmp_path, "Gaming\t2010-04-29\tUCa\tPewDiePie\t101000000\t3956\t3.0\t2.08\n"
    )

    row = next(iter(channels(path)))

    assert row.channel_id == "UCa"
    assert row.join_date == date(2010, 4, 29)
    assert row.subscribers == 101_000_000


def test_the_weekly_stream_can_be_restricted_to_selected_channels(tmp_path):
    """The filter is what makes the load affordable: 18.9M rows against ~0.4M."""
    path = _weeks_file(
        tmp_path,
        "UCa\tGaming\t2017-07-03 00:00:00\t1.0\t0.0\t1.0\t0.0\t1\t0\t1\n",
        "UCz\tGaming\t2017-07-03 00:00:00\t1.0\t0.0\t1.0\t0.0\t1\t0\t1\n",
    )

    assert [row.channel_id for row in weeks(path, keep={"UCa"})] == ["UCa"]


# --------------------------------------------------------------------------
# Loader
# --------------------------------------------------------------------------


def _world(tmp_path):
    selection = Selection(members={SLUG: {"UCa", "UCb"}})
    channels_path = _channels_file(
        tmp_path,
        "Education\t2012-01-05\tUCa\tAlpha\t50000\t120\t1.0\t1.0\n",
        "Education\t2013-02-06\tUCb\tBeta\t20000\t80\t2.0\t1.0\n",
        "Gaming\t2011-03-07\tUCz\tOffNiche\t90000\t400\t3.0\t1.0\n",
    )
    weeks_path = _weeks_file(
        tmp_path,
        "UCa\tEducation\t2017-01-01 00:00:00\t1000.0\t0.0\t100.0\t0.0\t10\t0\t1\n",
        "UCa\tEducation\t2017-01-08 00:00:00\t2000.0\t1000.0\t150.0\t50.0\t11\t1\t1\n",
        "UCb\tEducation\t2018-06-03 00:00:00\t500.0\t0.0\t60.0\t0.0\t5\t0\t1\n",
        "UCz\tGaming\t2017-01-01 00:00:00\t9.0\t0.0\t9.0\t0.0\t9\t0\t9\n",
    )
    hits_path = _hits_file(
        tmp_path,
        {
            "video_id": "v1",
            "channel_id": "UCa",
            "slug": SLUG,
            "upload_date": "2017-01-04",
            "relevance": 0.81,
        },
        # Same video, a niche its channel was not assigned to.
        {
            "video_id": "v1",
            "channel_id": "UCa",
            "slug": "chemical-spills",
            "upload_date": "2017-01-04",
            "relevance": 0.60,
        },
        # A channel that did not survive selection.
        {
            "video_id": "v9",
            "channel_id": "UCz",
            "slug": SLUG,
            "upload_date": "2017-01-04",
            "relevance": 0.90,
        },
    )
    return selection, channels_path, weeks_path, hits_path


def _load(engine, tmp_path):
    selection, channels_path, weeks_path, hits_path = _world(tmp_path)
    return load(
        engine,
        selection=selection,
        hits=hits_path,
        channels_path=channels_path,
        timeseries_path=weeks_path,
        run_id=RUN,
        at=AT,
    )


def test_it_refuses_a_database_not_named_backtest(engine, tmp_path):
    """A positive check, not a "is this the live URL" check. The negative form fails
    open on a copy, a second live file, or a Postgres URL; this one fails closed."""
    with pytest.raises(RefusingLiveDatabase, match="backtest"):
        _load(engine, tmp_path)


def test_it_loads_only_the_selected_channels(backtest_engine, tmp_path):
    report = _load(backtest_engine, tmp_path)

    with session_scope(backtest_engine) as session:
        loaded = set(session.scalars(sa.select(Channel.channel_id)))
    assert loaded == {"UCa", "UCb"}
    assert report.channels == 2
    assert report.channels_without_metadata == []


def test_first_seen_is_the_first_weekly_reading_not_the_join_date(backtest_engine, tmp_path):
    """`inputs.member_join` bounds membership on `first_seen`, so this is what makes
    a channel whose series starts in 2018 invisible to a 2017 decision date. The
    YouTube join date would make it visible years before any data existed."""
    _load(backtest_engine, tmp_path)

    with session_scope(backtest_engine) as session:
        rows = dict(session.execute(sa.select(Channel.channel_id, Channel.first_seen)).all())
    assert rows["UCa"].date() == date(2017, 1, 1)
    assert rows["UCb"].date() == date(2018, 6, 3)


def test_crawl_time_subscriber_counts_are_never_written_as_a_snapshot(backtest_engine, tmp_path):
    """`subscribers_cc` describes 2019-10. Landing it at any earlier `observed_date`
    is exactly the leak Phase A closed."""
    _load(backtest_engine, tmp_path)

    with session_scope(backtest_engine) as session:
        subs = set(session.scalars(sa.select(ChannelSnapshot.subs)))
    assert 50_000 not in subs
    assert subs == {100, 150, 60}


def test_weekly_rows_land_on_the_week_ending_date(backtest_engine, tmp_path):
    _load(backtest_engine, tmp_path)

    with session_scope(backtest_engine) as session:
        days = sorted(set(session.scalars(sa.select(ChannelSnapshot.observed_date))))
    assert days == [date(2017, 1, 1), date(2017, 1, 8), date(2018, 6, 3)]


def test_a_video_joins_only_the_niche_its_channel_was_assigned(backtest_engine, tmp_path):
    """The scan scores a video against every niche whose prefilter it clears. Keeping
    all of them would put one video in several clusters and double-count it in every
    supply denominator."""
    report = _load(backtest_engine, tmp_path)

    with session_scope(backtest_engine) as session:
        rows = session.execute(
            sa.select(
                ClusterMember.item_id, ClusterMember.cluster_id, ClusterMember.relevance
            ).where(ClusterMember.item_type == "video")
        ).all()
    assert rows == [("v1", SLUG, 0.81)]
    assert report.videos == 1
    assert report.video_members == 1


def test_video_publish_dates_survive(backtest_engine, tmp_path):
    """`inputs.on_niche_join` bounds on `published_at`; a NULL here would silently
    drop the video from every bounded query."""
    _load(backtest_engine, tmp_path)

    with session_scope(backtest_engine) as session:
        published = session.scalar(sa.select(Video.published_at))
    assert published.date() == date(2017, 1, 4)


def test_channel_country_is_null_not_guessed(backtest_engine, tmp_path):
    """YouNiverse has no country column. `supply.geo_concentration` must report
    itself uncomputable rather than read an all-NULL population as concentrated."""
    _load(backtest_engine, tmp_path)

    with session_scope(backtest_engine) as session:
        assert set(session.scalars(sa.select(Channel.country))) == {None}


def test_it_creates_one_cluster_per_surviving_niche(backtest_engine, tmp_path):
    report = _load(backtest_engine, tmp_path)

    with session_scope(backtest_engine) as session:
        clusters = list(session.scalars(sa.select(Cluster.cluster_id)))
        members = list(
            session.scalars(
                sa.select(ClusterMember.item_id).where(ClusterMember.item_type == "channel")
            )
        )
    assert clusters == [SLUG]
    assert sorted(members) == ["UCa", "UCb"]
    assert report.clusters == 1


def test_loading_twice_changes_nothing(backtest_engine, tmp_path):
    """Re-running a load is safe — the same rule the collectors live under."""
    _load(backtest_engine, tmp_path)
    with session_scope(backtest_engine) as session:
        before = session.scalar(sa.select(sa.func.count()).select_from(ChannelSnapshot))

    _load(backtest_engine, tmp_path)

    with session_scope(backtest_engine) as session:
        after = session.scalar(sa.select(sa.func.count()).select_from(ChannelSnapshot))
    assert before == after == 3
