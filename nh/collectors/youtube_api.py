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


def _sponsor_signal(description: str | None) -> bool | None:
    """None when there is no description to read — absent is not False (rule 7)."""
    return None if description is None else bool(_SPONSOR_RE.search(description))


_MIDROLL_S = 480
_SHORT_S = 60


@dataclass(frozen=True, slots=True)
class _Seed:
    id: int
    slug: str
    keywords: list[str]
    #: The market the seed is about (`niche_seeds.geo`), sent as `regionCode`.
    #: Discovery was never geo-neutral: the API's own reference documents that a
    #: request without `regionCode` is served with `regionCode=US` — the response
    #: property's stated default — so omitting the parameter meant *inferring* a
    #: US basis instead of recording one (ADR-0035 rule 1, ADR-0037). Sending the
    #: seed's stated geo pins the basis explicitly; a seed that states none sends
    #: nothing and accepts the server default.
    geo: str | None


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
        # re-run — a manual retry, a second scheduled fire — sails past the real
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
                    for item in self._search(query, order, seed.geo):
                        video_ids.setdefault(item["id"]["videoId"])
                        channel_ids.setdefault(item["snippet"]["channelId"])
                        yield Raw(
                            kind="search_hit",
                            key=item["id"]["videoId"],
                            payload={
                                "seed_id": seed.id,
                                "query": query,
                                "order": order,
                                # Provenance for the geo basis (ADR-0037): what was
                                # actually sent, so a replay does not have to guess.
                                # None means the server's documented US default.
                                "region": seed.geo or None,
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
        yield from self._backfill(seen=set(video_ids))

    def _backfill(self, seen: set[str]) -> Iterable[Raw]:
        """Enrich videos RSS found, which arrive with no duration at all.

        A feed gives title, published and views but never duration, so `is_short`
        and `midroll_eligible` stay NULL and every format-sensitive metric has to
        exclude the video. That was 91% of the corpus. At 1 unit per 50 ids this
        costs ~250 units once against thousands spare, and it runs last so
        discovery — the expensive, irreplaceable stage — always spends first
        (ADR-0012).
        """
        backlog = {v: c for v, c in self._unenriched_ids() if v not in seen}
        if not backlog:
            return
        self.log.info("backfilling %d unenriched videos", len(backlog))

        returned: set[str] = set()
        for item in self._enrich("videos", list(backlog)):
            returned.add(item["id"])
            yield Raw(kind="video", key=item["id"], payload=item)

        # An id the API declined to return is deleted or private. Mark it
        # consulted so it stops being re-queried every night forever — but only
        # if we actually got to ask. An id skipped because the budget ran out is
        # not missing, and marking it so would lose it permanently.
        if self.quota.remaining == 0:
            self.log.warning(
                "budget ran out mid-backfill; %d ids left unasked", len(backlog) - len(returned)
            )
            return
        for video_id, channel_id in backlog.items():
            if video_id not in returned:
                # channel_id travels with it: `videos.channel_id` is NOT NULL, so
                # the upsert's insert path needs it, and the raw record is more
                # useful for recording which channel lost a video.
                yield Raw(
                    kind="video_missing",
                    key=video_id,
                    payload={"video_id": video_id, "channel_id": channel_id},
                )

    def _unenriched_ids(self) -> list[tuple[str, str]]:
        """`(video_id, channel_id)` oldest-first, so a backlog too large for one
        night drains deterministically rather than re-shuffling and starving the
        same ids every time."""
        with session_scope(self.engine) as session:
            return [
                (video_id, channel_id)
                for video_id, channel_id in session.execute(
                    sa.select(Video.video_id, Video.channel_id)
                    .where(Video.enriched.is_(False))
                    .order_by(Video.first_seen)
                    .limit(self.settings.yt_backfill_max_ids)
                )
            ]

    def _seeds(self) -> list[_Seed]:
        with session_scope(self.engine) as session:
            rows = session.execute(
                sa.select(NicheSeed.id, NicheSeed.slug, NicheSeed.keywords, NicheSeed.geo).where(
                    NicheSeed.active
                )
            ).all()
        if not rows:
            # NOT "run `nh seed`". `apply_seeds` keeps `active` outside its upsert
            # update set on purpose, so a niche someone deliberately stopped survives
            # the next re-seed — which also means re-seeding cannot start one. ADR-0039
            # was written as a code edit alone and therefore did nothing for a day;
            # sending the next operator to the same dead end would repeat it.
            self.log.warning(
                "no active niche_seeds — discovery is idle and will spend 0 search "
                "units. Enrichment and backfill still run. To resume discovery: "
                "UPDATE niche_seeds SET active = 1 WHERE slug IN (...)"
            )
        return [_Seed(*row) for row in rows]

    def _search(self, query: str, order: str, region: str | None) -> Iterator[dict[str, Any]]:
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
            if region:
                # The seed's stated market, made explicit (ADR-0037). Omitting the
                # parameter is NOT neutral: the API serves the query with a US
                # default anyway (documented on the response's regionCode field),
                # from whatever IP the nightly happens to run on. This is a viewpoint
                # parameter — "results viewable in, and ranked for, this market" —
                # not a filter on creator geography; global English supply stays in
                # the pool and geo_concentration keeps measuring the divergence.
                params["regionCode"] = region
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
        if raw.kind == "video_missing":
            return self._norm_missing(raw)
        raise ValueError(f"unknown raw kind {raw.kind!r}")

    def _norm_missing(self, raw: Raw) -> Batch:
        """A video the API would not return: deleted, private, or region-blocked.

        `enriched` is set without a duration, which slightly redefines the flag as
        "the API has been consulted about this id" rather than "this id has a
        duration". That is the honest reading: the raw record documents the
        absence, unknown duration still correctly excludes it from every
        format-sensitive metric, and the id stops costing a request every night
        forever (ADR-0012).
        """
        return Batch(
            upserts=[
                Upsert(
                    Video,
                    {
                        "video_id": raw.key,
                        "channel_id": raw.payload["channel_id"],
                        "enriched": True,
                    },
                )
            ]
        )

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
                        "description": snippet.get("description"),
                        "published_at": as_utc(snippet.get("publishedAt")),
                        "duration_s": duration,
                        "category_id": snippet.get("categoryId"),
                        "audio_lang": snippet.get("defaultAudioLanguage"),
                        "tags": snippet.get("tags"),
                        "topics": _topics(item),
                        # Unknown duration means unknown format, not "not a short".
                        "is_short": _is_short(duration, tagged_short),
                        "midroll_eligible": None if duration is None else duration >= _MIDROLL_S,
                        # Absent description is unknown, not "no sponsor" (rule 7);
                        # an empty one is genuinely known to carry no signal.
                        "sponsor_signal": _sponsor_signal(snippet.get("description")),
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
