"""Weights are computed within a family, and a second family must not move the first.

`weights()` scores a term `1/k` where k counts the lexicons containing it. That
makes the family a parameter, not a global: Slice 6 adds ~30 backtest niches, and
computing them in the same family as the five live ones would re-weight the live
lexicons with no `LEXICON_VERSION` bump, because nobody would have edited a live
lexicon.
"""

from __future__ import annotations

import pytest

from nh.clustering.lexicon import _COMMON, LEXICONS, weights

#: The live weights for a handful of load-bearing terms, frozen. If this moves, the
#: relevance scorer moves, and every stored supply number stops being comparable.
GOLDEN = {
    ("aviation-disasters", "crash"): 1.0,
    ("aviation-disasters", "runway"): 1.0,
    ("aviation-disasters", "documentary"): 0.0,
    ("engineering-failures", "collapse"): 0.5,
    ("corporate-collapse", "collapse"): 0.5,
    ("true-crime-trials", "verdict"): 1.0,
    ("true-crime-trials", "murder"): 1.0,
    # The guard on a deliberate exclusion (ADR-0028): `fraud` lives in
    # corporate-collapse alone. The day someone adds it to true-crime-trials as
    # well, this drops to 0.5 for BOTH and the white-collar-trial boundary moves
    # silently. That is what this pin is for.
    ("corporate-collapse", "fraud"): 1.0,
}

#: The retired `court-cases` entry, frozen here as a literal so the removal can be
#: checked forever without git archaeology. ADR-0028 removed it from LEXICONS.
RETIRED_COURT_CASES = (
    "court",
    "trial",
    "judge",
    "jury",
    "verdict",
    "lawsuit",
    "case",
    "supreme court",
    "ruling",
    "precedent",
    "statute",
    "constitutional",
    "landmark case",
    "appeal",
    "plaintiff",
    "defendant",
    "prosecutor",
    "attorney",
    "lawyer",
    "defence",
    "defense",
    "testimony",
    "witness",
    "evidence",
    "hearing",
    "indictment",
    "plea",
    "settlement",
    "damages",
    "injunction",
    "subpoena",
    "cross examination",
    "legal",
    "law",
    "litigation",
    "acquitted",
    "convicted",
    "conviction",
    "sentence",
    "sentenced",
)


def test_the_live_weights_are_what_they_were():
    live = weights()
    for (slug, term), expected in GOLDEN.items():
        assert live[slug][term] == expected, f"{slug}.{term} moved"


def test_removing_court_cases_moved_no_surviving_weight():
    """ADR-0028 removed `court-cases` and added `true-crime-trials` in one commit.

    The removal was safe because the retired lexicon was term-disjoint from the four
    that continue — measured 2026-08-28, zero weights moved. This turns that one-off
    measurement into a standing property over EVERY term, not a golden handful: if a
    future edit makes the families overlap, the four survivors' weights shift and this
    reds.

    It also states why removal had to happen in the same commit as the addition
    rather than earlier: the new lexicon shares heavily with the retired one, so a
    family holding both would score true-crime's most discriminative vocabulary at
    0.5 — a dead lexicon suppressing the terms its own replacement needs.
    """
    survivors = {k: v for k, v in LEXICONS.items() if k != "true-crime-trials"}
    with_corpse = weights({**survivors, "court-cases": RETIRED_COURT_CASES})
    live = weights()

    for slug in survivors:
        assert live[slug] == with_corpse[slug], f"{slug} moved when court-cases left"


def test_keeping_the_retired_lexicon_would_have_suppressed_its_successor():
    """The argument for one commit rather than two, asserted."""
    both = weights({**LEXICONS, "court-cases": RETIRED_COURT_CASES})

    assert weights()["true-crime-trials"]["verdict"] == 1.0
    assert both["true-crime-trials"]["verdict"] == 0.5


def test_a_second_family_does_not_move_the_live_weights():
    """The whole point. Backtest lexicons are computed separately."""
    before = weights()
    extra = {f"bt-{i}": ("nuclear", "reactor", "crash") for i in range(30)}
    weights(extra)  # a separate family, computed independently
    assert weights() == before


def test_merging_families_WOULD_move_them():
    """The failure being prevented, asserted so nobody 'simplifies' it away.

    `crash` is unique to aviation among the live five, so it weighs 1.0. Put it in
    30 more lexicons and it weighs 1/31.
    """
    merged = weights({**LEXICONS, **{f"bt-{i}": ("crash",) for i in range(30)}})
    assert merged["aviation-disasters"]["crash"] == pytest.approx(1 / 31)
    assert weights()["aviation-disasters"]["crash"] == 1.0


def test_common_terms_weigh_zero_in_any_family():
    """`_COMMON` is unioned into every lexicon, so `shared == total` always holds.
    This is why the dilution hits domain terms and not the genre words — the
    opposite of what one might expect."""
    for family in (LEXICONS, {"a": ("x",), "b": ("y",)}):
        computed = weights(family)
        for slug in family:
            for term in _COMMON:
                assert computed[slug][term] == 0.0


def test_a_family_of_one_is_refused():
    """It would not fail — it would silently score every term 0.0, collapsing the
    domain axis and making every relevance score 0. A family of one has nothing to
    discriminate against."""
    with pytest.raises(ValueError, match="at least two members"):
        weights({"solo": ("reactor", "meltdown")})


def test_family_size_changes_how_aggressively_terms_are_zeroed():
    """Not a quirk — a constraint on how backtest families must be sized.

    The rule is `0.0 if shared == total else 1/shared`, so "in every lexicon" and
    "in two" mean different things at different family sizes. In a family of two, a
    shared term IS in every lexicon and weighs 0. In the live family of five,
    `collapse` is in two and weighs 0.5.

    So a backtest family of two would zero far more of its vocabulary than
    production does, and the same 0.55 relevance threshold would be a stricter
    instrument. Backtest families are sized like the live one — five or six — so
    the construction matches.
    """
    pair = weights({"a": ("reactor", "shared"), "b": ("meltdown", "shared")})
    assert pair["a"]["shared"] == 0.0  # in all two
    assert pair["a"]["reactor"] == 1.0

    trio = weights({"a": ("shared", "x"), "b": ("shared", "y"), "c": ("z",)})
    assert trio["a"]["shared"] == 0.5  # in two of three

    assert weights()["engineering-failures"]["collapse"] == 0.5  # two of five
