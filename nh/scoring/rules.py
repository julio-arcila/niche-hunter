"""Insight rules: predicates over what was computed, emitting `alerts` rows.

Three rules, and the count is the point. `docs/INSIGHT_RULES.md` listed ten planned and
defined two, both of which named metrics that do not exist — one needs
`voice.unanswered_rate` (no source, Reddit still pending) and one needs
`demand.season_index` (defined nowhere). A rule that cannot fire is worse than no rule
because it reads as coverage.

**Two constraints every rule here obeys, from ADR-0052.**

1. *An alert is a citation.* ADR-0045 names an alert as a surface that puts a number in
   front of a person, so no rule may read a metric the scorer decided while the exposition
   axis is unvalidated — and every active cluster is on that axis. `test_rules.py` asserts
   this against `gates.SCORER_DEPENDENT` rather than trusting the docstrings below.
2. *Night-over-night means consecutive STORED days.* `features_daily` has no row for
   2026-08-30 — the nightly a sleeping Mac ate before the launchd port — and no rule may
   fire on that hole or on the next one.

Alerts are append-only and unique on `(cluster_id, rule, fired_on)`, so re-running a day
is a no-op and the first firing of the day is the one that survives — the same discipline
as a snapshot, for the same reason.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import Alert, ClusterMember, FeatureDaily, NicheSeed
from nh.db.provenance import Stamp
from nh.db.upsert import insert_ignore
from nh.features.demand import LAG_DAYS, WINDOW_DAYS, _window
from nh.features.inputs import BALLAST_DRIFT_SHARE, demand_terms

#: Rule 1. How far above its own history a 28-day demand window must sit. Two sigma
#: against a baseline of ~13 non-overlapping windows — which is a small n for an sd, and
#: saying so is the point: this is a flag for a human to look, `severity="info"`, not a
#: finding.
BREAKOUT_Z = 2.0
#: Below this many baseline windows the sd is not worth computing. 365 days of dailies
#: gives 13; eight is "most of a year present".
BREAKOUT_MIN_WINDOWS = 8
BASELINE_DAYS = 365

#: Rule 3. `inputs_n` falling by more than half between stored days.
COLLAPSE_RATIO = 0.5

#: The metrics Rule 2 watches for a definition change. Named rather than "everything with
#: a definition", because `uploads_per_week` carries `DEFINITION_SPAN_RATE`, a second and
#: unrelated definition tag — a rule that treated every tag as one axis would report a
#: step whenever either moved and could not say which.
DEFINITION_WATCHED = ("on_niche_share", "median_views")


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    severity: str
    evidence: dict[str, Any]


def _stored_days(session: Session, cluster_id: str, day: date, back: int = 2) -> list[date]:
    """The `back` most recent days at or before `day` that actually have rows, newest first.

    The whole of constraint 2 lives in this function. Asking for "yesterday" would compare
    2026-08-31 against a day that does not exist and fire on every gap forever.
    """
    return list(
        session.scalars(
            sa.select(FeatureDaily.day)
            .where(FeatureDaily.cluster_id == cluster_id, FeatureDaily.day <= day)
            .group_by(FeatureDaily.day)
            .order_by(FeatureDaily.day.desc())
            .limit(back)
        )
    )


def _rows_on(session: Session, cluster_id: str, day: date) -> dict[str, FeatureDaily]:
    return {
        row.name: row
        for row in session.scalars(
            sa.select(FeatureDaily).where(
                FeatureDaily.cluster_id == cluster_id, FeatureDaily.day == day
            )
        )
    }


def demand_breakout(session: Session, cluster_id: str, day: date) -> Finding | None:
    """Rule 1 — a 28-day demand window well above the cluster's own year.

    Computed from `demand_snapshots` through `demand._window`, the same helper
    `wiki_momentum_28d` uses, rather than from `features_daily`: the feature table holds
    four days and the baseline needs a year. Reusing the helper is what keeps the alert's
    window identical to the metric's.

    Baseline windows are **non-overlapping**. Rolling ones are autocorrelated and would
    understate the sd, which inflates every z — the failure mode where a rule fires
    constantly and is then ignored.

    Ungated: `demand.*` is scorer-independent, so this says nothing about relevance.
    """
    terms = demand_terms(session, cluster_id, "wikipedia")
    if not terms:
        return None
    hi = day - timedelta(days=LAG_DAYS)
    mid = hi - timedelta(days=WINDOW_DAYS)
    points, recent = _window(session, terms, mid, hi)
    if not points:
        return None

    baseline: list[float] = []
    edge = mid
    while (mid - edge).days < BASELINE_DAYS:
        lower = edge - timedelta(days=WINDOW_DAYS)
        n, total = _window(session, terms, lower, edge)
        if n:
            baseline.append(total)
        edge = lower
    if len(baseline) < BREAKOUT_MIN_WINDOWS:
        return None

    mean = statistics.fmean(baseline)
    sd = statistics.stdev(baseline)
    if sd <= 0:
        return None
    z = (recent - mean) / sd
    if z < BREAKOUT_Z:
        return None
    return Finding(
        rule="demand_breakout",
        severity="info",
        evidence={
            "z": round(z, 3),
            "recent_window_views": round(recent, 1),
            "baseline_mean": round(mean, 1),
            "baseline_sd": round(sd, 1),
            "baseline_windows": len(baseline),
            "window": [mid.isoformat(), hi.isoformat()],
            "articles": terms,
            # Attached, never thresholded: a human can read a spike as a news event and a
            # rule cannot. This is the documented false positive for Rule 1.
            "volatility_365d": _volatility(session, cluster_id, day),
            "note": (
                "an observation about attention, not a forecast — Gate E's null is about "
                "prediction and this rule does not predict"
            ),
        },
    )


def _volatility(session: Session, cluster_id: str, day: date) -> float | None:
    return session.scalar(
        sa.select(FeatureDaily.value).where(
            FeatureDaily.cluster_id == cluster_id,
            FeatureDaily.day == day,
            FeatureDaily.name == "wiki_volatility_365d",
        )
    )


def definition_step(session: Session, cluster_id: str, day: date) -> Finding | None:
    """Rule 2 — a value that moved because the definition moved.

    Not news about the niche, and the reason this rule exists: ADR-0047 moved
    `on_niche_share` 0.076 -> 0.227 on an **identical numerator of 230**, and nothing said
    so at the time. This is also what fires on 2026-09-14 when ADR-0050's sunset reverts
    `supply.*` to `v2-on-niche`.

    Ungated: it cites no metric VALUE, only that a definition changed, which is a fact
    about the pipeline rather than about the niche.
    """
    days = _stored_days(session, cluster_id, day)
    if len(days) < 2 or days[0] != day:
        return None
    today, previous = days[0], days[1]
    now, before = _rows_on(session, cluster_id, today), _rows_on(session, cluster_id, previous)

    moved = []
    for name in DEFINITION_WATCHED:
        a, b = before.get(name), now.get(name)
        if a is None or b is None:
            continue
        was = (a.detail or {}).get("definition")
        became = (b.detail or {}).get("definition")
        if was is not None and became is not None and was != became:
            moved.append({"metric": name, "from": was, "to": became})

    ballast_move = _ballast_move(now, before, session, cluster_id)
    if not moved and ballast_move is None:
        return None
    return Finding(
        rule="definition_step",
        severity="watch",
        evidence={
            "from_day": previous.isoformat(),
            "to_day": today.isoformat(),
            "definitions": moved,
            "ballast": ballast_move,
            "note": "values either side of this day are not comparable",
        },
    )


def _ballast_move(
    now: dict[str, FeatureDaily], before: dict[str, FeatureDaily], session: Session, cluster_id: str
) -> dict | None:
    """The size of the ballast cut, night over night, as a share of member channels.

    On the DELTA and never the level, for the reason `jobs.status` gives: history-of-ideas
    sits at 126 of 205 by construction, and a rule that fires on that fires forever.
    """
    a = (before.get("on_niche_share").detail or {}) if before.get("on_niche_share") else {}
    b = (now.get("on_niche_share").detail or {}) if now.get("on_niche_share") else {}
    was, became = a.get("ballast"), b.get("ballast")
    if not isinstance(was, dict) or not isinstance(became, dict):
        return None  # first night after the stamp landed: absent is not a change
    if was.get("channels") is None or became.get("channels") is None:
        return None
    members = (
        session.scalar(
            sa.select(sa.func.count()).where(
                ClusterMember.cluster_id == cluster_id, ClusterMember.item_type == "channel"
            )
        )
        or 1
    )
    delta = abs(became["channels"] - was["channels"])
    if delta / members <= BALLAST_DRIFT_SHARE:
        return None
    return {
        "from": was["channels"],
        "to": became["channels"],
        "member_channels": members,
        "share": round(delta / members, 4),
    }


def evidence_collapse(session: Session, cluster_id: str, day: date) -> Finding | None:
    """Rule 3 — a metric that stopped being computable, or lost most of its inputs.

    A source went quiet, a join broke, or a retirement removed a population. Every one of
    those looks like a working pipeline from `nh status`, which checks that collection
    happened rather than that it produced anything readable.

    Ungated: it reads existence and `inputs_n`, never a value. Its documented false
    positive — a cluster retired between the two days — is checked rather than left to the
    reader, because that is a decision and not a collapse.
    """
    days = _stored_days(session, cluster_id, day)
    if len(days) < 2 or days[0] != day:
        return None
    if not _is_active(session, cluster_id):
        return None
    today, previous = days[0], days[1]
    now, before = _rows_on(session, cluster_id, today), _rows_on(session, cluster_id, previous)

    lost, thinned = [], []
    for name, was in before.items():
        became = now.get(name)
        if was.value is None:
            continue
        if became is None or became.value is None:
            lost.append(
                {"metric": name, "reason": (became.detail or {}).get("reason") if became else None}
            )
        elif (
            was.inputs_n
            and became.inputs_n is not None
            and became.inputs_n < was.inputs_n * COLLAPSE_RATIO
        ):
            # The NAME and the fact, always; the counts only when the metric is not gated.
            # `inputs_n` is how many rows the scorer decided about, and ADR-0052 withholds
            # it alongside the value in `nh niche show` — "a half-blank row reads as a bug
            # rather than as a decision". An alert quoting the count of a metric whose
            # value is withheld would be that decision leaking out of a side door.
            entry: dict[str, Any] = {"metric": name}
            if _citable(name):
                entry |= {"from": was.inputs_n, "to": became.inputs_n}
            else:
                entry["counts"] = "withheld — unvalidated scorer (ADR-0052)"
            thinned.append(entry)
    if not lost and not thinned:
        return None
    return Finding(
        rule="evidence_collapse",
        severity="watch",
        evidence={
            "from_day": previous.isoformat(),
            "to_day": today.isoformat(),
            "went_null": lost,
            "lost_inputs": thinned,
        },
    )


def _citable(name: str) -> bool:
    """Whether this metric's numbers may appear in an alert.

    Imported from the gate rather than re-listed: `gates.SCORER_DEPENDENT` is itself
    derived by execution (`test_gates.py` recomputes it), so a metric that starts reading
    relevance stops being quotable here without anyone editing this file.
    """
    from nh.api.gates import SCORER_DEPENDENT

    return name not in SCORER_DEPENDENT


def _is_active(session: Session, cluster_id: str) -> bool:
    """Rule 3's documented false positive, checked rather than left to the reader.

    A retired cluster stops accruing feature rows, so every metric it had goes NULL at
    once — which is a decision, not a collapse, and firing on it would make the rule's
    loudest day the day it was least useful.
    """
    return bool(session.scalar(sa.select(NicheSeed.active).where(NicheSeed.slug == cluster_id)))


RULES = (demand_breakout, definition_step, evidence_collapse)


def evaluate(session: Session, day: date, mark: Stamp) -> int:
    """The phase. One `alerts` row per firing rule per cluster per day."""
    clusters = list(
        session.scalars(sa.select(NicheSeed.slug).where(NicheSeed.active).order_by(NicheSeed.slug))
    )
    rows = []
    for cluster_id in clusters:
        for rule in RULES:
            finding = rule(session, cluster_id, day)
            if finding is None:
                continue
            rows.append(
                mark(
                    Alert,
                    {
                        "cluster_id": cluster_id,
                        "rule": finding.rule,
                        "severity": finding.severity,
                        "fired_on": day,
                        "evidence": finding.evidence,
                    },
                )
            )
    if not rows:
        return 0
    return insert_ignore(session, Alert, rows, conflict_on=("cluster_id", "rule", "fired_on"))
