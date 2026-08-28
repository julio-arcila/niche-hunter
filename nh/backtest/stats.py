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
