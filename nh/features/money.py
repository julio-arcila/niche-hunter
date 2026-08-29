"""Money metrics: what the niche's inventory is worth to advertisers.

Slice 2 ships one, and it is display-only — the money composite arrives in
Slice 5. It is here because the roadmap asks for features spanning three groups
and because, once durations exist, it costs one query.
"""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import Channel, ClusterMember, Video
from nh.features.inputs import (
    KP_ADEQUATE_KEYWORDS,
    KpInputs,
    _day_end,
    keyword_planner_rows,
    member_join,
    on_niche_join,
    relevance_coverage,
    window_start,
)
from nh.features.types import FeatureResult

GROUP = "money"
WINDOW_DAYS = 90
#: Per-video and exactly measured, so videos are the honest sample unit. 100
#: because the window is video-rich and 30 videos can be two channels' output.
CONFIDENCE_N = 100


#: Two bid values that are not measurements. Measured 2026-08-28: they sit on eight
#: unrelated keywords across both markets, and both are exactly US$16.00 and US$1.60 at
#: one implied rate while the other ~100 priced cells are non-round. That is an imputed
#: estimator default, the same shape as the $1.21 default the RPM disclosure pass caught.
#:
#: Two exact literals, and deliberately no heuristic. The durable signature — round USD
#: at the implied rate — is documented in docs/SOURCES.md and is NOT implemented here on
#: purpose: a roundness rule would silently start discarding real bids that happen to
#: land on a round number, and the discarding would be invisible. This set cannot grow
#: without a diff on a named constant.
SENTINEL_BIDS = frozenset({64_083.40, 6_408.34})


def _real_bid(value: float | None) -> float | None:
    """A bid cell, or None if it is absent or an imputed sentinel.

    Per CELL, never per row. Measured: `humanism` GB carries a sentinel `bid_low`
    (6,408.34) beside a real `bid_high` (47,045.50), so dropping the whole row would
    throw away a genuine measurement. The two fully degenerate rows, where both cells
    are the sentinel, fall out on their own.
    """
    return None if value is None or value in SENTINEL_BIDS else value


def _kp_confidence(kp: KpInputs, used: int) -> float:
    """Curation coverage times sample adequacy.

    The `relevance_coverage` analogue for a source with no videos in it: what we can
    fail to see is a curated keyword, not a judged video. Leakage-safe because the
    numerator is day-bounded while the denominator is timeless curation — and before any
    export exists the caller has already returned `empty()`, so coverage is never
    multiplied into a confident zero.
    """
    coverage = min(len(kp.rows) / kp.curated, 1.0) if kp.curated else 0.0
    return coverage * min(used / KP_ADEQUATE_KEYWORDS, 1.0)


def _one_currency(rows) -> str | None:
    """The single currency of these rows, or None if they disagree."""
    seen = {r.currency for r in rows if r.currency}
    return seen.pop() if len(seen) == 1 else None


def _decided(session: Session, cluster_id: str, day) -> float:
    """Share of the cluster's videos we could decide on-niche or not."""
    judged, total = relevance_coverage(session, cluster_id, day)
    return min(judged / total, 1.0) if total else 0.0


def midroll_eligible_share(session: Session, cluster_id: str, day: date) -> FeatureResult:
    """Share of the niche's recent long-form videos that can carry mid-roll ads.

    Unknown durations are excluded from numerator *and* denominator. Counting them
    as ineligible would be the NULL-as-False trap: before the enrichment backfill
    runs, 91% of videos have no duration, and treating those as "no mid-roll" would
    report a confident near-zero for every niche.
    """
    since = window_start(day, WINDOW_DAYS)
    until = _day_end(day)
    known, eligible = session.execute(
        sa.select(
            sa.func.count(Video.video_id),
            sa.func.sum(sa.case((Video.midroll_eligible.is_(True), 1), else_=0)),
        )
        .join(Channel, Channel.channel_id == Video.channel_id)
        .join(ClusterMember, member_join(Video.channel_id, cluster_id, day=day))
        .where(
            Video.midroll_eligible.is_not(None),
            Video.published_at.is_not(None),
            Video.published_at >= since,
            Video.published_at <= until,
            # Both numerator and denominator restrict to on-niche: the question is
            # what share of THIS NICHE's supply can carry a midroll, and a channel's
            # off-niche uploads answer a different question.
            sa.exists(sa.select(1).where(on_niche_join(cluster_id, day)).correlate(Video)),
        )
    ).one()

    if not known:
        return FeatureResult.empty(
            GROUP,
            "midroll_eligible_share",
            "no member video in the window has a known duration "
            "(the enrichment backfill has not reached this cluster yet)",
            window_days=WINDOW_DAYS,
        )
    return FeatureResult(
        group=GROUP,
        name="midroll_eligible_share",
        value=(eligible or 0) / known,
        # Times relevance coverage, like the supply metrics: this is now computed
        # over videos we judged, and how much of the cluster we could judge is a
        # distinct way it lies. Held-out precision on that judgement is 0.781.
        confidence=min(known / CONFIDENCE_N, 1.0) * _decided(session, cluster_id, day),
        inputs_n=known,
        detail={
            "definition": "v2-on-niche",
            "videos_with_known_duration": known,
            "midroll_eligible": eligible or 0,
            "window": [since.date().isoformat(), day.isoformat()],
            "note": "unknown durations excluded from both sides, never counted ineligible",
            "inputs": {"tables": ["videos", "cluster_members"]},
        },
    )


def priced_share(session: Session, cluster_id: str, day: date, *, geo: str) -> FeatureResult:
    """Share of the niche's curated keywords that advertisers actually bid on.

    A legitimate 0.0: keywords exist, none carries a real bid, and "advertisers pay
    nothing for this audience" is a finding rather than an absence. That is only honest
    because the denominator is day-bounded — before any export it is empty and the guard
    below returns NULL instead.
    """
    kp = keyword_planner_rows(session, cluster_id, day, geo)
    if not kp.rows:
        return _no_rows("priced_share", kp, geo)
    priced = sum(
        1 for r in kp.rows if _real_bid(r.bid_low) is not None or _real_bid(r.bid_high) is not None
    )
    sentinel_cells = sum(
        (r.bid_low in SENTINEL_BIDS) + (r.bid_high in SENTINEL_BIDS) for r in kp.rows
    )
    return FeatureResult(
        group=GROUP,
        name="priced_share",
        value=priced / len(kp.rows),
        confidence=_kp_confidence(kp, len(kp.rows)),
        inputs_n=len(kp.rows),
        detail={
            "geo": geo,
            "keywords": [r.keyword for r in kp.rows],
            "priced": priced,
            "curated": kp.curated,
            "sentinel_cells_excluded": sentinel_cells,
            **_period(kp.rows),
            "note": "zero is a measurement here: keywords observed, none bid on",
            "inputs": {"tables": ["keyword_metrics", "seed_terms"]},
        },
    )


def competition_index_mean(
    session: Session, cluster_id: str, day: date, *, geo: str
) -> FeatureResult:
    """Mean advertiser competition on the niche's keywords, 0-100 as the export gives it.

    Advertiser competition for SEARCH ads. It says nothing about how much video already
    exists in the niche — that is `supply.*`, a different auction and a different market.
    """
    kp = keyword_planner_rows(session, cluster_id, day, geo)
    if not kp.rows:
        return _no_rows("competition_index_mean", kp, geo)
    indexed = [r.competition_index for r in kp.rows if r.competition_index is not None]
    if not indexed:
        return FeatureResult.empty(
            GROUP,
            "competition_index_mean",
            "keywords observed but none carries a competition index",
            geo=geo,
            keywords_observed=len(kp.rows),
        )
    return FeatureResult(
        group=GROUP,
        name="competition_index_mean",
        value=sum(indexed) / len(indexed),
        confidence=_kp_confidence(kp, len(indexed)),
        inputs_n=len(indexed),
        detail={
            "geo": geo,
            "keywords_with_index": len(indexed),
            "curated": kp.curated,
            **_period(kp.rows),
            "note": "advertiser competition on search ads, not video supply in the niche",
            "inputs": {"tables": ["keyword_metrics", "seed_terms"]},
        },
    )


def vw_cpc(session: Session, cluster_id: str, day: date, *, geo: str) -> FeatureResult:
    """Volume-weighted cost per click across the niche's keywords, in account currency.

    A keyword's price is the mean of whichever bid cells are real, so `humanism` GB —
    sentinel low, real high — contributes its high rather than being discarded. A keyword
    with no real price or no volume is excluded from both sides, never counted as zero.
    """
    kp = keyword_planner_rows(session, cluster_id, day, geo)
    if not kp.rows:
        return _no_rows("vw_cpc", kp, geo)
    currency = _one_currency(kp.rows)
    if currency is None and {r.currency for r in kp.rows if r.currency}:
        return _mixed_currency("vw_cpc", kp, geo)

    weighted, weight, used = 0.0, 0.0, 0
    for r in kp.rows:
        cells = [c for c in (_real_bid(r.bid_low), _real_bid(r.bid_high)) if c is not None]
        if not cells or not r.avg_monthly_searches:
            continue
        weighted += r.avg_monthly_searches * (sum(cells) / len(cells))
        weight += r.avg_monthly_searches
        used += 1
    if not weight:
        return FeatureResult.empty(
            GROUP,
            "vw_cpc",
            "no keyword has both a real bid and a volume",
            geo=geo,
            keywords_observed=len(kp.rows),
        )
    return FeatureResult(
        group=GROUP,
        name="vw_cpc",
        value=weighted / weight,
        confidence=_kp_confidence(kp, used),
        inputs_n=used,
        detail={
            "geo": geo,
            "currency": currency,
            "keywords_priced": used,
            "curated": kp.curated,
            **_period(kp.rows),
            "note": "weights are power-of-ten bucket midpoints; order-of-magnitude at best",
            "inputs": {"tables": ["keyword_metrics", "seed_terms"]},
        },
    )


def median_bid_high(session: Session, cluster_id: str, day: date, *, geo: str) -> FeatureResult:
    """Median top-of-page high bid across the niche's keywords, in account currency.

    An advertiser's SEARCH-ad bid, not YouTube RPM — a different auction with different
    inventory. The RPM disclosure pass of 2026-08-28 returned n=0 across nine units, so
    this proxy is what exists, and it is a tier signal rather than a price.
    """
    kp = keyword_planner_rows(session, cluster_id, day, geo)
    if not kp.rows:
        return _no_rows("median_bid_high", kp, geo)
    currency = _one_currency(kp.rows)
    if currency is None and {r.currency for r in kp.rows if r.currency}:
        return _mixed_currency("median_bid_high", kp, geo)

    highs = sorted(b for r in kp.rows if (b := _real_bid(r.bid_high)) is not None)
    if not highs:
        return FeatureResult.empty(
            GROUP,
            "median_bid_high",
            "no keyword carries a real top-of-page bid",
            geo=geo,
            keywords_observed=len(kp.rows),
        )
    mid = len(highs) // 2
    value = highs[mid] if len(highs) % 2 else (highs[mid - 1] + highs[mid]) / 2
    return FeatureResult(
        group=GROUP,
        name="median_bid_high",
        value=value,
        confidence=_kp_confidence(kp, len(highs)),
        inputs_n=len(highs),
        detail={
            "geo": geo,
            "currency": currency,
            "keywords_priced": len(highs),
            "curated": kp.curated,
            "sentinel_cells_excluded": sum(1 for r in kp.rows if r.bid_high in SENTINEL_BIDS),
            **_period(kp.rows),
            "note": "a search-ad bid, not YouTube RPM; no exchange rate is applied (ADR-0031)",
            "inputs": {"tables": ["keyword_metrics", "seed_terms"]},
        },
    )


def _no_rows(name: str, kp: KpInputs, geo: str) -> FeatureResult:
    """The universal guard: never a confident zero before an export exists."""
    reason = (
        "no keyword_planner term mapped to this cluster"
        if not kp.curated
        else f"no Keyword Planner reading for geo {geo!r} on or before this day"
    )
    return FeatureResult.empty(GROUP, name, reason, geo=geo, curated=kp.curated)


def _mixed_currency(name: str, kp: KpInputs, geo: str) -> FeatureResult:
    return FeatureResult.empty(
        GROUP,
        name,
        "rows span more than one currency and ADR-0031 forbids inventing a rate",
        geo=geo,
        currencies=sorted({r.currency for r in kp.rows if r.currency}),
    )


def _period(rows) -> dict:
    """The described period as `window`, the key `_provenance` already renders."""
    row = rows[0]
    if not row.period_start:
        return {}
    return {"window": [row.period_start.isoformat(), row.observed_date.isoformat()]}
