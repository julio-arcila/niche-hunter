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
import requests
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


# -- the geo basis is sent, not inferred (ADR-0037) --------------------------


@responses.activate
def test_discovery_sends_the_seeds_stated_geo_as_region_code(settings, engine):
    """Omitting regionCode is not neutral — the API's own reference documents a
    US default on the response's regionCode field — so the basis must be sent
    explicitly when the seed states one, and recorded in the raw payload."""
    apply_seeds(engine, ({**ONE_SEED[0], "geo": "US"},))
    _mock_api()
    collector = _collector(settings, engine)
    raws = [r for r in collector.fetch() if r.kind == "search_hit"]
    searches = [c.request.url for c in responses.calls if "/search" in c.request.url]
    assert searches and all("regionCode=US" in url for url in searches)
    assert all(r.payload["region"] == "US" for r in raws)


@responses.activate
def test_a_seed_without_a_geo_sends_no_region_code(settings, engine):
    """No invented geo becomes a request parameter (ADR-0024's rule, kept): a seed
    that states no market accepts the server default and records that as None."""
    apply_seeds(engine, ONE_SEED)  # no geo key
    _mock_api()
    collector = _collector(settings, engine)
    raws = [r for r in collector.fetch() if r.kind == "search_hit"]
    searches = [c.request.url for c in responses.calls if "/search" in c.request.url]
    assert searches and all("regionCode" not in url for url in searches)
    assert all(r.payload["region"] is None for r in raws)


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


def _prior_run(engine, units, *, same_quota_day=True, source="youtube_api"):
    """An earlier run, placed relative to the **quota day** rather than to now.

    An earlier version wrote the row at `utcnow() - 1 hour` as a stand-in for
    "earlier today". That is true for 23 hours a day and false for the one that
    matters: YouTube's quota resets at midnight America/Los_Angeles, so between
    00:00 and 01:00 Pacific a run "an hour ago" belongs to the *previous* quota day
    and is correctly not deducted. The suite went red at 00:50 Pacific on
    2026-08-28 — the code was right and the test was wrong, in the window where the
    behaviour it covers is most consequential.

    So the row is anchored to Pacific midnight explicitly, which is what
    `_spent_today` computes and therefore what these tests are really about.
    """
    from datetime import UTC, timedelta

    from nh.collectors.youtube_api import PACIFIC
    from nh.db.models import JobRun
    from nh.db.types import utcnow

    midnight = utcnow().astimezone(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    started = midnight + timedelta(minutes=1) if same_quota_day else midnight - timedelta(hours=1)
    with session_scope(engine) as s:
        s.add(
            JobRun(
                run_id="earlier",
                job="nightly",
                source=source,
                status="ok",
                started_at=started.astimezone(UTC),
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
    _prior_run(engine, 9_000, same_quota_day=False)
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


# -- enrichment backfill (ADR-0012) -----------------------------------------


def _unenriched(engine, *video_ids, channel="UC00000000000000000001"):
    from nh.db.models import Video

    with session_scope(engine) as s:
        for vid in video_ids:
            s.add(
                Video(
                    video_id=vid,
                    channel_id=channel,
                    title=vid,
                    enriched=False,
                    source="youtube_rss",
                    run_id="rss",
                )
            )


def _video_payload(video_id):
    item = {**VIDEO_ITEM, "id": video_id}
    return item


@responses.activate
def test_rss_discovered_videos_get_enriched(settings, engine):
    """The whole point: a feed gives no duration, so is_short and
    midroll_eligible stay NULL and every format-sensitive metric excludes it."""
    from nh.db.models import Video

    _unenriched(engine, "backfill001")
    responses.add(
        responses.GET, f"{API}/videos", json={"items": [_video_payload("backfill001")]}, status=200
    )
    record = _collector(settings, engine).run()
    assert record.status == "ok", record.error
    with session_scope(engine) as s:
        video = s.get(Video, "backfill001")
    assert video.enriched is True
    assert video.duration_s == 1111
    assert video.is_short is False


@responses.activate
def test_the_backfill_runs_after_discovery_not_before(settings, engine):
    """Discovery is the expensive, irreplaceable stage; it must always spend
    first, so the backfill can only ever consume what is left."""
    apply_seeds(engine, ONE_SEED)
    _unenriched(engine, "backfill001")
    _mock_api()
    responses.add(
        responses.GET, f"{API}/videos", json={"items": [_video_payload("backfill001")]}, status=200
    )
    _collector(settings, engine).run()
    paths = [c.request.url.split("?")[0].rsplit("/", 1)[-1] for c in responses.calls]
    assert paths.index("search") < paths.index("videos")


@responses.activate
def test_a_video_already_enriched_this_run_is_not_fetched_twice(settings, engine):
    apply_seeds(engine, ONE_SEED)
    _unenriched(engine, "vid00000001")  # the same id discovery will return
    _mock_api()
    _collector(settings, engine).run()
    video_calls = [c for c in responses.calls if "/videos" in c.request.url]
    assert len(video_calls) == 1


@responses.activate
def test_a_vanished_video_is_marked_consulted_without_inventing_a_duration(settings, engine):
    """Deleted or private: the API returns nothing for it. Marking it enriched
    stops it costing a request every night forever, and the NULL duration still
    correctly excludes it from format-sensitive metrics."""
    from nh.db.models import Video

    _unenriched(engine, "deleted0001")
    responses.add(responses.GET, f"{API}/videos", json={"items": []}, status=200)
    _collector(settings, engine).run()
    with session_scope(engine) as s:
        video = s.get(Video, "deleted0001")
    assert video.enriched is True
    assert video.duration_s is None
    assert video.is_short is None  # unknown format, not "not a short"


@responses.activate
def test_ids_left_unasked_when_the_budget_runs_out_are_not_marked_missing(settings, engine):
    """The dangerous case. An id skipped for want of quota is not deleted, and
    marking it consulted would lose it permanently — it would never be queued
    again."""
    from nh.db.models import Video

    settings.yt_quota_budget = 1  # one videos.list call, then nothing
    _unenriched(engine, *[f"v{i:011d}" for i in range(200)])
    responses.add(responses.GET, f"{API}/videos", json={"items": []}, status=200)
    _collector(settings, engine).run()
    with session_scope(engine) as s:
        still_queued = s.scalar(
            sa.select(sa.func.count()).select_from(Video).where(Video.enriched.is_(False))
        )
    assert still_queued > 0


@responses.activate
def test_the_backlog_is_bounded_by_the_configured_cap(settings, engine):
    settings.yt_backfill_max_ids = 50
    _unenriched(engine, *[f"v{i:011d}" for i in range(500)])
    responses.add(responses.GET, f"{API}/videos", json={"items": []}, status=200)
    collector = _collector(settings, engine)
    collector.run()
    assert collector.quota.used == 1  # 50 ids is one chunk, not ten


@responses.activate
def test_the_backlog_drains_oldest_first(settings, engine):
    """A backlog too large for one night must drain deterministically rather
    than re-shuffling and starving the same ids every time."""
    settings.yt_backfill_max_ids = 2
    _unenriched(engine, "older000001")
    _unenriched(engine, "newer000001")
    responses.add(responses.GET, f"{API}/videos", json={"items": []}, status=200)
    collector = _collector(settings, engine)
    ids = collector._unenriched_ids()
    assert ids[0][0] == "older000001"


def test_an_unenriched_video_with_no_backlog_costs_nothing(settings, engine):
    collector = _collector(settings, engine)
    assert collector._unenriched_ids() == []


@responses.activate
def test_a_backfill_only_run_never_calls_search(settings, engine):
    """The sweep exists to close the enrichment lag, not to discover. A pass that could
    spend 100 units per search.list would put the night's irreplaceable discovery budget
    at risk to do it — and it runs when discovery has already spent."""
    apply_seeds(engine, ONE_SEED)  # seeds present, and still not read
    _unenriched(engine, "sweep000001")
    responses.add(
        responses.GET, f"{API}/videos", json={"items": [_video_payload("sweep000001")]}, status=200
    )
    record = _collector(settings, engine, backfill_only=True).run()

    assert record.status == "ok", record.error
    assert not [c for c in responses.calls if "/search" in c.request.url]
    assert record.quota_used == 1, "one videos.list page, no search"


@responses.activate
def test_the_sweep_enriches_what_rss_left_behind(settings, engine):
    """The defect it closes: a feed supplies no duration, so is_short stays NULL and
    eligible_videos — which requires `is_short IS FALSE` — admits the whole discovery
    wave a night late and in a lump."""
    from nh.db.models import Video

    _unenriched(engine, "sweep000001")
    responses.add(
        responses.GET, f"{API}/videos", json={"items": [_video_payload("sweep000001")]}, status=200
    )
    _collector(settings, engine, backfill_only=True).run()

    with session_scope(engine) as s:
        video = s.get(Video, "sweep000001")
    assert video.enriched is True
    assert video.is_short is False, "this is the column eligible_videos gates on"


@responses.activate
def test_the_sweeps_spend_counts_against_the_next_runs_budget(settings, engine):
    """It must stay JobRun.source='youtube_api'. `_spent_today` sums by source, so a
    distinct name would silently exempt the sweep from the per-day ledger and the day
    could overshoot by the whole sweep."""
    _unenriched(engine, "sweep000001")
    responses.add(
        responses.GET, f"{API}/videos", json={"items": [_video_payload("sweep000001")]}, status=200
    )
    record = _collector(settings, engine, backfill_only=True).run()

    assert record.source == "youtube_api"
    assert _collector(settings, engine).quota.budget == settings.yt_quota_budget - record.quota_used


# -- what an error leaves behind (2026-09-15) --------------------------------------


@responses.activate
def test_a_403_stores_googles_reason_not_the_query_string(settings, engine):
    """The 2026-09-10 sweep failure was stored as 1,156 characters of request URL, and
    the one word that said why was in the body nobody kept. Whether that night was a
    transient the retry now absorbs is unknowable for exactly this reason."""
    apply_seeds(engine, ONE_SEED)
    responses.add(
        responses.GET,
        f"{API}/search",
        status=403,
        json={
            "error": {
                "message": "Access Not Configured. YouTube Data API has not been used.",
                "errors": [{"reason": "accessNotConfigured", "domain": "usageLimits"}],
            }
        },
    )
    record = _collector(settings, engine).run()

    assert record.status == "failed"
    assert "accessNotConfigured" in record.error
    assert "Access Not Configured" in record.error
    assert "key=" not in record.error


@responses.activate
def test_a_per_minute_403_is_retried_like_a_429(settings, engine, monkeypatch):
    """`userRateLimitExceeded` is YouTube's per-minute ceiling and Google lists it as
    retryable; `quotaExceeded` is the daily one and stops cleanly. They share a status
    code and used to share a fate."""
    import nh.collectors.youtube_api as mod

    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    apply_seeds(engine, ONE_SEED)
    responses.add(
        responses.GET,
        f"{API}/search",
        status=403,
        json={"error": {"errors": [{"reason": "userRateLimitExceeded"}]}},
    )
    _mock_api()  # the retry, and the rest of the night, succeed
    record = _collector(settings, engine).run()

    assert record.status == "ok", record.error
    searches = [c for c in responses.calls if "/search" in c.request.url]
    assert len(searches) >= 2, "the 403 was retried, not raised"


@responses.activate
def test_the_api_key_never_reaches_job_runs_error(settings, engine):
    """urllib3 phrases a transport failure with the full request URL, key included, and
    `job_runs.error` is backed up offsite every night. 2026-09-13 stored the key."""
    apply_seeds(engine, ONE_SEED)
    key = settings.yt_api_key
    assert key, "the collector must be configured for this to mean anything"
    responses.add(
        responses.GET,
        f"{API}/search",
        body=requests.ConnectionError(
            f"HTTPSConnectionPool: Max retries exceeded with url: /youtube/v3/search?q=x&key={key}"
        ),
    )
    record = _collector(settings, engine).run()

    assert record.status == "failed"
    assert key not in record.error
    assert "<redacted>" in record.error


@responses.activate
def test_a_non_json_error_body_still_omits_the_url(settings, engine):
    """A proxy's HTML page or an empty 5xx body has no `reason` to extract; the fallback
    must still not be `raise_for_status`, whose text is the URL."""
    apply_seeds(engine, ONE_SEED)
    responses.add(responses.GET, f"{API}/search", status=404, body="<html>not here</html>")
    record = _collector(settings, engine).run()

    assert record.status == "failed"
    assert "404" in record.error and "search" in record.error
    assert "key=" not in record.error


@responses.activate
def test_a_persistent_per_minute_403_names_its_own_ceiling(settings, engine, monkeypatch):
    """Exhausting the retries lands in the same QuotaExhausted the callers turn into
    "skip the rest of this run" — the right outcome — but the message used to blame the
    daily quota, which sends the operator to the wrong console. Caught by review the day
    the transient retry was added."""
    import nh.collectors.youtube_api as mod
    from nh.collectors.youtube_api import QuotaExhausted

    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    for _ in range(5):
        responses.add(
            responses.GET,
            f"{API}/search",
            status=403,
            json={"error": {"errors": [{"reason": "userRateLimitExceeded"}]}},
        )
    collector = _collector(settings, engine)

    with pytest.raises(QuotaExhausted) as raised:
        collector._get("search", 100, q="x")
    text = str(raised.value)
    assert "userRateLimitExceeded" in text and "per-minute ceiling" in text
    assert "most likely the daily" not in text
    assert collector.quota.used == 0, "nothing was charged for five rejections"


# -- the channel-reach watchlist (ADR-0059) -----------------------------------------

WATCH_NIGHT = "2026-09-20"
WATCH_BUILT = "2026-09-10"  # the builders' RSS snapshots land here, never on the night


def _watch_world(engine, *, read_tonight=False):
    """One small member channel whose five uploads sit at ages 14, 15, 16, 17 and 18 on
    the night, plus every way a video must stay out: a big channel, a short, a non-member,
    and an upload at age 13. All enriched, so none is in the unenriched backlog."""
    from datetime import date

    import sqlalchemy as sa

    from nh.db.models import Video, VideoSnapshot
    from tests.conftest_features import add_channel, make_cluster

    built, night = date.fromisoformat(WATCH_BUILT), date.fromisoformat(WATCH_NIGHT)
    make_cluster(engine)
    add_channel(engine, "UCsmall", subs=1_000, videos=5, age_days=4, day=built)
    add_channel(engine, "UCbig", subs=50_000, videos=5, age_days=4, day=built)
    add_channel(engine, "UCshort", subs=1_000, videos=5, age_days=4, is_short=True, day=built)
    add_channel(engine, "UCoutsider", subs=1_000, videos=5, age_days=4, member=False, day=built)
    add_channel(engine, "UCyoung", subs=1_000, videos=1, age_days=3, day=built)
    with session_scope(engine) as s:
        s.execute(sa.update(Video).values(enriched=True))
        if read_tonight:
            s.add(
                VideoSnapshot(
                    video_id="UCsmall-v0",
                    channel_id="UCsmall",
                    observed_date=night,
                    views=9,
                    source="youtube_rss",
                    run_id="rss",
                )
            )


def _serve_videos(engine, dead: set[str] | None = None):
    """Answer /videos with each requested id's own channel and publish date, so the
    enrichment upsert cannot move a video out of the population and fake a pass.

    `dead` is omitted from the response the way the real API omits a deleted or private
    id: 200, no error, the id simply absent from `items`.
    """
    import json
    from urllib.parse import parse_qs, urlparse

    from nh.db.models import Video

    def respond(request):
        ids = parse_qs(urlparse(request.url).query)["id"][0].split(",")
        items = []
        with session_scope(engine) as s:
            for vid in ids:
                if vid in (dead or set()):
                    continue
                row = s.get(Video, vid)
                snippet = {
                    **VIDEO_ITEM["snippet"],
                    "channelId": row.channel_id,
                    "publishedAt": row.published_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                items.append({**VIDEO_ITEM, "id": vid, "snippet": snippet})
        return 200, {}, json.dumps({"items": items})

    responses.add_callback(responses.GET, f"{API}/videos", callback=respond)


def _night_collector(settings, engine):
    from datetime import UTC, datetime

    night = datetime.fromisoformat(WATCH_NIGHT).replace(hour=14, minute=10, tzinfo=UTC)
    return _collector(settings, engine, backfill_only=True, observed_at=night)


def _requested(path="/videos"):
    from urllib.parse import parse_qs, urlparse

    return [
        vid
        for call in responses.calls
        if path in call.request.url
        for vid in parse_qs(urlparse(call.request.url).query)["id"][0].split(",")
    ]


@responses.activate
def test_the_watchlist_reads_exactly_the_registered_population(settings, engine):
    """Ages 14-17 only, long-form only, small active-cluster members only. The
    pre-registered outcome reads a video at its smallest age in that window, so a
    video outside it costs quota and buys nothing — and one missing from it is an
    outcome censored by RSS feed position, which is what this exists to stop."""
    _watch_world(engine)
    _serve_videos(engine)
    record = _night_collector(settings, engine).run()

    assert record.status == "ok", record.error
    assert set(_requested()) == {"UCsmall-v0", "UCsmall-v1", "UCsmall-v2", "UCsmall-v3"}
    assert record.quota_used == 1, "four ids is one videos.list page"


@responses.activate
def test_a_video_already_read_tonight_is_not_bought_again(settings, engine):
    """The outcome takes max views across sources on the date, so an RSS snapshot counts
    exactly as an API one does. Re-reading it would spend quota on nothing."""
    _watch_world(engine, read_tonight=True)
    _serve_videos(engine)
    _night_collector(settings, engine).run()

    assert set(_requested()) == {"UCsmall-v1", "UCsmall-v2", "UCsmall-v3"}


@responses.activate
def test_a_capped_watchlist_keeps_the_videos_about_to_leave_the_window(settings, engine):
    """Oldest first: age 17 has one night left inside the reading window, age 14 has
    four. A capped night must drop the ones that can still be caught tomorrow."""
    _watch_world(engine)
    _serve_videos(engine)
    settings.yt_watchlist_max_ids = 2
    _night_collector(settings, engine).run()

    assert _requested() == ["UCsmall-v3", "UCsmall-v2"]


@responses.activate
def test_the_watchlist_is_read_once_per_night_however_many_runs_reach_it(settings, engine):
    """The primary run and the ADR-0057 sweep both call `_backfill`. Whichever arrives
    first writes tonight's snapshots; the second must find nothing left — and must find
    nothing because of those readings, not because the upsert moved a video out."""
    from datetime import date

    from nh.collectors.youtube_api import watchlist_population

    _watch_world(engine)
    _serve_videos(engine)
    _night_collector(settings, engine).run()
    after_first = len(_requested())
    _night_collector(settings, engine).run()

    assert after_first == 4
    assert len(_requested()) == after_first, "the second run bought nothing"
    with session_scope(engine) as s:
        still = s.scalars(watchlist_population(date.fromisoformat(WATCH_NIGHT))).all()
    assert len(still) == 4, "the population itself did not drift"


@responses.activate
def test_a_retired_cluster_is_not_watched(settings, engine):
    """Retired clusters keep collecting RSS history, but nothing analyses their channels
    at channel grain, so their videos are not worth a unit."""
    import sqlalchemy as sa

    from nh.db.models import Cluster

    _watch_world(engine)
    with session_scope(engine) as s:
        s.execute(sa.update(Cluster).values(active=False))
    _serve_videos(engine)
    record = _night_collector(settings, engine).run()

    assert record.status == "ok", record.error
    assert _requested() == []


@responses.activate
def test_only_ids_confirmed_tonight_are_excluded_not_ids_attempted(settings, engine):
    """The first version excluded every id discovery ATTEMPTED; one cut short by the
    ledger has no reading tonight and would silently drop out of its window. Review
    found that deleting the exclusion passed every watchlist test, because all of them
    ran the sweep, where the set is empty. This one fails if the exclusion is removed
    (v0 is bought twice) or widened to attempts (v1 is never bought)."""
    _watch_world(engine)
    _serve_videos(engine)
    collector = _night_collector(settings, engine)
    list(collector._backfill(seen={"UCsmall-v0", "UCsmall-v1"}, read_tonight={"UCsmall-v0"}))

    assert set(_requested()) == {"UCsmall-v1", "UCsmall-v2", "UCsmall-v3"}


@responses.activate
def test_a_declined_id_is_asked_again_by_the_sweep_and_is_not_logged_as_a_failure(
    settings, engine, caplog
):
    """The real shape of a night, which every other test here misses because its fake
    API returns everything asked for.

    A deleted or private id never gets a snapshot, so "no reading yet today" leaves it in
    the population and the ADR-0057 sweep asks again — by which point it is the ONLY id
    left, and the pass reads 0 of 1. Measured on 2026-09-17 as "213 of 213 ids not
    returned", which read as a dead collector and was not one: the primary pass had read
    7,392 of 7,605 half an hour earlier. So the line must not be a warning. The budget
    case must still be, and `test_a_budget_that_runs_out_mid_watchlist_warns` holds it.
    """
    import logging

    _watch_world(engine)
    _serve_videos(engine, dead={"UCsmall-v3"})

    _night_collector(settings, engine).run()
    first = set(_requested())
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="nh.collectors.youtube_api"):
        _night_collector(settings, engine).run()

    assert first == {"UCsmall-v0", "UCsmall-v1", "UCsmall-v2", "UCsmall-v3"}
    assert _requested()[-1:] == ["UCsmall-v3"], "the sweep re-asks exactly the dead id"
    watch = [r for r in caplog.records if r.message.startswith("watchlist: read")]
    assert [r.levelno for r in watch] == [logging.INFO], watch
    assert "gone (deleted or private)" in watch[0].getMessage()


@responses.activate
def test_a_last_batch_that_spends_the_final_unit_is_not_a_budget_warning(settings, engine, caplog):
    """Review's finding on the first version of this split, which inferred "left unasked"
    from `quota.remaining == 0` after the fact.

    Here every id IS asked, the last batch answers, and it happens to spend the ledger to
    exactly zero — while one id comes back declined. The coarse test cannot tell that
    from a batch never sent, so it would fire the budget alarm that this whole change
    exists to stop firing. `_enrich(asked=...)` reports what it actually sent, so the
    night reads as what it is: quiet."""
    import logging

    _watch_world(engine)
    _serve_videos(engine, dead={"UCsmall-v3"})
    collector = _night_collector(settings, engine)
    collector.quota.budget = collector.quota.used + 1  # exactly one videos.list page

    with caplog.at_level(logging.INFO, logger="nh.collectors.youtube_api"):
        list(collector._watchlist(set()))

    assert collector.quota.remaining == 0, "the premise: the ledger is spent"
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == [], (
        caplog.records
    )
    assert "watchlist: read 3 of 4; 1 gone (deleted or private)" in [
        r.message for r in caplog.records
    ]


@responses.activate
def test_a_budget_that_runs_out_mid_watchlist_warns(settings, engine, caplog):
    """The other half of the split, and the actionable one: an id the ledger stopped us
    asking about has no reading and may leave its window unread. That is quota to look
    at tonight, not an id that died on its own."""
    import logging

    _watch_world(engine)
    _serve_videos(engine)
    collector = _night_collector(settings, engine)
    collector.quota.budget = collector.quota.used  # nothing left to spend

    with caplog.at_level(logging.INFO, logger="nh.collectors.youtube_api"):
        list(collector._watchlist(set()))

    warned = [
        r for r in caplog.records if "watchlist" in r.message and r.levelno >= logging.WARNING
    ]
    assert len(warned) == 1, caplog.records
    assert "left unasked" in warned[0].getMessage()


@responses.activate
def test_a_watchlist_reread_records_views_and_leaves_the_video_row_alone(settings, engine):
    """A re-read 14-17 days after first capture carries tonight's title, description and
    duration. Upserting them would reach clustering's rescore and could flip `is_short`,
    so the watchlist writes the snapshot only, and keeps the payload as raw."""
    import sqlalchemy as sa

    from nh.db.models import RawRecord, Video, VideoSnapshot

    _watch_world(engine)
    _serve_videos(engine)  # serves VIDEO_ITEM's title, not the fixture's
    record = _night_collector(settings, engine).run()

    assert record.status == "ok", record.error
    with session_scope(engine) as s:
        assert s.get(Video, "UCsmall-v0").title == "UCsmall-v0", "the row was not touched"
        snap = s.scalars(
            sa.select(VideoSnapshot).where(
                VideoSnapshot.video_id == "UCsmall-v0", VideoSnapshot.source == "youtube_api"
            )
        ).one()
        assert snap.views == 125_000
        kinds = set(s.scalars(sa.select(RawRecord.kind).where(RawRecord.key == "UCsmall-v0")))
    assert kinds == {"video_watch"}
