"""The backtest niche set, and the properties that make it a fair instrument.

These are not tests of curation quality — no test can judge whether
"pipeline-failures" is a real YouTube niche. They pin the structural properties
that would otherwise silently make the backtest measure something other than what
the live pipeline measures.
"""

from __future__ import annotations

import pytest

from nh.backtest.niches import (
    BACKTEST_COMMON,
    BACKTEST_NICHES,
    backtest_weights,
    by_slug,
    families,
)
from nh.clustering.lexicon import LEXICONS, weights

#: Production's lexicons run 39-42 domain terms. Lexicon size drives on_niche_share,
#: which drives member count, which drives every supply metric and the outcome's
#: member set — so a 12-term and a 60-term lexicon are not the same instrument and
#: the cross-niche comparison would be measuring the curation.
MIN_TERMS, MAX_TERMS = 38, 45


def test_there_are_enough_niches_for_the_gate_to_fire():
    """Spearman SE is about 1/sqrt(N-1): at N=6 the smallest detectable rho is
    0.89 and a null result means nothing. 36 are curated expecting ~30 to survive
    the inclusion floor."""
    assert len(BACKTEST_NICHES) >= 30


@pytest.mark.parametrize("niche", BACKTEST_NICHES, ids=lambda n: n["slug"])
def test_every_lexicon_is_within_the_production_size_band(niche):
    assert MIN_TERMS <= len(niche["lexicon"]) <= MAX_TERMS


@pytest.mark.parametrize("niche", BACKTEST_NICHES, ids=lambda n: n["slug"])
def test_every_niche_carries_what_a_seed_carries(niche):
    assert niche["slug"] and niche["label"] and niche["family"] and niche["geo"]
    assert len(niche["wiki_topic"]) == 3
    pool = niche["wiki_event_pool"]
    assert pool["classes"] or pool["categories"], "an event stratum needs a pool to sample"


def test_families_are_sized_like_the_live_one():
    """`weights()` zeroes any term present in every lexicon of the family, so family
    size IS the instrument. A family of two zeroes every shared term; the live
    family of five zeroes only terms in all five. Six keeps the construction close."""
    for family, lexicons in families().items():
        assert 5 <= len(lexicons) <= 7, f"{family} has {len(lexicons)} members"


def test_slugs_are_unique_and_do_not_collide_with_production():
    slugs = [n["slug"] for n in BACKTEST_NICHES]
    assert len(slugs) == len(set(slugs))
    assert not set(slugs) & set(LEXICONS), "a backtest slug shadows a live niche"


def test_backtest_weights_do_not_touch_the_live_ones():
    """The whole reason weights() takes a family."""
    before = weights()
    backtest_weights()
    assert weights() == before


def test_a_term_unique_within_its_family_carries_full_weight():
    computed = backtest_weights()
    assert computed["nuclear-accidents"]["reactor"] == 1.0
    assert computed["cyberattacks"]["ransomware"] == 1.0


def test_the_family_genre_words_weigh_nothing():
    """Same job `_COMMON` does live: these are how the niche is phrased, not what
    separates it from its siblings."""
    computed = backtest_weights()
    for niche in BACKTEST_NICHES:
        for term in BACKTEST_COMMON:
            assert computed[niche["slug"]][term] == 0.0


def test_a_term_shared_within_a_family_is_discounted():
    """`evacuation` appears in two members of catastrophic-failure, so it carries
    half the evidence of a term unique to one."""
    computed = backtest_weights()["nuclear-accidents"]
    assert computed["evacuation"] == 0.5
    assert computed["reactor"] == 1.0


def test_families_share_terms_at_roughly_the_production_rate():
    """The discriminative weighting only does work when siblings actually overlap.

    Lexicons written to be perfectly disjoint would give every term weight 1.0 and
    the `1/k` rule would be inert — the backtest's scorer would then be a different
    instrument from production's, at the same threshold. Measured: the live family
    of five shares 2 domain terms; these six families share 1 to 8. Comparable, and
    the assertion is loose on purpose because the number is a property of English,
    not a target to hit.
    """
    import collections

    for family, lexicons in families().items():
        counts = collections.Counter(t for terms in lexicons.values() for t in terms)
        shared = sum(1 for k in counts.values() if k > 1)
        assert 1 <= shared <= 15, f"{family} shares {shared} domain terms"


def test_by_slug_covers_every_niche():
    assert set(by_slug()) == {n["slug"] for n in BACKTEST_NICHES}
