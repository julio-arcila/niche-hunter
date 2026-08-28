"""Which way is this niche going? A demand-trajectory classifier.

**Pure by construction, and that is the anti-leakage guarantee.** `classify` takes
a mapping and a threshold set and returns a stage. It has no `Session`, no clock,
no queries — a function that cannot read anything cannot read a snapshot from after
the decision date. Slice 6 replays this at historical dates, and leakage there is
the failure mode that makes a backtest look excellent and mean nothing; auditing
one pure call site is a different job from auditing six feature modules.

**A demand-trajectory stage, not a lifecycle stage**, and the name is deliberate
(ADR-0023). A lifecycle classifier would read supply momentum too, and supply
momentum does not exist: `video_snapshots` holds one day. `demand_snapshots` holds
1,096. So this reads the axis that has history and says so, rather than implying a
completeness it does not have. That narrows what Slice 6 can conclude — and the
narrowing is the strongest sequencing argument available: if demand trajectory
alone predicts nothing, the thesis is dead regardless of supply, and that is
learnable today from data already on disk.

**Zero tuned constants.** Both cutoffs are 0, because zero *is* the definition of
growing and of a positive gap — not a number chosen because the output looked
right. docs/METRICS.md warns about that trap three separate times
(`winner_age_years`, the relevance thresholds, `geo_tier1_share`). Slice 6 tunes
these on one window and validates on another, which is what Slice 6 is for; until
then they are definitions rather than parameters.

There is no confidence floor either. A floor would be a fourth constant, and it
would hide a weak call behind `unknown` instead of reporting it — `stage_confidence`
carries that information without discarding the stage.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class Stage(StrEnum):
    """What the two axes say together."""

    EMERGING = "emerging"  # demand rising, more attention than incumbent content
    CONTESTED = "contested"  # demand rising, but supply already keeps up
    COOLING = "cooling"  # demand falling, though still under-served
    SATURATED = "saturated"  # demand falling and well served
    UNKNOWN = "unknown"  # an axis is missing; not a fifth kind of niche


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Frozen, versioned, and recorded on every row that used them.

    Versioned because Slice 6 will move these and every stored stage has to stay
    attributable to the cutoffs that produced it.
    """

    version: str = "2026-08-27.zero"
    momentum: float = 0.0
    gap: float = 0.0


DEFAULT = Thresholds()

#: The axes, named once. `momentum` is demand.wiki_yoy and NOT wiki_momentum_28d:
#: measured, three of four niches peak in September, so a late-August
#: month-over-month reading is the school calendar rather than a trend.
MOMENTUM = "momentum"
GAP = "gap"


def classify(
    vector: Mapping[str, float | None], thresholds: Thresholds = DEFAULT
) -> tuple[Stage, dict]:
    """`(stage, evidence)` from a demand-trajectory vector.

    `vector` needs `momentum` and `gap`; anything else is carried into the evidence
    untouched, so a caller can attach the values it wants traceable without this
    function growing an opinion about them.
    """
    momentum, gap = vector.get(MOMENTUM), vector.get(GAP)
    missing = [name for name, value in ((MOMENTUM, momentum), (GAP, gap)) if value is None]
    evidence = {
        "thresholds": thresholds.version,
        "axes": {MOMENTUM: momentum, GAP: gap},
        "basis": sorted({MOMENTUM, GAP} - set(missing)),
        **{k: v for k, v in vector.items() if k not in (MOMENTUM, GAP)},
    }
    if missing:
        # Not a fifth kind of niche. An absent axis is an absent measurement, and
        # defaulting it to 0 would silently classify every un-measured cluster as
        # cooling or saturated (data rule 7).
        evidence["reason"] = f"no {' and no '.join(missing)}"
        return Stage.UNKNOWN, evidence

    rising = momentum > thresholds.momentum
    underserved = gap > thresholds.gap
    if rising:
        return (Stage.EMERGING if underserved else Stage.CONTESTED), evidence
    return (Stage.COOLING if underserved else Stage.SATURATED), evidence
