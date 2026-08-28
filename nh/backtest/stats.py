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


def stride(spacing_days: int, horizon_days: int) -> int:
    """How many consecutive decision dates one outcome window spans."""
    if spacing_days <= 0:
        return 1
    return max(1, math.ceil(horizon_days / spacing_days))


def independent_windows(dates: int, spacing_days: int, horizon_days: int) -> int:
    """How many non-overlapping outcome windows the dates actually cover.

    Consecutive weekly decision dates share 179 of their 180 outcome days, so their
    correlations are near-copies of each other. Quoting the raw date count as the
    sample size would shrink every interval by roughly the square root of the overlap
    factor and manufacture significance out of autocorrelation.
    """
    if dates <= 0 or spacing_days <= 0:
        return 0
    return 1 + (dates - 1) // stride(spacing_days, horizon_days)


def thin(
    per_date: list[tuple[str, list[float], list[float]]],
    *,
    spacing_days: int,
    horizon_days: int,
) -> list[tuple[str, list[float], list[float]]]:
    """Keep only dates whose outcome windows do not overlap.

    Annotating the result with a window count is not enough. The permutation null and
    the bootstrap both treat each date as a draw, so run over 195 weekly dates they
    would return an interval about five times too narrow and a p-value to match — the
    gate could then pass on autocorrelation alone. Measured on the test suite: four
    copies of a single date with rho=0.486 produce p=0.034, which is a significant
    result derived from one observation.

    So the estimate is reported over every date, and the *inference* is computed over
    these. Fewer observations and an honest interval, rather than more and a false one.
    """
    return per_date[:: stride(spacing_days, horizon_days)]


def _aggregate_rho(per_date: list[float | None]) -> float | None:
    usable = [rho for rho in per_date if rho is not None]
    return mean(usable) if usable else None


def evaluate(
    per_date: list[tuple[str, list[float], list[float]]],
    *,
    spacing_days: int = 7,
    horizon_days: int = 180,
    seed: int = SEED,
    draws: int = DRAWS,
) -> tuple[Aggregate, list[DateResult]]:
    """The primary result: correlate per date, aggregate, then test against the null.

    `per_date` is `(date, scores, outcomes)` with the two lists aligned by niche.

    The null shuffles the outcome labels **within each date**, which preserves the
    temporal structure and each date's score distribution and breaks only the
    score↔outcome link. Shuffling across dates would also destroy the fact that some
    dates are simply better for growth than others, and would test a weaker null than
    the one the gate claims to reject.

    `rho` is the estimate over every date supplied. The p-value and the interval are
    computed over `thin()`ned dates only, because overlapping outcome windows are not
    independent draws — see that function for the measurement.
    """
    results = [
        DateResult(date=day, rho=spearman(scores, outcomes), n=len(scores))
        for day, scores, outcomes in per_date
    ]
    observed = _aggregate_rho([r.rho for r in results])
    counts = [r.n for r in results if r.rho is not None]
    aggregate_shell = Aggregate(
        rho=observed,
        p_value=None,
        ci_low=None,
        ci_high=None,
        dates=len(results),
        independent_windows=independent_windows(len(results), spacing_days, horizon_days),
        n_median=sorted(counts)[len(counts) // 2] if counts else 0,
        draws=draws,
    )
    if observed is None:
        return aggregate_shell, results

    rng = random.Random(seed)
    independent = thin(per_date, spacing_days=spacing_days, horizon_days=horizon_days)
    null: list[float] = []
    for _ in range(draws):
        shuffled = []
        for _day, scores, outcomes in independent:
            permuted = list(outcomes)
            rng.shuffle(permuted)
            shuffled.append(spearman(scores, permuted))
        value = _aggregate_rho(shuffled)
        if value is not None:
            null.append(value)

    # Two-sided, and +1 in both parts: a p-value of exactly 0 claims more resolution
    # than `draws` samples can support. With 10,000 draws the floor is 1e-4.
    extreme = sum(1 for value in null if abs(value) >= abs(observed))
    p_value = (extreme + 1) / (len(null) + 1) if null else None

    low, high = _bootstrap_ci(independent, rng, draws=draws)
    return (
        Aggregate(
            rho=observed,
            p_value=p_value,
            ci_low=low,
            ci_high=high,
            dates=aggregate_shell.dates,
            independent_windows=aggregate_shell.independent_windows,
            n_median=aggregate_shell.n_median,
            draws=draws,
        ),
        results,
    )


def _bootstrap_ci(
    per_date: list[tuple[str, list[float], list[float]]],
    rng: random.Random,
    *,
    draws: int,
    level: float = 0.95,
) -> tuple[float | None, float | None]:
    """Percentile interval, resampling **niches**, not dates.

    Resampling dates would treat 195 overlapping windows as 195 independent draws and
    return an interval about five times too narrow. Resampling the niches inside each
    date measures the thing that actually varies: which niches happened to be in the
    portfolio.
    """
    if not per_date:
        return None, None
    values: list[float] = []
    for _ in range(draws):
        shuffled = []
        for _day, scores, outcomes in per_date:
            n = len(scores)
            if n < 3:
                continue
            picks = [rng.randrange(n) for _ in range(n)]
            shuffled.append(spearman([scores[i] for i in picks], [outcomes[i] for i in picks]))
        value = _aggregate_rho(shuffled)
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
