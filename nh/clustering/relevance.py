"""Is this video about its cluster's niche?

Pure: no session, no clock, no corpus. `score()` is a function of the text and the
frozen lexicon, which is what lets Slice 6 replay a historical day and reproduce the
decision that was actually made rather than the one today's corpus would produce.

Why this exists at all. `cluster_members` assigns *channels* to seeds and videos
inherit their channel's cluster at query time, so a channel that published one
plane-crash video contributes its entire catalogue to `aviation-disasters`.
Measured on 2026-08-27, only 22.2% of video titles contained even one word from
their own niche's vocabulary (42.4% once descriptions were available), and
restricting `supply.median_views` to on-niche videos moved it by 0.42x to 3.37x and
swapped two clusters' supply ranks. Identity — which niche a channel belongs to —
is a separate question, still answered by discovery lineage (ADR-0013). This
answers topicality, which was previously not asked and silently answered yes.

**Unscorable is not zero.** A title in a script the lexicon cannot read scores no
matches, and calling that "off-niche" would silently delete Hindi aviation content
from the corpus — 10.5% of titles are non-Latin. Those get `value=None` and a
reason, are excluded from numerator *and* denominator wherever they are counted,
and drag the relevance-coverage leg of confidence down instead. Same pattern
`money.midroll_eligible_share` already uses for an unknown duration (data rule 7).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: The title is the promise a video makes; a description carries sponsor blocks,
#: link farms and boilerplate. Title evidence is worth double.
TITLE_WEIGHT = 2.0
#: Distinct terms counted per field. Caps are the length normalisation: without
#: them a 5,000-character description outvotes the title by volume alone, and a
#: keyword-stuffed title outscores a precise one.
TITLE_CAP = 3.0
DESCRIPTION_CAP = 3.0
#: Raw evidence at which relevance reads 0.5. The curve saturates, so 1.0 is
#: unreachable by construction — the scorer never claims certainty.
HALF = 2.0

_WORD = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class Score:
    """`value is None` means unscorable; `reason` then says why."""

    value: float | None
    matched: dict[str, float] = field(default_factory=dict)
    reason: str | None = None

    @property
    def scorable(self) -> bool:
        return self.value is not None


def normalise(text: str) -> str:
    """Lowercase, punctuation to spaces. Emoji and hashtags fall out as separators."""
    return _WORD.sub(" ", text.lower()).strip()


def _latin_share(text: str) -> float | None:
    """Share of the letters that are Latin. None when there are no letters at all."""
    letters = [c for c in text if unicodedata.category(c).startswith("L")]
    if not letters:
        return None
    latin = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
    return latin / len(letters)


def _matches(text: str, weights: dict[str, float]) -> dict[str, float]:
    """Distinct terms present, not occurrences.

    A description repeating "plane" thirty times is one piece of evidence, not
    thirty; naming three distinct aviation concepts is three. Multi-word entries
    match as phrases, single words against the token set.
    """
    normalised = normalise(text)
    tokens = set(normalised.split())
    padded = f" {normalised} "
    found = {}
    for term, weight in weights.items():
        hit = f" {term} " in padded if " " in term else term in tokens
        if hit and weight > 0:
            found[term] = weight
    return found


def _capped(matched: dict[str, float], cap: float) -> float:
    """Sum of the strongest matches, up to `cap` worth of evidence."""
    return min(sum(sorted(matched.values(), reverse=True)), cap)


def score(title: str | None, description: str | None, weights: dict[str, float]) -> Score:
    """Relevance of one video's text to one cluster's vocabulary."""
    if not (title or "").strip():
        return Score(None, reason="unscorable: no title")
    share = _latin_share(title)
    if share is None:
        return Score(None, reason="unscorable: title has no letters")
    if share < 0.5:
        # An English lexicon cannot read this. Scoring it 0 would call it off-niche.
        return Score(None, reason="unscorable: non-Latin script")

    in_title = _matches(title, weights)
    in_description = _matches(description or "", weights)
    # A term already credited in the title is not credited again in the description.
    only_description = {t: w for t, w in in_description.items() if t not in in_title}

    raw = TITLE_WEIGHT * _capped(in_title, TITLE_CAP) + _capped(only_description, DESCRIPTION_CAP)
    matched = {t: TITLE_WEIGHT * w for t, w in in_title.items()} | only_description
    return Score(raw / (raw + HALF), matched)
