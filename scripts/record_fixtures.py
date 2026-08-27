"""Record real API responses into tests/fixtures/, once, by hand.

Tests must never touch the network (.claude/rules/data.md rule 7), so this runs
outside pytest. It needs a real `NH_YT_API_KEY` and costs about 102 quota units:
one `search.list` (100) plus one `videos.list` and one `channels.list` (1 each).

    uv run python scripts/record_fixtures.py

The fixtures currently checked in are hand-built to the *documented* response
shape. That pins the normalization logic, because `normalize()` is pure — but it
cannot catch a wrong assumption about what the API actually returns. Running this
replaces guesses with evidence. Re-run monthly per the Slice 8 runbook, since
response shapes drift.

Nothing written here may contain the API key: the key travels as a query
parameter, never in a response body, and this asserts that before writing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import requests

from nh.collectors.youtube_api import (
    _PARTS,
    API,
    CHANNEL_FIELDS,
    SEARCH_FIELDS,
    VIDEO_FIELDS,
)
from nh.collectors.youtube_rss import FEED_URL
from nh.config import get_settings

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
QUERY = "plane crash investigation"


def _get(endpoint: str, key: str, **params: Any) -> dict[str, Any]:
    params["key"] = key
    response = requests.get(f"{API}/{endpoint}", params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _write(path: Path, content: str, key: str) -> None:
    if key and key in content:
        raise SystemExit(f"refusing to write {path}: it contains the API key")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"  wrote {path.relative_to(FIXTURES.parent.parent)} ({len(content):,} bytes)")


def main() -> int:
    settings = get_settings()
    key = settings.yt_api_key
    if not key:
        print("NH_YT_API_KEY is not set — create .env from .env.example first.", file=sys.stderr)
        return 1

    print(f"recording youtube_api fixtures (~102 quota units) for {QUERY!r}")
    search = _get(
        "search",
        key,
        part="snippet",
        q=QUERY,
        type="video",
        order="viewCount",
        maxResults=5,
        relevanceLanguage="en",
        fields=SEARCH_FIELDS,
    )
    _write(FIXTURES / "youtube_api" / "search_page.json", json.dumps(search, indent=2), key)

    video_ids = [i["id"]["videoId"] for i in search.get("items", [])]
    channel_ids = [i["snippet"]["channelId"] for i in search.get("items", [])]
    if not video_ids:
        print("search returned nothing — pick a different QUERY", file=sys.stderr)
        return 1

    part, _ = _PARTS["videos"]
    videos = _get("videos", key, part=part, id=",".join(video_ids), fields=VIDEO_FIELDS)
    _write(FIXTURES / "youtube_api" / "videos.json", json.dumps(videos, indent=2), key)

    part, _ = _PARTS["channels"]
    channels = _get("channels", key, part=part, id=",".join(channel_ids), fields=CHANNEL_FIELDS)
    _write(FIXTURES / "youtube_api" / "channels.json", json.dumps(channels, indent=2), key)

    print("recording youtube_rss fixture (no quota cost)")
    feed = requests.get(
        FEED_URL.format(channel_ids[0]),
        headers={"User-Agent": settings.rss_user_agent},
        timeout=20,
    )
    feed.raise_for_status()
    _write(FIXTURES / "youtube_rss" / "feed_real.xml", feed.text, key)
    _write(
        FIXTURES / "youtube_rss" / "feed_headers.json",
        json.dumps(
            {k: v for k, v in feed.headers.items() if k.lower() in ("etag", "last-modified")},
            indent=2,
        ),
        key,
    )

    print(
        "\ndone. Now repoint the end-to-end tests in tests/test_youtube_api.py and\n"
        "tests/test_youtube_rss.py at these files and delete the hand-built payloads —\n"
        "any assertion that changes is a wrong assumption this just caught."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
