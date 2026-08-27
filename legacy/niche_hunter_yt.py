"""
niche_hunter_yt.py — YouTube Data API v3 collector for a Niche Hunter pipeline.

Free tier: 10,000 quota units/day, resets at midnight Pacific.
Only an API key is required for public data (no OAuth).

Endpoint costs (the only thing that matters for budgeting):
  search.list           100 units   discovery — the ONLY expensive call
  videos.list             1 unit    up to 50 ids per call
  channels.list           1 unit    up to 50 ids per call
  playlistItems.list      1 unit    50 items per page
  commentThreads.list     1 unit    100 comments per page

Typical daily budget for 1–2 niches:
  60 searches            6,000  ->  ~3,000 candidate videos
  enrich 3,000 videos       60
  enrich 1,500 channels     30
  baselines, 500 channels 1,000  (playlistItems + videos per channel)
  comments, 300 videos     300
  ----------------------------------
                         ~7,400   leaves headroom for retries

Usage:
  export YT_API_KEY=...
  python niche_hunter_yt.py "aviation disasters documentary" "plane crash investigation"
"""

import os
import re
import sys
import json
import time
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone

import requests

API = "https://www.googleapis.com/youtube/v3"
KEY = os.environ["YT_API_KEY"]
DB_PATH = os.environ.get("NH_DB", "niche_hunter.db")


# ----------------------------------------------------------------------------
# Quota + transport
# ----------------------------------------------------------------------------


class Quota:
    def __init__(self, budget=9_500):  # keep 500 in reserve
        self.budget, self.used = budget, 0

    def spend(self, n):
        if self.used + n > self.budget:
            raise RuntimeError(f"quota budget exhausted ({self.used}/{self.budget})")
        self.used += n


Q = Quota()


def call(endpoint, cost, **params):
    """GET with retries. Charges quota only on success."""
    params["key"] = KEY
    for attempt in range(5):
        r = requests.get(f"{API}/{endpoint}", params=params, timeout=30)
        if r.status_code == 200:
            Q.spend(cost)
            return r.json()
        if r.status_code == 403:
            body = r.text
            if "quotaExceeded" in body:
                raise RuntimeError("daily quota exceeded")
            if "commentsDisabled" in body:
                return {"items": [], "_disabled": True}
            r.raise_for_status()
        if r.status_code in (429, 500, 503):
            time.sleep(2**attempt)
            continue
        r.raise_for_status()
    raise RuntimeError(f"retries exhausted for {endpoint}")


def chunks(xs, n=50):
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def iso_dur_to_s(d):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def rfc3339(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------
# 1. Discovery (search.list — 100 units each, ~500 results max per query)
# ----------------------------------------------------------------------------


def discover(query, days_back=90, pages=3, order="date", duration="any", lang=None, region=None):
    """
    order="date"      -> unbiased pool incl. flops   (denominator for breakthrough rate)
    order="viewCount" -> what is winning right now   (numerator / outlier seed)
    duration: any | short(<4m) | medium(4-20m) | long(>20m)
    """
    out, token = [], None
    since = rfc3339(datetime.now(timezone.utc) - timedelta(days=days_back))
    for _ in range(pages):
        params = dict(
            part="snippet",
            q=query,
            type="video",
            order=order,
            publishedAfter=since,
            maxResults=50,
            fields="nextPageToken,items(id/videoId,snippet(channelId,publishedAt,title))",
        )
        if duration != "any":
            params["videoDuration"] = duration
        if lang:
            params["relevanceLanguage"] = lang
        if region:
            params["regionCode"] = region
        if token:
            params["pageToken"] = token
        data = call("search", 100, **params)
        for it in data.get("items", []):
            out.append(
                {
                    "video_id": it["id"]["videoId"],
                    "channel_id": it["snippet"]["channelId"],
                    "published_at": it["snippet"]["publishedAt"],
                    "title": it["snippet"]["title"],
                    "query": query,
                }
            )
        token = data.get("nextPageToken")
        if not token:
            break
    return out


# ----------------------------------------------------------------------------
# 2. Enrichment (videos.list / channels.list — 1 unit per 50 ids)
# ----------------------------------------------------------------------------

VIDEO_FIELDS = (
    "items(id,snippet(channelId,publishedAt,title,description,tags,"
    "categoryId,defaultAudioLanguage),contentDetails(duration),"
    "statistics(viewCount,likeCount,commentCount),topicDetails(topicCategories))"
)


def enrich_videos(video_ids):
    out = {}
    for batch in chunks(list(video_ids)):
        data = call(
            "videos",
            1,
            part="snippet,contentDetails,statistics,topicDetails",
            id=",".join(batch),
            maxResults=50,
            fields=VIDEO_FIELDS,
        )
        for it in data.get("items", []):
            sn, st = it["snippet"], it.get("statistics", {})
            desc = sn.get("description", "")
            out[it["id"]] = {
                "video_id": it["id"],
                "channel_id": sn["channelId"],
                "published_at": sn["publishedAt"],
                "title": sn["title"],
                "tags": sn.get("tags", []),
                "category_id": sn.get("categoryId"),
                "audio_lang": sn.get("defaultAudioLanguage"),
                "duration_s": iso_dur_to_s(it["contentDetails"]["duration"]),
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)) if "likeCount" in st else None,
                "comments": int(st.get("commentCount", 0)) if "commentCount" in st else None,
                "topics": [
                    u.rsplit("/", 1)[-1]
                    for u in it.get("topicDetails", {}).get("topicCategories", [])
                ],
                "is_short": iso_dur_to_s(it["contentDetails"]["duration"]) <= 60
                or "#shorts" in sn["title"].lower(),
                "midroll_eligible": iso_dur_to_s(it["contentDetails"]["duration"]) >= 480,
                "sponsor_signal": bool(
                    re.search(r"sponsored|use code|affiliate|promo code|partner", desc, re.I)
                ),
            }
    return out


CHANNEL_FIELDS = (
    "items(id,snippet(title,publishedAt,country,customUrl),"
    "statistics(viewCount,subscriberCount,hiddenSubscriberCount,videoCount),"
    "brandingSettings/channel/keywords,topicDetails/topicCategories)"
)


def enrich_channels(channel_ids):
    out = {}
    for batch in chunks(list(channel_ids)):
        data = call(
            "channels",
            1,
            part="snippet,statistics,brandingSettings,topicDetails",
            id=",".join(batch),
            maxResults=50,
            fields=CHANNEL_FIELDS,
        )
        for it in data.get("items", []):
            sn, st = it["snippet"], it.get("statistics", {})
            out[it["id"]] = {
                "channel_id": it["id"],
                "title": sn["title"],
                "created_at": sn["publishedAt"],
                "country": sn.get("country"),
                "subs": None
                if st.get("hiddenSubscriberCount")
                else int(st.get("subscriberCount", 0)),
                "total_views": int(st.get("viewCount", 0)),
                "video_count": int(st.get("videoCount", 0)),
                "keywords": it.get("brandingSettings", {}).get("channel", {}).get("keywords"),
                "topics": [
                    u.rsplit("/", 1)[-1]
                    for u in it.get("topicDetails", {}).get("topicCategories", [])
                ],
                "uploads_playlist": "UU" + it["id"][2:],  # derive, no extra call
            }
    return out


# ----------------------------------------------------------------------------
# 3. Channel baseline (playlistItems.list + videos.list — ~2 units per channel)
# ----------------------------------------------------------------------------


def channel_recent_videos(channel_id, n=50):
    """Last n uploads with full stats. Uploads playlist = 'UU' + channelId[2:]."""
    data = call(
        "playlistItems",
        1,
        part="contentDetails",
        playlistId="UU" + channel_id[2:],
        maxResults=min(n, 50),
        fields="items/contentDetails/videoId",
    )
    ids = [it["contentDetails"]["videoId"] for it in data.get("items", [])]
    return list(enrich_videos(ids).values()) if ids else []


def channel_baseline(videos, subs, min_age_days=30, max_age_days=180):
    """Median views over long-form uploads in a fixed age window (age-normalization lite)."""
    now = datetime.now(timezone.utc)
    eligible = []
    for v in videos:
        age = (now - datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))).days
        if min_age_days <= age <= max_age_days and not v["is_short"]:
            eligible.append(v)
    if not eligible:
        return None
    views = [v["views"] for v in eligible]
    med = statistics.median(views)
    dates = sorted(
        datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")) for v in eligible
    )
    cadence = ((dates[-1] - dates[0]).days / max(len(dates) - 1, 1)) if len(dates) > 1 else None
    return {
        "n": len(eligible),
        "median_views": med,
        "p90_views": sorted(views)[int(0.9 * (len(views) - 1))],
        "views_per_sub": (med / subs) if subs else None,
        "upload_interval_days": cadence,
        "breakthroughs": [
            v["video_id"]
            for v in eligible
            if v["views"] >= 5 * med or (subs and v["views"] >= 10 * subs)
        ],
    }


# ----------------------------------------------------------------------------
# 4. Comment sampling (commentThreads.list — 1 unit per 100 comments)
# ----------------------------------------------------------------------------


def sample_comments(video_id, n=100):
    """Feed to a language detector for audience-geo (RPM) estimation."""
    data = call(
        "commentThreads",
        1,
        part="snippet",
        videoId=video_id,
        maxResults=min(n, 100),
        order="relevance",
        textFormat="plainText",
        fields="items/snippet/topLevelComment/snippet(authorChannelId/value,textOriginal,likeCount,publishedAt)",
    )
    if data.get("_disabled"):
        return None
    return [
        {
            "author": c["snippet"]["topLevelComment"]["snippet"]
            .get("authorChannelId", {})
            .get("value"),
            "text": c["snippet"]["topLevelComment"]["snippet"]["textOriginal"],
            "likes": c["snippet"]["topLevelComment"]["snippet"]["likeCount"],
        }
        for c in data.get("items", [])
    ]


# ----------------------------------------------------------------------------
# 5. Storage (SQLite; swap for Postgres when the pipeline grows)
# ----------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos   (video_id TEXT PRIMARY KEY, channel_id TEXT, data JSON, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, data JSON, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS baselines(channel_id TEXT, data JSON, computed_at TEXT);
CREATE TABLE IF NOT EXISTS snapshots(video_id TEXT, views INTEGER, at TEXT);
CREATE TABLE IF NOT EXISTS discoveries(video_id TEXT, query TEXT, order_by TEXT, at TEXT);
"""


def db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    return con


def upsert(con, table, key, key_val, data, extra=None):
    now = datetime.now(timezone.utc).isoformat()
    cols = {key: key_val, "data": json.dumps(data), "fetched_at": now, **(extra or {})}
    con.execute(
        f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        list(cols.values()),
    )


# ----------------------------------------------------------------------------
# 6. Orchestration for one niche run
# ----------------------------------------------------------------------------


def run_niche(queries, search_pages=2, baseline_limit=300, small_channel_max_subs=10_000):
    con = db()
    now = datetime.now(timezone.utc).isoformat()

    # Discovery: both an unbiased pool (date) and the winners (viewCount)
    found = []
    for q in queries:
        for order in ("date", "viewCount"):
            for row in discover(q, pages=search_pages, order=order):
                found.append(row)
                con.execute(
                    "INSERT INTO discoveries VALUES (?,?,?,?)", (row["video_id"], q, order, now)
                )
    video_ids = {r["video_id"] for r in found}
    print(f"discovered {len(video_ids)} videos, quota used {Q.used}")

    # Enrich videos + channels
    videos = enrich_videos(video_ids)
    for vid, v in videos.items():
        upsert(con, "videos", "video_id", vid, v, {"channel_id": v["channel_id"]})
        con.execute("INSERT INTO snapshots VALUES (?,?,?)", (vid, v["views"], now))
    channels = enrich_channels({v["channel_id"] for v in videos.values()})
    for cid, c in channels.items():
        upsert(con, "channels", "channel_id", cid, c)
    print(f"enriched {len(videos)} videos / {len(channels)} channels, quota used {Q.used}")

    # Baselines for small channels first (that's where the signal is)
    small = [
        c
        for c in channels.values()
        if c["subs"] is not None and c["subs"] <= small_channel_max_subs
    ]
    for c in small[:baseline_limit]:
        vids = channel_recent_videos(c["channel_id"])
        for v in vids:
            upsert(con, "videos", "video_id", v["video_id"], v, {"channel_id": v["channel_id"]})
            con.execute("INSERT INTO snapshots VALUES (?,?,?)", (v["video_id"], v["views"], now))
        b = channel_baseline(vids, c["subs"])
        if b:
            con.execute(
                "INSERT INTO baselines VALUES (?,?,?)", (c["channel_id"], json.dumps(b), now)
            )
    con.commit()

    # Quick niche-level summary
    rows = [
        json.loads(r[0])
        for r in con.execute("SELECT data FROM baselines WHERE computed_at=?", (now,))
    ]
    if rows:
        br = sum(1 for b in rows if b["breakthroughs"]) / len(rows)
        print(f"small channels baselined: {len(rows)}  breakthrough rate: {br:.1%}")
    print(f"done. quota used: {Q.used}")
    con.close()


if __name__ == "__main__":
    run_niche(sys.argv[1:] or ["aviation disasters documentary"])
