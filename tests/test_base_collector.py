"""The Collector contract, exercised against a fake source.

These tests are the enforcement mechanism for .claude/rules/data.md. If a change
to base.py lets a collector skip provenance, duplicate a snapshot, mutate one, or
kill the nightly job on a source outage, one of these goes red.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest
import sqlalchemy as sa

from nh.collectors.base import FLUSH_EVERY, Batch, Collector, Raw, Snapshot, Upsert
from nh.collectors.quota import QuotaExhausted, QuotaLedger
from nh.db.models import Channel, ChannelSnapshot, JobRun, RawRecord, Video, VideoSnapshot
from nh.db.session import AppendOnlyViolation, session_scope

RUN_ID = "11111111-1111-1111-1111-111111111111"


class FakeCollector(Collector):
    """One channel and one of its videos, with no network anywhere."""

    source = "youtube_api"
    quota_budget = 100

    def __init__(self, *args, views: int = 1_000, payloads: int = 1, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.views = views
        self.payloads = payloads

    def fetch(self) -> Iterable[Raw]:
        for i in range(self.payloads):
            self.quota.spend(1, "videos.list")
            yield Raw(
                kind="video",
                key=f"vid{i}",
                payload={"id": f"vid{i}", "channelId": "UC0", "views": self.views},
            )

    def normalize(self, raw: Raw) -> Batch:
        vid, cid = raw.payload["id"], raw.payload["channelId"]
        return Batch(
            upserts=[
                Upsert(Channel, {"channel_id": cid, "title": "Fake Channel"}),
                Upsert(Video, {"video_id": vid, "channel_id": cid, "title": f"Video {vid}"}),
            ],
            snapshots=[
                Snapshot(VideoSnapshot, {"video_id": vid, "views": raw.payload["views"]}),
                Snapshot(ChannelSnapshot, {"channel_id": cid, "subs": None}),
            ],
        )


class ExplodingCollector(FakeCollector):
    def fetch(self) -> Iterable[Raw]:
        raise ConnectionError("source is down")


def _count(engine, model) -> int:
    with session_scope(engine) as s:
        return s.scalar(sa.select(sa.func.count()).select_from(model))


# -- provenance -------------------------------------------------------------


def test_every_written_row_carries_source_run_id_and_at(engine, settings):
    FakeCollector(RUN_ID, settings=settings, engine=engine).run()
    with session_scope(engine) as s:
        for model in (Channel, Video, VideoSnapshot, RawRecord):
            row = s.scalars(sa.select(model)).first()
            assert row is not None, model
            assert row.run_id == RUN_ID
            assert row.source == "youtube_api"
            assert row.at is not None


def test_raw_payload_is_stored_before_normalization(engine, settings):
    FakeCollector(RUN_ID, settings=settings, engine=engine).run()
    with session_scope(engine) as s:
        raw = s.scalars(sa.select(RawRecord)).one()
    assert raw.kind == "video"
    assert raw.payload == {"id": "vid0", "channelId": "UC0", "views": 1_000}


# -- idempotency ------------------------------------------------------------


def test_rerunning_the_same_day_does_not_duplicate_entities(engine, settings):
    FakeCollector(RUN_ID, settings=settings, engine=engine).run()
    FakeCollector("22222222-2222-2222-2222-222222222222", settings=settings, engine=engine).run()
    assert _count(engine, Channel) == 1
    assert _count(engine, Video) == 1


def test_rerunning_the_same_day_does_not_duplicate_or_overwrite_snapshots(engine, settings):
    """The series must gain no duplicate point and lose no original reading."""
    FakeCollector(RUN_ID, settings=settings, engine=engine, views=1_000).run()
    FakeCollector(RUN_ID, settings=settings, engine=engine, views=9_999).run()
    with session_scope(engine) as s:
        rows = s.scalars(sa.select(VideoSnapshot)).all()
    assert len(rows) == 1
    assert rows[0].views == 1_000  # first reading of the day wins; never rewritten


def test_upsert_updates_supplied_columns_without_nulling_the_rest(engine, settings):
    """INSERT OR REPLACE (the prototypes' choice) would blank `country` here."""
    with session_scope(engine) as s:
        s.add(
            Channel(
                channel_id="UC0",
                title="Old",
                country="US",
                source="seed",
                run_id="seed",
            )
        )
    FakeCollector(RUN_ID, settings=settings, engine=engine).run()
    with session_scope(engine) as s:
        channel = s.get(Channel, "UC0")
    assert channel.title == "Fake Channel"  # updated
    assert channel.country == "US"  # preserved, not clobbered


# -- append-only ------------------------------------------------------------


def test_updating_a_snapshot_raises(engine, settings):
    FakeCollector(RUN_ID, settings=settings, engine=engine).run()
    with pytest.raises(AppendOnlyViolation), session_scope(engine) as s:
        s.scalars(sa.select(VideoSnapshot)).one().views = 42


def test_deleting_a_snapshot_raises(engine, settings):
    FakeCollector(RUN_ID, settings=settings, engine=engine).run()
    with pytest.raises(AppendOnlyViolation), session_scope(engine) as s:
        s.delete(s.scalars(sa.select(VideoSnapshot)).one())


def test_snapshot_written_to_a_mutable_model_is_rejected(engine, settings):
    class Sloppy(FakeCollector):
        def normalize(self, raw: Raw) -> Batch:
            return Batch(snapshots=[Snapshot(Channel, {"channel_id": "UC0"})])

    record = Sloppy(RUN_ID, settings=settings, engine=engine).run()
    assert record.status == "failed"
    assert "does not inherit AppendOnly" in record.error


# -- absent data ------------------------------------------------------------


def test_null_measures_stay_null(engine, settings):
    FakeCollector(RUN_ID, settings=settings, engine=engine).run()
    with session_scope(engine) as s:
        snap = s.scalars(sa.select(ChannelSnapshot)).one()
    assert snap.subs is None  # hidden subscriber count, not zero subscribers


# -- outage handling --------------------------------------------------------


def test_a_source_outage_is_recorded_not_raised(engine, settings):
    record = ExplodingCollector(RUN_ID, settings=settings, engine=engine).run()
    assert record.status == "failed"
    assert "ConnectionError" in record.error
    assert record.finished_at is not None


def test_raise_on_error_is_available_for_debugging(engine, settings):
    with pytest.raises(ConnectionError):
        ExplodingCollector(RUN_ID, settings=settings, engine=engine).run(raise_on_error=True)


def test_unconfigured_source_is_skipped_not_failed(engine, settings):
    settings.yt_api_key = None
    record = FakeCollector(RUN_ID, settings=settings, engine=engine).run()
    assert record.status == "skipped"
    assert _count(engine, RawRecord) == 0


def test_job_run_records_quota_and_row_counts(engine, settings):
    FakeCollector(RUN_ID, settings=settings, engine=engine, payloads=3).run()
    with session_scope(engine) as s:
        run = s.scalars(sa.select(JobRun)).one()
    assert run.status == "ok"
    assert run.quota_used == 3
    assert run.quota_budget == 100
    assert run.raw_written == 3
    assert run.snapshots_written == 4  # 3 distinct videos + 1 channel (deduped by day)


# -- quota ------------------------------------------------------------------


def test_quota_ledger_refuses_to_overspend():
    ledger = QuotaLedger(budget=100)
    ledger.spend(100, "search.list")
    assert ledger.remaining == 0
    with pytest.raises(QuotaExhausted):
        ledger.spend(1, "videos.list")
    assert ledger.by_endpoint == {"search.list": 100}


def test_quota_ledger_is_per_instance_not_global():
    """The prototype's module-level `Q = Quota()` could not be reset between
    runs or reported per collector."""
    a, b = QuotaLedger(100), QuotaLedger(100)
    a.spend(50)
    assert b.used == 0


# -- partial-run durability -------------------------------------------------


class DiesMidRunCollector(FakeCollector):
    """Yields past one flush boundary, then dies — a feed timing out at 700 of 800."""

    def fetch(self) -> Iterable[Raw]:
        for i in range(FLUSH_EVERY + 100):
            yield Raw(
                kind="video",
                key=f"vid{i}",
                payload={"id": f"vid{i}", "channelId": "UC0", "views": i},
            )
        raise ConnectionError("source died two thirds of the way through")


def test_a_crash_midway_keeps_everything_already_flushed(engine, settings):
    """The rows written before the failure are unbackfillable; losing them to a
    rollback would defeat the whole point of collecting nightly."""
    record = DiesMidRunCollector(RUN_ID, settings=settings, engine=engine).run()
    assert record.status == "failed"
    assert _count(engine, VideoSnapshot) == FLUSH_EVERY
    assert _count(engine, Video) == FLUSH_EVERY


def test_the_job_run_row_survives_a_crash(engine, settings):
    DiesMidRunCollector(RUN_ID, settings=settings, engine=engine).run()
    with session_scope(engine) as s:
        run = s.scalars(sa.select(JobRun)).one()
    assert run.status == "failed"
    assert "ConnectionError" in run.error
    assert run.snapshots_written == FLUSH_EVERY + 1  # 500 videos + 1 channel, deduped by day


def test_exhausting_a_ledger_stops_further_spending_without_charging():
    ledger = QuotaLedger(budget=1_000)
    ledger.spend(200, "search.list")
    ledger.exhaust()
    assert ledger.used == 200  # nothing fabricated
    assert ledger.remaining == 0
    assert not ledger.can_afford(1)
