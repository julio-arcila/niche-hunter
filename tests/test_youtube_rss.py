"""youtube_rss collector.

`tests/fixtures/youtube_rss/feed.xml` is hand-built to the documented Atom shape,
including a third entry with no `media:community` block — a video uploaded minutes
ago, before YouTube attaches statistics. That case is the whole reason views must
be nullable: writing 0 there would look like a genuine flop forever after.
"""

from __future__ import annotations

from pathlib import Path

import requests
import responses
import sqlalchemy as sa

from nh.collectors.base import Raw
from nh.collectors.youtube_rss import FAIL_LIMIT, FEED_URL, YouTubeRssCollector, parse_feed
from nh.db.models import Channel, FeedState, Video, VideoSnapshot
from nh.db.session import session_scope

RUN_ID = "55555555-5555-5555-5555-555555555555"
CHANNEL = "UC00000000000000000001"
FEED_XML = (Path(__file__).parent / "fixtures" / "youtube_rss" / "feed.xml").read_text()


def _collector(settings, engine):
    settings.rss_workers = 1  # keep `responses` single-threaded and the test fast
    settings.rss_jitter_s = (0.0, 0.0)
    return YouTubeRssCollector(RUN_ID, settings=settings, engine=engine)


def _known_channel(engine, channel_id: str = CHANNEL) -> None:
    with session_scope(engine) as s:
        s.add(Channel(channel_id=channel_id, title="Air Disaster Files", source="test", run_id="t"))


def _raw(status=200, xml=FEED_XML, prior_fail_count=0):
    return Raw(
        kind="feed",
        key=CHANNEL,
        payload={
            "status": status,
            "xml": xml,
            "etag": 'W/"abc"',
            "last_modified": "Wed, 26 Aug 2026 22:00:00 GMT",
            "prior_fail_count": prior_fail_count,
            "fetched_at": "2026-08-27T09:00:00+00:00",
        },
    )


# -- parsing: pure ----------------------------------------------------------


def test_parse_reads_every_entry():
    entries = parse_feed(FEED_XML)
    assert [e["video_id"] for e in entries] == ["vid00000001", "vid00000002", "vid00000003"]
    assert entries[0]["views"] == 125_000
    assert entries[0]["likes"] == 4_300


def test_a_video_with_no_statistics_block_yields_null_not_zero():
    """A just-uploaded video has no media:community. Zero would be a lie that
    survives forever in the series."""
    entry = parse_feed(FEED_XML)[2]
    assert entry["views"] is None
    assert entry["likes"] is None


# -- normalize: pure --------------------------------------------------------


def test_a_healthy_poll_yields_videos_snapshots_and_feed_state(settings, engine):
    batch = _collector(settings, engine).normalize(_raw())
    assert len(batch.snapshots) == 3
    models = {u.model for u in batch.upserts}
    assert models == {FeedState, Video}
    state = next(u for u in batch.upserts if u.model is FeedState)
    assert state.values["fail_count"] == 0
    assert state.values["last_status"] == 200


def test_rss_never_writes_the_enriched_flag(settings, engine):
    """Omitted, so the column default covers insert and an existing True survives
    update — a re-poll must never downgrade a row youtube_api enriched."""
    batch = _collector(settings, engine).normalize(_raw())
    for upsert in batch.upserts:
        if upsert.model is Video:
            assert "enriched" not in upsert.values
            assert "duration_s" not in upsert.values


def test_a_304_updates_feed_state_only(settings, engine):
    batch = _collector(settings, engine).normalize(_raw(status=304, xml=None))
    assert batch.snapshots == []
    assert len(batch.upserts) == 1
    assert batch.upserts[0].values["fail_count"] == 0  # 304 is a healthy poll


def test_a_failure_increments_the_prior_fail_count(settings, engine):
    batch = _collector(settings, engine).normalize(_raw(status=None, xml=None, prior_fail_count=2))
    assert batch.upserts[0].values["fail_count"] == 3


def test_a_success_resets_the_fail_count(settings, engine):
    batch = _collector(settings, engine).normalize(_raw(prior_fail_count=4))
    state = next(u for u in batch.upserts if u.model is FeedState)
    assert state.values["fail_count"] == 0


def test_feed_state_never_writes_hot(settings, engine):
    """A channel flagged hot by hand must survive the nightly poll."""
    batch = _collector(settings, engine).normalize(_raw())
    assert "hot" not in batch.upserts[0].values


# -- end to end -------------------------------------------------------------


@responses.activate
def test_a_full_poll_persists_the_series(settings, engine):
    _known_channel(engine)
    responses.add(responses.GET, FEED_URL.format(CHANNEL), body=FEED_XML, status=200)
    record = _collector(settings, engine).run()
    assert record.status == "ok", record.error
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(VideoSnapshot)) == 3
        assert s.scalar(sa.select(sa.func.count()).select_from(Video)) == 3
        assert (
            s.scalar(sa.select(VideoSnapshot.views).where(VideoSnapshot.video_id == "vid00000001"))
            == 125_000
        )


@responses.activate
def test_rss_does_not_clobber_enrichment(settings, engine):
    """The guarantee the whole upsert design exists for."""
    _known_channel(engine)
    with session_scope(engine) as s:
        s.add(
            Video(
                video_id="vid00000001",
                channel_id=CHANNEL,
                title="Old title",
                duration_s=1111,
                tags=["aviation"],
                enriched=True,
                source="youtube_api",
                run_id="earlier",
            )
        )
    responses.add(responses.GET, FEED_URL.format(CHANNEL), body=FEED_XML, status=200)
    _collector(settings, engine).run()
    with session_scope(engine) as s:
        video = s.get(Video, "vid00000001")
    assert video.title == "Plane crash investigation: the final minutes"  # supplied -> updated
    assert video.duration_s == 1111  # not supplied -> preserved
    assert video.tags == ["aviation"]
    assert video.enriched is True  # never downgraded


@responses.activate
def test_a_circuit_broken_channel_is_not_polled(settings, engine):
    _known_channel(engine)
    with session_scope(engine) as s:
        s.add(FeedState(channel_id=CHANNEL, fail_count=FAIL_LIMIT))
    _collector(settings, engine).run()
    assert len(responses.calls) == 0


@responses.activate
def test_one_dead_feed_does_not_end_the_run(settings, engine):
    _known_channel(engine)
    _known_channel(engine, "UC00000000000000000002")
    responses.add(responses.GET, FEED_URL.format(CHANNEL), body=FEED_XML, status=200)
    responses.add(
        responses.GET,
        FEED_URL.format("UC00000000000000000002"),
        body=requests.exceptions.ConnectionError("refused"),
    )
    record = _collector(settings, engine).run()
    assert record.status == "ok"
    with session_scope(engine) as s:
        states = dict(s.execute(sa.select(FeedState.channel_id, FeedState.fail_count)).all())
        assert s.scalar(sa.select(sa.func.count()).select_from(VideoSnapshot)) == 3
    assert states[CHANNEL] == 0
    assert states["UC00000000000000000002"] == 1


@responses.activate
def test_rerunning_the_same_day_keeps_the_first_reading(settings, engine):
    _known_channel(engine)
    responses.add(responses.GET, FEED_URL.format(CHANNEL), body=FEED_XML, status=200)
    _collector(settings, engine).run()
    bumped = FEED_XML.replace('views="125000"', 'views="999999"')
    responses.reset()
    responses.add(responses.GET, FEED_URL.format(CHANNEL), body=bumped, status=200)
    _collector(settings, engine).run()
    with session_scope(engine) as s:
        rows = s.scalars(
            sa.select(VideoSnapshot.views).where(VideoSnapshot.video_id == "vid00000001")
        ).all()
    assert rows == [125_000]  # one row per day per source; first reading stands


@responses.activate
def test_no_known_channels_is_a_clean_empty_run(settings, engine):
    record = _collector(settings, engine).run()
    assert record.status == "ok"
    assert record.snapshots_written == 0


@responses.activate
def test_an_exception_outside_the_requests_hierarchy_still_costs_only_one_feed(settings, engine):
    """A worker thread that raises abandons every feed queued behind it, so the
    catch in _poll is deliberately broad rather than requests-specific."""
    _known_channel(engine)
    _known_channel(engine, "UC00000000000000000002")
    responses.add(responses.GET, FEED_URL.format(CHANNEL), body=FEED_XML, status=200)
    responses.add(
        responses.GET,
        FEED_URL.format("UC00000000000000000002"),
        body=OSError("dns exploded outside requests"),
    )
    record = _collector(settings, engine).run()
    assert record.status == "ok"
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(VideoSnapshot)) == 3


# -- the run's day boundary (ADR-0062) ------------------------------------------


def _frozen_clock(monkeypatch, instant):
    """Pin the clock `past_deadline()` reads. `base.utcnow` is the one read the deadline
    makes; `fetched_at` in the payload comes from the collector module's own import and is
    not what is under test."""
    from nh.collectors import base

    monkeypatch.setattr(base, "utcnow", lambda: instant)


def test_the_deadline_is_utc_midnight_after_the_run_start_day(settings, engine):
    """Derived from `observed_at`, never from a wall-clock cap: a run started at 14:10 UTC
    on DAY may take readings until 00:00 UTC on DAY+1 — 19:00 local — and no later."""
    from datetime import UTC, datetime

    from tests.conftest_features import DAY

    started = datetime.combine(DAY, datetime.min.time(), tzinfo=UTC).replace(hour=14, minute=10)
    collector = YouTubeRssCollector(RUN_ID, settings=settings, engine=engine, observed_at=started)
    assert collector.deadline == datetime(2026, 8, 28, 0, 0, tzinfo=UTC)


@responses.activate
def test_past_the_deadline_no_feed_is_polled_and_the_run_is_degraded(settings, engine, monkeypatch):
    """2026-09-20, replayed: the run started on its day and the clock is now the next
    morning. Every feed is skipped — no request, no `feed_state` row, no `fail_count` —
    and the run says so in `job_runs` rather than reading `ok`."""
    from datetime import UTC, datetime, timedelta

    _known_channel(engine)
    _known_channel(engine, "UC00000000000000000002")
    responses.add(responses.GET, FEED_URL.format(CHANNEL), body=FEED_XML, status=200)
    collector = _collector(settings, engine)
    _frozen_clock(monkeypatch, collector.deadline + timedelta(hours=8, minutes=42))

    record = collector.run()

    assert len(responses.calls) == 0
    assert record.status == "degraded"
    assert "2 of 2 feeds not polled" in record.error
    assert record.snapshots_written == 0
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(FeedState)) == 0
    # And a clock inside the day polls as before — the deadline is a boundary, not a cap.
    _frozen_clock(monkeypatch, collector.deadline - timedelta(hours=1))
    assert not collector.past_deadline()
    assert collector.deadline.tzinfo is UTC
    assert collector.deadline.time() == datetime.min.time()


@responses.activate
def test_a_feed_skipped_for_the_deadline_keeps_its_prior_fail_count(settings, engine, monkeypatch):
    """A channel three failures from the breaker must not be pushed toward FAIL_LIMIT by the
    run's own lateness: skipped is not failed."""
    from datetime import timedelta

    _known_channel(engine)
    with session_scope(engine) as s:
        s.add(FeedState(channel_id=CHANNEL, fail_count=FAIL_LIMIT - 3))
    collector = _collector(settings, engine)
    _frozen_clock(monkeypatch, collector.deadline + timedelta(minutes=1))

    collector.run()

    with session_scope(engine) as s:
        state = s.get(FeedState, CHANNEL)
    assert state.fail_count == FAIL_LIMIT - 3
    assert state.last_polled is None
