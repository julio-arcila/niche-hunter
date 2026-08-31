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
            "model judging a model and does NOT discharge this deferral. ADR-0028 "
            "added `true-crime-trials` to the family on 2026-08-28 with NO measured "
            "precision at all — 0.781 belongs to the old five — so its rows must be "
            "part of whatever sample is drawn"
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
        metric="exposition axis — human validation before anything is TRUSTED from it",
        blocker=(
            "domain x exposition (P 0.866 / R 0.736 held-out) rests on 107 MACHINE "
            "labels from fable-5 under a written criterion. kappa 0.845 across two "
            "rules and two raters bounds rule stability but cannot detect a bias two "
            "models share. EVENT's 0.781 rests on 298 human labels, so shipping the "
            "eleven now would put a weaker-evidenced scorer beside a stronger one "
            "under the same `relevance` column"
        ),
        kind="manual",
        trigger=(
            "a human labels 60-100 rows sampled FROM ABOVE the shipping threshold "
            "(not uniformly — the 2026-08-28 interrater audit's outstanding "
            "correction), drawn from pivot-domain videos scored by the committed "
            "EXPOSITION literal, and precision clears the bar pre-registered in "
            "ADR-0041: the 95% Wilson LOWER BOUND on precision is at least 0.70, "
            "which is 79/100 or 65/80 correct. Parity with EVENT's 0.781 was "
            "considered and rejected as undecidable at this n — it would need "
            "87/100, i.e. the humans reproducing the machine estimate exactly. "
            "The draw is postponed, never shrunk, until 80 rows clear 0.55 across "
            "at least 6 domains, capped at 15 per domain. The ACTIVATION half of "
            "this entry is "
            "discharged (ADR-0040): the eleven are live for discovery, because the "
            "sample cannot be drawn until they collect — 19 of 120 pivot videos "
            "clear 0.55 across 4 of 11 domains, against a 60-100 requirement, and a "
            "niche gains members only through discovery on its own seeds. Quota is "
            "no longer an argument either way: the disaster niches went to 0 "
            "(ADR-0039), so all eleven cost 6,600 of 9,500 with 2,900 spare. "
            "CORRECTED 2026-08-30 (ADR-0043): this entry used to be titled 'before it "
            "scores anything' and that was false — `features/run.py` filters on "
            "`Cluster.active` and nothing else, so the eleven entered `features_daily` "
            "and `scorecards` on 2026-08-29, the first run after ADR-0040 activated "
            "them for DISCOVERY. 253 feature rows and 11 scorecards per day since. "
            "Accepted rather than gated: features are recomputable, and what this "
            "deferral withholds is TRUST, not computation — value/sustainability/"
            "opportunity stay NULL behind Gate E and no ranking ships. The stored rows "
            "carry NO marker that they predate validation; check the day against "
            "ADR-0043 before trusting a series that spans it"
        ),
        consumer=(
            "the exposition half of `relevance`. CORRECTED 2026-08-30, because this "
            "field and the title above both said 'nothing they score ships until this "
            "clears', and that was false as written: `features/run.py` selects every "
            "`Cluster.active` row and has no axis-validation filter, so the eleven "
            "entered `features_daily` and `scorecards` on 2026-08-29, the first run "
            "after ADR-0040 activated them for DISCOVERY. `active` is one flag doing "
            "two jobs and ADR-0040 only meant to turn on the first — the same shape as "
            "the ADR-0039 addendum. Measured: 253 feature rows and 11 scorecards per "
            "day since, philosophy-of-science among them at gap 0.2 / supply 0.0. What "
            "is actually withheld is TRUST, not computation: `value`, `sustainability` "
            "and `opportunity` stay NULL behind Gate E, no ranking ships, and no "
            "evidence page cites these numbers. Accepted rather than gated (ADR-0043): "
            "features are recomputable by design, so a fail costs a recompute, not "
            "history. The rows carry no marker saying they predate validation — read "
            "`detail.definition` and the day against ADR-0043 before trusting a series "
            "that spans it"
        ),
        cost="~45 minutes of reading, plus the pre-registration paragraph",
    ),
    Deferral(
        metric="geo_basis stamped into feature detail, and rendered",
        blocker=(
            "ADR-0035 requires every metric to carry the population it measures, but "
            "nothing stamps it. `nh niche show` prints a demand number and a supply "
            "number from different populations with nothing saying so"
        ),
        kind="manual",
        trigger="SLICE 9 — it becomes arithmetically live the day a geo=US level ships",
        consumer="every demand and supply metric; scorecards.gap above all",
        cost=(
            "larger than it looks. Not just a constant and a detail key: `cli.py::"
            "_provenance` renders a FIXED list of named keys, so an unrendered key "
            "repeats ADR-0031's `currency` bug exactly — fold it into Slice 9's "
            "existing _provenance task. And `gap` lives in `scorecards`, not "
            "`features_daily`, so a per-feature detail key never reaches the place "
            "ADR-0035 decision 2 actually requires it"
        ),
    ),
    Deferral(
        metric="scorecards.gap — re-specification to compare like with like",
        blocker=(
            "no corpus holds both supply geo composition and an outcome. Measured: "
            "data/backtest.db has country for 0 of 4,527 channels, YouNiverse has no "
            "country column, and load.py writes NULL by design. The live corpus has "
            "country but no outcome. So the test that would justify a re-spec has no "
            "instrument — the same shape as Gate E's emergence claim"
        ),
        kind="manual",
        trigger=(
            "a corpus exists carrying per-channel geo AND a forward outcome. Note the "
            "cheap partial: ~91 quota units of channels.list over the 4,527 backtest "
            "ids would supply present-day country, but that is 2026 attribute on 2019 "
            "channels — the leakage class ADR-0026 already documents — and at n=29 "
            "niches the detectable rho is 0.378, so a null from it would be weak"
        ),
        consumer="scorecards.gap; nothing else",
        cost="a pre-registration plus the corpus that does not exist yet",
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
        metric="money.tier1_cpc_ratio",
        blocker=(
            "the ratio needs a tier-1 market to compare against a non-tier-1 one, and "
            "both ingested exports are tier-1. The legacy formula's TIER1 is "
            "US/GB/CA/AU, so US (96 rows) and GB (66 rows) give a numerator with no "
            "denominator. The other four money.* metrics shipped 2026-08-29 and are no "
            "longer deferred"
        ),
        kind="query",
        trigger="keyword_metrics holds both a tier-1 and a non-tier-1 geo",
        consumer="the money picture; nothing composite while ADR-0029 stands",
        cost="small — one more manual CSV export from a non-tier-1 market, then a metric",
    ),
    Deferral(
        metric="demand.kp_trend_last3_vs_first3",
        blocker=(
            "the twelve monthly columns are empty in every export so far — measured "
            "0/360 across the 2026-08 US and GB files — and `keyword_metrics` has no "
            "column to store them in even if they arrive. total_monthly_searches "
            "shipped 2026-08-29 and is no longer deferred"
        ),
        # Manual, not query: nothing in the schema holds monthly columns, so no SQL
        # can answer this. An earlier plan proposed a query trigger here, which would
        # have matched no branch in `_query_fires` and returned None forever —
        # indistinguishable from manual, but pretending to be checkable.
        kind="manual",
        trigger="an export whose twelve monthly columns are populated; check the next CSV by eye",
        consumer="demand momentum from search rather than from pageviews",
        cost="a schema column and a migration, then the metric",
    ),
    Deferral(
        metric="per-market KP metric variants (total_monthly_searches_gb, vw_cpc_gb, ...)",
        blocker=(
            "ADR-0035 rule 3: do not open a second market until the first validates. "
            "The 66 GB rows ARE ingested and the loader reads them today — "
            "`keyword_planner_rows(session, cluster, day, 'GB')` returns them — so "
            "nothing decays while this waits; only the registration is withheld"
        ),
        kind="manual",
        trigger=(
            "the US instance has been judged useful by its operator, or a second "
            "market becomes the subject of a decision. reports/geo_value_2026-08-28.md "
            "measured that the value ranking reorders between US and GB, which is why "
            "these will matter"
        ),
        consumer="a catalogue serving operators in more than one market (ADR-0036)",
        cost="tiny — `_geo(fn, 'GB', suffix='_gb')` per metric; the loader already takes geo",
    ),
    Deferral(
        metric="voice.* (question_rate, unanswered_rate, recommendation_threads)",
        blocker=(
            "Reddit API access is APPLIED FOR and pending, filed 2026-08-29 under "
            "the Responsible Builder Policy — a state this entry used to deny, "
            "saying 'never applied for, not pending, unstarted'. Approval gates "
            "everything: no credential exists to write a fixture against"
        ),
        kind="setting",
        trigger="NH_REDDIT_CLIENT_ID is set",
        consumer="INSIGHT_RULES Rule 7; a confidence penalty on scorecards, never a required input",
        cost="large — new tables, a migration, fixtures that need live credentials to record",
    ),
    Deferral(
        metric="cost_risk.* (primary-source density and cadence, PD asset density, brand-safety, enforcement trend)",
        blocker=(
            "sources resolve for 2 of 6 niches — EDGAR works unauthenticated; "
            "CourtListener needs a free account since 2026-05-07 (measured "
            "2026-08-29: 401 unauthenticated, free tier 125 req/day); NTSB's CAROL "
            "API rejects documented payloads, USCG 403s, NIST has no API. "
            "Present-vs-absent is not high-vs-low"
        ),
        kind="manual",
        trigger="a source exists for a majority of seeds; see niche_seeds.primary_sources",
        consumer="scorecards.sustainability",
        cost="large — a collector package that does not exist",
    ),
    Deferral(
        metric="landmark-court-cases — seed reactivation",
        blocker=(
            "deactivated 2026-08-28 (ADR-0028). Post-Gate-E its evidence page would be "
            "one number over a column of NULLs: reference-article demand — the stratum "
            "carrying the school-calendar and curiosity-not-intent confounders, whose "
            "two readings invert rankings at rho -0.70 (ADR-0022) — over a supply that "
            "is empty by this niche's own definition"
        ),
        kind="manual",
        trigger=(
            "any one of: the demand-stratum arbitration resolves with a stratum an "
            "evidence page can defend; a future calibration validates a demand "
            "reading; the operator wants the page as an editorial choice. Reactivate "
            "with UPDATE niche_seeds SET active=1 WHERE slug='landmark-court-cases' — "
            "its 23 articles backfill quota-free on the next nightly (ADR-0022)"
        ),
        consumer="the demand-without-supply exemplar; ~600 search units/night when active",
        cost="one UPDATE plus one nightly for the demand backfill",
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
        if "tier-1 and a non-tier-1 geo" in trigger:
            # The legacy `cpc_geo_spread` compares tier-1 against the rest, so the
            # question is whether both CLASSES are present, not how many geos are.
            tier1 = ("US", "GB", "CA", "AU")
            geos = {
                g
                for (g,) in session.execute(sa.text("SELECT DISTINCT geo FROM keyword_metrics"))
                if g
            }
            return bool(geos & set(tier1)) and bool(geos - set(tier1))
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
