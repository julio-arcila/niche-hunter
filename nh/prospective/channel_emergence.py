"""The channel-emergence test (ADR-0069): does short-run outperformance convert to audience?

ADR-0060's H1 established that `views_per_sub` predicts a channel's 14-day reach. This asks
the consequential sequel — whether that attention becomes **subscribers** over 90 days.

Registered in `reports/channel_emergence_preregistration_2026-10-22.md` on 2026-10-22, before
any outcome for either decision date existed. The first readable outcome is 2026-11-30.

**It reuses ADR-0060's frozen cohort unchanged.** The predictor and all three controls are
read from the file whose bytes were hashed on 2026-09-15 and whose hash was recorded in a
merged commit seven weeks before this registration was written, so no choice here could have
been informed by them. Nothing new is frozen; `channel_reach.load_key` is the one reader.

**This is not a niche test and cannot become one.** ADR-0068 measured the arithmetic: at ten
active clusters a cross-sectional niche-grain test needs an observed rho above 0.636, so the
niche question is not asked here. Cluster enters only as the stratum the ranks are taken
within.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.backtest.stats import DRAWS, Row, evaluate_stratified, top_decile_lift
from nh.db.models import ChannelSnapshot
from nh.prospective.channel_reach import (
    CONTROLS,
    FrozenRow,
    KeyMismatch,
    NotRegistered,
    TooEarly,
    load_key,
)

REGISTRATION = "reports/channel_emergence_preregistration_2026-10-22.md"

#: ADR-0060's key, reused byte-for-byte. Not a copy: a second file with the same contents
#: would be a second thing to keep honest.
KEY_PATH = Path("reports/channel_reach_cohort_draw_key_2026-09-15.jsonl")

#: The sha256 the registration records. A constant a person sets in the commit that
#: registers the test — never a file or an environment variable the code reads, on the
#: `EXPOSITION_VALIDATED` pattern. `None` means unregistered and `read()` refuses.
REGISTERED_KEY_SHA256: str | None = (
    "1cb64d0acf07b50d5594389812c7725851adaabf3e38da2a0b6df2d28786e5f2"
)

DECISION_DATES = (date(2026, 9, 1), date(2026, 9, 8))

#: The outcome window. 90 is the horizon the registration names; the 7-day tolerance is the
#: same shape as ADR-0059's [14, 17] and absorbs a lost night without losing the channel.
OUTCOME_MIN_AGE, OUTCOME_MAX_AGE = 90, 97

#: The one read. No interim: ADR-0060's added nothing its verdict did not contain and cost a
#: clause in its own void list.
READ_DATE = date(2026, 12, 14)
REPORT = Path("reports/channel_emergence_2026-12-14.md")

SEED = 20261122
MIN_CHANNELS, MIN_CLUSTERS, CLUSTER_FLOOR = 200, 5, 20
CLUSTER_MIN_OUTCOMES = 10
ALPHA, LIFT_FLOOR = 0.05, 1.15

#: Above this share of exactly-zero outcomes the read returns INSTRUMENT rather than FAIL.
#: Measured 2026-10-22: at least 10% of cohort channels show no subscriber movement over 18
#: days, because YouTube publishes 3 significant figures. A degenerate outcome cannot test a
#: hypothesis, and calling that a FAIL would blame the predictor for the instrument.
MAX_TIED_SHARE = 0.40


@dataclass(frozen=True, slots=True)
class Growth:
    """The outcome for one frozen row. `value` is None when no reading landed."""

    value: float | None
    subs_t: int
    subs_r: int | None
    read_on: date | None


def subs_growth_90d(session: Session, rows: list[FrozenRow], t: date) -> dict[str, Growth]:
    """`ln(subs_r / subs_t)` per channel, for the rows frozen at `t`.

    `subs_r` is the reading on the SMALLEST `observed_date` in [t+90, t+97] carrying a
    non-NULL `subs`, taking the max across sources that date — the same "earliest real
    reading in the window" rule ADR-0059's outcome uses, so a channel read on several days
    contributes the one nearest its horizon.

    A channel with no reading in the window is absent, never zero (data rule 7). That
    includes a channel whose feed went 404 before the window; the caller counts those and
    the report states them, because survivorship is a limitation of this test rather than
    something to hide in a denominator.
    """
    ids = [r.channel_id for r in rows if r.t == t.isoformat()]
    if not ids:
        return {}
    window = (t + timedelta(days=OUTCOME_MIN_AGE), t + timedelta(days=OUTCOME_MAX_AGE))
    readings = session.execute(
        sa.select(
            ChannelSnapshot.channel_id,
            ChannelSnapshot.observed_date,
            sa.func.max(ChannelSnapshot.subs),
        )
        .where(
            ChannelSnapshot.channel_id.in_(ids),
            ChannelSnapshot.observed_date >= window[0],
            ChannelSnapshot.observed_date <= window[1],
            ChannelSnapshot.subs.is_not(None),
        )
        .group_by(ChannelSnapshot.channel_id, ChannelSnapshot.observed_date)
        .order_by(ChannelSnapshot.channel_id, ChannelSnapshot.observed_date)
    )
    earliest: dict[str, tuple[date, int]] = {}
    for channel_id, day, subs in readings:
        if subs and channel_id not in earliest:
            earliest[channel_id] = (day, subs)

    out: dict[str, Growth] = {}
    for row in rows:
        if row.t != t.isoformat():
            continue
        subs_t = round(math.exp(row.ln_subs))
        hit = earliest.get(row.channel_id)
        if hit is None or subs_t <= 0:
            out[row.channel_id] = Growth(None, subs_t, None, None)
            continue
        day, subs_r = hit
        out[row.channel_id] = Growth(math.log(subs_r / subs_t), subs_t, subs_r, day)
    return out


def _rows_for(frozen: list[FrozenRow], growth: dict[str, Growth], t: date) -> list[Row]:
    """Frozen predictor and controls joined to the outcome, for one decision date.

    `Row` is `nh.backtest.stats`' 5-tuple `(unit, block, predictor, outcome, controls)` —
    the same shape ADR-0060 used, so the statistic is literally the same code path.
    """
    out: list[Row] = []
    for row in frozen:
        if row.t != t.isoformat():
            continue
        g = growth.get(row.channel_id)
        if g is None or g.value is None:
            continue
        out.append(
            (
                row.channel_id,
                row.cluster_id,
                row.views_per_sub,
                g.value,
                tuple(float(getattr(row, name)) for name in CONTROLS),
            )
        )
    return out


def tied_share(per_date: list[tuple[str, list[Row]]]) -> float:
    """Share of outcomes that are exactly zero — the publication-floor degeneracy check."""
    rows = [r for _, rows in per_date for r in rows]
    if not rows:
        return 1.0
    return sum(1 for r in rows if r[3] == 0.0) / len(rows)


@dataclass(frozen=True, slots=True)
class Hypothesis:
    rho: float | None
    p: float | None
    lift: float | None


@dataclass(frozen=True, slots=True)
class Findings:
    n_channels: int
    clusters_at_floor: int
    n_terminated: int
    tied: float
    t0e: Hypothesis
    h1e: Hypothesis


def _judge(h: Hypothesis, *, floor: float | None) -> tuple[bool, str]:
    if h.rho is None or h.p is None or (floor is not None and h.lift is None):
        return False, "could not be computed"
    if h.rho <= 0:
        return False, f"rho {h.rho:+.3f} is not positive"
    if h.p >= ALPHA:
        return False, f"p {h.p:.4f} is not below {ALPHA}"
    if floor is not None and h.lift is not None and h.lift < floor:
        return False, f"top-decile lift {h.lift:.3f} is below {floor}"
    tail = f", lift {h.lift:.3f}" if floor is not None else ""
    return True, f"rho {h.rho:+.3f}, p {h.p:.4f}{tail}"


def verdict(f: Findings) -> dict[str, tuple[str, str]]:
    """Power, then degeneracy, then the instrument, then H1e. The order is registered.

    Three ways to return something other than PASS/FAIL, each of which says the test could
    not be run rather than that the hypothesis is false:

    * below the floors — INCONCLUSIVE, the registered n was not reached;
    * too many tied outcomes — INSTRUMENT, the 3-significant-figure publication floor
      flattened the outcome;
    * T0e null — INSTRUMENT, 14-day reach does not reach subscribers by any route, so the
      predictor was never given a path to the outcome.

    `_judge`'s FAIL is reserved for the case where the instrument worked and the claim did
    not hold. Conflating the three is how a measurement problem gets recorded as a finding.
    """
    if f.n_channels < MIN_CHANNELS or f.clusters_at_floor < MIN_CLUSTERS:
        why = (
            f"{f.n_channels} channels with an outcome (floor {MIN_CHANNELS}), "
            f"{f.clusters_at_floor} clusters at {CLUSTER_FLOOR} (floor {MIN_CLUSTERS})"
        )
        return {"H1e": ("INCONCLUSIVE — under the registered floors", why)}
    if f.tied > MAX_TIED_SHARE:
        why = f"{f.tied:.0%} of outcomes are exactly zero (cap {MAX_TIED_SHARE:.0%})"
        return {"H1e": ("INSTRUMENT — the outcome is degenerate", why)}
    ok, why = _judge(f.t0e, floor=None)
    if not ok:
        return {"H1e": ("INSTRUMENT — 14-day reach does not reach subscribers", why)}
    ok, why = _judge(f.h1e, floor=LIFT_FLOOR)
    return {"H1e": ("PASS" if ok else "FAIL", why)}


def measure(session: Session, frozen: list[FrozenRow], *, draws: int = DRAWS) -> Findings:
    """Compute T0e and H1e over both decision dates. Reads nothing but the outcome."""
    per_date: list[tuple[str, list[Row]]] = []
    terminated = 0
    for t in DECISION_DATES:
        growth = subs_growth_90d(session, frozen, t)
        terminated += sum(1 for g in growth.values() if g.value is None)
        per_date.append((t.isoformat(), _rows_for(frozen, growth, t)))

    # Floors are counted on DISTINCT channels, not channel-dates: 977 channels across
    # 1,473 rows means ~500 appear at both decision dates, and counting rows would let a
    # 200-channel floor be cleared by 200 appearances of 120 channels. ADR-0060's own
    # "agreement across two cohorts" claim overstated independence for exactly this
    # reason, which is worth not repeating one registration later.
    by_cluster: dict[str, set[str]] = {}
    for _, rows in per_date:
        for unit, block, *_rest in rows:
            by_cluster.setdefault(block, set()).add(unit)
    keep = {b for b, units in by_cluster.items() if len(units) >= CLUSTER_MIN_OUTCOMES}
    kept = [(d, [r for r in rows if r[1] in keep]) for d, rows in per_date]
    n_channels = len({unit for _, rows in kept for unit, *_ in rows})
    at_floor = sum(1 for units in by_cluster.values() if len(units) >= CLUSTER_FLOOR)

    h1e_rho, h1e_p, _per_date_rhos = evaluate_stratified(kept, draws=draws, seed=SEED)
    h1e = Hypothesis(h1e_rho, h1e_p, top_decile_lift(kept))
    # T0e is registered as the instrument check and needs ADR-0060's measured 14-day reach
    # joined to this outcome; it is computed by the read, which has both in hand.
    return Findings(
        n_channels=n_channels,
        clusters_at_floor=at_floor,
        n_terminated=terminated,
        tied=tied_share(kept),
        t0e=Hypothesis(None, None, None),
        h1e=h1e,
    )


def refuse_unless_ready(session: Session, *, key_path: Path = KEY_PATH) -> list[FrozenRow]:
    """Every refusal the registration promises, before a single number is computed.

    There is deliberately no flag that skips any of this.
    """
    if REGISTERED_KEY_SHA256 is None:
        raise NotRegistered("REGISTERED_KEY_SHA256 is unset; there is no registration to read")
    rows, sha = load_key(key_path)
    if sha != REGISTERED_KEY_SHA256:
        raise KeyMismatch(f"{key_path} is {sha}, the registration recorded {REGISTERED_KEY_SHA256}")
    latest = session.scalar(sa.select(sa.func.max(ChannelSnapshot.observed_date)))
    if latest is None or latest < READ_DATE:
        raise TooEarly(
            f"the verdict reads on {READ_DATE} and the newest channel reading is {latest}"
        )
    if REPORT.exists():
        raise FileExistsError(f"{REPORT} exists; a registered read is rendered once")
    return rows
