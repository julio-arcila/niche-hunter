"""
niche_hunter_rss.py — zero-quota tracking layer for the Niche Hunter.

Feed URLs (no auth, no API quota):
  https://www.youtube.com/feeds/videos.xml?channel_id=UC...
  https://www.youtube.com/feeds/videos.xml?playlist_id=PL.../UU.../UULF.../UUSH...

What a feed gives you (last 15 entries only, no pagination):
  videoId, channelId, title, published, updated, description, thumbnail URL,
  media:statistics views, media:starRating count (≈ likes since dislikes were hidden)

What it does NOT give you: duration, comment count, subscriber count, tags,
category, Shorts flag. Enrich new videos once via videos.list (1 unit / 50).

Usage:
  python niche_hunter_rss.py            # polls every channel in the channels table
  NH_DB=niche_hunter.db python niche_hunter_rss.py --hot   # only channels flagged hot
"""

import os
import sys
import json
import time
import random
import sqlite3
import statistics
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

DB_PATH = os.environ.get("NH_DB", "niche_hunter.db")
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
HEADERS = {"User-Agent": "niche-hunter-rss/0.1 (+contact@example.com)"}
WORKERS = 8  # polite concurrency; feeds are unofficial, don't hammer them
JITTER_S = (0.2, 0.8)

SCHEMA = """
CREATE TABLE IF NOT EXISTS rss_snapshots (
    video_id TEXT, channel_id TEXT, views INTEGER, likes INTEGER, at TEXT);
CREATE INDEX IF NOT EXISTS ix_rss_video ON rss_snapshots(video_id, at);
CREATE TABLE IF NOT EXISTS rss_videos (
    video_id TEXT PRIMARY KEY, channel_id TEXT, title TEXT, published_at TEXT,
    thumbnail TEXT, description TEXT, first_seen TEXT, enriched INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS feed_state (
    channel_id TEXT PRIMARY KEY, etag TEXT, last_modified TEXT, last_polled TEXT,
    last_status INTEGER, fail_count INTEGER DEFAULT 0, hot INTEGER DEFAULT 0);
"""


# ----------------------------------------------------------------------------
# Fetch + parse
# ----------------------------------------------------------------------------


def fetch_feed(channel_id, etag=None, last_modified=None):
    headers = dict(HEADERS)
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    time.sleep(random.uniform(*JITTER_S))
    r = requests.get(FEED.format(channel_id), headers=headers, timeout=20)
    if r.status_code == 304:
        return 304, None, etag, last_modified
    if r.status_code == 429:
        time.sleep(30)
        return 429, None, etag, last_modified
    if r.status_code != 200:
        return r.status_code, None, etag, last_modified
    return 200, r.text, r.headers.get("ETag"), r.headers.get("Last-Modified")


def parse_feed(xml_text):
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        mg = e.find("media:group", NS)
        comm = mg.find("media:community", NS) if mg is not None else None
        stats = comm.find("media:statistics", NS) if comm is not None else None
        rating = comm.find("media:starRating", NS) if comm is not None else None
        thumb = mg.find("media:thumbnail", NS) if mg is not None else None
        desc = mg.find("media:description", NS) if mg is not None else None
        out.append(
            {
                "video_id": e.findtext("yt:videoId", namespaces=NS),
                "channel_id": e.findtext("yt:channelId", namespaces=NS),
                "title": e.findtext("a:title", namespaces=NS),
                "published_at": e.findtext("a:published", namespaces=NS),
                "updated_at": e.findtext("a:updated", namespaces=NS),
                "views": int(stats.get("views", 0)) if stats is not None else None,
                "likes": int(rating.get("count", 0)) if rating is not None else None,
                "thumbnail": thumb.get("url") if thumb is not None else None,
                "description": (desc.text or "")[:2000] if desc is not None else "",
            }
        )
    return out


# ----------------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------------


def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.executescript(SCHEMA)
    return con


def store(con, channel_id, entries, status, etag, last_mod):
    now = datetime.now(timezone.utc).isoformat()
    new_ids = []
    if entries:
        for v in entries:
            cur = con.execute("SELECT 1 FROM rss_videos WHERE video_id=?", (v["video_id"],))
            if cur.fetchone() is None:
                new_ids.append(v["video_id"])
                con.execute(
                    "INSERT INTO rss_videos (video_id,channel_id,title,published_at,thumbnail,description,first_seen) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        v["video_id"],
                        v["channel_id"],
                        v["title"],
                        v["published_at"],
                        v["thumbnail"],
                        v["description"],
                        now,
                    ),
                )
            if v["views"] is not None:
                con.execute(
                    "INSERT INTO rss_snapshots VALUES (?,?,?,?,?)",
                    (v["video_id"], v["channel_id"], v["views"], v["likes"], now),
                )
    fails = 0 if status in (200, 304) else 1
    con.execute(
        "INSERT INTO feed_state (channel_id,etag,last_modified,last_polled,last_status,fail_count) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET etag=excluded.etag, "
        "last_modified=excluded.last_modified, last_polled=excluded.last_polled, "
        "last_status=excluded.last_status, fail_count=fail_count+?",
        (channel_id, etag, last_mod, now, status, fails, fails),
    )
    return new_ids


# ----------------------------------------------------------------------------
# Poll loop
# ----------------------------------------------------------------------------


def poll_channel(channel_id, etag, last_mod):
    status, xml_text, etag, last_mod = fetch_feed(channel_id, etag, last_mod)
    entries = parse_feed(xml_text) if xml_text else None
    return channel_id, status, entries, etag, last_mod


def poll_all(hot_only=False):
    con = db()
    q = (
        "SELECT c.channel_id, f.etag, f.last_modified FROM channels c "
        "LEFT JOIN feed_state f USING(channel_id) "
        "WHERE COALESCE(f.fail_count,0) < 5"
    )
    if hot_only:
        q += " AND f.hot = 1"
    targets = con.execute(q).fetchall()
    con.close()
    print(f"polling {len(targets)} channels")

    new_video_ids, stats = [], {200: 0, 304: 0, "err": 0}
    con = db()
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(poll_channel, cid, et, lm) for cid, et, lm in targets]
        for i, f in enumerate(as_completed(futs), 1):
            cid, status, entries, etag, lm = f.result()
            new_video_ids += store(con, cid, entries, status, etag, lm)
            stats[status if status in (200, 304) else "err"] += 1
            if i % 200 == 0:
                con.commit()
    con.commit()
    con.close()
    print(f"done: {stats}  new videos: {len(new_video_ids)}")
    return new_video_ids  # hand these to enrich_videos() in niche_hunter_yt.py


# ----------------------------------------------------------------------------
# Derived metrics (read-only; run after a few days of snapshots)
# ----------------------------------------------------------------------------


def video_velocity(con, video_id):
    """views/day over last 24h and since publish, from rss_snapshots."""
    rows = con.execute(
        "SELECT views, at FROM rss_snapshots WHERE video_id=? ORDER BY at", (video_id,)
    ).fetchall()
    if len(rows) < 2:
        return None
    pub = con.execute(
        "SELECT published_at FROM rss_videos WHERE video_id=?", (video_id,)
    ).fetchone()
    t = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    (v0, t0), (v1, t1) = rows[0], rows[-1]
    days_span = max((t(t1) - t(t0)).total_seconds() / 86400, 1e-6)
    age_days = max((t(t1) - t(pub[0])).total_seconds() / 86400, 1e-6) if pub else None
    last = [r for r in rows if (t(t1) - t(r[1])).total_seconds() <= 86400 * 1.05]
    vel_24h = (
        (last[-1][0] - last[0][0])
        / max((t(last[-1][1]) - t(last[0][1])).total_seconds() / 86400, 1e-6)
        if len(last) > 1
        else None
    )
    return {
        "views_now": v1,
        "age_days": age_days,
        "views_per_day_lifetime": v1 / age_days if age_days else None,
        "views_per_day_observed": (v1 - v0) / days_span,
        "views_per_day_24h": vel_24h,
        "acceleration": (vel_24h / ((v1 - v0) / days_span)) if vel_24h and v1 > v0 else None,
    }


def channel_breakthroughs(con, channel_id, k=5.0):
    """Videos whose current views >= k x channel median, using feed data only."""
    rows = con.execute(
        "SELECT video_id, MAX(views) FROM rss_snapshots WHERE channel_id=? GROUP BY video_id",
        (channel_id,),
    ).fetchall()
    if len(rows) < 5:
        return []
    med = statistics.median(v for _, v in rows)
    return [(vid, v, round(v / med, 1)) for vid, v in rows if med and v >= k * med]


def mark_hot(con, channel_id, hot=True):
    con.execute("UPDATE feed_state SET hot=? WHERE channel_id=?", (int(hot), channel_id))


if __name__ == "__main__":
    poll_all(hot_only="--hot" in sys.argv)
