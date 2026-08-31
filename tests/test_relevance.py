"""The relevance scorer, and the properties that keep it honest.

Every `supply.*` number depends on this function, so the tests that matter most are
not "does it score this video highly" but the structural ones: unscorable is not
zero, the corpus never enters the weights, and the scorer measures topic rather
than the documentary vocabulary all five niches share.
"""

from __future__ import annotations

import pytest

from nh.clustering.lexicon import (
    _COMMON,
    LEXICON_VERSION,
    LEXICONS,
    event_weights,
    exposition_weights,
    weights,
)
from nh.clustering.relevance import (
    DESCRIPTION_CAP,
    RELEVANCE_HIGH,
    RELEVANCE_LOW,
    Score,
    normalise,
    score,
)

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
    """Both carry the same evidence; only its position differs."""
    in_title = score("runway crash", "nothing relevant here", AVIATION)
    in_description = score("nothing relevant here", "runway crash", AVIATION)
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
        ("aviation-disasters", "The pilot lost the cockpit and the plane crashed on the runway"),
        ("maritime-disasters", "The vessel capsized at sea and the crew were lost"),
        ("corporate-collapse", "The CEO hid the accounting fraud and the company collapsed"),
        ("engineering-failures", "The concrete girder buckled and the bridge collapsed"),
        ("true-crime-trials", "The jury reached a guilty verdict and the judge passed sentence"),
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


# -- the second axis ---------------------------------------------------------


def test_domain_words_alone_are_not_enough():
    """The measured reason this axis exists. A domain-only scorer reached precision
    0.62 at best, and every false positive looked like this line: squarely inside
    the vocabulary, squarely outside the niche."""
    assert score("Changi Airport Plane Spotting", None, AVIATION).value == 0.0
    assert (
        score("Why Concrete Needs Steel Reinforcement", None, W["engineering-failures"]).value
        == 0.0
    )


def test_event_words_alone_are_not_enough():
    """The mirror. A fatal fire is not an aviation disaster."""
    assert score("Tragic fire kills three in apartment block", None, AVIATION).value == 0.0


def test_both_axes_together_score():
    assert score("Plane crashes on runway", None, AVIATION).value > 0.5


def test_the_two_axes_are_reported_separately():
    """`cluster_members.detail` carries both, so a reviewer can see which half of
    the judgement was weak."""
    result = score("Boeing 737 crashed on the runway", None, AVIATION)
    assert set(result.detail) == {"domain", "event"}
    assert result.detail["domain"] > 0 and result.detail["event"] > 0


def test_event_terms_are_marked_in_the_matched_map():
    matched = score("Plane crashed on the runway", None, AVIATION).matched
    assert any(k.startswith("~") for k in matched)  # event axis
    assert any(not k.startswith("~") for k in matched)  # domain axis


def test_the_thresholds_carry_their_measured_provenance():
    """A constant chosen against labels must not drift into one chosen against a
    metric. The docstring beside these is where the evidence lives."""
    assert 0.0 <= RELEVANCE_LOW < RELEVANCE_HIGH < 1.0


def test_a_topic_title_scores_zero_under_event_and_nonzero_under_exposition():
    """ADR-0033's blocker, frozen as a standing regression.

    The score is a geometric mean, so a second axis that matches nothing zeroes a
    perfect domain match. Measured on 120 real discovered videos from the pivot
    domains, the EVENT axis matched 1 of 120 titles — which is why all eleven were
    landed inactive rather than switched on.
    """
    title = "Falsifiability and the scientific method explained"
    domain = weights(LEXICONS)["philosophy-of-science"]

    assert score(title, "", domain, event_weights(), "event").value == 0.0
    assert score(title, "", domain, exposition_weights(), "exposition").value > 0.0


def test_detail_names_the_axis_that_produced_the_row():
    """Constraint from ADR-0034: a stored row must say which axis judged it, so a
    reader can tell a pre-change row from a post-change one without git archaeology.
    The event-family assertion is unchanged and is itself part of the no-movement
    evidence — the default call still writes exactly `event`."""
    title = "Falsifiability and the scientific method explained"
    domain = weights(LEXICONS)["philosophy-of-science"]

    assert set(score(title, "", domain, exposition_weights(), "exposition").detail) == {
        "domain",
        "exposition",
    }
    assert set(score(title, "", domain).detail) == {"domain", "event"}


def test_the_default_second_axis_is_still_event():
    """The whole per-family change must be invisible to every existing caller. All of
    them pass positionally, so the default is what keeps the live five bit-identical."""
    title = "Plane crashed on the runway after engine failure"
    domain = weights(LEXICONS)["aviation-disasters"]

    assert score(title, "", domain) == score(title, "", domain, event_weights(), "event")


# -- the latin-script non-english gate (ADR-0046) ------------------------------
# `_latin_share` catches SCRIPTS, and that was read for two years as catching
# languages. It is not: a Spanish title is ~100% Latin letters, so it passed, matched
# nothing, scored exactly 0.0, and `is_noise = value <= RELEVANCE_LOW` filed it as
# DECIDED off-niche -- the outcome that gate's own comment forbids. Measured on the
# live corpus: 854 es/fr/pt/de/it rows, none caught, 1.1% on-niche against English's
# 20.2%. See reports/supply_audit_2026-08-30.md (addendum).

EXPO = exposition_weights()


@pytest.mark.parametrize(
    "title",
    [
        "Cómo entender la economía: el método para invertir",
        "Pourquoi la France est dans une crise sans fin",
        "Warum die Wirtschaft nicht mehr funktioniert",
        "Por que a economia nao funciona como todos esperam",
        "Perché la filosofia della scienza è importante",
    ],
)
def test_a_latin_script_non_english_title_is_unscorable_not_noise(title):
    """The three states are not two. These must land NULL, exactly as Korean does --
    excluded from numerator and denominator alike, not decided off-niche."""
    result = score(title, None, W["trading"], EXPO, "exposition")
    assert result.value is None
    assert result.reason == "unscorable: latin-script non-english"


@pytest.mark.parametrize(
    "title",
    [
        # Place names and proper nouns whose fragments look like function words once
        # digits and punctuation become separators. Every one of these FIRED against an
        # earlier version of the word sets while all three canaries still read zero --
        # which is why they are pinned here rather than trusted to a corpus count.
        "Los Angeles plane crash: what the NTSB report says",
        "Tour de France crash analysis",
        "The la Palma volcano collapse explained",
        "Murder in Sin City: Las Vegas verdict",
        "Son Kills Father in Las Vegas Trial",
        "Bashar al-Assad's Su-24 Strike Explained",
        "El Paso, Las Cruces: the trial",
        "Why Consciousness Must Come First, Per Kastrup",
        "Hard hat, die cast: inside the factory collapse",
        "Live 3pm EST - IL plane crash coverage",
        "Mac OS da Vinci build notes",
        "Flight ET302 crash: la MCAS story",
        "The Symbolism of Evil (La symbolique du mal) | Paul Ricoeur",
        # Second round, and the point of them: the block above SELECTED the removals,
        # so it is in-sample. These were drawn independently afterwards and 10 of 11
        # fired on the sets that the first block had just been used to validate.
        # DuPont La Porte (2014, four dead) and Le Mans 1955 are real cases in these
        # niches, not contrivances.
        "Du Pont, La Porte: chemical plant failure",
        "Le Mans, La Sarthe: 1955 disaster",
        "Del Rio, La Joya: the border crisis explained",
        "LA Des Moines crash: NTSB findings",
        "Au Pair Trial: La Defense Rests",
        "Der Spiegel im focus",
        "Comic Con LA 2026: what shipped",
        "Di Maio and La Russa: Italy explained",
        "Ce Ce Peniston, La Toya: 1990s trial",
        "Um, ou: filler words in courtroom testimony",
    ],
)
def test_english_titles_carrying_foreign_tokens_still_score(title):
    """Over-firing is the failure mode that matters: an English title wrongly withdrawn
    shrinks a niche silently, and no aggregate canary can see it.

    The corpus canaries (0 on-niche caught, 0 Indic, 0 sampled) went green on word sets
    that fired on 9 of the first 13 below. A number obtained by editing until it reads zero is a
    training-set number, not a safety margin — so the margin lives here instead."""
    assert score(title, None, W["aviation-disasters"], event_weights()).value is not None


def test_romanised_indic_titles_still_score():
    """Measured 0 fires across 9,243 romanised hi/ur/ta/mr/bn rows, and that is by
    construction: every token under three characters is excluded, which
    removes the romanised-Hindi particles (`ne`, `se`, `si`, `ci`, `lo`, `ya`) as a
    consequence of the length rule rather than as a hand-maintained exclusion list."""
    for title in (
        "Plane Crash Ka Sach - Kya Hua Tha Us Raat?",
        "Stock Market Kaise Kaam Karta Hai | Trading Basics",
    ):
        assert score(title, None, W["trading"], EXPO, "exposition").value is not None


def test_the_description_decides_only_when_the_title_cannot():
    """A short ambiguous title with a wholly foreign description is withdrawn; an
    English title is settled on the title alone and the description is never consulted
    -- which is also what keeps the gate cheap, since folding every 5KB description on
    every row is the one way to make it expensive."""
    spanish = (
        "En este video vamos a explicar por que la economia del pais no funciona como "
        "todos esperan, y que es lo que hay detras de las cifras que se publican hoy."
    )
    assert score("Bitcoin 2026", spanish, W["trading"], EXPO, "exposition").value is None
    english = score("How to trade the market open", spanish, W["trading"], EXPO, "exposition")
    assert english.value is not None


def test_the_gate_never_alters_a_numeric_score():
    """It can only withdraw a row, never move one.

    Structural rather than a pinned constant: the gate is an early return, so when
    `_non_english` is False every later line is byte-identical to the pre-gate scorer.
    Asserting the gate stays silent IS the assertion that the number is untouched. The
    value is pinned too, so a change to the axis arithmetic still trips something."""
    from nh.clustering.relevance import _non_english

    title = "Boeing 737 crash investigation: the black box findings"
    assert _non_english(title, None) is False
    result = score(title, None, W["aviation-disasters"], event_weights())
    assert result.value == pytest.approx(0.7071067811865476)


def test_folding_preserves_accented_words_that_normalise_destroys():
    """`normalise` substitutes `[^a-z0-9]+`, turning "cómo" into "c mo". Reusing it for
    the gate would destroy the exact signal the gate reads, so `_fold_tokens` folds
    rather than strips. This pins that they really do differ."""
    from nh.clustering.relevance import _fold_tokens

    assert "como" in _fold_tokens("Cómo")
    assert "como" not in normalise("Cómo").split()
    assert "lauft" in _fold_tokens("läuft")
    assert "strasse" in _fold_tokens("Straße")


def test_a_gate_caught_video_lands_null_and_not_noise():
    """The phase contract, which is the entire point of ADR-0046 and was untested.

    `assign_videos` writes `is_noise = value is not None and value <= RELEVANCE_LOW`.
    A gate-caught row must therefore reach it as `value=None` so it stores NULL relevance
    and `is_noise` False — the third state. If the gate ever returned 0.0 instead of
    None the row would be filed as a DECISION, which is the defect this ADR fixes,
    and every corpus canary would still read zero.

    Note the title has to be long enough to carry two function words: the shorter
    "Cómo entender la economía: el método" is NOT caught, because `el` was removed as an
    English proper-noun collider. That is the accepted residual, not a bug — see the
    word-set comment and ADR-0046."""
    result = score("Cómo entender la economía: el método para invertir", None, W["trading"], EXPO)
    assert result.value is None
    # exactly the expression in phase.assign_videos
    assert (result.value is not None and result.value <= RELEVANCE_LOW) is False
    assert result.reason == "unscorable: latin-script non-english"


def test_the_gate_reason_reaches_stored_detail():
    """`_detail` is what puts the reason in `cluster_members.detail`, so a later reader
    can tell a gate withdrawal from an unreadable-script one without git archaeology."""
    from nh.clustering.phase import _detail

    caught = score("Warum die Wirtschaft nicht mehr funktioniert", None, W["trading"], EXPO)
    assert _detail(caught)["reason"] == "unscorable: latin-script non-english"


@pytest.mark.parametrize(
    "title",
    [
        "Von Neumann and MIT",
        "Che Guevara: Con Man or Icon?",
    ],
)
def test_the_residual_attack_surface_is_recorded_not_closed(title):
    """These FIRE, and that is the point of pinning them.

    A third independent draw, built only from the surviving three-character tokens,
    fired on 7 of 16: `mit`/`von`/`der`, `che`/`con`, `con`/`hay`, `nas`/`uma`. The class
    cannot be closed by enumeration — every three-letter foreign function word is
    somebody's acronym or surname, and the next round would take `ser`, `ist`, `tem`,
    `sao` and still not be done.

    So the removals stopped, and the honest reason is the corpus margin rather than a
    canary: on-niche rows sitting one token from withdrawal fell from **75 to 4**, and
    those needing one more same-language word from **30 to 1**. The single survivor is
    `MIT Just Revealed the AI Bubble's Fatal Flaw`, one German token away.

    This test asserts the defect so that a later change to the word sets cannot silently
    alter it in either direction. If a future edit makes these score, that is good news —
    delete the test and say so in an ADR. It must not be deleted to make a diff green."""
    assert score(title, None, W["ai-and-software"], EXPO, "exposition").value is None
