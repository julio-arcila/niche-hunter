"""Builders for feature-layer tests.

Feature tests need a small, readable world: a cluster, some channels with known
subscriber counts, and videos with known views, ages and formats. Constructing
that inline in every test buries the one thing each test is actually about, so it
lives here and each test states only its own deviation from the default.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from nh.db.models import (
    Channel,
    ChannelSnapshot,
    Cluster,
    ClusterMember,
    Discovery,
    Video,
    VideoSnapshot,
)
from nh.db.session import session_scope

CLUSTER = "aviation-disasters"
DAY = date(2026, 8, 27)
RUN = "test-run"


def _at(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _video_member(cluster_id: str, video_id: str, relevant: bool | None) -> ClusterMember:
    """One video membership row. `relevant=None` is unscorable: relevance stays NULL
    and `is_noise` stays False, because "unreadable" is not "off-niche"."""
    relevance = None if relevant is None else (0.9 if relevant else 0.0)
    return ClusterMember(
        cluster_id=cluster_id,
        item_type="video",
        item_id=video_id,
        relevance=relevance,
        is_noise=relevance == 0.0,
        source="clustering",
        run_id=RUN,
    )


def make_cluster(engine, cluster_id: str = CLUSTER) -> None:
    with session_scope(engine) as s:
        s.add(Cluster(cluster_id=cluster_id, label="Aviation", source="clustering", run_id=RUN))


def add_channel(
    engine,
    channel_id: str,
    *,
    subs: int | None = 1_000,
    cluster_id: str = CLUSTER,
    member: bool = True,
    noise: bool = False,
    date_lineage: bool = True,
    videos: int = 0,
    views: int | list[int] = 1_000,
    age_days: int = 60,
    is_short: bool | None = False,
    relevant: bool | list[bool] | None = True,
    day: date = DAY,
) -> list[str]:
    """A channel with `videos` uploads, returning their ids.

    `subs=None` means the count is hidden — the channel gets no ChannelSnapshot
    row at all, which is how a hidden count is represented (never a zero).
    `is_short=None` means unknown format, which is how an unenriched RSS video
    looks. `date_lineage` controls whether the channel was ever discovered under
    `order=date`, the cohort's unbiased-denominator filter. `noise=True` writes the
    membership row with `is_noise` set, which every metric must exclude.
    """
    view_list = views if isinstance(views, list) else [views] * videos
    ids = []
    with session_scope(engine) as s:
        s.add(Channel(channel_id=channel_id, title=channel_id, source="test", run_id=RUN))
        if subs is not None:
            s.add(
                ChannelSnapshot(
                    channel_id=channel_id,
                    observed_date=day,
                    subs=subs,
                    source="youtube_api",
                    run_id=RUN,
                )
            )
        if member:
            s.add(
                ClusterMember(
                    cluster_id=cluster_id,
                    item_type="channel",
                    item_id=channel_id,
                    confidence=1.0,
                    is_noise=noise,
                    source="clustering",
                    run_id=RUN,
                )
            )
        relevance_list = relevant if isinstance(relevant, list) else [relevant] * videos
        for i in range(videos):
            vid = f"{channel_id}-v{i}"
            ids.append(vid)
            if member:
                s.add(_video_member(cluster_id, vid, relevance_list[i]))
            s.add(
                Video(
                    video_id=vid,
                    channel_id=channel_id,
                    title=vid,
                    published_at=_at(day - timedelta(days=age_days + i)),
                    is_short=is_short,
                    midroll_eligible=None if is_short is None else not is_short,
                    source="youtube_rss",
                    run_id=RUN,
                )
            )
            s.add(
                VideoSnapshot(
                    video_id=vid,
                    channel_id=channel_id,
                    observed_date=day,
                    views=view_list[i],
                    source="youtube_rss",
                    run_id=RUN,
                )
            )
            if date_lineage and i == 0:
                s.add(
                    Discovery(
                        video_id=vid,
                        seed_id=None,
                        query="q",
                        order_by="date",
                        observed_date=day,
                        source="youtube_api",
                        run_id=RUN,
                    )
                )
            elif not date_lineage and i == 0:
                s.add(
                    Discovery(
                        video_id=vid,
                        seed_id=None,
                        query="q",
                        order_by="viewCount",
                        observed_date=day,
                        source="youtube_api",
                        run_id=RUN,
                    )
                )
    return ids


def session_for(engine):
    """A live session: feature functions take a Session, the fixtures give an Engine."""
    from nh.db.session import get_sessionmaker

    return get_sessionmaker(engine)()
