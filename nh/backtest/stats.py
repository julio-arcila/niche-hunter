"""The statistics Gate E is decided on. Pure functions, no database, no numpy.

Every routine here takes lists and returns numbers, so each one is testable against
a hand-computed example — which matters more than usual, because these are the only
functions in the project whose output is the verdict rather than an input to one.

Deterministic by construction: the permutation and bootstrap take an explicit seed
and use `random.Random(seed)`, never the global RNG. A p-value that changes between
runs cannot be cited in a report.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import mean

#: Independent draws for the permutation null and the bootstrap. 10,000 puts the
#: Monte-Carlo error on a p-value near 0.05 at about 0.002 — small against the
#: 0.05 threshold, and cheap on the ~30 pairs a single date holds.
DRAWS = 10_000
SEED = 20260827


def ranks(values: list[float]) -> list[float]:
    """Ranks with ties averaged.

    Tie-averaging, not ordinal position: three niches with an identical `gap` — which
    Slice 3 measured happening, 3 of 5 niches gapped at exactly 0 — must not be given
    an arbitrary order that the correlation then reads as signal.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            result[order[k]] = shared
        i = j + 1
    return result


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """None, not 0.0, when a correlation is undefined.

    It is undefined when either series is constant — which happens whenever every
    niche on a date shares a score — and 0.0 there would read as "measured, no
    relationship" rather than "not measurable".
    """
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denominator = math.sqrt(sum(d * d for d in dx) * sum(d * d for d in dy))
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / denominator


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation. The product ranks niches, so the test ranks them too."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    return pearson(ranks(xs), ranks(ys))


def partial_spearman(xs: list[float], ys: list[float], zs: list[float]) -> float | None:
    """Spearman between x and y with z held constant.

    The size control, and the reason it is in the pre-registration: a correlation
    that vanishes once niche size is partialled out means the scorecard ranks niches
    by how big they are, which needs no pipeline to reproduce.
    """
    rxy, rxz, ryz = spearman(xs, ys), spearman(xs, zs), spearman(ys, zs)
    if rxy is None or rxz is None or ryz is None:
        return None
    denominator = math.sqrt((1 - rxz**2) * (1 - ryz**2))
    if denominator == 0:
        return None
    return (rxy - rxz * ryz) / denominator


@dataclass(slots=True, frozen=True)
class DateResult:
    """One decision date's correlation, and how many niches it rests on."""

    date: str
    rho: float | None
    n: int


@dataclass(slots=True, frozen=True)
class Aggregate:
    rho: float | None
    p_value: float | None
    ci_low: float | None
    ci_high: float | None
    dates: int
    #: Overlapping 180-day windows are not independent observations. This is the
    #: count the report quotes, and it is what the p-value and the interval were
    #: actually computed on — not merely a caveat printed beside them.
    independent_windows: int
    n_median: int
    draws: int = DRAWS

    @property
    def detectable_rho(self) -> float | None:
        """The smallest correlation two standard errors from zero at this N.

        Reported next to the result so a null at low N reads as underpowered rather
        than as evidence of no effect — the distinction the pre-registration insists
        on, because only one of them licenses abandoning the thesis.
        """
        return 2 / math.sqrt(self.n_median - 1) if self.n_median > 1 else None


def independent_windows(dates: int, spacing_days: int, horizon_days: int) -> int:
    """How many non-overlapping outcome windows the dates actually cover.

    Reported as a diagnostic, not used as a sample size. Consecutive weekly decision
    dates share 179 of their 180 outcome days, so their correlations are near-copies;
    quoting the raw date count would misdescribe the evidence. The *inference* handles
    the same problem structurally — see `evaluate`.
    """
    if dates <= 0 or spacing_days <= 0:
        return 0
    stride = max(1, math.ceil(horizon_days / spacing_days))
    return 1 + (dates - 1) // stride


def _aggregate_rho(per_date: list[float | None]) -> float | None:
    usable = [rho for rho in per_date if rho is not None]
    return mean(usable) if usable else None


def evaluate(
    per_date: list[tuple[str, list[str], list[float], list[float]]],
    *,
    spacing_days: int = 7,
    horizon_days: int = 180,
    seed: int = SEED,
    draws: int = DRAWS,
) -> tuple[Aggregate, list[DateResult]]:
    """The primary result: correlate per date, aggregate, then test against the null.

    `per_date` is `(date, cluster_ids, scores, outcomes)`, the three lists aligned.
    The cluster ids are not decoration — they are what makes the null correct.

    **The null permutes niche labels globally: one permutation per replication,
    applied to every date.** This preserves each niche's score trajectory and each
    niche's outcome trajectory and mismatches only which trajectory goes with which,
    so the serial structure of both series survives into the null.

    Permuting independently *within* each date does not, and the difference is the
    whole inference. A within-date null implicitly asserts that the dates are
    independent replicates, so the mean of D per-date correlations gets a standard
    error shrunk by sqrt(D) — with ~195 weekly dates over 180-day outcome windows
    that is roughly a fivefold overstatement, and the gate could pass on
    autocorrelation alone. Measured on the test suite: four weekly copies of a single
    date with rho=0.486 come back at p=0.034 under a within-date null and stay
    non-significant under this one.

    An earlier draft thinned the dates to non-overlapping windows instead. That is a
    partial fix for the same problem — it throws away 96% of the data to buy honesty
    — and a global permutation gets the honesty without the discard.
    """
    results = [
        DateResult(date=day, rho=spearman(scores, outcomes), n=len(scores))
        for day, _clusters, scores, outcomes in per_date
    ]
    observed = _aggregate_rho([r.rho for r in results])
    counts = [r.n for r in results if r.rho is not None]
    n_median = sorted(counts)[len(counts) // 2] if counts else 0
    windows = independent_windows(len(results), spacing_days, horizon_days)
    if observed is None:
        return (
            Aggregate(None, None, None, None, len(results), windows, n_median, draws),
            results,
        )

    rng = random.Random(seed)
    labels = sorted({cluster for _d, clusters, _s, _o in per_date for cluster in clusters})
    null: list[float] = []
    for _ in range(draws):
        shuffled = list(labels)
        rng.shuffle(shuffled)
        mapping = dict(zip(labels, shuffled, strict=True))
        value = _aggregate_rho(
            [
                _relabelled(clusters, scores, outcomes, mapping)
                for _d, clusters, scores, outcomes in per_date
            ]
        )
        if value is not None:
            null.append(value)

    # Two-sided, and +1 in both parts: a p-value of exactly 0 claims more resolution
    # than `draws` samples can support. With 10,000 draws the floor is 1e-4.
    extreme = sum(1 for value in null if abs(value) >= abs(observed))
    p_value = (extreme + 1) / (len(null) + 1) if null else None

    low, high = _bootstrap_ci(per_date, labels, rng, draws=draws)
    return (
        Aggregate(observed, p_value, low, high, len(results), windows, n_median, draws),
        results,
    )


def _relabelled(
    clusters: list[str],
    scores: list[float],
    outcomes: list[float],
    mapping: dict[str, str],
) -> float | None:
    """One date's correlation after the global relabelling.

    A niche whose partner under `mapping` is absent from this date is dropped rather
    than matched to something else, so the null never invents a pair the data could
    not produce.
    """
    by_cluster = dict(zip(clusters, outcomes, strict=True))
    xs, ys = [], []
    for cluster, x in zip(clusters, scores, strict=True):
        partner = by_cluster.get(mapping[cluster])
        if partner is not None:
            xs.append(x)
            ys.append(partner)
    return spearman(xs, ys)


def evaluate_partial(
    per_date: list[tuple[str, list[str], list[float], list[float], list[float]]],
    *,
    spacing_days: int = 7,
    horizon_days: int = 180,
    seed: int = SEED,
    draws: int = DRAWS,
) -> tuple[Aggregate, list[DateResult]]:
    """The size control, tested rather than eyeballed.

    `per_date` is `(date, cluster_ids, scores, outcomes, controls)`. Computes the
    per-date partial Spearman of score against outcome with `controls` held constant,
    aggregates across dates exactly as `evaluate` does, and tests it against the same
    global label-permutation null.

    Why a test and not a sign check: the pre-registration requires the primary to
    "survive controlling for niche size" and defines failure as the correlation
    *disappearing* under the control. A partial rho of +0.03 has disappeared by any
    ordinary reading, and a bare `> 0` would pass it. Reading a residual sign as
    survival is how a scorecard that ranks niches by how big they are gets called a
    finding — which the roadmap names as the way this project fails while appearing
    to succeed.

    The null relabels **outcomes only**, keeping each niche's score and its size
    together. Size is a property of the niche whose score is on trial, so it belongs
    on the score side of the permutation; breaking that pairing would test a
    different and weaker null.
    """
    results = [
        DateResult(date=day, rho=partial_spearman(scores, outcomes, controls), n=len(scores))
        for day, _clusters, scores, outcomes, controls in per_date
    ]
    observed = _aggregate_rho([r.rho for r in results])
    counts = [r.n for r in results if r.rho is not None]
    n_median = sorted(counts)[len(counts) // 2] if counts else 0
    windows = independent_windows(len(results), spacing_days, horizon_days)
    if observed is None:
        return (
            Aggregate(None, None, None, None, len(results), windows, n_median, draws),
            results,
        )

    rng = random.Random(seed)
    labels = sorted({c for _d, clusters, _s, _o, _z in per_date for c in clusters})
    null: list[float] = []
    for _ in range(draws):
        shuffled = list(labels)
        rng.shuffle(shuffled)
        mapping = dict(zip(labels, shuffled, strict=True))
        per_draw = []
        for _day, clusters, scores, outcomes, controls in per_date:
            by_cluster = dict(zip(clusters, outcomes, strict=True))
            xs, ys, zs = [], [], []
            for cluster, x, z in zip(clusters, scores, controls, strict=True):
                partner = by_cluster.get(mapping[cluster])
                if partner is not None:
                    xs.append(x)
                    ys.append(partner)
                    zs.append(z)
            per_draw.append(partial_spearman(xs, ys, zs))
        value = _aggregate_rho(per_draw)
        if value is not None:
            null.append(value)

    extreme = sum(1 for value in null if abs(value) >= abs(observed))
    p_value = (extreme + 1) / (len(null) + 1) if null else None
    return (
        Aggregate(observed, p_value, None, None, len(results), windows, n_median, draws),
        results,
    )


def _bootstrap_ci(
    per_date: list[tuple[str, list[str], list[float], list[float]]],
    labels: list[str],
    rng: random.Random,
    *,
    draws: int,
    level: float = 0.95,
) -> tuple[float | None, float | None]:
    """Percentile interval, resampling **niches** — the same niches at every date.

    Resampling dates would treat overlapping windows as independent draws and return
    an interval several times too narrow. Resampling niches independently per date
    would break the panel the same way the within-date null does. Resampling the
    niche *set* once per replication measures what actually varies: which niches
    happened to be in the portfolio.
    """
    if not per_date or not labels:
        return None, None
    values: list[float] = []
    for _ in range(draws):
        picks = [labels[rng.randrange(len(labels))] for _ in range(len(labels))]
        per_date_rho = []
        for _day, clusters, scores, outcomes in per_date:
            index = {cluster: i for i, cluster in enumerate(clusters)}
            rows = [index[c] for c in picks if c in index]
            if len(rows) < 3:
                continue
            per_date_rho.append(spearman([scores[i] for i in rows], [outcomes[i] for i in rows]))
        value = _aggregate_rho(per_date_rho)
        if value is not None:
            values.append(value)
    if not values:
        return None, None
    values.sort()
    tail = (1 - level) / 2
    return (
        values[max(0, int(tail * len(values)) - 1)],
        values[min(len(values) - 1, int((1 - tail) * len(values)))],
    )


# --- channel grain: stratified partial rank correlation (ADR-0060) -----------------

#: (unit, block, predictor, outcome, controls) — one channel at one decision date.
Row = tuple[str, str, float, float, tuple[float, ...]]
MIN_STRATIFIED_ROWS = 5


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gauss-Jordan with partial pivoting; None when the system is singular."""
    n = len(b)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col and m[r][col]:
                factor = m[r][col] / m[col][col]
                for k in range(col, n + 1):
                    m[r][k] -= factor * m[col][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def residuals(y: list[float], columns: list[list[float]]) -> list[float] | None:
    """OLS residuals of `y` on an intercept and `columns`; None when singular."""
    x = [[1.0, *(col[i] for col in columns)] for i in range(len(y))]
    k = len(x[0])
    xtx = [[sum(r[i] * r[j] for r in x) for j in range(k)] for i in range(k)]
    xty = [sum(r[i] * v for r, v in zip(x, y, strict=True)) for i in range(k)]
    beta = _solve(xtx, xty)
    if beta is None:
        return None
    return [v - sum(b * c for b, c in zip(beta, r, strict=True)) for r, v in zip(x, y, strict=True)]


def block_ranks(values: list[float], blocks: list[str]) -> list[float]:
    """Average-tie ranks within each block, divided by (n_block + 1).

    Every block then has mean 0.5, so clusters of 16 and 45 channels share one scale and
    pool, and a predictor that only tracks which cluster a channel is in cannot correlate.
    """
    out = [0.0] * len(values)
    for block in set(blocks):
        idx = [i for i, b in enumerate(blocks) if b == block]
        for i, r in zip(idx, ranks([values[i] for i in idx]), strict=True):
            out[i] = r / (len(idx) + 1)
    return out


def stratified_partial_spearman(
    x: list[float], y: list[float], controls: list[list[float]], blocks: list[str]
) -> float | None:
    """Rank within block, residualise both ranks on the control ranks, correlate.

    With no controls this is the pooled within-block Spearman. A control that shares
    estimation noise with the predictor manufactures a correlation here — the registered
    channel-reach design was changed for exactly that reason (ADR-0060).
    """
    if len(x) < MIN_STRATIFIED_ROWS:
        return None
    rc = [block_ranks(c, blocks) for c in controls]
    ex = residuals(block_ranks(x, blocks), rc)
    ey = residuals(block_ranks(y, blocks), rc)
    return None if ex is None or ey is None else pearson(ex, ey)


def _stratified_rho(rows: list[Row], outcomes: list[float]) -> float | None:
    controls = [list(c) for c in zip(*(r[4] for r in rows), strict=True)]
    return stratified_partial_spearman(
        [r[2] for r in rows], outcomes, controls, [r[1] for r in rows]
    )


def evaluate_stratified(
    per_date: list[tuple[str, list[Row]]], *, seed: int = SEED, draws: int = DRAWS
) -> tuple[float | None, float | None, list[float | None]]:
    """Mean of per-date stratified rhos, and its within-block permutation p-value.

    One permutation of unit labels per replication, within each block, applied to every
    date — Gate E's global scheme, blocked. Outcomes move; predictor and controls stay
    with their unit. A unit whose partner is absent at a date is dropped, never matched
    to something else, as `_relabelled` does.
    """
    by_date = [_stratified_rho(rows, [r[3] for r in rows]) for _, rows in per_date]
    usable = [v for v in by_date if v is not None]
    if not usable:
        return None, None, by_date
    observed = mean(usable)
    labels: dict[str, set[str]] = {}
    for _, rows in per_date:
        for unit, block, *_ in rows:
            labels.setdefault(block, set()).add(unit)
    ordered = {b: sorted(u) for b, u in sorted(labels.items())}
    rng = random.Random(seed)
    extreme = completed = 0
    for _ in range(draws):
        mapping: dict[str, str] = {}
        for units in ordered.values():
            shuffled = units[:]
            rng.shuffle(shuffled)
            mapping.update(zip(units, shuffled, strict=True))
        values = []
        for _, rows in per_date:
            y_of = {r[0]: r[3] for r in rows}
            kept = [(r, y_of[mapping[r[0]]]) for r in rows if mapping[r[0]] in y_of]
            if len(kept) >= MIN_STRATIFIED_ROWS:
                value = _stratified_rho([k[0] for k in kept], [k[1] for k in kept])
                if value is not None:
                    values.append(value)
        if values:
            completed += 1
            extreme += abs(mean(values)) >= abs(observed)
    p_value = (extreme + 1) / (completed + 1) if completed else None
    return observed, p_value, by_date


def top_decile_lift(per_date: list[tuple[str, list[Row]]]) -> float | None:
    """exp(mean residual) of the outcome over the top within-(date, block) decile of the
    predictor. Residuals from OLS on the controls plus block and date fixed effects.

    What a reader of a ranked list gets from its top, in the outcome's own units — the
    registered effect floor, because at channel grain significance alone is cheap.
    """
    rows = [r for _, rs in per_date for r in rs]
    dates = [d for d, rs in per_date for _ in rs]
    if len(rows) < MIN_STRATIFIED_ROWS:
        return None
    controls = [list(c) for c in zip(*(r[4] for r in rows), strict=True)]
    blocks = sorted({r[1] for r in rows})
    effects = [[1.0 if r[1] == b else 0.0 for r in rows] for b in blocks[1:]]
    effects += [[1.0 if d == day else 0.0 for d in dates] for day in sorted(set(dates))[1:]]
    res = residuals([r[3] for r in rows], controls + effects)
    if res is None:
        return None
    groups: dict[tuple[str, str], list[int]] = {}
    for i, (r, d) in enumerate(zip(rows, dates, strict=True)):
        groups.setdefault((d, r[1]), []).append(i)
    picked: list[int] = []
    for idx in groups.values():
        top = max(1, math.ceil(0.1 * len(idx)))
        picked += sorted(idx, key=lambda i: (-rows[i][2], rows[i][0]))[:top]
    return math.exp(mean(res[i] for i in picked))
