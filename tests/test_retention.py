"""Payload compression and bounded retention.

Both exist because YouTube's Atom feeds carry no cache validators — no ETag, no
Last-Modified — so a conditional GET can never return 304 and every nightly poll
stores the full ~64 KB of XML per channel, near-identical to last night's.
Measured on real data: 95.8 MB of feed payloads from three runs.
"""

from __future__ import annotations

import gzip
import json
from datetime import timedelta

import pytest
import sqlalchemy as sa

from nh.db.models import RawRecord, VideoSnapshot
from nh.db.raw import CODEC_GZIP, CODEC_JSON, COMPRESS_OVER, UnknownCodec, decode, encode
from nh.db.retention import prune_raw_records, storage_report
from nh.db.session import session_scope
from nh.db.types import utcnow

SMALL = {"id": "vid1", "views": 100}
BULK = {"status": 200, "xml": "<feed>" + "<entry>padding</entry>" * 500 + "</feed>"}


def _raw(engine, kind="feed", age_days=0, payload=None):
    with session_scope(engine) as s:
        s.add(
            RawRecord(
                kind=kind,
                key=f"k{age_days}{kind}",
                source="youtube_rss",
                run_id="t",
                at=utcnow() - timedelta(days=age_days),
                **encode(payload if payload is not None else BULK),
            )
        )


# -- encoding ---------------------------------------------------------------


def test_a_small_payload_stays_readable_json():
    """Kept queryable on purpose: only bulk documents are worth trading
    inspectability for bytes."""
    columns = encode(SMALL)
    assert columns["codec"] == CODEC_JSON
    assert columns["payload"] == SMALL
    assert columns["payload_gz"] is None


def test_a_bulk_payload_is_compressed():
    columns = encode(BULK)
    assert columns["codec"] == CODEC_GZIP
    assert columns["payload"] is None
    assert len(columns["payload_gz"]) < len(json.dumps(BULK)) // 4


def test_the_threshold_is_size_not_kind():
    """A large `video` payload compresses and a small `feed` one does not — the
    rule is about bytes, so no kind has to be special-cased as it grows."""
    assert encode({"x": "a" * (COMPRESS_OVER + 1)})["codec"] == CODEC_GZIP
    assert encode({"x": "a" * 10})["codec"] == CODEC_JSON


@pytest.mark.parametrize("payload", [SMALL, BULK, {}, {"nested": {"a": [1, 2, {"b": None}]}}])
def test_every_payload_round_trips(payload, engine):
    with session_scope(engine) as s:
        s.add(RawRecord(kind="feed", key="k", source="s", run_id="r", **encode(payload)))
    with session_scope(engine) as s:
        assert decode(s.scalars(sa.select(RawRecord)).one()) == payload


def test_an_unknown_codec_is_an_error_not_a_silent_empty():
    class Fake:
        codec, payload, payload_gz = "brotli", None, b""

    with pytest.raises(UnknownCodec, match="brotli"):
        decode(Fake())


def test_the_stored_blob_is_real_gzip():
    """Inspectable with standard tools, not a bespoke format."""
    blob = encode(BULK)["payload_gz"]
    assert json.loads(gzip.decompress(blob).decode()) == BULK


# -- retention --------------------------------------------------------------


def test_aged_bulk_payloads_are_deleted(engine):
    _raw(engine, age_days=30)
    _raw(engine, age_days=1)
    result = prune_raw_records(engine, days=14)
    assert result.deleted == 1
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(RawRecord)) == 1


def test_non_bulk_kinds_are_kept_however_old(engine):
    """Search hits, videos and channels are small and stay indefinitely — the
    replay value outlasts the storage cost."""
    _raw(engine, kind="video", age_days=400, payload=SMALL)
    _raw(engine, kind="channel", age_days=400, payload=SMALL)
    assert prune_raw_records(engine, days=14).deleted == 0
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(RawRecord)) == 2


def test_snapshots_are_never_touched(engine):
    """The line that matters. Raw payloads are a replay convenience; snapshots are
    the unbackfillable asset and no retention path may reach them."""
    with session_scope(engine) as s:
        s.add(
            VideoSnapshot(
                video_id="v1",
                observed_date=(utcnow() - timedelta(days=999)).date(),
                views=10,
                source="youtube_rss",
                run_id="t",
            )
        )
    _raw(engine, age_days=999)
    prune_raw_records(engine, days=1)
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(VideoSnapshot)) == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(RawRecord)) == 0


def test_dry_run_reports_without_deleting(engine):
    _raw(engine, age_days=30)
    result = prune_raw_records(engine, days=14, dry_run=True)
    assert result.deleted == 1 and result.dry_run
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(RawRecord)) == 1


def test_a_zero_day_window_is_refused(engine):
    """Guards against a config typo silently wiping every raw payload."""
    with pytest.raises(ValueError, match="at least 1 day"):
        prune_raw_records(engine, days=0)


def test_storage_report_splits_by_kind_and_codec(engine):
    _raw(engine, kind="feed", age_days=1)
    _raw(engine, kind="video", age_days=1, payload=SMALL)
    report = {(k, c): (n, b) for k, c, n, b in storage_report(engine)}
    assert report[("feed", CODEC_GZIP)][0] == 1
    assert report[("video", CODEC_JSON)][0] == 1
    assert all(size > 0 for _, size in report.values())
