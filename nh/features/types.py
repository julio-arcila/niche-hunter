"""What a feature function returns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FeatureResult:
    """One metric, one cluster, one day.

    `value` is None when the metric could not be computed — never 0, which is a
    measurement (data rule 7). An uncomputable metric still returns a result:
    "we looked and there was nothing" is a fact worth a row, it is what lets
    `nh niche show` tell missing from zero, and it keeps the row count stable so
    a metric silently vanishing is visible.
    """

    group: str
    name: str
    value: float | None
    confidence: float | None
    inputs_n: int
    detail: dict[str, Any] | None = None

    @classmethod
    def empty(cls, group: str, name: str, reason: str, **detail: Any) -> FeatureResult:
        return cls(group, name, None, 0.0, 0, {"reason": reason, **detail})
