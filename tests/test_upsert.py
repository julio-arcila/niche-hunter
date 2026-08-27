"""Heterogeneous batches.

A collector routinely emits rows of different shapes for the same model in one
batch: `youtube_api` sees a video first as a four-column search result, then as a
fully enriched `videos.list` item. Before `_group()` bucketed on the column set,
both landed in a single multi-row VALUES — which either fails to bind or drops the
rich row's columns from the SET clause, because `upsert()` reads them off row zero.
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa

from nh.collectors.base import Batch, Collector, Raw, Upsert
from nh.db.models import RawRecord, Video
from nh.db.session import session_scope

RUN_ID = "33333333-3333-3333-3333-333333333333"

SPARSE = {"video_id": "vid1", "channel_id": "UC0", "title": "From search"}
RICH = {
    "video_id": "vid1",
    "channel_id": "UC0",
    "title": "Enriched",
    "duration_s": 511,
    "is_short": False,
    "tags": ["aviation"],
    "enriched": True,
}


class MixedShapeCollector(Collector):
    source = "youtube_api"

    def __init__(self, *args, order=(SPARSE, RICH), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.order = order

    def fetch(self) -> Iterable[Raw]:
        for i, payload in enumerate(self.order):
            yield Raw(kind="video", key=f"k{i}", payload=payload)

    def normalize(self, raw: Raw) -> Batch:
        return Batch(upserts=[Upsert(Video, dict(raw.payload))])


def _video(engine):
    with session_scope(engine) as s:
        return s.get(Video, "vid1")


def test_sparse_and_rich_rows_for_one_model_both_persist(engine, settings):
    record = MixedShapeCollector(RUN_ID, settings=settings, engine=engine).run()
    assert record.status == "ok", record.error
    video = _video(engine)
    assert video.title == "Enriched"
    assert video.duration_s == 511
    assert video.tags == ["aviation"]


def test_a_later_sparse_row_does_not_null_enriched_columns(engine, settings):
    """The ordering that actually bites: RSS re-polls a video the API already
    enriched. The sparse write must touch only the columns it supplies."""
    collector = MixedShapeCollector(RUN_ID, settings=settings, engine=engine, order=(RICH, SPARSE))
    record = collector.run()
    assert record.status == "ok", record.error
    video = _video(engine)
    assert video.title == "From search"  # supplied, so updated
    assert video.duration_s == 511  # not supplied, so preserved
    assert video.tags == ["aviation"]
    assert video.enriched is True


def test_both_shapes_are_counted_as_upserts(engine, settings):
    record = MixedShapeCollector(RUN_ID, settings=settings, engine=engine).run()
    assert record.rows_upserted == 2


def test_raw_records_are_written_for_every_payload(engine, settings):
    MixedShapeCollector(RUN_ID, settings=settings, engine=engine).run()
    with session_scope(engine) as s:
        raws = s.scalars(sa.select(RawRecord).order_by(RawRecord.key)).all()
    assert [r.key for r in raws] == ["k0", "k1"]
    assert raws[0].payload == SPARSE
    assert all(r.run_id == RUN_ID and r.source == "youtube_api" for r in raws)


# -- bind-parameter ceiling -------------------------------------------------


class FanOutCollector(Collector):
    """One payload, many rows — the shape youtube_rss has, where a single feed
    yields ~15 videos. FLUSH_EVERY counts raws, so 500 feeds became ~7,500 Video
    upserts in one statement and blew past SQLite's 32,766 bind parameters."""

    source = "youtube_rss"

    def __init__(self, *args, rows_per_raw=1_000, raws=8, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.rows_per_raw, self.raws = rows_per_raw, raws

    def fetch(self):
        for i in range(self.raws):
            yield Raw(kind="feed", key=f"UC{i}", payload={"n": i})

    def normalize(self, raw: Raw) -> Batch:
        base = raw.payload["n"] * self.rows_per_raw
        return Batch(
            upserts=[
                Upsert(
                    Video,
                    {
                        "video_id": f"v{base + j:09d}",
                        "channel_id": raw.key,
                        "title": f"video {base + j}",
                        "duration_s": 600,
                        "category_id": "27",
                        "audio_lang": "en",
                        "is_short": False,
                    },
                )
                for j in range(self.rows_per_raw)
            ]
        )


def test_a_wide_batch_past_the_bind_parameter_ceiling_still_writes(engine, settings):
    """8,000 rows x 10 columns is ~80,000 bind parameters — well past SQLite's
    32,766. The write layer chunks rather than the caller capping batch size,
    because a collector cannot know how wide its rows are."""
    record = FanOutCollector(RUN_ID, settings=settings, engine=engine).run()
    assert record.status == "ok", record.error
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Video)) == 8_000
    assert record.rows_upserted == 8_000


def test_chunking_does_not_break_conflict_handling(engine, settings):
    """Re-running must still update in place, not duplicate, across chunks."""
    FanOutCollector(RUN_ID, settings=settings, engine=engine).run()
    FanOutCollector(RUN_ID, settings=settings, engine=engine).run()
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Video)) == 8_000
