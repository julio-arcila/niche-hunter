"""Metrics that are not implemented, and the condition that would change that.

Slice 5's stated exit — "every metric implemented or explicitly deferred" — is
dischargeable by writing thirty paragraphs, which would be a slice that produced no
capability. A deferral is only worth anything if it carries four things: the
blocker, a **checkable trigger**, the consumer that goes NULL without it, and a
rough cost. A deferral without a trigger is a wall; a deferral with one is a work
queue.

The point is the trigger. `ADR-0016` started a four-week clock on Google Ads access
that expires 2026-09-24 and is enforced by nothing but a sentence in an ADR — the
same class of problem `ADR-0003` solved for provenance by making the rule
mechanical rather than reviewed. As a row with a date trigger it enforces itself.

`nh deferrals` evaluates what it can and prints what has come unblocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.config import get_settings
from nh.db.session import session_scope

Kind = Literal["date", "setting", "query", "manual"]


@dataclass(frozen=True, slots=True)
class Deferral:
    metric: str
    blocker: str
    #: How `trigger` is checked. `manual` means no machine can answer it, and saying
    #: so is better than a trigger that silently never fires.
    kind: Kind
    trigger: str
    consumer: str
    cost: str


#: Ordered roughly by how close each is to firing.
DEFERRALS: tuple[Deferral, ...] = (
    Deferral(
        metric="relevance rule — independent human validation",
        blocker=(
            "held-out precision 0.781 was measured against labels written by the "
            "same system that wrote the lexicon; a second model agreed at kappa "
            "0.943, which shows the criterion is unambiguous but cannot detect a "
            "bias two language models share. A cross-FAMILY pass (fable-5, blind) "
            "on 2026-08-28 held precision at 0.875 and agreed at kappa 0.883 — so "
            "the figure is not visibly a same-family artifact — but it is still a "
            "model judging a model and does NOT discharge this deferral"
        ),
        kind="manual",
        trigger=(
            "a human labels the sample — REQUIRED BEFORE SLICE 7, not before "
            "Slice 6. Draw it FROM ABOVE the 0.55 threshold and take 60-100 rows: "
            "reports/spotcheck_50.jsonl is a uniform sample and yields only 8 rows "
            "above the cut, a 95% interval of [0.53, 0.98] that no gate can act on "
            "(reports/relevance_interrater_2026-08-28.md)"
        ),
        consumer=(
            "every supply.* and money.* number, and the niches Slice 6 constructs from YouNiverse"
        ),
        cost="~45 minutes of reading at 60-100 rows; scripts/spotcheck_agreement.py reports kappa",
    ),
    Deferral(
        metric="supply.median_top_video_age",
        blocker=(
            "corpus is 96% under 90 days old — RSS returns a channel's newest 15 "
            "entries, so the metric reports the collection window, not the niche"
        ),
        kind="query",
        trigger="share of on-niche videos older than 365 days >= 0.20",
        consumer="the evergreen half of sustainability; cost_risk's evergreen score",
        cost="none — implemented and measured, just unregistered",
    ),
    Deferral(
        metric="supply.format_mix",
        blocker="is_short is NULL for 92% of videos until the enrichment backfill runs",
        kind="query",
        trigger="share of videos with a known is_short >= 0.80",
        consumer="nothing yet; a supply composite input",
        cost="small — one query plus a scalar reduction of a distribution",
    ),
    Deferral(
        metric="openness.rss_acceleration",
        blocker="needs a view series per video; video_snapshots has one day",
        kind="query",
        trigger="video_snapshots spans >= 30 distinct observed_dates",
        consumer="openness; INSIGHT_RULES candidates",
        cost="small — the prototype's function ports nearly unchanged",
    ),
    Deferral(
        metric="money.* (vw_cpc, priced_share, median_bid_high, competition_index_mean, tier1_cpc_ratio)",
        blocker="no Google Ads access; NH_GADS_CUSTOMER_ID empty and google-ads.yaml absent",
        kind="date",
        trigger="2026-09-24",
        consumer="scorecards.value, and through it opportunity",
        cost="medium — ADR-0016 pre-specifies the storage contract; CSV path needs one export per country",
    ),
    Deferral(
        metric="demand.total_monthly_searches, demand.kp_trend_last3_vs_first3",
        blocker="same Keyword Planner access",
        kind="date",
        trigger="2026-09-24",
        consumer="demand corroboration; nothing structural",
        cost="small once the collector exists",
    ),
    Deferral(
        metric="voice.* (question_rate, unanswered_rate, recommendation_threads)",
        blocker=(
            "Reddit API access was never applied for — not pending, unstarted. "
            "Approval under the Responsible Builder Policy is required first"
        ),
        kind="setting",
        trigger="NH_REDDIT_CLIENT_ID is set",
        consumer="INSIGHT_RULES Rule 7; a confidence penalty on scorecards, never a required input",
        cost="large — new tables, a migration, fixtures that need live credentials to record",
    ),
    Deferral(
        metric="cost_risk.* (primary-source density and cadence, PD asset density, brand-safety, enforcement trend)",
        blocker=(
            "sources resolve for 2 of 6 niches — CourtListener and EDGAR work "
            "unauthenticated, NTSB's CAROL API rejects documented payloads, USCG "
            "403s, NIST has no API. Present-vs-absent is not high-vs-low"
        ),
        kind="manual",
        trigger="a source exists for a majority of seeds; see niche_seeds.primary_sources",
        consumer="scorecards.sustainability",
        cost="large — a collector package that does not exist",
    ),
    Deferral(
        metric="scorecards.value / sustainability / opportunity / ci_low / ci_high",
        blocker="their inputs are deferred above; opportunity's weights are a Slice 6 OUTPUT",
        kind="manual",
        trigger="money.* lands (value); cost_risk.* lands (sustainability); Gate E chooses weights (opportunity)",
        consumer="the headline score",
        cost="medium, and deliberately last — a composite with invented weights is worse than a NULL",
    ),
)


def _query_fires(trigger: str, engine: Engine | None) -> bool | None:
    """Evaluate the handful of data conditions we know how to check."""
    with session_scope(engine) as session:
        if "older than 365 days" in trigger:
            total, old = session.execute(
                sa.text(
                    "SELECT count(*), sum(CASE WHEN julianday('now') - "
                    "julianday(v.published_at) > 365 THEN 1 ELSE 0 END) "
                    "FROM videos v JOIN cluster_members cm "
                    "ON cm.item_id = v.video_id AND cm.item_type = 'video' "
                    "WHERE cm.relevance >= 0.55 AND v.published_at IS NOT NULL"
                )
            ).one()
            return bool(total) and (old or 0) / total >= 0.20
        if "known is_short" in trigger:
            total, known = session.execute(
                sa.text(
                    "SELECT count(*), sum(CASE WHEN is_short IS NOT NULL THEN 1 ELSE 0 END) "
                    "FROM videos"
                )
            ).one()
            return bool(total) and (known or 0) / total >= 0.80
        if "distinct observed_dates" in trigger:
            days = session.scalar(
                sa.text("SELECT count(DISTINCT observed_date) FROM video_snapshots")
            )
            return (days or 0) >= 30
    return None


def fires(deferral: Deferral, today: date, engine: Engine | None = None) -> bool | None:
    """`True` unblocked, `False` still blocked, `None` not machine-checkable."""
    if deferral.kind == "date":
        return today > date.fromisoformat(deferral.trigger)
    if deferral.kind == "setting":
        name = deferral.trigger.split()[0].removeprefix("NH_").lower()
        return bool(getattr(get_settings(), name, None))
    if deferral.kind == "query":
        return _query_fires(deferral.trigger, engine)
    return None
