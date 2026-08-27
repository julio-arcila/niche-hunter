"""
niche_hunter_reddit.py — Reddit demand-side layer for the Niche Hunter (PRAW).

pip install praw

ACCESS REALITY (2026):
  * Reddit's Responsible Builder Policy requires approval BEFORE any API access.
    Self-service app registration closed in late 2025. File the access ticket,
    describe the use case honestly, wait. Grandfathered credentials still work.
  * Free tier once approved: ~100 queries/min per OAuth client, averaged over a
    10-minute window. One listing call returns up to 100 items, so this is not
    the bottleneck — approval is.
  * Use a real User-Agent in the required format or you get throttled:
      "<platform>:<app_id>:<version> (by u/<username>)"
  * Watch reddit.auth.limits (remaining / reset) — that header is the truth,
    not any number in a blog post.

WHAT REDDIT GIVES THE NICHE HUNTER (that YouTube/Trends don't):
  1. Subreddit ecosystem per niche  -> size, activity, growth via snapshots
  2. Question mining                -> unmet demand phrased as questions, upvote-weighted
  3. "Recommend a channel" threads  -> supply detection: who's already serving this
  4. YouTube links in the wild      -> which videos/channels the community shares
  5. RPM/CPM disclosures            -> calibration data for the RPM model
  6. Comment text                   -> language/geo proxy, vocabulary for embeddings

Usage:
  export REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=... REDDIT_USER_AGENT="linux:nichehunter:0.1 (by u/you)"
  python niche_hunter_reddit.py "aviation disasters" "plane crash"
"""

import os
import re
import sys
import json
import time
import sqlite3
from datetime import datetime, timezone
from collections import Counter

import praw
from prawcore.exceptions import TooManyRequests, Forbidden, NotFound

DB_PATH = os.environ.get("NH_DB", "niche_hunter.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS reddit_subs (
    name TEXT, subscribers INTEGER, active INTEGER, created_utc INTEGER,
    nsfw INTEGER, title TEXT, description TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS reddit_posts (
    id TEXT PRIMARY KEY, subreddit TEXT, title TEXT, selftext TEXT, url TEXT,
    score INTEGER, upvote_ratio REAL, num_comments INTEGER, created_utc INTEGER,
    flair TEXT, is_question INTEGER, yt_ids TEXT, query TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS reddit_rpm_disclosures (
    post_id TEXT, subreddit TEXT, metric TEXT, value REAL, niche_hint TEXT,
    created_utc INTEGER, excerpt TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS reddit_comments (
    id TEXT PRIMARY KEY, post_id TEXT, body TEXT, score INTEGER, created_utc INTEGER);
"""

QUESTION_RE = re.compile(
    r"^(how|why|what|when|where|which|who|can|does|do|is|are|should|eli5|anyone know|"
    r"looking for|recommend|any good)\b|\?$",
    re.I,
)
YT_ID_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")
YT_CHANNEL_RE = re.compile(r"youtube\.com/(?:@[\w.-]+|channel/UC[\w-]{22}|c/[\w.-]+)")
RPM_RE = re.compile(
    r"\b(rpm|cpm)\b[^$\d]{0,40}\$?\s?(\d{1,3}(?:\.\d{1,2})?)|"
    r"\$\s?(\d{1,3}(?:\.\d{1,2})?)\s*(rpm|cpm)\b",
    re.I,
)


# ----------------------------------------------------------------------------
# Client
# ----------------------------------------------------------------------------


def client():
    r = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ["REDDIT_USER_AGENT"],
        ratelimit_seconds=600,  # let PRAW sleep through a window instead of raising
    )
    r.read_only = True
    return r


def guarded(fn, *a, **kw):
    """Retry on 429 with backoff informed by rate-limit headers."""
    for attempt in range(5):
        try:
            return fn(*a, **kw)
        except TooManyRequests:
            time.sleep(min(300, 15 * 2**attempt))
        except (Forbidden, NotFound):
            return None
    return None


def limits(reddit):
    l = reddit.auth.limits
    return {k: l.get(k) for k in ("remaining", "used", "reset_timestamp")}


def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.executescript(SCHEMA)
    return con


# ----------------------------------------------------------------------------
# 1. Subreddit ecosystem
# ----------------------------------------------------------------------------


def find_subreddits(reddit, query, limit=25):
    """Map a niche keyword to its subreddits. Snapshot size/activity every run."""
    out = []
    for s in guarded(lambda: list(reddit.subreddits.search(query, limit=limit))) or []:
        out.append(snapshot_subreddit(s))
    return [s for s in out if s]


def snapshot_subreddit(s):
    try:
        return {
            "name": s.display_name,
            "subscribers": s.subscribers,
            "active": getattr(s, "accounts_active", None) or getattr(s, "active_user_count", None),
            "created_utc": int(s.created_utc),
            "nsfw": int(bool(s.over18)),
            "title": s.title,
            "description": (s.public_description or "")[:500],
        }
    except (Forbidden, NotFound):
        return None


# ----------------------------------------------------------------------------
# 2–4. Post harvesting: questions, channel-recommendation threads, YT links
# ----------------------------------------------------------------------------


def harvest_posts(reddit, subreddit, query=None, sort="new", time_filter="month", limit=500):
    """
    query=None  -> listing (new/hot/top/rising) — volume + cadence
    query=str   -> subreddit.search — topic-specific demand
    Listings cap around 1000 items; vary time_filter and sort to widen coverage.
    """
    sub = reddit.subreddit(subreddit)
    if query:
        gen = sub.search(query, sort=sort, time_filter=time_filter, limit=limit)
    else:
        gen = {
            "new": sub.new,
            "hot": sub.hot,
            "rising": sub.rising,
            "top": lambda limit: sub.top(time_filter=time_filter, limit=limit),
        }[sort](limit=limit)
    posts = guarded(lambda: list(gen)) or []
    rows = []
    for p in posts:
        text = f"{p.title}\n{getattr(p, 'selftext', '') or ''}\n{p.url or ''}"
        rows.append(
            {
                "id": p.id,
                "subreddit": subreddit,
                "title": p.title,
                "selftext": (getattr(p, "selftext", "") or "")[:4000],
                "url": p.url,
                "score": p.score,
                "upvote_ratio": p.upvote_ratio,
                "num_comments": p.num_comments,
                "created_utc": int(p.created_utc),
                "flair": p.link_flair_text,
                "is_question": int(bool(QUESTION_RE.search(p.title.strip()))),
                "yt_ids": json.dumps(sorted(set(YT_ID_RE.findall(text)))),
                "query": query,
            }
        )
    return rows


def question_clusters(rows, min_score=3):
    """Upvote-weighted question titles -> raw material for your embedding/cluster step."""
    qs = [
        (r["title"], r["score"], r["num_comments"])
        for r in rows
        if r["is_question"] and r["score"] >= min_score
    ]
    return sorted(qs, key=lambda x: -(x[1] + 2 * x[2]))


def supply_signals(rows):
    """
    From 'recommend a channel' style threads: how many get answered with YouTube links,
    and which channels/videos keep appearing. Unanswered recommendation requests are gaps.
    """
    rec = [
        r
        for r in rows
        if re.search(
            r"recommend|any good|looking for.*(channel|video|documentar)", r["title"], re.I
        )
    ]
    answered = [r for r in rec if json.loads(r["yt_ids"])]
    vid_counter = Counter(v for r in rows for v in json.loads(r["yt_ids"]))
    return {
        "recommendation_threads": len(rec),
        "answered_with_youtube": len(answered),
        "unanswered_rate": round(1 - len(answered) / len(rec), 2) if rec else None,
        "top_shared_video_ids": vid_counter.most_common(25),  # feed to videos.list -> channels
    }


def comments_for(reddit, post_id, limit=200):
    sub = guarded(lambda: reddit.submission(id=post_id))
    if not sub:
        return []
    sub.comments.replace_more(limit=0)  # each replace_more costs a request; 0 = top-level only
    return [
        {
            "id": c.id,
            "post_id": post_id,
            "body": c.body[:4000],
            "score": c.score,
            "created_utc": int(c.created_utc),
        }
        for c in sub.comments.list()[:limit]
    ]


# ----------------------------------------------------------------------------
# 5. RPM / CPM disclosures for calibration
# ----------------------------------------------------------------------------

CREATOR_SUBS = [
    "PartneredYoutube",
    "NewTubers",
    "youtube",
    "youtubers",
    "YouTube_startups",
    "YoutubeAutomation",
]


def rpm_disclosures(reddit, subs=CREATOR_SUBS, per_sub=300, time_filter="year"):
    """
    Pulls posts mentioning RPM/CPM with a dollar figure. Niche hint = title words.
    These are noisy; use as calibration points with n>=5 per niche, not gospel.
    """
    out = []
    for s in subs:
        for r in harvest_posts(
            reddit, s, query="rpm OR cpm", sort="new", time_filter=time_filter, limit=per_sub
        ):
            text = f"{r['title']}\n{r['selftext']}"
            for m in RPM_RE.finditer(text):
                metric = (m.group(1) or m.group(4)).lower()
                val = float(m.group(2) or m.group(3))
                if 0.1 <= val <= 100:
                    out.append(
                        {
                            "post_id": r["id"],
                            "subreddit": s,
                            "metric": metric,
                            "value": val,
                            "niche_hint": r["title"][:120],
                            "created_utc": r["created_utc"],
                            "excerpt": text[max(0, m.start() - 80) : m.end() + 80].replace(
                                "\n", " "
                            ),
                        }
                    )
    return out


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------


def run(niche_terms, per_query_limit=300):
    reddit, con = client(), db()
    now = datetime.now(timezone.utc).isoformat()

    # ecosystem
    subs = {}
    for t in niche_terms:
        for s in find_subreddits(reddit, t):
            subs[s["name"]] = s
    for s in subs.values():
        con.execute(
            "INSERT INTO reddit_subs VALUES (?,?,?,?,?,?,?,?)",
            (
                s["name"],
                s["subscribers"],
                s["active"],
                s["created_utc"],
                s["nsfw"],
                s["title"],
                s["description"],
                now,
            ),
        )
    ranked = sorted(subs.values(), key=lambda s: -(s["subscribers"] or 0))
    print(f"{len(ranked)} subreddits; top: {[(s['name'], s['subscribers']) for s in ranked[:8]]}")

    # demand: topic search across top subs + a broad r/all search
    all_rows = []
    for s in ranked[:8]:
        for t in niche_terms:
            rows = harvest_posts(
                reddit, s["name"], query=t, sort="new", time_filter="year", limit=per_query_limit
            )
            all_rows += rows
    for t in niche_terms:
        all_rows += harvest_posts(
            reddit, "all", query=t, sort="top", time_filter="year", limit=per_query_limit
        )
    for r in all_rows:
        con.execute(
            "INSERT OR REPLACE INTO reddit_posts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["id"],
                r["subreddit"],
                r["title"],
                r["selftext"],
                r["url"],
                r["score"],
                r["upvote_ratio"],
                r["num_comments"],
                r["created_utc"],
                r["flair"],
                r["is_question"],
                r["yt_ids"],
                r["query"],
                now,
            ),
        )
    con.commit()

    qs = question_clusters(all_rows)
    sup = supply_signals(all_rows)
    print(
        f"posts: {len(all_rows)}  questions: {len(qs)}  supply: {json.dumps({k: v for k, v in sup.items() if k != 'top_shared_video_ids'})}"
    )
    for title, score, nc in qs[:15]:
        print(f"  [{score:>4} ^ {nc:>3} c] {title}")
    print("  top shared video ids ->", [v for v, _ in sup["top_shared_video_ids"][:10]])

    # calibration
    disc = rpm_disclosures(reddit)
    for d in disc:
        con.execute(
            "INSERT INTO reddit_rpm_disclosures VALUES (?,?,?,?,?,?,?,?)",
            (
                d["post_id"],
                d["subreddit"],
                d["metric"],
                d["value"],
                d["niche_hint"],
                d["created_utc"],
                d["excerpt"],
                now,
            ),
        )
    con.commit()
    print(f"rpm/cpm disclosures captured: {len(disc)}   rate limits: {limits(reddit)}")
    con.close()


if __name__ == "__main__":
    run(sys.argv[1:] or ["aviation disasters", "plane crash investigation"])
