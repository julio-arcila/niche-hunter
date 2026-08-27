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

**Two axes, because one did not work.** Domain vocabulary alone reached precision
0.62 at best against 298 hand labels, and every false positive was the same shape:
on-domain, off-niche — airport plane spotting, a concrete-reinforcement tutorial,
"Settlement vs Adjudication", a food-delivery growth story. The niche is *domain
AND event*, so relevance is the geometric mean of a domain score and a failure/case
score. A geometric mean rather than a sum because either axis at zero should mean
zero: a tutorial about bridges is not a bridge collapse, and a video about a
collapse with no engineering content is not this niche either.

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
from math import sqrt

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

#: Frozen 2026-08-27 against 298 hand labels (reports/relevance_2026-08-27.md).
#: Chosen on a deterministic half of the labels by the rule "smallest threshold
#: whose precision reaches 0.90", then measured on the half never used to choose.
#:
#:   tuning half   precision 0.900  recall 0.562   (base rate 29.6%, n=162)
#:   HELD-OUT half precision 0.781  recall 0.694   (base rate 28.6%, n=126)
#:
#: The 0.90 target did NOT generalise — held-out precision is 0.781. That is the
#: number to quote, and it is stated in METRICS.md beside every metric that
#: depends on it. It is still 2.7x the purity of the status quo, which is no
#: filter at all and therefore precision 0.286.
#:
#: Three revisions were made against these labels, and the report says so: the
#: event axis, the domain-verb additions to it (which moved no measured number),
#: and suffix matching. Held-out precision moved 0.62 -> 0.774 -> 0.774 -> 0.781.
#: Further iteration on 298 labels would be fitting noise, so it stopped here.
#:
#: Do not re-tune this against a metric. It was chosen against labels, and the one
#: way to make a relevance filter produce any ranking you like is to move this
#: number until the ranking looks right. Same warning docs/METRICS.md carries for
#: `winner_age_years`.
RELEVANCE_HIGH = 0.55
#: Below-or-equal is off-niche. Exactly zero means one whole axis found nothing,
#: which separates hard: 6.4% of those are on-niche against a 28.6% base rate.
#: Anything strictly above lands in the undecided band, which measured 37.5%
#: on-niche — close enough to that base rate to carry almost no information, which
#: is why it is excluded from numerator and denominator rather than guessed.
RELEVANCE_LOW = 0.0

_WORD = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class Score:
    """`value is None` means unscorable; `reason` then says why."""

    value: float | None
    #: Terms that produced the score. Event-axis terms are prefixed `~` so the two
    #: axes stay legible in `cluster_members.detail` without a nested structure.
    matched: dict[str, float] = field(default_factory=dict)
    reason: str | None = None
    detail: dict[str, float] = field(default_factory=dict)

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


def _singular(token: str) -> str:
    """Strip one plural/third-person suffix. Not a stemmer, and deliberately not.

    Exact token matching missed "crashes", "collapses", "sinks" — the same event
    written in the present tense. A real stemmer would also collapse "collapsed"
    into "collaps" and start matching things nobody wrote down, which is the kind
    of silent broadening a frozen lexicon exists to prevent. Two suffixes, applied
    to both sides, and nothing else.
    """
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _matches(text: str, weights: dict[str, float]) -> dict[str, float]:
    """Distinct terms present, not occurrences.

    A description repeating "plane" thirty times is one piece of evidence, not
    thirty; naming three distinct aviation concepts is three. Multi-word entries
    match as phrases, single words against the token set.
    """
    normalised = normalise(text)
    words = normalised.split()
    tokens = set(words) | {_singular(w) for w in words}
    padded = f" {normalised} "
    found = {}
    for term, weight in weights.items():
        if weight <= 0:
            continue
        hit = f" {term} " in padded if " " in term else _singular(term) in tokens
        if hit:
            found[term] = weight
    return found


def _capped(matched: dict[str, float], cap: float) -> float:
    """Sum of the strongest matches, up to `cap` worth of evidence."""
    return min(sum(sorted(matched.values(), reverse=True)), cap)


def _axis(title: str, description: str, weights: dict[str, float]) -> tuple[float, dict]:
    """Saturating evidence on one axis, and the terms that produced it."""
    in_title = _matches(title, weights)
    in_description = _matches(description, weights)
    # A term already credited in the title is not credited again below it.
    only_description = {t: w for t, w in in_description.items() if t not in in_title}
    raw = TITLE_WEIGHT * _capped(in_title, TITLE_CAP) + _capped(only_description, DESCRIPTION_CAP)
    matched = {t: TITLE_WEIGHT * w for t, w in in_title.items()} | only_description
    return raw / (raw + HALF), matched


def score(
    title: str | None,
    description: str | None,
    weights: dict[str, float],
    event: dict[str, float] | None = None,
) -> Score:
    """Relevance of one video's text to one cluster's niche.

    `event` defaults to `lexicon.event_weights()`. It is a parameter rather than an
    import so the function stays pure and a test can vary one axis at a time.
    """
    if not (title or "").strip():
        return Score(None, reason="unscorable: no title")
    share = _latin_share(title)
    if share is None:
        return Score(None, reason="unscorable: title has no letters")
    if share < 0.5:
        # An English lexicon cannot read this. Scoring it 0 would call it off-niche.
        return Score(None, reason="unscorable: non-Latin script")

    if event is None:
        from nh.clustering.lexicon import event_weights

        event = event_weights()
    domain, domain_terms = _axis(title, description or "", weights)
    failure, event_terms = _axis(title, description or "", event)
    return Score(
        sqrt(domain * failure),
        domain_terms | {f"~{t}": w for t, w in event_terms.items()},
        detail={"domain": round(domain, 4), "event": round(failure, 4)},
    )
