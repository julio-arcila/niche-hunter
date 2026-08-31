"""YouTube channel Atom feeds — zero-quota view velocity.

Ported from `legacy/niche_hunter_rss.py`. This is the collector that matters most:
it costs no quota and produces the one series that cannot be reconstructed later.
Views are a stock; velocity is a difference between observations, so a night not
polled is a night of velocity gone permanently.

    https://www.youtube.com/feeds/videos.xml?channel_id=UC...

What a feed gives: videoId, channelId, title, published, updated, description,
thumbnail, `media:statistics/@views`, `media:starRating/@count` (≈ likes, since
dislikes were hidden). What it does NOT give: duration, comment count, subscriber
count, tags, category, Shorts flag — `youtube_api` supplies those.

Last 15 entries only, no pagination: a channel uploading more than 15 times
between polls loses the overflow permanently. Unofficial endpoint, so politeness
*is* the rate limit — conditional GETs, bounded workers, jitter, and a circuit
breaker after repeated failures.
"""

from __future__ import annotations

import random
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import requests
import sqlalchemy as sa

from nh.collectors.base import Batch, Collector, Raw, Snapshot, Upsert
from nh.collectors.parse import as_int, as_utc
from nh.db.models import Channel, FeedState, Video, VideoSnapshot
from nh.db.session import session_scope
from nh.db.types import utcnow

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
#: Stop polling a channel after this many consecutive failures. From
#: .claude/rules/sources.md — a dead feed must not be retried forever.
FAIL_LIMIT = 5
TIMEOUT_S = 20


@dataclass(frozen=True, slots=True)
class _Target:
    channel_id: str
    etag: str | None
    last_modified: str | None
    fail_count: int


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """Atom + media RSS -> plain dicts. Pure, so it is testable straight from a
    recorded feed with no HTTP in the loop."""
    entries = []
    for entry in ET.fromstring(xml_text).findall("a:entry", NS):
        group = entry.find("media:group", NS)
        community = group.find("media:community", NS) if group is not None else None
        stats = community.find("media:statistics", NS) if community is not None else None
        rating = community.find("media:starRating", NS) if community is not None else None
        entries.append(
            {
                "video_id": entry.findtext("yt:videoId", namespaces=NS),
                "channel_id": entry.findtext("yt:channelId", namespaces=NS),
                "title": entry.findtext("a:title", namespaces=NS),
                # Feeds truncate long descriptions, so this is the text as served,
                # not necessarily the full text. An absent one stays None.
                "description": group.findtext("media:description", namespaces=NS)
                if group is not None
                else None,
                "published_at": entry.findtext("a:published", namespaces=NS),
                # An absent count is unknown, not zero (data rule 6).
                "views": as_int(stats.get("views")) if stats is not None else None,
                "likes": as_int(rating.get("count")) if rating is not None else None,
            }
        )
    return entries


class YouTubeRssCollector(Collector):
    source = "youtube_rss"
    description = "YouTube channel Atom feeds — zero-quota view velocity."
    quota_budget = None  # no countable quota; politeness is the limit

    # -- fetch ---------------------------------------------------------------

    def fetch(self) -> Iterable[Raw]:
        """Workers do HTTP only; the generator yields on the main thread, so
        `normalize()` and `_flush()` never touch the session concurrently."""
        targets = self._targets()
        if not targets:
            self.log.warning("no channels to poll — run the youtube_api collector first")
            return
        self.log.info("polling %d feeds with %d workers", len(targets), self.settings.rss_workers)
        with ThreadPoolExecutor(self.settings.rss_workers) as pool:
            futures = [pool.submit(self._poll, target) for target in targets]
            for future in as_completed(futures):
                yield future.result()

    def _targets(self) -> list[_Target]:
        """Every known channel not currently circuit-broken."""
        with session_scope(self.engine) as session:
            rows = session.execute(
                sa.select(
                    Channel.channel_id,
                    FeedState.etag,
                    FeedState.last_modified,
                    sa.func.coalesce(FeedState.fail_count, 0),
                )
                .outerjoin(FeedState, FeedState.channel_id == Channel.channel_id)
                .where(sa.func.coalesce(FeedState.fail_count, 0) < FAIL_LIMIT)
            ).all()
        return [_Target(*row) for row in rows]

    def _poll(self, target: _Target) -> Raw:
        """Runs on a worker thread. Never raises: one dead feed must not end the run."""
        time.sleep(random.uniform(*self.settings.rss_jitter_s))
        headers = {"User-Agent": self.settings.rss_user_agent}
        if target.etag:
            headers["If-None-Match"] = target.etag
        if target.last_modified:
            headers["If-Modified-Since"] = target.last_modified
        status: int | None = None
        xml: str | None = None
        etag, last_modified = target.etag, target.last_modified
        try:
            response = requests.get(
                FEED_URL.format(target.channel_id), headers=headers, timeout=TIMEOUT_S
            )
            status = response.status_code
            # 304 carries no body; storing one would grow raw_records by ~20KB per
            # channel per day for content that did not change.
            xml = response.text if status == 200 else None
            etag = response.headers.get("ETag") or etag
            last_modified = response.headers.get("Last-Modified") or last_modified
        except Exception as exc:
            # Deliberately broad. **The count of such catches lives in
            # `.claude/rules/python.md` and nowhere else** — this comment used to say
            # "the second of only two such catches in the codebase", which that rule
            # already records as false, and which was still sitting here uncorrected on
            # 2026-08-31 for anyone who read the code instead of the rule.
            # This runs on a worker thread:
            # anything escaping here abandons every feed still queued behind it,
            # costing a night of velocity that cannot be re-fetched. A malformed
            # header or a DNS failure outside requests' own hierarchy must cost
            # one channel, not the run.
            self.log.warning("feed %s failed: %s", target.channel_id, exc)
        return Raw(
            kind="feed",
            key=target.channel_id,
            payload={
                "status": status,
                "xml": xml,
                "etag": etag,
                "last_modified": last_modified,
                "prior_fail_count": target.fail_count,
                # fetch owns the clock; normalize must stay pure.
                "fetched_at": utcnow().isoformat(),
            },
        )

    # -- normalize -----------------------------------------------------------

    def normalize(self, raw: Raw) -> Batch:
        payload = raw.payload
        healthy = payload["status"] in (200, 304)
        batch = Batch(
            upserts=[
                Upsert(
                    FeedState,
                    {
                        "channel_id": raw.key,
                        "etag": payload["etag"],
                        "last_modified": payload["last_modified"],
                        "last_polled": as_utc(payload["fetched_at"]),
                        "last_status": payload["status"],
                        # upsert() cannot express `fail_count = fail_count + 1`, so
                        # fetch carries the prior value forward and this stays pure.
                        "fail_count": 0 if healthy else payload["prior_fail_count"] + 1,
                        # `hot` is omitted so a channel flagged by hand stays flagged.
                    },
                )
            ]
        )
        for entry in parse_feed(payload["xml"]) if payload["xml"] else []:
            video = {
                "video_id": entry["video_id"],
                "channel_id": entry["channel_id"],
                "title": entry["title"],
                "published_at": as_utc(entry["published_at"]),
                # `enriched` is deliberately absent: on insert the column
                # default applies, and on update an existing True survives
                # because absent columns never reach the SET clause.
            }
            if entry["description"]:
                # Same reasoning as `enriched`: an empty feed description must not
                # overwrite the fuller text `youtube_api` may already have stored.
                # `_group` buckets by column set, so a mixed batch is fine.
                video["description"] = entry["description"]
            batch.upserts.append(Upsert(Video, video))
            batch.snapshots.append(
                Snapshot(
                    VideoSnapshot,
                    {
                        "video_id": entry["video_id"],
                        "channel_id": entry["channel_id"],
                        "views": entry["views"],
                        "likes": entry["likes"],
                        "comments": None,  # a feed never carries a comment count
                    },
                )
            )
        return batch
