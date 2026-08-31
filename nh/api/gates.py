"""What a reader may be shown, and what the labelling deferral withholds.

**Why this module exists, stated once so it is not re-derived as bureaucracy.**
ADR-0045 made the exposition-labelling requirement fire when a score is CITED, and
implemented that as a query on non-NULL `scorecards.value` / `sustainability` /
`opportunity`. Measured 2026-08-31: those are 0 of 10, and **Gate E holds them NULL
permanently** because Gate E failed — so the trigger can never fire. Meanwhile `gap`,
`supply`, `demand`, `stage` and `openness` are 10 of 10 non-NULL for ten unvalidated
exposition clusters, and `nh niche show` already prints them.

So the register stays green while the numbers are on screen. ADR-0052's resolution is not
to teach the deferral to detect a surface — it is to make every read path refuse to serve
what the deferral covers. This module is that refusal.

**It withholds; it never softens.** A caveat beside a number is read as a number. What a
gated metric returns is the reason it is withheld and the command that discharges it, which
is serving the deferral register rather than citing the score.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The verdict on ADR-0041's exposition sample, once a human has computed it. `None` means
#: unlabelled or uncomputed. `True` means the 95% Wilson LOWER bound on precision came in at
#: or above 0.70 (79 of 100); `False` means it did not.
#:
#: **A constant a person sets, never a file or an environment variable the code reads** —
#: the same shape and the same reason as `inputs.BALLAST_VALIDATED`. An `NH_SHOW_UNVALIDATED`
#: env var was considered and refused in ADR-0052: it would be a stored setting standing in
#: for a human verdict, which is exactly what ADR-0050 forbids one layer down. Set it in the
#: commit that writes the result report and the interval into ADR-0041.
EXPOSITION_VALIDATED: bool | None = None

#: Metrics whose value or confidence changes when the relevance threshold changes — i.e.
#: the scorer decided them.
#:
#: **Derived by execution, not by reading the queries.** `test_gates.py` runs every metric
#: in `features.run.METRICS` twice on a synthetic corpus, once at `RELEVANCE_HIGH` and once
#: at an impossible threshold, and asserts this set is exactly the set that moved. The
#: method is not fastidiousness: the plan this module came from reasoned from the query text
#: and put all of `openness.*` on the safe side, because ADR-0047 established that openness
#: is unaffected by *ballast*. True, and a different claim —
#: `openness.winner_age_years` joins `on_niche_join` at `nh/features/openness.py:167` and
#: reads `relevance >= RELEVANCE_HIGH` directly. A hand-maintained table ships that mistake
#: into the gate; a derived one cannot.
SCORER_DEPENDENT: frozenset[str] = frozenset(
    {
        # supply.* — all six, plus the cross-cluster rank built from them
        "uploads_per_week",
        "median_views",
        "on_niche_share",
        "geo_concentration",
        "format_mix",
        "top10_concentration",
        "pressure_index",
        # money
        "midroll_eligible_share",
        # openness — one of the three, and the one a reader would not guess
        "winner_age_years",
    }
)

#: Every `scorecards` column that carries a composite of the above. Withheld wholesale for a
#: gated cluster: `gap` is demand-minus-supply and `stage` is derived from both, so neither
#: is separable from the scorer. `value`/`sustainability`/`opportunity`/`ci_*` are NULL
#: behind Gate E anyway and are listed for completeness rather than effect.
SCORECARD_FIELDS: frozenset[str] = frozenset(
    {
        "gap",
        "gap_confidence",
        "supply",
        "demand",
        "stage",
        "stage_confidence",
        "openness",
        "value",
        "sustainability",
        "opportunity",
        "ci_low",
        "ci_high",
    }
)

#: Axes whose scorer has not been validated against human labels. `event` is not here: its
#: relevance rule was measured against 298 human labels at held-out precision 0.781
#: (reports/relevance_2026-08-27.md). `exposition` rests on 107 MACHINE labels from one
#: model family, which is the whole of ADR-0041's objection.
UNVALIDATED_AXES: frozenset[str] = frozenset({"exposition"})

WITHHELD = (
    "computed, unvalidated, and not shown: the {axis} relevance rule rests on machine "
    "labels only (ADR-0041). A drawn sample is waiting — "
    "`uv run python scripts/label_exposition.py`, ~20 minutes."
)


@dataclass(frozen=True, slots=True)
class Verdict:
    """Whether a number may be shown, and if not, what to show instead."""

    citable: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.citable


CITABLE = Verdict(True)


def axis_of(cluster_id: str) -> str | None:
    """The relevance axis a cluster is scored on, or `None` if it has no lexicon.

    Imported lazily: `nh.api` must stay importable without dragging the clustering layer
    into a caller that only wants to read rows.
    """
    from nh.clustering.lexicon import AXES

    return AXES.get(cluster_id)


def axis_validated(axis: str | None) -> bool:
    """Whether `axis`'s scorer has cleared its human-label bar."""
    if axis not in UNVALIDATED_AXES:
        return True  # `event`, or a cluster with no lexicon and so nothing scored
    return EXPOSITION_VALIDATED is True


def citable(name: str, cluster_id: str) -> Verdict:
    """May this metric's value be shown for this cluster?

    Two independent facts, and both must hold: the metric does not read a relevance
    decision, OR the axis that decides it has been validated. A metric no scorer touched is
    citable for every cluster — the demand series and the Keyword Planner numbers do not
    become suspect because a lexicon is unproven.
    """
    if name not in SCORER_DEPENDENT:
        return CITABLE
    axis = axis_of(cluster_id)
    if axis_validated(axis):
        return CITABLE
    return Verdict(False, WITHHELD.format(axis=axis))


def scorecard_citable(cluster_id: str) -> Verdict:
    """May any `scorecards` field be shown for this cluster?

    All or nothing, deliberately. `gap` is demand minus supply; showing `demand` alone from
    a row whose `supply` is withheld invites the reader to reconstruct the difference, which
    is the citation the gate exists to prevent.
    """
    axis = axis_of(cluster_id)
    if axis_validated(axis):
        return CITABLE
    return Verdict(False, WITHHELD.format(axis=axis))
