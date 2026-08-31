"""Shared input queries for the feature functions.

Every metric that needs "this cluster's channels" or "this channel's eligible
videos" comes here. One definition, so supply and openness cannot quietly drift
apart — two metrics disagreeing about which videos count is the kind of bug that
survives review because both numbers look reasonable in isolation.

Everything is parameterised by `day` and nothing reads the clock. That is
re-run determinism now (the same day recomputes to the same values) and the
anti-leakage property Slice 6's backtest will depend on: a feature must never see
a row that did not exist at the decision date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.clustering.relevance import RELEVANCE_HIGH as _RELEVANCE_HIGH
from nh.db.models import (
    Channel,
    ChannelSnapshot,
    Cluster,
    ClusterMember,
    Discovery,
    KeywordMetric,
    SeedTerm,
    Video,
    VideoSnapshot,
)

#: Views on a very fresh upload have not settled, so comparing one against an
#: older video measures age rather than performance. A stopgap until the snapshot
#: series supports views-at-day-30 — see docs/METRICS.md supply.median_views.
AGE_FLOOR_DAYS = 14

#: An RSS feed returns at most 15 entries. Capping every channel at 15 keeps
#: API-discovered channels from getting a deeper window than RSS-only ones, which
#: would make their medians incomparable.
FEED_DEPTH = 15

#: Openness is about small entrants. Above this, views-per-sub measures audience
#: retention rather than whether a newcomer can get reach.
COHORT_MAX_SUBS = 10_000

#: Below this a channel has no stable median to compare a breakout against.
COHORT_MIN_VIDEOS = 5

#: Read-time cuts on `cluster_members.relevance`, imported rather than redefined so
#: the calibration report and the queries cannot drift apart. See
#: reports/relevance_2026-08-27.md: held-out precision 0.781, recall 0.694, against
#: a 28.6% base rate.
RELEVANCE_HIGH = _RELEVANCE_HIGH


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def window_start(day: date, window_days: int) -> datetime:
    """Midnight at the first civil day of a `window_days`-long window ending on `day`.

    `day - window_days` is the off-by-one this exists to prevent: paired with a
    `time.max` upper bound it spans `window_days + 1` civil days, because both
    endpoints are then whole days. Measured on the live corpus 2026-08-28 —
    `uploads_per_week` counted 69 and 80 videos for corporate-collapse and
    court-cases where the documented 28-day window gives 67 and 76, inflating every
    published "per week" figure by ~3.6% while dividing by 4.0 weeks.

    Use with `>= window_start(...)` and `<= _day_end(...)`: inclusive at both ends,
    exactly `window_days` civil days.
    """
    return _midnight(day - timedelta(days=window_days - 1))


def _day_end(day: date) -> datetime:
    """The last instant of `day`, so a same-day publish is inside the window."""
    return datetime.combine(day, time.max, tzinfo=UTC)


def _until(day: date) -> datetime:
    """The exclusive upper bound for "on or before `day`".

    The whole of `day` is visible everywhere in this layer: snapshots bound on
    `observed_date <= day`, which is a date, so a timestamp bound has to include
    the last instant of that day to agree with it. Hand-copied `time.max` did the
    same thing in three places; naming it once means the convention can be tested
    rather than remembered.
    """
    return _midnight(day + timedelta(days=1))


def member_join(column, cluster_id: str, item_type: str = "channel", day: date | None = None):
    """The membership predicate, defined once.

    Every metric that resolves an item to a cluster joins on the same three
    conditions plus `is_noise IS FALSE`, and until Slice 4 four of the six join
    sites had hand-copied the first three and dropped the fourth. That was
    invisible while nothing wrote noise, and would have become a live corruption
    the moment something did: `supply._confidence` takes its universe from
    `member_channels` (noise-free) and its numerator from a leaky join, so
    coverage — and therefore confidence — could exceed 1.0.

    The module docstring already promised "one definition, so supply and openness
    cannot quietly drift apart". This is that promise made mechanical.

    `day` bounds membership to channels already known then. It is a NARROWER
    guarantee than it looks, and the gap is worth stating: `cluster_members` records
    which cluster a channel is in *now*, and `trivial.dominant_seed` decides that by
    counting discovery rows as of today. A channel first surfaced by aviation
    queries in January and by maritime queries in August has a dominant seed that
    changed, and `first_seen` cannot reconstruct which one it held at a past date.
    Closing that needs `dominant_seed` recomputed from day-bounded lineage.

    It does not affect the backtest — YouNiverse channels have no discovery lineage,
    so their membership comes from the relevance aggregate over their own videos,
    which IS pure — and it is registered as a deferral rather than left implicit.
    """
    predicate = sa.and_(
        ClusterMember.item_id == column,
        ClusterMember.item_type == item_type,
        ClusterMember.cluster_id == cluster_id,
        ClusterMember.is_noise.is_(False),
    )
    if day is None:
        return predicate
    return sa.and_(predicate, Channel.first_seen < _until(day))


def member_channels(session: Session, cluster_id: str, day: date | None = None) -> list[str]:
    """Non-noise, non-ballast channel members of a cluster as of `day`.

    Ballast is excluded here as well as in the video-side predicates, and it has to
    be: `supply._confidence` takes `universe` from this and `contributing` from a
    `member_join` query, and its clamp comment says coverage above 1.0 "means those
    two populations have drifted apart again — a bug in the query, not a value". Two
    predicates would be exactly that drift.
    """
    return list(
        session.scalars(
            sa.select(ClusterMember.item_id)
            .join(Channel, Channel.channel_id == ClusterMember.item_id)
            .where(
                member_join(ClusterMember.item_id, cluster_id, day=day),
                ClusterMember.item_id.notin_(_ballast_channels(cluster_id, day)),
            )
        )
    )


#: Decided videos a channel must have in a cluster before "never on-niche" is
#: evidence rather than absence. **A judgement call, not a derivation, and saying
#: otherwise would be the failure docs/METRICS.md warns about three times.** Measured
#: on the live corpus, marked counts fall smoothly — 605 / 556 / 503 / 465 / 301 / 57
#: at N = 5/8/10/12/15/20 — with no break at ten. The one real cliff is 12 -> 15, and
#: it is `FEED_DEPTH` biting: above the cap the rule stops asking for evidence a feed
#: can supply and exempts exactly the RSS-fed channels it exists for, which bounds N
#: from above. Ten is "comfortably below the cap, comfortably above the range where a
#: catalogue is barely known".
#:
#: Two things make the dial tolerable. Numerator invariance holds at EVERY N and every
#: day (see below), so N moves denominators only. And it is a read-time constant like
#: `RELEVANCE_HIGH`: retuning it is a query, never a rewrite of stored rows — the
#: series steps and `supply.DEFINITION` marks the step. Two earlier drafts of this
#: comment also promised the value was stamped into metric `detail` as `ballast_n`.
#: It never was, and the claim is deleted rather than left standing: this constant is
#: the single place N lives.
BALLAST_DECIDED = 10


def _ballast_channels(cluster_id: str, day: date | None = None):
    """Sub-select of channel ids that have published nothing this cluster can read.

    A channel joins a cluster on ONE discovered video (`clustering.trivial`) with no
    threshold, and `youtube_rss` then polls it forever, so its whole catalogue lands
    in the cluster whether or not the lexicon can read any of it. Measured 2026-08-31
    under `LEXICON_VERSION 2026-08-31.4`: 503 of 2,307 member channels across the ten
    active clusters have ten decided videos and not one on-niche, carrying 8,994 video
    rows that sat in every coverage denominator.

    **Decided, not scored.** `decided = on-niche + decided-noise`; undecided mid-band
    and unscorable rows are not judgements and must not count as evidence against a
    channel — data rule 7's absent-is-not-zero at channel grain. That is what makes
    this safe beside ADR-0046's language gate: 43 channels whose catalogue the gate
    reveals as unreadable have `decided = 0`, are NOT ballast, stay members, and
    correctly drag `relevance_coverage` down as unscorable instead.

    **Zero on-niche, not a small share.** 342 channels sit at exactly one on-niche
    video, so any tolerance above zero takes them and removes real on-niche rows from
    numerators. Zero buys **numerator invariance**: a ballast channel has contributed
    nothing above the threshold, so this can only ever shrink a denominator. It holds
    per day as well as overall — zero on-niche across a catalogue implies zero across
    every published-before-`day` prefix of it.

    **Day-bounded, and that is the whole reason this is a query rather than a stored
    flag.** An earlier design marked `cluster_members.is_noise` on the channel row in
    the clustering phase. That flag is an aggregate as of the RUN date, so it leaked
    post-`day` information into day-bounded reads — measured, 114 pre-2026 video rows
    vanished from a replay at a 2025 decision date, and five of the nine
    `BACKTEST_METRICS` route through these predicates. This module's own docstring
    promises the opposite ("a feature must never see a row that did not exist at the
    decision date"). Computing the set per read removes the leak by construction, and
    deletes the stored flag, its clobber hazard and its reconciliation ordering with
    it — there is no state to move.

    Uncorrelated with respect to the outer row: it depends only on `cluster_id` and
    `day`, so it is evaluated once per statement rather than per video. Measured
    19-23ms per execution live, 87ms on `data/backtest.db`. Per feature PASS, after
    the tautological `on_niche_join` clause was removed, it materialises 99 times and
    three A/B runs against a neutralised predicate measured -2.81s / +0.47s / +0.09s
    on a ~35s pass — indistinguishable from noise. An earlier version of this line
    read "~0.4s across all ten clusters", which was a per-execution figure presented
    as a per-pass one.

    One impurity remains and is pre-existing, not new: "decided" is read under the
    CURRENT lexicon, the accepted caveat of every relevance read (ADR-0018).
    """
    decided = sa.case((ClusterMember.relevance >= RELEVANCE_HIGH, 1), (ClusterMember.is_noise, 1))
    on_niche = sa.case((ClusterMember.relevance >= RELEVANCE_HIGH, 1))
    inner = sa.orm.aliased(Video)
    return (
        sa.select(inner.channel_id)
        .join(ClusterMember, ClusterMember.item_id == inner.video_id)
        .where(
            ClusterMember.item_type == "video",
            ClusterMember.cluster_id == cluster_id,
            sa.true() if day is None else inner.published_at < _until(day),
        )
        .group_by(inner.channel_id)
        .having(sa.func.count(decided) >= BALLAST_DECIDED)
        .having(sa.func.count(on_niche) == 0)
    )


#: ADR-0050's sunset. Ballast raised `history-of-ideas on_niche_share` 0.076 -> 0.227
#: with an IDENTICAL numerator of 230 — the whole move is denominator removal — on
#: machine judgements alone, and the sample that could test it is drawn and unlabelled.
#: On this date, with no recorded result, the rule reverts to v2 rather than continuing
#: indefinitely. A date, not a reminder: the reviewer's complaint was precisely that an
#: unvalidated 3x move could sit forever, and "validate it eventually" does not answer
#: that. `reports/recall_labelling_2026-08-31.jsonl` is what clears it.
BALLAST_SUNSET = date(2026, 9, 14)

#: The result of ADR-0050, once a human has computed it. `None` means unlabelled or
#: uncomputed — the sunset governs. `True` means the 95% Wilson UPPER bound on the hit
#: rate came in at or below 0.10 (at most 4 of 100); `False` means it did not.
#:
#: **Deliberately a constant a person sets, not a file the code reads.** Completing the
#: labels is not the same event as passing the bar, so auto-resuming v3 the moment the
#: file fills would resume it on a FAILING sample. And code that graded its own
#: validation would be the circularity ADR-0041 exists to prevent, one level up. Set it
#: in the same commit that writes the result report and the k into ADR-0047.
BALLAST_VALIDATED: bool | None = None


def ballast_active(today: date | None = None) -> bool:
    """Whether ADR-0047's exclusion applies at all (ADR-0050).

    `today` is the operator's calendar, NOT the feature's decision date — the two are
    different clocks and conflating them is how a replay starts depending on when it is
    run. A `day`-bounded read stays `day`-bounded; what this switches is which
    *definition* is in force, the same class of change as moving `BALLAST_DECIDED`, and
    `supply.definition()` stamps it into every row so a stored series self-describes
    across the step.
    """
    if BALLAST_VALIDATED is not None:
        return BALLAST_VALIDATED
    return (today or date.today()) < BALLAST_SUNSET


def not_ballast(cluster_id: str, day: date | None = None):
    """This video's channel is not ballast in this cluster as of `day` (ADR-0047).

    Named for what it tests. An earlier version was called `from_a_member_channel`,
    which described the stored-flag design it came from and stopped being true when
    the predicate became a ballast tally — it does not check membership at all.

    Applied where it can bite: `relevance_coverage`, `numerator_coverage` and
    `member_channels`. Not `on_niche_join`, where it is a tautology (see there), and
    not `member_join`, which is what leaves `openness.*` deliberately unfiltered.

    Measured on the live corpus, applying this
    moves history-of-ideas coverage 2608/3246 -> 870/1384 and `on_niche_share`
    0.076 -> 0.226.

    Returns a true-everywhere clause once `ballast_active()` goes false, so the revert
    ADR-0050 commits to is this one line and no migration — which is the property that
    let ADR-0047 ship on structure while its evidence was still outstanding.
    """
    if not ballast_active():
        return sa.true()
    return Video.channel_id.notin_(_ballast_channels(cluster_id, day))


def on_niche_join(cluster_id: str, day: date | None = None):
    """Join predicate for a video judged on-niche, as of `day`.

    Deliberately `relevance >= RELEVANCE_HIGH` and not `is_noise IS FALSE`. The
    three states are not two: `is_noise` marks only the decided off-niche case, so
    a NULL-relevance (unscorable) or mid-band (undecided) video is not noise and is
    also not on-niche. Both are excluded from numerator *and* denominator, and
    lower confidence instead of being guessed into one side.

    **Deliberately does NOT carry the ballast filter (ADR-0047).** It would be a
    tautology: this predicate already requires `relevance >= RELEVANCE_HIGH`, and a
    ballast channel has zero videos above that threshold by definition, so the clause
    could never remove a row. Measured — 0 of 297 cluster-day-metric cells changed
    with it present, and the whole suite passed with it removed. It also cost ~4s per
    feature pass and was the only route by which the predicate reached three call
    sites that wrap this in `sa.exists(...).correlate(Video)`, where an earlier
    version compiled wrong. Ballast is filtered where it can actually bite: the two
    coverage functions and `member_channels`.
    """
    predicate = sa.and_(
        ClusterMember.item_id == Video.video_id,
        ClusterMember.item_type == "video",
        ClusterMember.cluster_id == cluster_id,
        ClusterMember.relevance >= RELEVANCE_HIGH,
    )
    if day is None:
        return predicate
    # Relevance is a pure function of (title, description, lexicon_version), so a
    # video's score never changes. Membership as of a past day is therefore
    # membership now, restricted to videos that existed then — which is why this
    # needs no history table (ADR-0018) and why one clause is the whole fix.
    return sa.and_(predicate, Video.published_at < _until(day))


def relevance_coverage(
    session: Session, cluster_id: str, day: date | None = None
) -> tuple[int, int]:
    """`(decided, total)` videos in the cluster — the share we could judge at all.

    A metric restricted to on-niche videos depends on a decision we make about each
    one, so "how much of the cluster could we decide about" is a distinct way it
    lies and belongs in confidence. Undecided and unscorable both count against.
    """
    decided, total = session.execute(
        sa.select(
            sa.func.count(
                sa.case(
                    (
                        sa.or_(
                            ClusterMember.relevance >= RELEVANCE_HIGH,
                            ClusterMember.is_noise.is_(True),
                        ),
                        1,
                    )
                )
            ),
            sa.func.count(),
        )
        .select_from(ClusterMember)
        .join(Video, Video.video_id == ClusterMember.item_id)
        .where(
            ClusterMember.item_type == "video",
            ClusterMember.cluster_id == cluster_id,
            not_ballast(cluster_id, day),
            sa.true() if day is None else Video.published_at < _until(day),
        )
    ).one()
    return decided or 0, total or 0


def numerator_coverage(
    session: Session, cluster_id: str, day: date | None = None
) -> tuple[int, int, int]:
    """`(on_niche, judgeable, total)` videos in the cluster.

    The counterpart to `relevance_coverage`, for metrics whose claim is sized by
    their **numerator** rather than by the whole cluster. `relevance_coverage` asks
    "how much of the cluster could we decide about" and counts a decided negative
    as knowledge, which is right for a share metric like `supply.on_niche_share`
    where that negative sits in the denominator. It is wrong for a volume metric:
    a video decided off-niche contributes nothing to the volume, so deciding it
    must not raise confidence in the volume.

    `judgeable` is every video that could still have entered the numerator —
    on-niche, undecided, or unscorable — i.e. everything not decided off-niche.
    The three states are not two (`on_niche_join`), so all three are counted here
    for the same reason they are excluded there.

    Callers read the ratio `on_niche / judgeable`. Two degenerate cases, and they
    are different: `judgeable == 0` with videos present means the scorer decided
    every one of them off-niche, which is full decisiveness and reads 1.0;
    `total == 0` means the cluster holds no videos and there was nothing to be
    decisive about, which reads 0.0. Returning all three counts keeps that
    distinction at the call site rather than hiding it in a ratio.
    """
    on_niche, judgeable, total = session.execute(
        sa.select(
            sa.func.count(sa.case((ClusterMember.relevance >= RELEVANCE_HIGH, 1))),
            sa.func.count(sa.case((ClusterMember.is_noise.is_(False), 1))),
            sa.func.count(),
        )
        .select_from(ClusterMember)
        .join(Video, Video.video_id == ClusterMember.item_id)
        .where(
            ClusterMember.item_type == "video",
            ClusterMember.cluster_id == cluster_id,
            not_ballast(cluster_id, day),
            sa.true() if day is None else Video.published_at < _until(day),
        )
    ).one()
    return on_niche or 0, judgeable or 0, total or 0


def eligible_niche_videos(
    session: Session, cluster_id: str, day: date
) -> dict[str, list[tuple[str, int]]]:
    """`eligible_videos`, restricted to videos judged on-niche.

    Supply asks what a newcomer competes against *in this niche*; openness asks
    whether a video beat *its own channel's* baseline, and that baseline must be the
    channel's whole output. Two different questions, so two different pools — see
    docs/METRICS.md on both `supply.median_views` and
    `openness.breakthrough_rate_cohort`. Do not merge them back together.

    **The relevance filter is applied after the FEED_DEPTH cut, not before.**
    `eligible_videos` ranks each channel's catalogue and keeps the newest 15,
    deliberately, so an API-discovered channel gets no deeper window than an
    RSS-only one (data rule 9). Filtering first would let an on-niche-sparse channel
    reach much further back in time and would destroy that comparability silently —
    the medians would still look reasonable.
    """
    pool = eligible_videos(session, cluster_id, day)
    if not pool:
        return {}
    on_niche = set(
        session.scalars(
            sa.select(ClusterMember.item_id)
            .join(Video, Video.video_id == ClusterMember.item_id)
            .where(on_niche_join(cluster_id, day))
        )
    )
    kept = {
        channel_id: [row for row in rows if row[0] in on_niche] for channel_id, rows in pool.items()
    }
    return {channel_id: rows for channel_id, rows in kept.items() if rows}


def eligible_videos(
    session: Session, cluster_id: str, day: date
) -> dict[str, list[tuple[str, int]]]:
    """`channel_id -> [(video_id, views), ...]`, newest first, capped at FEED_DEPTH.

    Eligible means: long-form (`is_short IS FALSE` — a NULL is unknown format and
    is excluded, never treated as long-form), published at least AGE_FLOOR_DAYS
    before `day`, and with at least one view observation on or before `day`.

    Views are the max over snapshots up to `day` rather than the value on the
    latest date. For a monotonically increasing counter these agree, and the max
    is robust to one source under-reporting on a given day.
    """
    latest = (
        sa.select(
            VideoSnapshot.video_id,
            sa.func.max(VideoSnapshot.views).label("views"),
        )
        .where(VideoSnapshot.observed_date <= day, VideoSnapshot.views.is_not(None))
        .group_by(VideoSnapshot.video_id)
        .subquery()
    )
    ranked = (
        sa.select(
            Video.channel_id.label("channel_id"),
            Video.video_id.label("video_id"),
            latest.c.views.label("views"),
            sa.func.row_number()
            .over(partition_by=Video.channel_id, order_by=Video.published_at.desc())
            .label("rn"),
        )
        .join(latest, latest.c.video_id == Video.video_id)
        .join(Channel, Channel.channel_id == Video.channel_id)
        .join(ClusterMember, member_join(Video.channel_id, cluster_id, day=day))
        .where(
            Video.is_short.is_(False),
            Video.published_at.is_not(None),
            Video.published_at <= _midnight(day - timedelta(days=AGE_FLOOR_DAYS)),
        )
        .subquery()
    )
    out: dict[str, list[tuple[str, int]]] = {}
    for channel_id, video_id, views in session.execute(
        sa.select(ranked.c.channel_id, ranked.c.video_id, ranked.c.views).where(
            ranked.c.rn <= FEED_DEPTH
        )
    ):
        out.setdefault(channel_id, []).append((video_id, views))
    return out


def latest_subs(session: Session, cluster_id: str, day: date) -> dict[str, int]:
    """`channel_id -> subs` for member channels whose count is visible on `day`.

    A hidden subscriber count is absent from this mapping rather than present as
    zero. Callers must treat "not in the dict" as unknown (data rule 7).
    """
    rows = session.execute(
        sa.select(
            ChannelSnapshot.channel_id,
            sa.func.max(ChannelSnapshot.subs),
        )
        .join(Channel, Channel.channel_id == ChannelSnapshot.channel_id)
        .join(ClusterMember, member_join(ChannelSnapshot.channel_id, cluster_id, day=day))
        .where(ChannelSnapshot.observed_date <= day, ChannelSnapshot.subs.is_not(None))
        .group_by(ChannelSnapshot.channel_id)
    ).all()
    return {channel_id: subs for channel_id, subs in rows if subs is not None}


def date_discovered_channels(
    session: Session, cluster_id: str, day: date | None = None
) -> set[str]:
    """Member channels with at least one video found under `order=date`.

    This is the unbiased-denominator filter, and it is the whole reason
    `Discovery.order_by` is a column. A channel that entered the sample only
    through `order=viewCount` is there *because* it had a winner; counting it in
    an openness denominator inflates the rate by construction. Measured: without
    this filter the breakthrough rate is flat across all five niches.
    """
    return set(
        session.scalars(
            sa.select(Video.channel_id)
            .join(Discovery, Discovery.video_id == Video.video_id)
            .join(Channel, Channel.channel_id == Video.channel_id)
            .join(ClusterMember, member_join(Video.channel_id, cluster_id, day=day))
            .where(
                Discovery.order_by == "date",
                # `discoveries` is append-only and already carries observed_date;
                # it was simply never used. A replay without it admits every
                # channel discovered years after the decision date.
                sa.true() if day is None else Discovery.observed_date <= day,
            )
            .distinct()
        )
    )


def cohort(session: Session, cluster_id: str, day: date) -> dict[str, list[int]]:
    """The openness cohort: `channel_id -> [views, ...]` of its eligible videos.

    Membership requires all three of: subscriber count visible and at or below
    COHORT_MAX_SUBS, at least COHORT_MIN_VIDEOS eligible videos, and `order=date`
    discovery lineage. Each filter is load-bearing — see docs/METRICS.md.
    """
    videos = eligible_videos(session, cluster_id, day)
    subs = latest_subs(session, cluster_id, day)
    dated = date_discovered_channels(session, cluster_id, day)
    return {
        channel_id: [views for _, views in rows]
        for channel_id, rows in videos.items()
        if len(rows) >= COHORT_MIN_VIDEOS
        and channel_id in dated
        and 0 < subs.get(channel_id, 0) <= COHORT_MAX_SUBS
    }


def demand_terms(
    session: Session, cluster_id: str, source: str, stratum: str = "topic"
) -> list[str]:
    """Active demand terms for the cluster's seed, at one level of the subject.

    Joins through `clusters.seed_id`, which is the one place to touch when Slice 4
    changes what a `cluster_id` is. Deliberately does NOT fall back to
    `niche_seeds.keywords`: those are YouTube search phrases and are demand-dead
    elsewhere — most read literal zero on Trends — so reusing them would
    manufacture confident nonsense (ADR-0015).

    `stratum` defaults to `topic` so every existing caller keeps the articles it
    already had and the stored series stays comparable. The `event` stratum is
    carried alongside rather than replacing it: measured, the two invert the demand
    ranking end to end, and which one is right is a question for Gate E rather than
    for an argument (ADR-0022).
    """
    return list(
        session.scalars(
            sa.select(SeedTerm.term)
            .join(Cluster, Cluster.seed_id == SeedTerm.seed_id)
            .where(
                Cluster.cluster_id == cluster_id,
                SeedTerm.source == source,
                SeedTerm.stratum == stratum,
                SeedTerm.active.is_(True),
            )
            .order_by(SeedTerm.term)
        )
    )


#: A Keyword Planner basket's honest sample unit is the KEYWORD, and the first US
#: export carried 30 of them. Deliberately not `money.CONFIDENCE_N`, which is
#: documented as per-video ("videos are the honest n") and named for
#: `midroll_eligible_share`: reusing 100 here would pin every KP confidence near
#: 0.30 forever regardless of how well curated the niche is.
KP_ADEQUATE_KEYWORDS = 30


@dataclass(frozen=True, slots=True)
class KpInputs:
    """What one cluster's Keyword Planner basket looks like in one market.

    `curated` is the denominator that makes coverage meaningful: how many keywords
    this niche *claims*, against how many we could actually observe. It counts seed
    terms, not rows, so a market with no export reads as 0/6 rather than as a niche
    that happens to have no keywords.
    """

    rows: list[KeywordMetric]
    curated: int


def keyword_planner_rows(session: Session, cluster_id: str, day: date, geo: str) -> KpInputs:
    """The latest Keyword Planner reading per curated term, in one market, as of `day`.

    **`geo` has no default, deliberately (ADR-0038).** A seed term asserts "this niche
    cares about this keyword", which is geo-independent curation; which market a number
    was measured in is a property of the *observation* and lives on
    `keyword_metrics.geo`. A default here would silently pick a market on the caller's
    behalf, which is the conflation ADR-0038 removed.

    Joins on `(lower(term), lang)` — the same key `nh kp ingest`'s match report uses, so
    the report cannot claim a coverage the features do not get. `demand_terms` is
    deliberately not reused: it returns bare strings, dropping the `lang` this join needs,
    and has no notion of `day`.

    **The day bound is `observed_date <= day`, and it is approximate on purpose.**
    `observed_date` is the last day of the twelve-month period the numbers describe
    (ADR-0027's third reading), so it precedes the export by up to a month and
    `period_start` may be ~365 days earlier. Bounding on provenance `at` instead would be
    stricter but would break the feature layer's uniform time axis, where every metric
    bounds on the date a value describes rather than the date we fetched it — the same
    approximation the Wikipedia backfill already accepts.

    When a second monthly export lands, the newer period wins per term and the older row
    stays for history: `keyword_metrics` is append-only and never overwritten.
    """
    terms = session.execute(
        sa.select(SeedTerm.term, SeedTerm.lang)
        .join(Cluster, Cluster.seed_id == SeedTerm.seed_id)
        .where(
            Cluster.cluster_id == cluster_id,
            SeedTerm.source == "keyword_planner",
            SeedTerm.active.is_(True),
        )
    ).all()
    if not terms:
        return KpInputs(rows=[], curated=0)

    wanted = {(t.lower(), ln) for t, ln in terms}
    ranked = (
        sa.select(
            KeywordMetric,
            sa.func.row_number()
            .over(
                partition_by=(sa.func.lower(KeywordMetric.keyword), KeywordMetric.lang),
                order_by=KeywordMetric.observed_date.desc(),
            )
            .label("rn"),
        )
        .where(KeywordMetric.geo == geo, KeywordMetric.observed_date <= day)
        .subquery()
    )
    latest = session.scalars(
        sa.select(KeywordMetric).from_statement(
            sa.select(ranked).where(ranked.c.rn == 1).order_by(ranked.c.keyword)
        )
    ).all()
    rows = [r for r in latest if (r.keyword.lower(), r.lang) in wanted]
    return KpInputs(rows=rows, curated=len(terms))
