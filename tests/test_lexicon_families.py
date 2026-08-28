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
    ("court-cases", "verdict"): 1.0,
}


def test_the_live_weights_are_what_they_were():
    live = weights()
    for (slug, term), expected in GOLDEN.items():
        assert live[slug][term] == expected, f"{slug}.{term} moved"


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
