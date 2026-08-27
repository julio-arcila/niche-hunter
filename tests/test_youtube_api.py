"""youtube_api collector.

The payloads below are hand-built to the *documented* Data API v3 response shape,
not captured from the wire. That is enough to pin all the normalization logic,
because `normalize()` is pure — but it cannot catch a wrong assumption about what
the API actually returns. `scripts/record_fixtures.py` captures the real thing;
once `tests/fixtures/youtube_api/` is populated, the end-to-end tests here should
be repointed at it. Until then, treat shape (not logic) as unverified.
"""

from __future__ import annotations

import pytest
import responses
import sqlalchemy as sa

from nh.collectors.base import Raw
from nh.collectors.youtube_api import API, YouTubeApiCollector
from nh.db.models import Channel, ChannelSnapshot, Discovery, JobRun, Video, VideoSnapshot
from nh.db.session import session_scope
from nh.seeds import apply_seeds

RUN_ID = "44444444-4444-4444-4444-444444444444"

ONE_SEED = (
    {
        "slug": "aviation-disasters",
        "label": "Aviation disasters",
        "keywords": ["plane crash investigation"],
        "lang": "en",
    },
)

SEARCH_ITEM = {
    "id": {"videoId": "vid00000001"},
    "snippet": {
        "channelId": "UC00000000000000000001",
        "publishedAt": "2026-06-01T10:00:00Z",
        "title": "Plane crash investigation: the final minutes",
    },
}

VIDEO_ITEM = {
    "id": "vid00000001",
    "snippet": {
        "channelId": "UC00000000000000000001",
        "publishedAt": "2026-06-01T10:00:00Z",
        "title": "Plane crash investigation: the final minutes",
        "description": "Full breakdown. Sponsored by nobody.",
        "tags": ["aviation", "ntsb"],
        "categoryId": "27",
        "defaultAudioLanguage": "en",
    },
    "contentDetails": {"duration": "PT18M31S"},
    "statistics": {"viewCount": "125000", "likeCount": "4300", "commentCount": "512"},
    "topicDetails": {"topicCategories": ["https://en.wikipedia.org/wiki/Aviation"]},
}

CHANNEL_ITEM = {
    "id": "UC00000000000000000001",
    "snippet": {
        "title": "Air Disaster Files",
        "publishedAt": "2019-03-04T08:00:00Z",
        "country": "US",
    },
    "statistics": {"viewCount": "8200000", "subscriberCount": "42000", "videoCount": "180"},
    "brandingSettings": {"channel": {"keywords": "aviation crash ntsb"}},
    "topicDetails": {"topicCategories": ["https://en.wikipedia.org/wiki/Aviation"]},
}


def _collector(settings, engine, **kw):
    return YouTubeApiCollector(RUN_ID, settings=settings, engine=engine, **kw)


def _mock_api(search_pages=1, video_items=None, channel_items=None):
    for _ in range(search_pages * 2):  # both sort orders
        responses.add(responses.GET, f"{API}/search", json={"items": [SEARCH_ITEM]}, status=200)
    responses.add(
        responses.GET, f"{API}/videos", json={"items": video_items or [VIDEO_ITEM]}, status=200
    )
    responses.add(
        responses.GET,
        f"{API}/channels",
        json={"items": channel_items or [CHANNEL_ITEM]},
        status=200,
    )


# -- normalize: pure, no HTTP ----------------------------------------------


def test_search_hit_yields_a_discovery_row_carrying_its_sort_order(settings, engine):
    collector = _collector(settings, engine)
    batch = collector.normalize(
        Raw(
            "search_hit",
            "vid00000001",
            {"seed_id": 1, "query": "q", "order": "date", "item": SEARCH_ITEM},
        )
    )
    (snapshot,) = batch.snapshots
    assert snapshot.model is Discovery
    assert snapshot.values["order_by"] == "date"
    assert snapshot.values["seed_id"] == 1


def test_search_hit_also_yields_a_stub_video(settings, engine):
    """So a run whose enrichment is cut short by the budget still leaves every
    discovered id resolvable rather than an orphan."""
    collector = _collector(settings, engine)
    (upsert,) = collector.normalize(
        Raw(
            "search_hit",
            "vid00000001",
            {"seed_id": 1, "query": "q", "order": "date", "item": SEARCH_ITEM},
        )
    ).upserts
    assert upsert.model is Video
    assert "enriched" not in upsert.values  # never downgrade an enriched row
    assert upsert.values["title"].startswith("Plane crash")


def test_video_normalizes_duration_and_format_flags(settings, engine):
    (upsert,) = (
        _collector(settings, engine).normalize(Raw("video", "vid00000001", VIDEO_ITEM)).upserts
    )
    assert upsert.values["duration_s"] == 18 * 60 + 31
    assert upsert.values["is_short"] is False
    assert upsert.values["midroll_eligible"] is True
    assert upsert.values["enriched"] is True
    assert upsert.values["topics"] == ["Aviation"]


def test_unknown_duration_leaves_format_flags_null(settings, engine):
    item = {**VIDEO_ITEM, "contentDetails": {}}
    (upsert,) = _collector(settings, engine).normalize(Raw("video", "v", item)).upserts
    assert upsert.values["duration_s"] is None
    assert upsert.values["is_short"] is None  # unknown format, not "not a short"
    assert upsert.values["midroll_eligible"] is None


def test_shorts_tag_wins_when_duration_is_unknown(settings, engine):
    item = {**VIDEO_ITEM, "contentDetails": {}}
    item["snippet"] = {**VIDEO_ITEM["snippet"], "title": "quick clip #Shorts"}
    (upsert,) = _collector(settings, engine).normalize(Raw("video", "v", item)).upserts
    assert upsert.values["is_short"] is True


def test_absent_statistics_land_as_null_not_zero(settings, engine):
    item = {**VIDEO_ITEM, "statistics": {}}
    (snapshot,) = _collector(settings, engine).normalize(Raw("video", "v", item)).snapshots
    assert snapshot.values["views"] is None
    assert snapshot.values["likes"] is None


def test_hidden_subscriber_count_is_null(settings, engine):
    item = {**CHANNEL_ITEM}
    item["statistics"] = {**CHANNEL_ITEM["statistics"], "hiddenSubscriberCount": True}
    (snapshot,) = _collector(settings, engine).normalize(Raw("channel", item["id"], item)).snapshots
    assert snapshot.values["subs"] is None
    assert snapshot.values["total_views"] == 8_200_000  # other stats still read


def test_uploads_playlist_is_derived_not_fetched(settings, engine):
    (upsert,) = (
        _collector(settings, engine)
        .normalize(Raw("channel", CHANNEL_ITEM["id"], CHANNEL_ITEM))
        .upserts
    )
    assert upsert.values["uploads_playlist"] == "UU00000000000000000001"


def test_unknown_raw_kind_is_an_error(settings, engine):
    with pytest.raises(ValueError, match="unknown raw kind"):
        _collector(settings, engine).normalize(Raw("nonsense", "k", {}))


# -- end to end -------------------------------------------------------------


@responses.activate
def test_a_full_run_writes_every_table(settings, engine):
    apply_seeds(engine, ONE_SEED)
    _mock_api()
    record = _collector(settings, engine).run()
    assert record.status == "ok", record.error
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Video)) == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(Channel)) == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(VideoSnapshot)) == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(ChannelSnapshot)) == 1
        video = s.get(Video, "vid00000001")
    # the stub from search and the rich row from videos.list, merged in one batch
    assert video.enriched is True
    assert video.duration_s == 1111


@responses.activate
def test_both_sort_orders_are_recorded(settings, engine):
    apply_seeds(engine, ONE_SEED)
    _mock_api()
    _collector(settings, engine).run()
    with session_scope(engine) as s:
        orders = sorted(s.scalars(sa.select(Discovery.order_by)))
    assert orders == ["date", "viewCount"]


@responses.activate
def test_quota_is_charged_only_for_successful_calls(settings, engine):
    apply_seeds(engine, ONE_SEED)
    responses.add(responses.GET, f"{API}/search", json={}, status=503)  # retried, not charged
    _mock_api()
    collector = _collector(settings, engine)
    collector.run()
    # 2 searches (100 each) + 1 videos + 1 channels; the 503 costs nothing
    assert collector.quota.used == 202
    assert collector.quota.by_endpoint == {"search": 200, "videos": 1, "channels": 1}


@responses.activate
def test_job_run_records_the_quota_spend(settings, engine):
    apply_seeds(engine, ONE_SEED)
    _mock_api()
    _collector(settings, engine).run()
    with session_scope(engine) as s:
        run = s.scalars(sa.select(JobRun)).one()
    assert run.quota_used == 202
    assert run.quota_budget == settings.yt_quota_budget


@responses.activate
def test_rerunning_the_same_day_adds_no_duplicate_rows(settings, engine):
    apply_seeds(engine, ONE_SEED)
    _mock_api()
    _collector(settings, engine).run()
    responses.reset()
    _mock_api()
    _collector(settings, engine).run()
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(VideoSnapshot)) == 1
        assert s.scalar(sa.select(sa.func.count()).select_from(Discovery)) == 2  # 2 orders, once


@responses.activate
def test_a_tiny_budget_stops_cleanly_and_keeps_what_it_got(settings, engine):
    """Running out of quota is a degraded run, not a failure. The rows already
    collected are still worth keeping and job_runs.quota_used tells the story."""
    settings.yt_quota_budget = 100  # exactly one search
    apply_seeds(engine, ONE_SEED)
    _mock_api()
    record = _collector(settings, engine).run()
    assert record.status == "ok"
    assert record.quota_used == 100
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(Discovery)) == 1


def test_without_an_api_key_the_source_is_skipped(settings, engine):
    settings.yt_api_key = None
    record = _collector(settings, engine).run()
    assert record.status == "skipped"


@responses.activate
def test_no_active_seeds_is_a_clean_empty_run(settings, engine):
    record = _collector(settings, engine).run()
    assert record.status == "ok"
    assert record.rows_upserted == 0


# -- the quota is per day, not per run --------------------------------------


def _prior_run(engine, units, hours_ago=1, source="youtube_api"):
    from datetime import timedelta

    from nh.db.models import JobRun
    from nh.db.types import utcnow

    with session_scope(engine) as s:
        s.add(
            JobRun(
                run_id="earlier",
                job="nightly",
                source=source,
                status="ok",
                started_at=utcnow() - timedelta(hours=hours_ago),
                quota_used=units,
            )
        )


def test_todays_earlier_spend_is_deducted_from_this_runs_budget(settings, engine):
    """Without this, a manual retry sails past the real ceiling and gets throttled
    by Google rather than stopping cleanly on our own budget."""
    _prior_run(engine, 9_000)
    collector = _collector(settings, engine)
    assert collector.quota.budget == settings.yt_quota_budget - 9_000


def test_a_fully_spent_day_leaves_a_zero_budget(settings, engine):
    _prior_run(engine, 9_500)
    assert _collector(settings, engine).quota.budget == 0


def test_the_budget_never_goes_negative(settings, engine):
    _prior_run(engine, 99_999)
    assert _collector(settings, engine).quota.budget == 0


def test_another_sources_spend_does_not_count(settings, engine):
    _prior_run(engine, 5_000, source="youtube_rss")
    assert _collector(settings, engine).quota.budget == settings.yt_quota_budget


def test_spend_before_midnight_pacific_does_not_count(settings, engine):
    """The window is the Pacific quota day, not UTC and not local midnight."""
    _prior_run(engine, 9_000, hours_ago=48)
    assert _collector(settings, engine).quota.budget == settings.yt_quota_budget


@responses.activate
def test_an_exhausted_day_collects_nothing_but_does_not_fail(settings, engine):
    apply_seeds(engine, ONE_SEED)
    _prior_run(engine, 9_500)
    _mock_api()
    record = _collector(settings, engine).run()
    assert record.status == "ok"
    assert record.quota_used == 0
    assert len(responses.calls) == 0  # never even asked


@responses.activate
def test_an_upstream_quota_403_stops_cleanly_rather_than_burning_retries(settings, engine):
    """Google's real ceiling is not our budget. Retrying a quotaExceeded only
    wastes time and buries the reason under 'retries exhausted'."""
    apply_seeds(engine, ONE_SEED)
    responses.add(
        responses.GET,
        f"{API}/search",
        json={"error": {"errors": [{"reason": "quotaExceeded"}]}},
        status=403,
    )
    record = _collector(settings, engine).run()
    assert record.status == "ok"
    assert len(responses.calls) == 1  # one attempt, no retry storm
