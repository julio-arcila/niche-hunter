"""The relevance scorer, and the properties that keep it honest.

Every `supply.*` number depends on this function, so the tests that matter most are
not "does it score this video highly" but the structural ones: unscorable is not
zero, the corpus never enters the weights, and the scorer measures topic rather
than the documentary vocabulary all five niches share.
"""

from __future__ import annotations

import pytest

from nh.clustering.lexicon import _COMMON, LEXICON_VERSION, LEXICONS, weights
from nh.clustering.relevance import DESCRIPTION_CAP, Score, normalise, score

W = weights()
AVIATION = W["aviation-disasters"]


# -- weights are a function of the lexicon, never of the corpus ---------------


def test_a_term_unique_to_one_niche_carries_full_weight():
    assert AVIATION["runway"] == 1.0


def test_a_term_shared_by_two_niches_carries_half():
    """`collapse` is genuine in both a bridge and a company, and is worth half a
    vote in each rather than being dropped."""
    assert W["engineering-failures"]["collapse"] == 0.5
    assert W["corporate-collapse"]["collapse"] == 0.5


def test_a_term_in_every_niche_carries_nothing():
    """This is the whole defence against measuring documentary-ness. These words
    are how the seed keywords were written, not what separates the niches."""
    for term in _COMMON:
        assert all(W[slug][term] == 0.0 for slug in LEXICONS)


def test_every_lexicon_covers_every_common_term():
    for slug in LEXICONS:
        assert set(_COMMON) <= set(W[slug])


def test_the_version_is_stamped_and_looks_dated():
    assert LEXICON_VERSION and LEXICON_VERSION[:4].isdigit()


# -- unscorable is not zero (data rule 7) ------------------------------------


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("", "no title"),
        ("   ", "no title"),
        ("🚀🔥💥", "no letters"),
        ("क्या पंखा आपको और ज्यादा गरमी का एहसास कराता है", "non-Latin script"),
        ("नेपाल वरदल वनक रहसय", "non-Latin script"),
    ],
)
def test_text_the_lexicon_cannot_read_is_unscorable_not_off_niche(title, reason):
    result = score(title, None, AVIATION)
    assert result.value is None
    assert result.scorable is False
    assert reason in result.reason


def test_a_none_title_is_unscorable():
    assert score(None, "a description about a plane crash", AVIATION).value is None


def test_a_latin_title_with_some_emoji_is_still_scored():
    """35% of real titles carry emoji; only the script gate should reject text."""
    assert score("Plane Crash Investigation 🛬💥 #shorts", None, AVIATION).scorable


def test_an_english_title_that_matches_nothing_scores_zero_not_none():
    """Genuinely off-niche is a decision, and a decision is not an absence."""
    result = score("Maruti Grand Vitara Maintenance Cost", None, AVIATION)
    assert result.value == 0.0
    assert result.reason is None


# -- what the score counts ---------------------------------------------------


def test_distinct_terms_count_not_occurrences():
    once = score("A plane story", "plane", AVIATION)
    many = score("A plane story", "plane plane plane plane plane plane", AVIATION)
    assert once.value == many.value


def test_the_title_outweighs_the_description():
    in_title = score("runway", "nothing relevant here", AVIATION)
    in_description = score("nothing relevant here", "runway", AVIATION)
    assert in_title.value > in_description.value


def test_a_link_farm_description_cannot_outvote_the_title():
    """A 5,000-character description naming every term in the lexicon is capped."""
    stuffed = " ".join(LEXICONS["aviation-disasters"])
    assert score("unrelated words only", stuffed, AVIATION).value <= DESCRIPTION_CAP / (
        DESCRIPTION_CAP + 2.0
    )


def test_zero_weight_terms_contribute_nothing():
    assert score("The documentary story of a tragedy explained", None, AVIATION).value == 0.0


def test_multi_word_terms_match_as_phrases():
    assert "air traffic control" in score("Inside air traffic control", None, AVIATION).matched
    assert "air traffic control" not in score("air and traffic and control", None, AVIATION).matched


def test_matched_terms_are_reported_for_traceability():
    """`cluster_members.detail` carries this, so a supply number reaches its rows."""
    result = score("Boeing 737 crash on the runway", None, AVIATION)
    assert {"boeing", "crash", "runway"} <= set(result.matched)


def test_the_score_is_bounded_and_never_claims_certainty():
    everything = " ".join(LEXICONS["aviation-disasters"])
    result = score(everything, everything, AVIATION)
    assert 0.0 <= result.value < 1.0


def test_scoring_is_deterministic():
    args = ("Air France 447 crash investigation", "The Airbus fell into the ocean.", AVIATION)
    assert score(*args) == score(*args)


# -- the negative control, as a unit test ------------------------------------


@pytest.mark.parametrize(
    ("slug", "title"),
    [
        ("aviation-disasters", "The pilot lost the cockpit and the plane hit the runway"),
        ("maritime-disasters", "The vessel capsized and the lifeboat drifted at sea"),
        ("corporate-collapse", "The CEO hid the accounting fraud from shareholders"),
        ("engineering-failures", "The concrete girder buckled and the bridge fell"),
        ("court-cases", "The jury reached a verdict and the judge passed sentence"),
    ],
)
def test_a_title_scores_highest_against_its_own_niche(slug, title):
    """If a niche's text scored as well against a foreign lexicon, the scorer would
    be measuring genre. Measured on the real corpus the margin is 2.5x-3.8x on the
    mean; here it only has to be strictly greater."""
    own = score(title, None, W[slug]).value
    foreign = [score(title, None, W[other]).value for other in W if other != slug]
    assert own > max(foreign)


def test_normalise_strips_punctuation_hashtags_and_case():
    assert normalise("Plane-Crash! #Aviation") == "plane crash aviation"


def test_score_equality_is_structural():
    assert Score(None, reason="x") == Score(None, reason="x")
