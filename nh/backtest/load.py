"""Materialise a selected backtest population into a separate database.

The backtest reuses `nh/features/*` unchanged (ADR-0026), so it has to hand those
functions the tables they already read: `channels`, `channel_snapshots`, `videos`,
`cluster_members`, `clusters`. This module is the adapter, and it is the only place
where YouNiverse's vocabulary is translated into the project's.

It writes into `data/backtest.db`, never the live corpus, and `refuse_live()` makes
that a precondition rather than an instruction. The live database holds six
production seeds with real history; a replay dropping 30 fake clusters and millions
of 2019 rows into it would leave `nh nightly` RSS-polling channels that stopped
uploading in 2019 and ranking live niches against phantom ones.

What is deliberately NOT loaded:

- **Crawl-time subscriber and video counts** (`subscribers_cc`, `videos_cc`). They
  describe 2019-10 and a replay scores 2017; writing them as a snapshot at any
  earlier `observed_date` is precisely the leak Phase A closed.
- **Video titles and descriptions.** The relevance score is computed once during
  the scan and stored on `cluster_members.relevance`; the three threshold variants
  are read-time cuts on that number, so no downstream step needs the text again.
  Keeping it would add tens of GB to hold data nothing reads.
- **Per-video view counts.** YouNiverse has them only at crawl time — one 2019-11
  reading per video, dated after nearly every decision date. Loading them would
  produce a `video_snapshots` table that every bounded query correctly ignores while
  looking, to a reader, like reach history. `supply.median_views` is therefore not
  replayable and `supply.views_per_new_video` stands in for it; the report says so.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.backtest.niches import by_slug
from nh.backtest.select import Selection
from nh.backtest.youniverse import CRAWL_DATE, channels, weeks
from nh.db.models import (
    Channel,
    ChannelSnapshot,
    Cluster,
    ClusterMember,
    NicheSeed,
    SeedTerm,
    Video,
)
from nh.db.session import session_scope
from nh.db.upsert import insert_ignore, upsert

SOURCE = "youniverse"
#: Rows per flush. The timeseries file is 18.9M rows; holding a niche's worth in
#: memory is fine, holding the file is not.
CHUNK = 5_000


class RefusingLiveDatabase(RuntimeError):
    """Raised when `load` is pointed at anything but a dedicated backtest file."""


@dataclass(slots=True)
class LoadReport:
    clusters: int = 0
    channels: int = 0
    channel_weeks: int = 0
    videos: int = 0
    video_members: int = 0
    #: Channels selected into a niche that YouNiverse's channel file does not
    #: describe. Counted, never silently dropped.
    channels_without_metadata: list[str] = field(default_factory=list)


def refuse_live(engine: Engine) -> None:
    """The backtest may only write to a database whose name says what it is.

    A substring check on the URL, not a check for "is this the configured live URL".
    The negative form fails open — a second live database, a copy, a Postgres URL —
    while the positive form fails closed: an operator who has not deliberately
    pointed at a backtest file gets an exception instead of a contaminated corpus.
    """
    url = str(engine.url)
    if "backtest" not in url:
        raise RefusingLiveDatabase(
            f"refusing to load backtest data into {url!r}: the database name must "
            "contain 'backtest'. Set NH_DATABASE_URL=sqlite:///data/backtest.db."
        )


def _stamp(run_id: str, at: datetime) -> dict[str, object]:
    return {"source": SOURCE, "run_id": run_id, "at": at}


def _clusters(engine: Engine, selection: Selection, run_id: str, at: datetime) -> int:
    """One seed and one cluster per surviving niche.

    `clusters.cluster_id` is the slug itself rather than a generated id, so a row in
    `features_daily` names its niche and the replay's output is readable without a
    join.
    """
    catalogue = by_slug()
    with session_scope(engine) as session:
        for slug in selection.kept:
            niche = catalogue[slug]
            upsert(
                session,
                NicheSeed,
                [
                    {
                        "slug": slug,
                        "label": niche["label"],
                        "keywords": list(niche["lexicon"])[:20],
                        "geo": niche.get("geo"),
                        "lang": "en",
                        "active": True,
                        "notes": "backtest niche (YouNiverse), not a production seed",
                    }
                ],
                conflict_on=["slug"],
            )
        seeds = dict(session.execute(sa.select(NicheSeed.slug, NicheSeed.id)).all())
        # Demand terms, without which every demand metric returns empty and `gap`
        # is NULL for every niche — a backtest that computes nothing while running
        # cleanly. The topic stratum only: it is the pre-registered primary, and the
        # event stratum needs `scripts/select_demand_articles.py` to resolve each
        # pool against Wikidata first, which is network work and a separate commit.
        upsert(
            session,
            SeedTerm,
            [
                {
                    "seed_id": seeds[slug],
                    "source": "wikipedia",
                    "term": article,
                    "geo": "",
                    "stratum": "topic",
                    "lang": "en",
                    "active": True,
                }
                for slug in selection.kept
                for article in catalogue[slug]["wiki_topic"]
            ],
            conflict_on=["seed_id", "source", "term", "stratum"],
        )
        upsert(
            session,
            Cluster,
            [
                {
                    "cluster_id": slug,
                    "seed_id": seeds.get(slug),
                    "label": catalogue[slug]["label"],
                    "active": True,
                    "member_counts": {"channel": len(selection.members[slug])},
                    **_stamp(run_id, at),
                }
                for slug in selection.kept
            ],
        )
    return len(selection.kept)


def _snapshots(
    engine: Engine, path: Path, members: set[str], run_id: str, at: datetime
) -> tuple[int, dict[str, date]]:
    """Weekly rows for member channels only, plus each channel's first observed week.

    `observed_date` is the week-ending date (ADR-0027). `subs` NULL where the source
    has no reading — `_window`'s daily arithmetic downstream reads a missing week as
    a gap, which is what it is.
    """
    written = 0
    first_week: dict[str, date] = {}
    batch: list[dict[str, object]] = []

    def flush() -> int:
        if not batch:
            return 0
        with session_scope(engine) as session:
            count = insert_ignore(
                session,
                ChannelSnapshot,
                batch,
                conflict_on=["channel_id", "observed_date", "source"],
            )
        batch.clear()
        return count

    for row in weeks(path, keep=members):
        seen = first_week.get(row.channel_id)
        if seen is None or row.week_ending < seen:
            first_week[row.channel_id] = row.week_ending
        batch.append(
            {
                "channel_id": row.channel_id,
                "observed_date": row.week_ending,
                "subs": row.subs,
                "total_views": row.views,
                "video_count": row.videos,
                **_stamp(run_id, at),
            }
        )
        if len(batch) >= CHUNK:
            written += flush()
    written += flush()
    return written, first_week


def _channels(
    engine: Engine,
    path: Path,
    members: set[str],
    first_week: dict[str, date],
    run_id: str,
    at: datetime,
) -> tuple[int, list[str]]:
    """Channel rows for the selected members.

    `first_seen` is the channel's first *weekly reading*, not its YouTube join date
    and not now. It is the day this pipeline could first have known the channel
    existed, and `inputs.member_join` bounds membership on it — so a channel whose
    series starts in 2018 is correctly invisible to a 2017 decision date.
    """
    written = 0
    batch: list[dict[str, object]] = []
    found: set[str] = set()

    def flush() -> int:
        if not batch:
            return 0
        with session_scope(engine) as session:
            count = upsert(session, Channel, batch)
        batch.clear()
        return count

    def midnight(day: date) -> datetime:
        return datetime.combine(day, datetime.min.time(), tzinfo=UTC)

    for row in channels(path):
        if row.channel_id not in members:
            continue
        found.add(row.channel_id)
        start = first_week.get(row.channel_id, CRAWL_DATE)
        batch.append(
            {
                "channel_id": row.channel_id,
                "title": row.name,
                # No country column in YouNiverse. NULL, not a guess — and
                # `supply.geo_concentration` reports itself uncomputable rather
                # than treating an all-NULL population as perfect concentration.
                "country": None,
                "created_at": midnight(row.join_date) if row.join_date else None,
                "first_seen": midnight(start),
                **_stamp(run_id, at),
            }
        )
        if len(batch) >= CHUNK:
            written += flush()
    written += flush()
    return written, sorted(members - found)


def _members(engine: Engine, selection: Selection, run_id: str, at: datetime) -> None:
    rows = [
        {
            "cluster_id": slug,
            "item_type": "channel",
            "item_id": channel_id,
            "is_noise": False,
            **_stamp(run_id, at),
        }
        for slug in selection.kept
        for channel_id in sorted(selection.members[slug])
    ]
    with session_scope(engine) as session:
        upsert(session, ClusterMember, rows, conflict_on=["item_type", "item_id"])


def _videos(
    engine: Engine, hits: Path, selection: Selection, run_id: str, at: datetime
) -> tuple[int, int]:
    """Videos and their memberships, from the scan's hit file.

    A hit is kept only when its slug is the niche its channel was actually assigned
    to. The scan scores a video against every niche whose prefilter it clears, so a
    video can appear several times; keeping all of them would put one video in
    several clusters and double-count it in every supply denominator.
    """
    owner = {channel_id: slug for slug in selection.kept for channel_id in selection.members[slug]}
    videos: list[dict[str, object]] = []
    members: list[dict[str, object]] = []
    written_videos = written_members = 0

    def flush() -> tuple[int, int]:
        if not videos:
            return 0, 0
        with session_scope(engine) as session:
            v = upsert(session, Video, videos)
            m = upsert(session, ClusterMember, members, conflict_on=["item_type", "item_id"])
        videos.clear()
        members.clear()
        return v, m

    with gzip.open(hits, "rt", encoding="utf-8") as handle:
        for line in handle:
            hit = json.loads(line)
            channel_id, video_id = hit.get("channel_id"), hit.get("video_id")
            if not video_id or owner.get(channel_id) != hit.get("slug"):
                continue
            published = hit.get("upload_date") or ""
            videos.append(
                {
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "published_at": (
                        datetime.fromisoformat(published).replace(tzinfo=UTC)
                        if len(published) == 10
                        else None
                    ),
                    "first_seen": at,
                    **_stamp(run_id, at),
                }
            )
            members.append(
                {
                    "cluster_id": hit["slug"],
                    "item_type": "video",
                    "item_id": video_id,
                    "relevance": hit.get("relevance"),
                    "is_noise": False,
                    "detail": {"scored_by": "nh.backtest.scan", "source": SOURCE},
                    **_stamp(run_id, at),
                }
            )
            if len(videos) >= CHUNK:
                v, m = flush()
                written_videos += v
                written_members += m
    v, m = flush()
    return written_videos + v, written_members + m


def load(
    engine: Engine,
    *,
    selection: Selection,
    hits: Path,
    channels_path: Path,
    timeseries_path: Path,
    run_id: str,
    at: datetime,
) -> LoadReport:
    """Write a selected population into a backtest database. Idempotent.

    Order is load-bearing: the weekly series is read first because it is what
    supplies each channel's `first_seen`, and `first_seen` is what bounds membership
    at a past decision date.
    """
    refuse_live(engine)
    report = LoadReport()
    members = {channel_id for slug in selection.kept for channel_id in selection.members[slug]}

    report.clusters = _clusters(engine, selection, run_id, at)
    report.channel_weeks, first_week = _snapshots(engine, timeseries_path, members, run_id, at)
    report.channels, report.channels_without_metadata = _channels(
        engine, channels_path, members, first_week, run_id, at
    )
    _members(engine, selection, run_id, at)
    report.videos, report.video_members = _videos(engine, hits, selection, run_id, at)
    return report
