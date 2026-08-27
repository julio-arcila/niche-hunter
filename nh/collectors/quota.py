"""Per-run quota accounting.

The prototype's ``Q = Quota()`` was a module-level singleton: it could not be
reset between runs, shared between collectors, or written to `job_runs`. This is
one ledger per collector run, and the nightly job persists what it spent.
"""

from __future__ import annotations

from collections import Counter


class QuotaExhausted(RuntimeError):
    """The run hit its budget. Stop cleanly; do not retry into an overspend."""


class QuotaLedger:
    """Charge only on success, mirroring the prototypes' `call()` semantics: a
    request that 4xx'd or was retried never cost a unit, so it must not be
    billed against the budget."""

    def __init__(self, budget: int | None = None) -> None:
        self.budget = budget
        self.used = 0
        self.by_endpoint: Counter[str] = Counter()

    @property
    def remaining(self) -> int | None:
        return None if self.budget is None else self.budget - self.used

    def can_afford(self, cost: int) -> bool:
        return self.budget is None or self.used + cost <= self.budget

    def spend(self, cost: int, endpoint: str = "-") -> None:
        if not self.can_afford(cost):
            raise QuotaExhausted(
                f"budget exhausted: {self.used}/{self.budget} used, {cost} more requested "
                f"for {endpoint!r}"
            )
        self.used += cost
        self.by_endpoint[endpoint] += cost

    def exhaust(self) -> None:
        """Mark the budget spent without charging anything.

        For when the *upstream* ceiling is hit rather than ours: the source has
        told us there is nothing left today, so every later call in this run
        should short-circuit instead of asking again and being refused again.
        """
        self.budget = self.used

    def summary(self) -> dict[str, object]:
        return {"used": self.used, "budget": self.budget, "by_endpoint": dict(self.by_endpoint)}
