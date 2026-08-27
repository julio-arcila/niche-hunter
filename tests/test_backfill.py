"""Rescuing `videos.description` from payloads we already hold.

Data rule 2 says re-normalizing history must be a query, never a re-fetch. These
tests pin the three properties that make that true in practice: the text is
actually recovered, recovering it does not rewrite the provenance of the collector
that fetched it, and the prune cannot delete the last copy (ADR-0017).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from nh.collectors.youtube_rss import parse_feed
from nh.db.models import Channel, RawRecord, Video
from nh.db.raw import encode
from nh.db.retention import LastCopyRefused, prune_raw_records
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.jobs.backfill import backfill_descriptions, extract

FIXTURES = Path(__file__).parent / "fixtures" / "youtube_rss"
FEED = (FIXTURES / "feed_real.xml").read_text()


def _seed_feed(engine, *, age_days: int = 0) -> list[dict]:
    """A stored feed payload plus the stub video rows a collector would have left."""
    entries = parse_feed(FEED)
    with session_scope(engine) as s:
        s.add(
            RawRecord(
                kind="feed",
                key="UCfeed",
                source="youtube_rss",
                run_id="collector-run",
                at=utcnow() - timedelta(days=age_days),
                **encode({"status": 200, "xml": FEED}),
            )
        )
        s.add(Channel(channel_id="UCfeed", source="youtube_rss", run_id="collector-run"))
        for entry in entries:
            s.add(
                Video(
                    video_id=entry["video_id"],
                    channel_id=entry["channel_id"],
                    title=entry["title"],
                    source="youtube_rss",
                    run_id="collector-run",
                    at=utcnow(),
                )
            )
    return entries


# -- extraction --------------------------------------------------------------


def test_the_feed_parser_now_carries_the_description():
    entries = parse_feed(FEED)
    assert any(e["description"] for e in entries)
    assert all("description" in e for e in entries)


def _without_descriptions() -> str:
    """The same feed with the description element renamed, not removed — so the
    entries still parse and the only thing missing is the text."""
    return FEED.replace("media:description>", "media:ignored>")


def test_an_entry_without_a_description_yields_none_not_empty_string():
    assert all(entry["description"] is None for entry in parse_feed(_without_descriptions()))


def test_extract_skips_entries_with_no_text():
    record = SimpleNamespace(
        kind="feed",
        codec="json",
        payload={"status": 200, "xml": _without_descriptions()},
    )

    assert extract(record) == []


# -- the backfill ------------------------------------------------------------


def test_it_recovers_descriptions_from_stored_payloads(engine):
    entries = _seed_feed(engine)
    expected = sum(1 for e in entries if e["description"])

    result = backfill_descriptions(engine)

    assert result.written == expected
    with session_scope(engine) as s:
        stored = s.scalar(
            sa.select(sa.func.count()).select_from(Video).where(Video.description.is_not(None))
        )
    assert stored == expected


def test_it_does_not_rewrite_the_provenance_of_the_original_collector(engine):
    """The run that moved the text between two of our own columns is not the run
    that fetched it. `nh.db.provenance.stamp` names this case explicitly."""
    _seed_feed(engine)

    backfill_descriptions(engine)

    with session_scope(engine) as s:
        sources = set(s.scalars(sa.select(Video.source)).all())
        run_ids = set(s.scalars(sa.select(Video.run_id)).all())
    assert sources == {"youtube_rss"}
    assert run_ids == {"collector-run"}


def test_rerunning_writes_nothing(engine):
    _seed_feed(engine)
    first = backfill_descriptions(engine)

    second = backfill_descriptions(engine)

    assert first.written > 0
    assert second.written == 0


def test_it_never_creates_a_video_row(engine):
    """A payload can name ids we do not hold; inserting a stub would give it no
    channel and the backfill's own provenance."""
    entries = _seed_feed(engine)
    with session_scope(engine) as s:
        s.execute(sa.delete(Video).where(Video.video_id == entries[0]["video_id"]))

    backfill_descriptions(engine)

    with session_scope(engine) as s:
        assert s.get(Video, entries[0]["video_id"]) is None


def test_dry_run_writes_nothing_and_records_no_job(engine):
    _seed_feed(engine)

    result = backfill_descriptions(engine, dry_run=True)

    assert result.found > 0
    assert result.written == 0
    with session_scope(engine) as s:
        assert (
            s.scalar(
                sa.select(sa.func.count()).select_from(Video).where(Video.description.is_not(None))
            )
            == 0
        )


def test_it_records_a_backfill_job_run(engine):
    _seed_feed(engine)

    backfill_descriptions(engine)

    with session_scope(engine) as s:
        row = s.execute(
            sa.text("SELECT job, source, status FROM job_runs ORDER BY id DESC LIMIT 1")
        ).one()
    assert row == ("backfill", "descriptions", "ok")


# -- the prune guard (ADR-0017) ---------------------------------------------


def test_prune_refuses_to_delete_the_last_copy_of_a_description(engine):
    _seed_feed(engine, age_days=30)

    with pytest.raises(LastCopyRefused, match="last copy"):
        prune_raw_records(engine, days=14)

    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(RawRecord)) == 1


def test_prune_proceeds_once_the_descriptions_are_stored(engine):
    _seed_feed(engine, age_days=30)
    backfill_descriptions(engine)

    result = prune_raw_records(engine, days=14)

    assert result.deleted == 1
    assert result.orphaned_descriptions == 0


def test_force_prunes_anyway_and_reports_what_it_cost(engine):
    _seed_feed(engine, age_days=30)

    result = prune_raw_records(engine, days=14, force=True)

    assert result.deleted == 1
    assert result.orphaned_descriptions > 0


def test_a_video_with_no_recoverable_text_does_not_block_the_prune_forever(engine):
    """The guard must count text the delete set actually holds, not every video
    missing a description — 1,044 of the real corpus have none in any payload, and
    a guard that can never be satisfied is a broken nightly."""
    _seed_feed(engine, age_days=30)
    backfill_descriptions(engine)
    with session_scope(engine) as s:
        s.add(
            Video(
                video_id="never_seen",
                channel_id="UCfeed",
                source="youtube_rss",
                run_id="collector-run",
                at=utcnow(),
            )
        )

    result = prune_raw_records(engine, days=14)

    assert result.deleted == 1
