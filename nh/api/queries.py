"""Read functions behind every surface (ADR-0052).

Pure: they take a session and return dataclasses. No Streamlit import, no HTTP, no
rendering decision. That boundary is the whole of the "replaceable front end" argument the
roadmap made for FastAPI — a **module** boundary gives it, and a second process for one
operator on one machine adds a port to babysit and no capability.

`nh/jobs/niche.py` already did this for one command and keeps its job; this module is the
rest of the surface. The citation gate lives in `jobs/niche.py::load` and in `gates`, not
here, because these functions return raw observations that no scorer touched — the demand
series and the corpus do not become suspect because a lexicon is unproven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import (
    Alert,
    Channel,
    ChannelSnapshot,
    Cluster,
    ClusterMember,
    DemandSnapshot,
    Discovery,
    FeatureDaily,
    NicheSeed,
    Video,
    VideoSnapshot,
)
from nh.features.inputs import _until, demand_terms, member_channels

FEED_LIMIT = 50
SERIES_LIMIT = 400


@dataclass(slots=True)
class NicheLine:
    """One row of the niche list. **No score**, deliberately.

    ADR-0029 forbids a ranked surface and Gate E is why. A list sorted by any number is a
    ranking however it is captioned, so this carries only what a person needs to pick a
    niche to look at: what it is, whether it is collecting, and how much of it exists.
    """

    cluster_id: str
    label: str | None
    active: bool
    member_channels: int
    videos: int
    latest_day: date | None


@dataclass(slots=True)
class SeriesPoint:
    term: str
    day: date
    value: float


@dataclass(slots=True)
class ChannelLine:
    channel_id: str
    title: str | None
    country: str | None
    subs: int | None
    videos: int


@dataclass(slots=True)
class FeedLine:
    """One discovered video, with the query that found it.

    `query` and `order_by` are the provenance that makes the corpus auditable: ADR-0051
    replaced five queries because 25 of 30 asked for the word "explained" while the scorer
    grades being an explainer, and that was only visible because every video records what
    surfaced it.
    """

    video_id: str
    title: str | None
    channel_id: str
    published_at: object
    query: str | None
    order_by: str | None
    url: str


@dataclass(slots=True)
class MetricPoint:
    day: date
    value: float | None
    confidence: float | None
    inputs_n: int | None
    definition: str | None
    run_id: str | None
    detail: dict = field(default_factory=dict)


def niche_list(session: Session) -> list[NicheLine]:
    """Every cluster, alphabetically. See `NicheLine` for why there is no ordering key."""
    seeds = dict(session.execute(sa.select(NicheSeed.id, NicheSeed.active)).all())
    labels = dict(session.execute(sa.select(NicheSeed.id, NicheSeed.label)).all())
    counts = dict(
        session.execute(
            sa.select(ClusterMember.cluster_id, sa.func.count())
            .where(ClusterMember.item_type == "channel")
            .group_by(ClusterMember.cluster_id)
        ).all()
    )
    videos = dict(
        session.execute(
            sa.select(ClusterMember.cluster_id, sa.func.count())
            .where(ClusterMember.item_type == "video")
            .group_by(ClusterMember.cluster_id)
        ).all()
    )
    days = dict(
        session.execute(
            sa.select(FeatureDaily.cluster_id, sa.func.max(FeatureDaily.day)).group_by(
                FeatureDaily.cluster_id
            )
        ).all()
    )
    rows = session.execute(
        sa.select(Cluster.cluster_id, Cluster.seed_id).order_by(Cluster.cluster_id)
    ).all()
    return [
        NicheLine(
            cluster_id=cluster_id,
            label=labels.get(seed_id),
            active=bool(seeds.get(seed_id)),
            member_channels=counts.get(cluster_id, 0),
            videos=videos.get(cluster_id, 0),
            latest_day=days.get(cluster_id),
        )
        for cluster_id, seed_id in rows
    ]


def demand_series(session: Session, cluster_id: str, day: date) -> list[SeriesPoint]:
    """The Wikipedia daily series behind the demand metrics, oldest first for plotting.

    Ungated: nothing about `demand_snapshots` passes through the relevance scorer.
    """
    articles = demand_terms(session, cluster_id, "wikipedia")
    if not articles:
        return []
    rows = session.execute(
        sa.select(DemandSnapshot.term, DemandSnapshot.observed_date, DemandSnapshot.value)
        .where(
            DemandSnapshot.source == "wikipedia",
            DemandSnapshot.term.in_(articles),
            DemandSnapshot.observed_date <= day,
        )
        .order_by(DemandSnapshot.observed_date.desc())
        .limit(SERIES_LIMIT)
    ).all()
    return sorted(
        (SeriesPoint(term, observed, value) for term, observed, value in rows),
        key=lambda p: (p.day, p.term),
    )


def channel_table(session: Session, cluster_id: str, day: date) -> list[ChannelLine]:
    """The cluster's member channels — the population `openness.*` measures.

    Through `features.inputs.member_channels`, never a second membership query: two
    answers to "who is in this cluster" is the drift `supply._confidence`'s clamp comment
    calls a bug in the query rather than a value.
    """
    members = member_channels(session, cluster_id, day)
    if not members:
        return []
    subs = dict(
        session.execute(
            sa.select(ChannelSnapshot.channel_id, sa.func.max(ChannelSnapshot.subs))
            .where(ChannelSnapshot.channel_id.in_(members), ChannelSnapshot.observed_date <= day)
            .group_by(ChannelSnapshot.channel_id)
        ).all()
    )
    videos = dict(
        session.execute(
            sa.select(Video.channel_id, sa.func.count())
            .where(Video.channel_id.in_(members))
            .group_by(Video.channel_id)
        ).all()
    )
    rows = session.execute(
        sa.select(Channel.channel_id, Channel.title, Channel.country).where(
            Channel.channel_id.in_(members)
        )
    ).all()
    return sorted(
        (
            ChannelLine(cid, title, country, subs.get(cid), videos.get(cid, 0))
            for cid, title, country in rows
        ),
        key=lambda c: (-(c.subs or 0), c.channel_id),
    )


def source_feed(session: Session, cluster_id: str, day: date) -> list[FeedLine]:
    """Recently discovered videos and the query that surfaced each.

    The end of the three-click chain: a number, its input rows, and then the actual video
    on YouTube. **Bounded by `day`** — it took the argument and ignored it until the
    2026-08-31 review, so a page rendered for an older day showed videos published after
    it. Latent, because the page always asks for the latest day, and exactly the shape of
    the leak `inputs.py`'s docstring exists to prevent. `outerjoin` on `discoveries` because most of the corpus arrives by RSS from
    channels already admitted — 5,511 of 73,464 member rows came from discovery (ADR-0049)
    — and showing only the discovered 7.5% would misrepresent where the corpus comes from.
    """
    rows = session.execute(
        sa.select(
            Video.video_id,
            Video.title,
            Video.channel_id,
            Video.published_at,
            Discovery.query,
            Discovery.order_by,
        )
        .join(
            ClusterMember,
            sa.and_(
                ClusterMember.item_id == Video.video_id,
                ClusterMember.item_type == "video",
                ClusterMember.cluster_id == cluster_id,
            ),
        )
        .outerjoin(Discovery, Discovery.video_id == Video.video_id)
        .where(Video.published_at < _until(day))
        .order_by(Video.published_at.desc())
        .limit(FEED_LIMIT)
    ).all()
    return [
        FeedLine(
            video_id=vid,
            title=title,
            channel_id=channel_id,
            published_at=published,
            query=query,
            order_by=order_by,
            url=f"https://www.youtube.com/watch?v={vid}",
        )
        for vid, title, channel_id, published, query, order_by in rows
    ]


def metric_history(session: Session, cluster_id: str, name: str) -> list[MetricPoint]:
    """One metric's stored series, carrying the definition each point was computed under.

    `definition` is per point and comes off the row, never from the current code. That is
    what makes the series readable across ADR-0050's sunset: on 2026-09-14 `supply.*`
    reverts to `v2-on-niche` and values step, and a chart that redrew history under
    today's definition would hide the step instead of marking it.
    """
    rows = session.execute(
        sa.select(
            FeatureDaily.day,
            FeatureDaily.value,
            FeatureDaily.confidence,
            FeatureDaily.inputs_n,
            FeatureDaily.detail,
            FeatureDaily.run_id,
        )
        .where(FeatureDaily.cluster_id == cluster_id, FeatureDaily.name == name)
        .order_by(FeatureDaily.day)
    ).all()
    return [
        MetricPoint(
            day=day,
            value=value,
            confidence=confidence,
            inputs_n=inputs_n,
            definition=(detail or {}).get("definition"),
            run_id=run_id,
            detail=detail or {},
        )
        for day, value, confidence, inputs_n, detail, run_id in rows
    ]


def definition_steps(points: list[MetricPoint]) -> list[tuple[date, str | None, str | None]]:
    """Where a series changed definition: `(day, from, to)`.

    Separated from `metric_history` so a renderer cannot forget to look. A step is not an
    anomaly to smooth over — it is the one thing that makes two sides of the series
    incomparable: the stored series for `history-of-ideas on_niche_share` reads 0.0781 on
    2026-08-29 and 0.2273 on 08-31, and a definition changed between them.
    """
    steps = []
    for previous, current in pairwise(points):
        if previous.definition != current.definition:
            steps.append((current.day, previous.definition, current.definition))
    return steps


@dataclass(slots=True)
class AlertLine:
    cluster_id: str
    rule: str
    severity: str
    fired_on: date
    evidence: dict


def alerts_feed(session: Session, limit: int = 200, day: date | None = None) -> list[AlertLine]:
    """Recent alerts, newest first, then by cluster and rule.

    Ordered by WHEN, not by how alarming — the same reason `niche_list` is alphabetical.
    A feed sorted by severity is a ranking of niches by badness, arrived at sideways.

    `day` narrows to one `fired_on`, which is what the nightly digest pushes.
    """
    q = sa.select(Alert.cluster_id, Alert.rule, Alert.severity, Alert.fired_on, Alert.evidence)
    if day is not None:
        q = q.where(Alert.fired_on == day)
    rows = session.execute(
        q.order_by(Alert.fired_on.desc(), Alert.cluster_id, Alert.rule).limit(limit)
    ).all()
    return [AlertLine(*row) for row in rows]


def alert_digest(session: Session, day: date) -> str:
    """One short line summarising a day's alerts, or `""` when there are none.

    **Rule names and counts, never evidence.** Three reasons, in the order they would
    bite: an alert is a citation surface (ADR-0045), so a push quoting a scorer-decided
    number would be the leak `gates.DISCLOSURES` exists to enumerate; a push is read on a
    lock screen, where a JSON blob is noise; and the evidence is one command away
    (`nh alerts`) for anyone who wants it.

    Empty string rather than "no alerts today", so the caller can test with `-n` and stay
    silent on a quiet night. A nightly digest that fires every night is one nobody reads.
    """
    lines = alerts_feed(session, day=day)
    if not lines:
        return ""
    by_rule: dict[str, list[str]] = {}
    for line in lines:
        by_rule.setdefault(f"{line.severity}/{line.rule}", []).append(line.cluster_id)
    parts = []
    for rule in sorted(by_rule):
        clusters = sorted(by_rule[rule])
        shown = ", ".join(clusters[:3]) + (f" +{len(clusters) - 3}" if len(clusters) > 3 else "")
        parts.append(f"{rule} x{len(clusters)} ({shown})")
    return " | ".join(parts)


def latest_day(session: Session, cluster_id: str | None = None) -> date | None:
    """The newest day with features, for a cluster or across all of them."""
    q = sa.select(sa.func.max(FeatureDaily.day))
    if cluster_id is not None:
        q = q.where(FeatureDaily.cluster_id == cluster_id)
    return session.scalar(q)


def video_snapshot_span(session: Session, video_id: str) -> list[tuple[date, int | None]]:
    """A video's view history — the bottom of the drill-down, and un-recomputable."""
    return [
        (observed, views)
        for observed, views in session.execute(
            sa.select(VideoSnapshot.observed_date, VideoSnapshot.views)
            .where(VideoSnapshot.video_id == video_id)
            .order_by(VideoSnapshot.observed_date)
        ).all()
    ]
