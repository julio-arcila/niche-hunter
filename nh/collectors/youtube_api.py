"""YouTube Data API v3 — discovery and enrichment.

Ported from `legacy/niche_hunter_yt.py`. Slice 1 scope is discovery + enrichment
only; channel baselines and comment sampling are deliberately out — both are
quota-expensive and neither is needed to start the snapshot clock.

Quota costs, the only thing that matters for budgeting:

    search.list           100 units   discovery — the ONLY expensive call
    videos.list             1 unit    up to 50 ids
    channels.list           1 unit    up to 50 ids

Discovery issues **both** sort orders for every query. `order=date` is the
unbiased pool including flops — the denominator of the breakthrough rate.
`order=viewCount` is what is winning right now — the numerator. `Discovery.order_by`
exists to keep them apart. Dropping either one looks like a harmless saving and
silently destroys the openness metric in Slice 2.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests
import sqlalchemy as sa

from nh.collectors.base import Batch, Collector, Raw, Snapshot, Upsert
from nh.collectors.parse import as_bool, as_int, as_utc, iso_duration_s
from nh.collectors.quota import QuotaExhausted, QuotaLedger
from nh.db.models import (
    Channel,
    ChannelSnapshot,
    Discovery,
    JobRun,
    NicheSeed,
    Video,
    VideoSnapshot,
)
from nh.db.session import session_scope

#: YouTube resets quota at midnight in this zone, not UTC and not local.
PACIFIC = ZoneInfo("America/Los_Angeles")

API = "https://www.googleapis.com/youtube/v3"
SEARCH_COST = 100
LIST_COST = 1
PAGE_SIZE = 50

SEARCH_FIELDS = "nextPageToken,items(id/videoId,snippet(channelId,publishedAt,title))"
VIDEO_FIELDS = (
    "items(id,snippet(channelId,publishedAt,title,description,tags,categoryId,"
    "defaultAudioLanguage),contentDetails(duration),"
    "statistics(viewCount,likeCount,commentCount),topicDetails(topicCategories))"
)
CHANNEL_FIELDS = (
    "items(id,snippet(title,publishedAt,country),"
    "statistics(viewCount,subscriberCount,hiddenSubscriberCount,videoCount),"
    "brandingSettings/channel/keywords,topicDetails/topicCategories)"
)
_PARTS = {
    "videos": ("snippet,contentDetails,statistics,topicDetails", VIDEO_FIELDS),
    "channels": ("snippet,statistics,brandingSettings,topicDetails", CHANNEL_FIELDS),
}

_SPONSOR_RE = re.compile(r"sponsored|use code|affiliate|promo code|partner", re.I)
_MIDROLL_S = 480
_SHORT_S = 60


@dataclass(frozen=True, slots=True)
class _Seed:
    id: int
    slug: str
    keywords: list[str]


def _topics(item: dict[str, Any]) -> list[str] | None:
    urls = item.get("topicDetails", {}).get("topicCategories")
    return [u.rsplit("/", 1)[-1] for u in urls] if urls else None


def _chunks(items: Sequence[str], n: int = PAGE_SIZE) -> Iterator[Sequence[str]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


class YouTubeApiCollector(Collector):
    source = "youtube_api"
    description = "YouTube Data API v3 — discovery and enrichment."
    quota_budget = 9_500

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The budget is per *day*, not per run. A ledger that starts fresh each
        # time has no idea an earlier run today already spent most of it, so a
        # re-run — a manual retry, a second cron fire — sails past the real
        # ceiling and gets throttled by Google instead of stopping cleanly.
        spent = self._spent_today()
        remaining = max(self.settings.yt_quota_budget - spent, 0)
        if spent:
            self.log.info(
                "%d units already spent this quota day; budget for this run: %d",
                spent,
                remaining,
            )
        self.quota = QuotaLedger(remaining)
        self._budget_warned = False  # the stop is per-query; the log line is per-run

    def _spent_today(self) -> int:
        """Units this source has already charged since midnight Pacific.

        YouTube resets quota at midnight America/Los_Angeles, which is neither UTC
        midnight nor local midnight, so the window has to be computed in that zone.
        """
        day_start = self.observed_at.astimezone(PACIFIC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        with session_scope(self.engine) as session:
            return (
                session.scalar(
                    sa.select(sa.func.coalesce(sa.func.sum(JobRun.quota_used), 0)).where(
                        JobRun.source == self.source,
                        JobRun.started_at >= day_start.astimezone(UTC),
                    )
                )
                or 0
            )

    # -- fetch ---------------------------------------------------------------

    def fetch(self) -> Iterable[Raw]:
        """Discovery, then enrichment. Reading a response to feed the next stage is
        plumbing, not normalization, so the whole pipeline lives in one generator."""
        video_ids: dict[str, None] = {}  # insertion-ordered dedupe
        channel_ids: dict[str, None] = {}
        for seed in self._seeds():
            for query in seed.keywords:
                for order in ("date", "viewCount"):
                    for item in self._search(query, order):
                        video_ids.setdefault(item["id"]["videoId"])
                        channel_ids.setdefault(item["snippet"]["channelId"])
                        yield Raw(
                            kind="search_hit",
                            key=item["id"]["videoId"],
                            payload={
                                "seed_id": seed.id,
                                "query": query,
                                "order": order,
                                "item": item,
                            },
                        )
        self.log.info(
            "discovery done: %d videos, %d channels, %d units spent",
            len(video_ids),
            len(channel_ids),
            self.quota.used,
        )
        for item in self._enrich("videos", list(video_ids)):
            yield Raw(kind="video", key=item["id"], payload=item)
        for item in self._enrich("channels", list(channel_ids)):
            yield Raw(kind="channel", key=item["id"], payload=item)

    def _seeds(self) -> list[_Seed]:
        with session_scope(self.engine) as session:
            rows = session.execute(
                sa.select(NicheSeed.id, NicheSeed.slug, NicheSeed.keywords).where(NicheSeed.active)
            ).all()
        if not rows:
            self.log.warning("no active niche_seeds — run `nh seed` first")
        return [_Seed(*row) for row in rows]

    def _search(self, query: str, order: str) -> Iterator[dict[str, Any]]:
        since = self.observed_at - timedelta(days=self.settings.yt_discover_days)
        token: str | None = None
        for _ in range(self.settings.yt_search_pages):
            if not self.quota.can_afford(SEARCH_COST):
                if not self._budget_warned:
                    self.log.warning(
                        "budget reached (%d units); stopping discovery", self.quota.used
                    )
                    self._budget_warned = True
                return
            params: dict[str, Any] = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": order,
                "publishedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "maxResults": PAGE_SIZE,
                "relevanceLanguage": "en",
                "fields": SEARCH_FIELDS,
            }
            if token:
                params["pageToken"] = token
            try:
                data = self._get("search", SEARCH_COST, **params)
            except QuotaExhausted as exc:
                self.log.warning("stopping discovery: %s", exc)
                self.quota.exhaust()  # every later query short-circuits
                return
            yield from data.get("items", [])
            token = data.get("nextPageToken")
            if not token:
                return

    def _enrich(self, endpoint: str, ids: list[str]) -> Iterator[dict[str, Any]]:
        part, fields = _PARTS[endpoint]
        for batch in _chunks(ids):
            if not self.quota.can_afford(LIST_COST):
                self.log.warning("budget reached; stopping %s enrichment", endpoint)
                return
            try:
                data = self._get(
                    endpoint, LIST_COST, part=part, fields=fields, id=",".join(batch), maxResults=50
                )
            except QuotaExhausted as exc:
                self.log.warning("stopping %s enrichment: %s", endpoint, exc)
                self.quota.exhaust()
                return
            yield from data.get("items", [])

    def _get(self, endpoint: str, cost: int, **params: Any) -> dict[str, Any]:
        """Charges quota only on a 200. A retried or rejected call costs nothing."""
        params["key"] = self.settings.yt_api_key
        for attempt in range(5):
            response = requests.get(f"{API}/{endpoint}", params=params, timeout=30)
            if response.status_code == 200:
                self.quota.spend(cost, endpoint)
                return response.json()
            if response.status_code == 403 and "quotaExceeded" in response.text:
                # Google's real daily ceiling, which is not the same number as our
                # self-imposed budget. Stop cleanly; retrying only wastes time.
                raise QuotaExhausted(f"daily quota exceeded upstream at {self.quota.used} units")
            if response.status_code in (429, 500, 503):
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
        raise QuotaExhausted(
            f"{endpoint} throttled past {attempt + 1} retries — most likely the daily "
            f"quota is spent upstream"
        )

    # -- normalize -----------------------------------------------------------

    def normalize(self, raw: Raw) -> Batch:
        if raw.kind == "search_hit":
            return self._norm_search(raw)
        if raw.kind == "video":
            return self._norm_video(raw)
        if raw.kind == "channel":
            return self._norm_channel(raw)
        raise ValueError(f"unknown raw kind {raw.kind!r}")

    def _norm_search(self, raw: Raw) -> Batch:
        """A Discovery row plus a stub Video, so a run whose enrichment is cut short
        by the budget still leaves every discovered id resolvable."""
        payload = raw.payload
        snippet = payload["item"]["snippet"]
        return Batch(
            upserts=[
                Upsert(
                    Video,
                    {
                        "video_id": raw.key,
                        "channel_id": snippet["channelId"],
                        "title": snippet.get("title"),
                        "published_at": as_utc(snippet.get("publishedAt")),
                    },
                )
            ],
            snapshots=[
                Snapshot(
                    Discovery,
                    {
                        "video_id": raw.key,
                        "seed_id": payload["seed_id"],
                        "query": payload["query"],
                        "order_by": payload["order"],
                    },
                )
            ],
        )

    def _norm_video(self, raw: Raw) -> Batch:
        item = raw.payload
        snippet, stats = item["snippet"], item.get("statistics", {})
        duration = iso_duration_s(item.get("contentDetails", {}).get("duration"))
        tagged_short = "#shorts" in (snippet.get("title") or "").lower()
        return Batch(
            upserts=[
                Upsert(
                    Video,
                    {
                        "video_id": raw.key,
                        "channel_id": snippet["channelId"],
                        "title": snippet.get("title"),
                        "published_at": as_utc(snippet.get("publishedAt")),
                        "duration_s": duration,
                        "category_id": snippet.get("categoryId"),
                        "audio_lang": snippet.get("defaultAudioLanguage"),
                        "tags": snippet.get("tags"),
                        "topics": _topics(item),
                        # Unknown duration means unknown format, not "not a short".
                        "is_short": _is_short(duration, tagged_short),
                        "midroll_eligible": None if duration is None else duration >= _MIDROLL_S,
                        "sponsor_signal": bool(_SPONSOR_RE.search(snippet.get("description", ""))),
                        "enriched": True,
                    },
                )
            ],
            snapshots=[
                Snapshot(
                    VideoSnapshot,
                    {
                        "video_id": raw.key,
                        "channel_id": snippet["channelId"],
                        "views": as_int(stats.get("viewCount")),
                        "likes": as_int(stats.get("likeCount")),
                        "comments": as_int(stats.get("commentCount")),
                    },
                )
            ],
        )

    def _norm_channel(self, raw: Raw) -> Batch:
        item = raw.payload
        snippet, stats = item["snippet"], item.get("statistics", {})
        hidden = as_bool(stats.get("hiddenSubscriberCount"))
        return Batch(
            upserts=[
                Upsert(
                    Channel,
                    {
                        "channel_id": raw.key,
                        "title": snippet.get("title"),
                        "country": snippet.get("country"),
                        "created_at": as_utc(snippet.get("publishedAt")),
                        # Derivable, so it costs no extra call.
                        "uploads_playlist": "UU" + raw.key[2:],
                        "keywords": item.get("brandingSettings", {})
                        .get("channel", {})
                        .get("keywords"),
                        "topics": _topics(item),
                    },
                )
            ],
            snapshots=[
                Snapshot(
                    ChannelSnapshot,
                    {
                        "channel_id": raw.key,
                        # A hidden count is unknown, not zero — writing 0 would
                        # poison every views-per-sub ratio computed from it.
                        "subs": None if hidden else as_int(stats.get("subscriberCount")),
                        "total_views": as_int(stats.get("viewCount")),
                        "video_count": as_int(stats.get("videoCount")),
                    },
                )
            ],
        )


def _is_short(duration_s: int | None, tagged_short: bool) -> bool | None:
    if duration_s is None:
        return True if tagged_short else None
    return duration_s <= _SHORT_S or tagged_short
