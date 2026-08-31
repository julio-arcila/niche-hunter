"""Builders for feature-layer tests.

Feature tests need a small, readable world: a cluster, some channels with known
subscriber counts, and videos with known views, ages and formats. Constructing
that inline in every test buries the one thing each test is actually about, so it
lives here and each test states only its own deviation from the default.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa

from nh.db.models import (
    Channel,
    ChannelSnapshot,
    Cluster,
    ClusterMember,
    DemandSeries,
    DemandSnapshot,
    Discovery,
    FeatureDaily,
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


def rich_corpus(engine):
    """A world rich enough that every relevance-reading metric actually moves.

    **Deliberately not minimal, and every element below earns its place.** A thin fixture
    makes the derivation test pass vacuously: the metric returns `empty()` at BOTH
    thresholds, nothing moves, and it is classified citable forever. The first version of
    this fixture did exactly that for four of the eight, each for its own reason — no
    `Channel.country` (`geo_concentration`), every video older than the 28-day supply
    window (`format_mix`), fewer than 20 on-niche videos with views
    (`top10_concentration`), and no `Channel.created_at` (`winner_age_years`). Not one of
    those is a relevance fact, and all four would have shipped classified as "the scorer
    does not touch this".

    `test_every_gated_metric_is_computable_here` fails if that regresses, so a later
    tightening of some metric's minimum cannot quietly re-empty the fixture.
    """
    make_cluster(engine)
    # Inside the 28-day supply window, with known formats, and enough on-niche videos with
    # views to clear top10_concentration's floor of 20.
    add_channel(engine, "big", subs=50_000, videos=12, views=list(range(900, 780, -10)), age_days=3)
    add_channel(
        engine, "small", subs=800, videos=10, views=[5_000, *range(40, 130, 10)], age_days=5
    )
    add_channel(engine, "shorts", subs=3_000, videos=6, views=250, age_days=7, is_short=True)
    # Mixed relevance is what gives the threshold something to change its mind about.
    add_channel(
        engine,
        "mixed",
        subs=2_000,
        videos=4,
        views=300,
        age_days=9,
        relevant=[True, True, False, None],
    )
    add_channel(engine, "offniche", subs=1_500, videos=4, views=200, age_days=11, relevant=False)
    # `geo_concentration` reads relevance only THROUGH ballast, so the fixture needs a
    # channel whose ballast status flips with the threshold — nothing else exercises that
    # path. Ten decided-noise videos plus one on-niche: at the real threshold it has an
    # on-niche video and stays a member; at an impossible one it has ten decided and zero
    # on-niche, becomes ballast, and leaves the channel population. A channel that is
    # ballast on BOTH sides would move nothing and teach nothing.
    add_channel(
        engine,
        "tipping",
        subs=900,
        videos=11,
        views=150,
        age_days=13,
        relevant=[True, *([False] * 10)],
    )
    add_keyword_metrics(engine)
    _give_channels_a_country_and_an_age(engine)
    add_demand(engine)
    _add_a_second_cluster_for_ranks(engine)
    return session_for(engine)


def add_demand(engine, *, cluster_id: str = CLUSTER, seed_id: int = 1, day: date = DAY) -> None:
    """Wikipedia dailies and one Trends curve, plus the seed terms that claim them.

    Both halves again, for the reason `add_keyword_metrics` states: without the
    `seed_terms` rows `demand_terms` returns nothing and every wiki metric — and every
    wiki DRILLDOWN — comes back empty while passing any assertion that only checks it did
    not raise.

    The Trends row carries the whole curve in `points`, because a Trends response is
    renormalised to its own peak and the curve-as-observed is the only honest unit
    (ADR-0015). A fixture storing one point per row would model a table that does not
    exist.
    """
    with session_scope(engine) as s:
        for source, term in (("wikipedia", "Test_Article"), ("trends", "test term")):
            s.add(
                SeedTerm(seed_id=seed_id, source=source, term=term, lang="en", geo="", active=True)
            )
        for offset in range(400):
            s.add(
                DemandSnapshot(
                    term="Test_Article",
                    source="wikipedia",
                    geo="",
                    observed_date=day - timedelta(days=offset),
                    value=1_000.0 + offset % 7 * 50,
                    run_id=RUN,
                )
            )
        s.add(
            DemandSeries(
                term="test term",
                geo="",
                timeframe="today 5-y",
                observed_date=day,
                points=[[str(day - timedelta(weeks=w)), 50.0 - w] for w in range(26, -1, -1)],
                source="trends",
                run_id=RUN,
            )
        )


def _add_a_second_cluster_for_ranks(engine, day: date = DAY) -> None:
    """`pressure_index` is a rank ACROSS clusters, so one cluster cannot exercise it.

    Its drilldown returns every cluster's component values, because a rank is not checkable
    from the ranked row alone — which is also why the metric stamps `ranked_over` and warns
    that it is not comparable across days whose cluster set changed.
    """
    from nh.features.run import PRESSURE_FROM

    with session_scope(engine) as s:
        for i, cluster in enumerate((CLUSTER, "other-cluster")):
            for name in PRESSURE_FROM:
                s.add(
                    FeatureDaily(
                        cluster_id=cluster,
                        day=day,
                        metric_group="supply",
                        name=name,
                        value=1.0 + i,
                        confidence=0.5,
                        inputs_n=10,
                        detail={},
                        source="features",
                        run_id=RUN,
                    )
                )


def _give_channels_a_country_and_an_age(engine):
    """`add_channel` sets neither, and two metrics return `empty()` without them.

    Set here rather than in `conftest_features` because that builder is shared by the whole
    feature suite: giving every fixture channel a country would change what
    `geo_concentration` returns in tests that assert on its absence.
    """
    with session_scope(engine) as s:
        for i, channel_id in enumerate(sorted(s.scalars(sa.select(Channel.channel_id)))):
            channel = s.get(Channel, channel_id)
            channel.country = "US" if i % 2 == 0 else "GB"
            channel.created_at = _at(DAY - timedelta(days=400 + 100 * i))
