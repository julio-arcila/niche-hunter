from __future__ import annotations

from nh.config import Settings


def test_importing_a_collector_never_requires_credentials():
    """The prototypes raised KeyError at import time on a missing env var,
    which made them unimportable and therefore untestable."""
    from nh.collectors import (  # noqa: F401
        keyword_planner,
        reddit,
        trends,
        youtube_api,
        youtube_rss,
    )


def test_configured_is_per_source():
    s = Settings(yt_api_key="k", reddit_client_id=None)
    assert s.configured("youtube_api")
    assert s.configured("youtube_rss")  # no auth needed
    assert not s.configured("reddit")


def test_unknown_source_defaults_to_configured():
    assert Settings().configured("wikipedia")
