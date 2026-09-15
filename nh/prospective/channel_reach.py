"""The channel-reach test: a pre-registered 14-day prospective test at channel grain.

Registered in `reports/channel_reach_preregistration_2026-09-15.md` (ADR-0060). It reads
the live corpus and never writes to it, which is why it lives outside `nh/backtest`:
`backtest.load.refuse_live` guards writes that would contaminate the live corpus, and
this module makes none.

Three halves, kept apart so they cannot leak into each other:
  * the frozen side, `freeze()` — predictors read at each decision date, written once to a
    draw-key file whose sha256 the registration records;
  * the outcome side, `next_reach()` — views at day 14 of the uploads after each date;
  * the verdict, `findings()` / `verdict()` / `render()` — the registered statistic and the
    gated ladder T0 → H1 → H2, applied once per scheduled read.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.backtest.stats import DRAWS, Row, evaluate_stratified, top_decile_lift
from nh.db.models import Cluster, Video, VideoSnapshot
from nh.features import inputs

REGISTRATION = "reports/channel_reach_preregistration_2026-09-15.md"
KEY_PATH = Path("reports/channel_reach_cohort_draw_key_2026-09-15.jsonl")
DECISION_DATES = (date(2026, 9, 1), date(2026, 9, 8))
READS: dict[str, tuple[date, tuple[date, ...]]] = {
    "interim": (date(2026, 9, 25), (date(2026, 9, 1),)),
    "primary": (date(2026, 10, 2), DECISION_DATES),
}
REPORTS = {
    "interim": Path("reports/channel_reach_interim_2026-09-25.md"),
    "primary": Path("reports/channel_reach_2026-10-02.md"),
}

#: The sha256 of the frozen draw key, as recorded in the registration. A constant a
#: person sets in the commit that registers the test — never a file or an environment
#: variable the code reads, on the `EXPOSITION_VALIDATED` pattern. `None` means
#: unregistered, and `read()` refuses.
REGISTERED_KEY_SHA256: str | None = None

SEED = 20260916
UPLOAD_WINDOW_DAYS = 7
READ_MIN_AGE, READ_MAX_AGE = 14, 17
CLUSTER_MIN_OUTCOMES = 10
MIN_CHANNELS, MIN_CLUSTERS, CLUSTER_FLOOR = 200, 5, 20
ALPHA, LIFT_FLOOR = 0.05, 1.25
CONTROLS = ("ln_subs", "catalogue_age", "n_elig")


class NotRegistered(RuntimeError):
    """`REGISTERED_KEY_SHA256` is unset: there is no registration to read against."""


class KeyMismatch(RuntimeError):
    """The draw key on disk is not the one the registration recorded."""


class TooEarly(RuntimeError):
    """The read's date has not been collected yet; its outcomes do not all exist."""


# --- the frozen side ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrozenRow:
    t: str
    channel_id: str
    cluster_id: str
    breakout_magnitude: float
    views_per_sub: float
    ln_median: float
    ln_subs: float
    catalogue_age: float
    n_elig: int


def _published(session: Session, ids: list[str]) -> dict[str, date]:
    rows = session.execute(
        sa.select(Video.video_id, Video.published_at).where(Video.video_id.in_(ids))
    )
    return {vid: pub.date() for vid, pub in rows if pub is not None}


def freeze_date(session: Session, cluster_id: str, t: date) -> tuple[list[FrozenRow], int]:
    """Frozen rows for one cluster at one decision date, and the count left absent.

    Every read is the production input, day-bounded at `t`. A zero median has neither a
    ratio nor a log, so that channel is absent — counted, never scored.
    """
    members = inputs.cohort(session, cluster_id, t)
    if not members:
        return [], 0
    eligible = inputs.eligible_videos(session, cluster_id, t)
    subs = inputs.latest_subs(session, cluster_id, t)
    published = _published(session, [vid for c in members for vid, _ in eligible[c]])
    rows, absent = [], 0
    for channel in sorted(members):
        views = [v for _, v in eligible[channel]]
        median = statistics.median(views)
        if not median or not subs.get(channel):
            absent += 1
            continue
        ages = [(t - published[vid]).days for vid, _ in eligible[channel] if vid in published]
        rows.append(
            FrozenRow(
                t=t.isoformat(),
                channel_id=channel,
                cluster_id=cluster_id,
                breakout_magnitude=math.log(max(views) / median),
                views_per_sub=median / subs[channel],
                ln_median=math.log(median),
                ln_subs=math.log(subs[channel]),
                catalogue_age=float(statistics.median(ages)),
                n_elig=len(views),
            )
        )
    return rows, absent


def freeze(session: Session, dates: tuple[date, ...] = DECISION_DATES) -> list[FrozenRow]:
    """Every active cluster at every decision date, pinned so ballast cannot differ."""
    clusters = sorted(
        session.scalars(sa.select(Cluster.cluster_id).where(Cluster.active.is_(True)))
    )
    rows: list[FrozenRow] = []
    with inputs.pinned_ballast(False):
        for t in dates:
            for cluster in clusters:
                rows += freeze_date(session, cluster, t)[0]
    return rows


def key_bytes(rows: list[FrozenRow]) -> bytes:
    ordered = sorted(rows, key=lambda r: (r.t, r.cluster_id, r.channel_id))
    return "".join(json.dumps(asdict(r), sort_keys=True) + "\n" for r in ordered).encode()


def write_key(rows: list[FrozenRow], path: Path = KEY_PATH) -> str:
    """Write the draw key once and return its sha256. Frozen means frozen: an existing
    file is refused rather than replaced."""
    if path.exists():
        raise FileExistsError(f"{path} exists; a frozen cohort is written once")
    data = key_bytes(rows)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def load_key(path: Path = KEY_PATH) -> tuple[list[FrozenRow], str]:
    data = path.read_bytes()
    rows = [FrozenRow(**json.loads(line)) for line in data.decode().splitlines() if line]
    return rows, hashlib.sha256(data).hexdigest()


# --- the outcome side ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Reach:
    value: float | None  # mean ln(1 + views at day 14) over read uploads; None if none read
    n_uploads: int
    n_read: int


def _uploads(session: Session, channels: set[str], t: date) -> dict[str, dict[str, date]]:
    """`channel -> {video_id: publish date}`: long-form uploads on civil days t+1..t+7."""
    rows = session.execute(
        sa.select(Video.channel_id, Video.video_id, Video.published_at).where(
            Video.channel_id.in_(channels),
            Video.is_short.is_(False),
            Video.published_at >= inputs._until(t),
            Video.published_at < inputs._until(t + timedelta(days=UPLOAD_WINDOW_DAYS)),
        )
    )
    out: dict[str, dict[str, date]] = {}
    for channel, vid, published in rows:
        out.setdefault(channel, {})[vid] = published.date()
    return out


def _readings(session: Session, published: dict[str, date]) -> dict[str, int]:
    """`video_id -> views` on the smallest age in [14, 17] with a non-NULL reading, max
    across sources that day. A NULL is not a reading, so it cannot become that day."""
    if not published:
        return {}
    lo = min(published.values()) + timedelta(days=READ_MIN_AGE)
    hi = max(published.values()) + timedelta(days=READ_MAX_AGE)
    rows = session.execute(
        sa.select(
            VideoSnapshot.video_id, VideoSnapshot.observed_date, sa.func.max(VideoSnapshot.views)
        )
        .where(
            VideoSnapshot.video_id.in_(list(published)),
            VideoSnapshot.observed_date.between(lo, hi),
            VideoSnapshot.views.is_not(None),
        )
        .group_by(VideoSnapshot.video_id, VideoSnapshot.observed_date)
    )
    best: dict[str, tuple[date, int]] = {}
    for vid, day, views in rows:
        age = (day - published[vid]).days
        if READ_MIN_AGE <= age <= READ_MAX_AGE and (vid not in best or day < best[vid][0]):
            best[vid] = (day, views)
    return {vid: views for vid, (_, views) in best.items()}


def next_reach(session: Session, channels: set[str], t: date) -> dict[str, Reach]:
    """Per channel with at least one long-form upload in the window. A channel that did
    not upload is absent from the mapping, never scored (data rule 7)."""
    uploads = _uploads(session, channels, t)
    readings = _readings(session, {v: p for vids in uploads.values() for v, p in vids.items()})
    out = {}
    for channel, vids in uploads.items():
        read = [math.log1p(readings[v]) for v in vids if v in readings]
        out[channel] = Reach(sum(read) / len(read) if read else None, len(vids), len(read))
    return out


# --- the verdict --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hypothesis:
    rho: float | None
    p: float | None
    lift: float | None


@dataclass(frozen=True, slots=True)
class Findings:
    interim: bool
    n_channels: int
    clusters_at_floor: int
    t0: Hypothesis
    h1: Hypothesis
    h2: Hypothesis


def _judge(h: Hypothesis, *, floor: float | None) -> tuple[bool, str]:
    if h.rho is None or h.p is None or (floor is not None and h.lift is None):
        return False, "could not be computed"
    if h.rho <= 0:
        return False, f"rho {h.rho:+.3f} is not positive"
    if h.p >= ALPHA:
        return False, f"p {h.p:.4f} is not below {ALPHA}"
    if floor is not None and h.lift < floor:
        return False, f"top-decile lift {h.lift:.3f} is below {floor}"
    tail = f", lift {h.lift:.3f}" if floor is not None else ""
    return True, f"rho {h.rho:+.3f}, p {h.p:.4f}{tail}"


def verdict(f: Findings) -> dict[str, tuple[str, str]]:
    """Interim, then power, then the instrument, then H1, then H2 only if H1 passed.

    Fixed-sequence gatekeeping holds the chance of any false PASS at ALPHA without
    splitting it. The order is part of the registration.
    """
    if f.interim:
        note = "a registered interim read; the verdict is 2026-10-02"
        return {"H1": ("INTERIM — not a verdict", note), "H2": ("INTERIM — not a verdict", note)}
    if f.n_channels < MIN_CHANNELS or f.clusters_at_floor < MIN_CLUSTERS:
        why = (
            f"{f.n_channels} channels with an outcome (floor {MIN_CHANNELS}); "
            f"{f.clusters_at_floor} clusters at {CLUSTER_FLOOR}+ (floor {MIN_CLUSTERS})"
        )
        return {
            "H1": ("INCONCLUSIVE — UNDERPOWERED", why),
            "H2": ("NOT TESTED", "no verdict on H1"),
        }
    ok, why = _judge(f.t0, floor=None)
    if not ok:
        instrument = f"the outcome does not track a channel's own level: {why}"
        return {
            "H1": ("INCONCLUSIVE — INSTRUMENT", instrument),
            "H2": ("NOT TESTED", "instrument failed"),
        }
    ok1, why1 = _judge(f.h1, floor=LIFT_FLOOR)
    if not ok1:
        return {"H1": ("FAIL", why1), "H2": ("NOT TESTED", "the gate is closed: H1 did not pass")}
    ok2, why2 = _judge(f.h2, floor=LIFT_FLOOR)
    return {"H1": ("PASS", why1), "H2": ("PASS" if ok2 else "FAIL", why2)}


_STEPS = {
    "T0": (lambda r: r.ln_median, ()),
    "H1": (lambda r: math.log(r.views_per_sub), CONTROLS),
    "H2": (lambda r: r.breakout_magnitude, CONTROLS),
}


def assemble(frozen: list[FrozenRow], reach: dict[tuple[str, str], Reach]):
    """`step -> [(date, rows)]` after the registered drops, plus the power counts."""
    with_outcome = [
        r for r in frozen if (o := reach.get((r.t, r.channel_id))) and o.value is not None
    ]
    per_cluster = Counter((r.t, r.cluster_id) for r in with_outcome)
    kept = [r for r in with_outcome if per_cluster[(r.t, r.cluster_id)] >= CLUSTER_MIN_OUTCOMES]
    dates = sorted({r.t for r in kept})
    steps: dict[str, list[tuple[str, list[Row]]]] = {}
    for name, (predictor, controls) in _STEPS.items():
        steps[name] = [
            (
                t,
                [
                    (
                        r.channel_id,
                        r.cluster_id,
                        predictor(r),
                        reach[(t, r.channel_id)].value,
                        tuple(float(getattr(r, c)) for c in controls),
                    )
                    for r in kept
                    if r.t == t
                ],
            )
            for t in dates
        ]
    at_floor = len({c for (_, c), n in per_cluster.items() if n >= CLUSTER_FLOOR})
    return steps, len({r.channel_id for r in kept}), at_floor, per_cluster


def findings(frozen, reach, *, interim: bool, draws: int = DRAWS) -> tuple[Findings, dict]:
    steps, n_channels, at_floor, per_cluster = assemble(frozen, reach)
    hyp = {}
    for name, per_date in steps.items():
        rho, p, _ = (
            evaluate_stratified(per_date, seed=SEED, draws=draws) if per_date else (None, None, [])
        )
        lift = top_decile_lift(per_date) if name != "T0" and per_date else None
        hyp[name] = Hypothesis(rho, p, lift)
    channel_dates = sum(len(rs) for _, rs in steps["T0"])
    f = Findings(interim, n_channels, at_floor, hyp["T0"], hyp["H1"], hyp["H2"])
    return f, {"per_cluster": per_cluster, "channel_dates": channel_dates}


def _num(x: float | None, fmt: str) -> str:
    return "n/a" if x is None else format(x, fmt)


def _preamble(f: Findings, extra: dict, key_sha: str) -> list[str]:
    n = extra["channel_dates"]
    crit = 1.96 / math.sqrt(n - 3) if n > 3 else None
    return [
        "# Channel reach — " + ("INTERIM read, not a verdict" if f.interim else "the verdict"),
        "",
        f"Registered in advance: `{REGISTRATION}`. Frozen cohort sha256 `{key_sha}`, "
        "verified against the registered constant before any outcome was read.",
        "",
        "## Read these before any number",
        "",
        "1. **No niche claim.** Every comparison is within a cluster; nothing here says any niche is open.",
        "2. **Frozen membership.** Cluster assignment is as of the registration, not as a nightly at t stored it.",
        "3. **Censoring.** Readings before the ADR-0059 watchlist were missing non-randomly by upload rate.",
        "4. **H2 was registered as low-power**: 5% of simulated seeds passed with a strong breakout "
        "effect, so an H2 FAIL is weak evidence of absence.",
        "",
        "## Power, before the result",
        "",
        f"- Distinct channels with an outcome: **{f.n_channels}** (floor {MIN_CHANNELS})",
        f"- Clusters reaching {CLUSTER_FLOOR} outcomes at some date: **{f.clusters_at_floor}** (floor {MIN_CLUSTERS})",
        f"- Channel-dates: **{n}**; two-sided critical rho ≈ **{_num(crit, '.3f')}**",
        "",
    ]


def render(f: Findings, extra: dict, *, key_sha: str) -> str:
    v = verdict(f)
    lines = [
        *_preamble(f, extra, key_sha),
        "## Verdict",
        "",
        f"> **H1: {v['H1'][0]}** — {v['H1'][1]}",
        ">",
        f"> **H2: {v['H2'][0]}** — {v['H2'][1]}",
        "",
        "## Every step",
        "",
        "| step | rho | p | top-decile lift |",
        "|---|---|---|---|",
    ]
    for name, h in (("T0 instrument", f.t0), ("H1 views_per_sub", f.h1), ("H2 breakout", f.h2)):
        lines.append(
            f"| {name} | {_num(h.rho, '+.3f')} | {_num(h.p, '.4f')} | {_num(h.lift, '.3f')} |"
        )
    lines += ["", "## Outcomes per cluster and date (descriptive only)", ""]
    lines += ["| date | cluster | outcomes | in the test |", "|---|---|---|---|"]
    for (t, c), k in sorted(extra["per_cluster"].items()):
        lines.append(
            f"| {t} | {c} | {k} | {'yes' if k >= CLUSTER_MIN_OUTCOMES else 'no, under 10'} |"
        )
    return "\n".join(lines) + "\n"


def read(session: Session, which: str, *, key_path: Path = KEY_PATH, draws: int = DRAWS) -> str:
    """Render a scheduled read. Refuses an unregistered test, an altered draw key, and a
    read whose date has not been collected — judged from the data, not the clock."""
    read_date, dates = READS[which]
    if REGISTERED_KEY_SHA256 is None:
        raise NotRegistered("REGISTERED_KEY_SHA256 is unset; there is no registration to read")
    rows, sha = load_key(key_path)
    if sha != REGISTERED_KEY_SHA256:
        raise KeyMismatch(f"{key_path} is {sha}, the registration recorded {REGISTERED_KEY_SHA256}")
    latest = session.scalar(sa.select(sa.func.max(VideoSnapshot.observed_date)))
    if latest is None or latest < read_date:
        raise TooEarly(f"the {which} read needs {read_date} collected; latest is {latest}")
    wanted = {d.isoformat() for d in dates}
    rows = [r for r in rows if r.t in wanted]
    reach: dict[tuple[str, str], Reach] = {}
    with inputs.pinned_ballast(False):
        for d in dates:
            channels = {r.channel_id for r in rows if r.t == d.isoformat()}
            reach.update(
                {(d.isoformat(), c): o for c, o in next_reach(session, channels, d).items()}
            )
    f, extra = findings(rows, reach, interim=which == "interim", draws=draws)
    return render(f, extra, key_sha=sha)
