"""Render the backtest's findings as `reports/backtest_<date>.md`.

The ordering here is the substance, not formatting. Three caveats come before any
number, because each of them changes what the number means and a reader who meets
the correlation first has already formed a belief the caveats then have to undo.

The renderer is also where the pre-registration is enforced mechanically: the primary
result is labelled primary, everything else is labelled secondary, and a secondary
that beats the primary is still labelled secondary. That is the only defence against
the garden of forking paths, and leaving it to the writer's discipline is how it gets
lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from nh.backtest.stats import Aggregate, DateResult

PREREGISTRATION = "reports/backtest_preregistration_2026-08-27.md"

CAVEATS = (
    (
        "Survivorship, and it is the defining limitation rather than a caveat",
        "Every channel in YouNiverse had crossed 10,000 subscribers by the "
        "2019-10-27 crawl. A channel that was small in 2016 and stayed small was "
        "never collected. This measures **relative growth among successes**, never "
        "emergence, and no sampling recovers the missing negative class.",
    ),
    (
        "The niches were defined by an unvalidated relevance rule",
        "Held-out precision 0.781 at threshold 0.55, recall 0.694, labelled by the "
        "same system that wrote the lexicon, kappa 0.943 against a second model. "
        "The human spot-check is deferred to before Slice 7. Every supply number "
        "below inherits that error rate.",
    ),
    (
        "The backtested `gap` is not the `gap` the live pipeline computes",
        "`supply.median_views` is not replayable — YouNiverse holds per-video view "
        "counts only as of its 2019 crawl, after every decision date here — so "
        "`supply.views_per_new_video` stands in for it. The live default is "
        "unchanged. A result here transfers to production only as far as that "
        "substitution holds.",
    ),
)


@dataclass(slots=True)
class Variant:
    """One cell of the secondary grid."""

    label: str
    stratum: str
    supply_from: str
    threshold: float
    horizon_days: int
    aggregate: Aggregate


@dataclass(slots=True)
class Findings:
    day: date
    primary: Variant
    niches_selected: int
    niches_committed: int
    dropped: list[tuple[str, int]] = field(default_factory=list)
    secondary: list[Variant] = field(default_factory=list)
    per_date: list[DateResult] = field(default_factory=list)
    #: Rank correlation of niche size with growth, and the primary controlling for
    #: it. A score that ranks by size is not a finding.
    size_rho: float | None = None
    size_controlled_rho: float | None = None
    #: Permutation p-value for the size-controlled correlation, under the same
    #: global label-permutation null as the primary. Amended in 2026-08-28 before
    #: any result existed: survival used to be a bare sign check, and +0.03 is not
    #: survival. See the pre-registration's amendment log.
    size_controlled_p: float | None = None
    failure_analysis: str = ""


def _num(value: float | None, digits: int = 3) -> str:
    """`n/a`, never `0.000`, for a quantity that was not computed."""
    return "n/a" if value is None else f"{value:.{digits}f}"


def verdict(findings: Findings) -> tuple[str, str]:
    """The Gate E verdict, applied from the pre-registered rule.

    Three outcomes, not two. **Underpowered is not the same as null**: with too few
    niches the smallest detectable correlation exceeds any effect worth having, and
    reporting that as "no relationship" would retire the thesis on the strength of a
    test that could not have detected one.
    """
    primary = findings.primary.aggregate
    detectable = primary.detectable_rho
    if primary.rho is None or primary.p_value is None:
        return "INCONCLUSIVE", "the primary correlation could not be computed"
    if findings.niches_selected < 20:
        return (
            "INCONCLUSIVE — UNDERPOWERED",
            f"{findings.niches_selected} niches survived selection; the smallest "
            f"detectable rho at this N is {_num(detectable)}. A null here is not "
            "evidence of no effect.",
        )
    if primary.p_value >= 0.05:
        return "FAIL", f"p = {_num(primary.p_value, 4)}, indistinguishable from the null"
    if primary.rho <= 0:
        return "FAIL", f"the correlation is {_num(primary.rho)} — the ranking is not positive"
    if findings.size_controlled_rho is None or findings.size_controlled_rho <= 0:
        return (
            "FAIL",
            "the correlation does not survive controlling for niche size, so the "
            "scorecard ranks niches by how big they are",
        )
    if findings.size_controlled_p is None or findings.size_controlled_p >= 0.05:
        return (
            "FAIL",
            f"the size-controlled correlation is {_num(findings.size_controlled_rho)} "
            f"but p = {_num(findings.size_controlled_p, 4)}: it is a positive residual, "
            "not a surviving one",
        )
    return (
        "PASS",
        f"rho = {_num(primary.rho)}, p = {_num(primary.p_value, 4)}, and "
        f"{_num(findings.size_controlled_rho)} (p = {_num(findings.size_controlled_p, 4)}) "
        "after controlling for size",
    )


def _variant_row(variant: Variant, *, primary: bool) -> str:
    a = variant.aggregate
    return (
        f"| {'**primary**' if primary else 'secondary'} | {variant.label} | "
        f"{variant.stratum} | {variant.supply_from} | {variant.threshold} | "
        f"{variant.horizon_days}d | {_num(a.rho)} | {_num(a.p_value, 4)} | "
        f"{_num(a.ci_low)} to {_num(a.ci_high)} |"
    )


def render(findings: Findings) -> str:
    label, reason = verdict(findings)
    primary = findings.primary.aggregate
    lines = [
        f"# Backtest — Gate E, {findings.day.isoformat()}",
        "",
        f"Primary result and verdict rule fixed in advance: `{PREREGISTRATION}`.",
        "",
        "## Read these three things before any number",
        "",
    ]
    for i, (heading, body) in enumerate(CAVEATS, start=1):
        lines += [f"{i}. **{heading}.** {body}", ""]

    lines += [
        "## Power, before the result",
        "",
        f"- Niches committed before the data landed: **{findings.niches_committed}**",
        f"- Niches surviving selection: **{findings.niches_selected}**",
        f"- Smallest rho detectable at this N: **{_num(primary.detectable_rho)}**",
        f"- Decision dates: {primary.dates} "
        f"(**{primary.independent_windows} quasi-independent windows** — the date "
        "count is a diagnostic, never a sample size)",
        f"- Permutation draws: {primary.draws}, niche labels permuted globally",
        "",
    ]
    if findings.dropped:
        lines += [
            "Dropped by the selection floors, reported rather than replaced "
            "(reviving or substituting one would be selection on the outcome):",
            "",
        ]
        lines += [f"- `{slug}` — {n} member channels" for slug, n in findings.dropped]
        lines += [""]

    lines += [
        "## The primary result",
        "",
        f"> **{label}** — {reason}",
        "",
        f"Spearman rank correlation between `{findings.primary.label}` and "
        f"`outcome.growth_{findings.primary.horizon_days}d`, over the validation "
        "window:",
        "",
        f"- rho = **{_num(primary.rho)}**",
        f"- permutation p = **{_num(primary.p_value, 4)}**",
        f"- 95% interval: {_num(primary.ci_low)} to {_num(primary.ci_high)}",
        "",
        "### The size baseline",
        "",
        "A score that ranks niches by how big they are needs no pipeline to "
        "reproduce, so the primary is reported against it rather than alone:",
        "",
        f"- niche size vs. growth: rho = **{_num(findings.size_rho)}**",
        f"- the primary, controlling for size: rho = **{_num(findings.size_controlled_rho)}**",
        "",
        "## Secondary results",
        "",
        "Every variant below is **secondary**, including any that outscores the "
        "primary. The pre-registration fixed the primary before these existed; a "
        "secondary that wins is a hypothesis for a later slice with a fresh "
        "validation window, not this gate's verdict.",
        "",
        "| role | score | stratum | supply | threshold | horizon | rho | p | 95% CI |",
        "|---|---|---|---|---|---|---|---|---|",
        _variant_row(findings.primary, primary=True),
    ]
    lines += [_variant_row(v, primary=False) for v in findings.secondary]

    lines += [
        "",
        "## Where the ranking goes wrong",
        "",
        findings.failure_analysis or "_Not yet written._",
        "",
        "## Per-date detail",
        "",
        "| date | rho | niches |",
        "|---|---|---|",
    ]
    lines += [f"| {r.date} | {_num(r.rho)} | {r.n} |" for r in findings.per_date]
    lines += [""]
    return "\n".join(lines)
