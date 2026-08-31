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
    KeywordMetric,
    NicheSeed,
    SeedTerm,
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


def make_cluster(engine, cluster_id: str = CLUSTER, *, seed_id: int | None = None) -> None:
    """A cluster, and by default the seed behind it.

    The seed matters: `supply.geo_concentration` returns `empty()` when the seed
    states no geo, so a fixture without one lets that metric pass every leakage
    test vacuously — which is how a day-blind metric shipped in the first place.
    """
    with session_scope(engine) as s:
        if seed_id is None:
            seed_id = 1
            if s.get(NicheSeed, seed_id) is None:
                s.add(
                    NicheSeed(id=seed_id, slug=cluster_id, label="Aviation", keywords=[], geo="US")
                )
                s.flush()
        s.add(
            Cluster(
                cluster_id=cluster_id,
                seed_id=seed_id,
                label="Aviation",
                source="clustering",
                run_id=RUN,
            )
        )


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
        # `first_seen` is set from `day`, not from the clock. DAY is a fixed date
        # in the past, so `utcnow()` would place every fixture channel AFTER the
        # day under test and the day-bounded membership joins would exclude it —
        # the fixture would be building a world that could not have existed.
        s.add(
            Channel(
                channel_id=channel_id,
                title=channel_id,
                first_seen=_at(day),
                source="test",
                run_id=RUN,
            )
        )
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


#: One realistic Keyword Planner basket: a priced keyword, an unpriced one, a
#: volume-less one, and the `humanism` GB shape — a SENTINEL low beside a REAL high,
#: which is the row a per-row exclusion rule would wrongly discard.
KP_BASKET = (
    # keyword, avg_monthly_searches, competition_index, bid_low, bid_high
    ("plane crash investigation", 50_000.0, 41, 1_200.0, 27_968.37),
    ("air traffic control", 5_000.0, 12, 900.0, 4_043.23),
    ("aviation safety", 500.0, 8, None, None),
    ("air crash analysis", None, 3, 300.0, 1_100.0),
    ("humanism", 50_000.0, 55, 6_408.34, 47_045.50),  # sentinel low, real high
)


def add_keyword_metrics(
    engine,
    *,
    cluster_id: str = CLUSTER,
    seed_id: int = 1,
    geo: str = "US",
    day: date = DAY,
    basket=KP_BASKET,
    currency: str = "COP",
    observed_offset_days: int = 30,
) -> None:
    """Seed terms plus day-dated Keyword Planner readings for a cluster.

    Both halves are required. Without the `seed_terms` rows the loader finds no curated
    keywords; without the `keyword_metrics` rows it finds no observations — and either
    way all five KP metrics return `empty()`, which passes every leakage assertion
    VACUOUSLY. That trap has already shipped two day-blind metrics here: it is why
    `make_cluster` sets a seed geo and why the leakage file carries `_set_country` and
    `_add_future_videos` as local patches.

    `observed_offset_days` places `observed_date` BEFORE `day` by default so the rows are
    visible; pass a negative offset to build a future-dated export that must not change a
    past answer.
    """
    observed = day - timedelta(days=observed_offset_days)
    with session_scope(engine) as s:
        existing = {
            t for (t,) in s.query(SeedTerm.term).filter(SeedTerm.source == "keyword_planner")
        }
        for keyword, volume, index, low, high in basket:
            if keyword not in existing:
                s.add(
                    SeedTerm(
                        seed_id=seed_id,
                        source="keyword_planner",
                        term=keyword,
                        lang="en",
                        geo="",  # curation is geo-independent (ADR-0038)
                        active=True,
                    )
                )
            s.add(
                KeywordMetric(
                    keyword=keyword,
                    geo=geo,
                    lang="en",
                    observed_date=observed,
                    period_start=observed - timedelta(days=364),
                    avg_monthly_searches=volume,
                    competition_index=index,
                    bid_low=low,
                    bid_high=high,
                    currency=currency,
                    method="ui_csv",
                    source="keyword_planner",
                    run_id=RUN,
                    at=_at(day),
                )
            )
