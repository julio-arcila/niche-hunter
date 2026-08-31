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
from functools import lru_cache
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


@lru_cache(maxsize=16)
def normalise(text: str) -> str:
    """Lowercase, punctuation to spaces. Emoji and hashtags fall out as separators.

    Cached, and the tiny `maxsize` is the point rather than a compromise. Titles are
    nearly all distinct, so a large cache would miss on every new video and pay for
    the privilege. What repeats is *within* one video: the scan prefilters a title
    once and then scores it against each niche whose prefilter it cleared, and every
    one of those re-normalises the same title and description. Sixteen entries hold
    the current video's two strings with room to spare, so the repeats hit and the
    next video evicts them. Measured: `re.sub` was the largest remaining cost in the
    scan after `_singular` was cached.
    """
    return _WORD.sub(" ", text.lower()).strip()


#: Function words that decide whether a Latin-script title is written in a language
#: the English lexicon cannot read. Frozen literals rather than a language-detection
#: dependency, for the same reason `LEXICONS` is data and not a model: a reviewer can
#: argue with a word list, and a statistical model drifts between versions and would
#: silently change frozen replays.
#:
#: Entries are stored already diacritic-folded ("fur", "uber", "nao", "voce", "perche",
#: "piu", "tres", "asi"), because that is the form `_fold_tokens` produces.
#:
#: **No token shorter than three characters, and no token that is also an English word,
#: a common proper-noun fragment, or a romanised-Hindi particle.** That rule replaced an
#: earlier hand-curated list, and the reason is worth keeping. The first version was
#: edited until three canaries read zero — no on-niche row caught, no romanised-Indic
#: row, no row of the drawn validation sample — and review pointed out that a number
#: obtained by editing until it reads zero is a training-set number, not a safety
#: margin. It was right: the canaries stayed green while 9 of 11 constructed English
#: titles fired, because `Las Vegas`, `al-Assad`, `Su-24`, `die cast`, `.com`, `Per` and
#: `ET302` all yield function words once digits and punctuation become separators.
#: Twenty-two such tokens went first — las, al, su, es, son, sin, come, per, die, hat,
#: est, il, sa, os, da, na, ed, com, comment, el, los, et — taking a constructed-English
#: attack from 9/11 to 0/11. Review then drew a SECOND set of English titles, and 10 of
#: 11 fired: `Du Pont, La Porte`, `Le Mans, La Sarthe`, `Del Rio, La Joya`, `Der Spiegel
#: im focus`, `Di Maio and La Russa`. The first block had been used to CHOOSE the 22
#: removals, so it was in-sample and could not have caught them. Every remaining
#: two-character token was then dropped as well, which is what makes the rule above true
#: as written rather than aspirational.
#:
#: Total cost 368 rows of catch (1,347 -> 979, 27%); benefit, both attack sets go to
#: zero and all five target languages are still caught on the corpus (es 267, pt 121,
#: fr 112, de 52, it 18). An earlier draft rejected the length rule for "losing a
#: language" — that was measured on ONE hand-written fixture, not the corpus, and was
#: wrong. Both attack sets are pinned in tests/test_relevance.py, because a margin
#: established by editing until a corpus count reads zero is a training-set number.
#:
#: The per-language sets deliberately OVERLAP ("como"/"para"/"por"/"que" in both es and
#: pt, "una" across three). That is why `_non_english` takes the per-language MAX rather
#: than a pooled union: pooling let one Spanish and one Italian word accumulate on
#: romanised-Hindi titles and fired the gate on them.
ENGLISH_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "is",
        "are",
        "was",
        "were",
        "and",
        "or",
        "for",
        "with",
        "how",
        "why",
        "what",
        "when",
        "where",
        "who",
        "this",
        "that",
        "these",
        "those",
        "you",
        "your",
        "it",
        "its",
        "from",
        "at",
        "by",
        "we",
        "our",
        "will",
        "can",
        "do",
        "does",
        "not",
        "be",
        "have",
        "has",
        "my",
        "they",
        "their",
        "his",
        "her",
        "him",
        "she",
        "he",
        "i",
        "about",
        "into",
        "after",
        "before",
        "if",
        "but",
        "than",
        "then",
        "there",
        "here",
        "all",
        "new",
        "more",
        "most",
        "best",
        "top",
        "vs",
    }
)

FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "es": frozenset(
        {
            "asi",
            "como",
            "con",
            "cual",
            "cuando",
            "del",
            "donde",
            "entre",
            "esta",
            "estas",
            "este",
            "estos",
            "hace",
            "hay",
            "hoy",
            "mas",
            "muy",
            "para",
            "pero",
            "por",
            "porque",
            "que",
            "quien",
            "ser",
            "sobre",
            "sus",
            "tiene",
            "toda",
            "todo",
            "todos",
            "una",
        }
    ),
    "fr": frozenset(
        {
            "aux",
            "avec",
            "ces",
            "cette",
            "chez",
            "dans",
            "des",
            "elle",
            "faire",
            "fait",
            "les",
            "leur",
            "mais",
            "notre",
            "nous",
            "pas",
            "pour",
            "pourquoi",
            "quand",
            "que",
            "qui",
            "quoi",
            "sans",
            "ses",
            "sont",
            "sous",
            "sur",
            "tous",
            "tout",
            "toute",
            "tres",
            "une",
            "votre",
            "vous",
        }
    ),
    "de": frozenset(
        {
            "aber",
            "alle",
            "auch",
            "auf",
            "aus",
            "bei",
            "das",
            "dass",
            "dem",
            "den",
            "der",
            "ein",
            "eine",
            "einem",
            "einen",
            "einer",
            "fur",
            "haben",
            "ihr",
            "ist",
            "kann",
            "mehr",
            "mit",
            "nach",
            "nicht",
            "noch",
            "nur",
            "oder",
            "sich",
            "sie",
            "sind",
            "uber",
            "und",
            "von",
            "warum",
            "wenn",
            "werden",
            "wie",
            "wir",
            "wird",
            "zum",
            "zur",
        }
    ),
    "pt": frozenset(
        {
            "aos",
            "como",
            "das",
            "dos",
            "esta",
            "este",
            "isso",
            "mais",
            "muito",
            "nao",
            "nas",
            "para",
            "pela",
            "pelo",
            "por",
            "porque",
            "quando",
            "que",
            "sao",
            "ser",
            "seu",
            "sua",
            "tem",
            "uma",
            "voce",
        }
    ),
    "it": frozenset(
        {
            "alla",
            "anche",
            "che",
            "chi",
            "con",
            "cosa",
            "dei",
            "del",
            "della",
            "delle",
            "gli",
            "molto",
            "nel",
            "nella",
            "perche",
            "piu",
            "quando",
            "questa",
            "questo",
            "sono",
            "una",
            "uno",
        }
    ),
}

_ANY_FUNCTION_WORD: frozenset[str] = frozenset().union(*FUNCTION_WORDS.values())

#: Distinct function words of one language a TITLE needs before it is called foreign.
#:
#: Two, but the honest justification is weaker than the first version of this comment
#: claimed, and the numbers are re-measured on the sets below rather than on the
#: hand-curated ones they replaced:
#:
#:   tthr  catch  en-fires  indic  ON-NICHE
#:      1   1233        47      3         1
#:      2    979        28      0         0   <- chosen
#:      3    875        25      0         0
#:
#: The earlier comment called the cliff below two "sheer" on the strength of 30 on-niche
#: rows and 32 Indic rows caught at threshold one. That was true of the old sets, and
#: dropping every token under three characters flattened it: threshold one now costs one
#: on-niche row and three Indic rows. **The word list is doing the safety work, not this
#: constant.** Two is still right — it is strictly safer than one and buys 104 rows over
#: three — but a future reader should know the margin is thin, and should re-measure
#: rather than trust this table if the sets change again.
TITLE_FOREIGN_HITS = 2
#: The same for a DESCRIPTION, which is longer and so needs more evidence. The
#: description axis is a gentle slope either way — on the final sets, 4..8 spans
#: 1,100..835 catch and 28..25 English fires with on-niche and Indic flat at zero
#: throughout — so six is the middle of a plateau rather than a tuned edge.
DESCRIPTION_FOREIGN_HITS = 6

_LETTERS = re.compile(r"[a-z]+")


@lru_cache(maxsize=16)
def _fold_tokens(text: str) -> frozenset[str]:
    """Distinct diacritic-folded words: "Cómo" -> "como", "läuft" -> "lauft".

    **Deliberately not `normalise()`.** That one substitutes `[^a-z0-9]+`, which turns
    "cómo" into "c mo" and "läuft" into "l uft" — it destroys exactly the signal this
    gate reads. Folding instead of stripping is what lets a frozen ASCII word list match
    accented text.

    Cached on the RAW string for the reason `normalise` gives: the repeats are within
    one video, when the backtest scan scores one title against every niche whose
    prefilter it cleared. Never pre-fold before calling — that splits the cache and
    defeats it. Returns a frozenset because the cached value is shared.
    """
    stripped = unicodedata.normalize("NFKD", text.casefold())
    return frozenset(_LETTERS.findall("".join(c for c in stripped if not unicodedata.combining(c))))


def _non_english(title: str, description: str | None) -> bool:
    """Is this Latin-script text written in a language the English lexicon cannot read?

    The title decides on its own when it can. The description is consulted only when the
    title is NOT clearly English — both because a short title often carries too few
    function words, and because folding every 5KB description on every row is the one
    way to make this expensive. Keep that ordering.
    """
    words = _fold_tokens(title)
    english = len(words & ENGLISH_FUNCTION_WORDS)
    foreign = len(words & _ANY_FUNCTION_WORD)
    per_language = max(len(words & group) for group in FUNCTION_WORDS.values())
    if per_language >= TITLE_FOREIGN_HITS and foreign > english:
        return True
    if foreign < english or not description:
        return False
    below = _fold_tokens(description)
    per_language = max(len(below & group) for group in FUNCTION_WORDS.values())
    return per_language >= DESCRIPTION_FOREIGN_HITS and (
        len(below & _ANY_FUNCTION_WORD) > 2 * len(below & ENGLISH_FUNCTION_WORDS)
    )


def _latin_share(text: str) -> float | None:
    """Share of the letters that are Latin. None when there are no letters at all."""
    letters = [c for c in text if unicodedata.category(c).startswith("L")]
    if not letters:
        return None
    latin = sum(1 for c in letters if "LATIN" in unicodedata.name(c, ""))
    return latin / len(letters)


@lru_cache(maxsize=500_000)
def _singular(token: str) -> str:
    """Strip one plural/third-person suffix. Not a stemmer, and deliberately not.

    Exact token matching missed "crashes", "collapses", "sinks" — the same event
    written in the present tense. A real stemmer would also collapse "collapsed"
    into "collaps" and start matching things nobody wrote down, which is the kind
    of silent broadening a frozen lexicon exists to prevent. Two suffixes, applied
    to both sides, and nothing else.

    Cached because it is pure and its inputs repeat enormously. Measured on the
    backtest scan: 35 million calls for 60,000 videos — 583 per video — and 54% of
    the whole scan's runtime. Two sources of repetition, both total: English word
    frequency is Zipfian, so the same few thousand tokens recur across every title;
    and `_matches` calls it on each *lexicon term*, which are the same ~50 fixed
    strings for every video scored. The cache changes no output — that is what
    `test_relevance.py` and the frozen 0.781 precision figure guarantee — it only
    stops the same answer being recomputed a billion times.
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
    axis: dict[str, float] | None = None,
    axis_name: str = "event",
) -> Score:
    """Relevance of one video's text to one cluster's niche.

    The second axis is **per family** (ADR-0034), and which one applies is the caller's
    decision: disaster niches ask "did something fail" (`EVENT`), topic niches ask "is
    this explaining something" (`EXPOSITION`). Passing it keeps this function pure and
    lets a test vary one axis at a time — the same reason it was already a parameter.

    `axis_name` is not decoration: it becomes the key under which the second axis lands
    in `detail`, so a stored row records which axis judged it and a later reader can
    tell a pre-change row from a post-change one without git archaeology.

    Defaults are exactly today's behaviour — `EVENT`, reported under `"event"` — so
    every existing caller and every stored row is unaffected.
    """
    if not (title or "").strip():
        return Score(None, reason="unscorable: no title")
    share = _latin_share(title)
    if share is None:
        return Score(None, reason="unscorable: title has no letters")
    if share < 0.5:
        # An English lexicon cannot read this. Scoring it 0 would call it off-niche.
        return Score(None, reason="unscorable: non-Latin script")
    if _non_english(title, description):
        # The gate above catches SCRIPTS, and for two years that was read as catching
        # languages. It is not: a Spanish or German title is ~100% Latin letters, so it
        # passed, matched nothing in an English lexicon, scored exactly 0.0, and
        # `is_noise = value <= RELEVANCE_LOW` filed it as DECIDED off-niche — precisely
        # what the comment above forbids. Measured 2026-08-31 over ENRICHED rows with an
        # exact-variant audio_lang: 854 es/fr/pt/de/it rows, none caught, 1.1%
        # on-niche against English's 22.1% (`en%`, same filter). ADR-0046.
        #
        # The reason string names no language on purpose. The word sets incidentally
        # catch Romanian, Albanian and Swahili through shared function words, which is
        # the right outcome — the lexicon cannot read those either — but naming a
        # language would sometimes be a false claim.
        return Score(None, reason="unscorable: latin-script non-english")

    if axis is None:
        from nh.clustering.lexicon import event_weights

        axis = event_weights()
    domain, domain_terms = _axis(title, description or "", weights)
    second, second_terms = _axis(title, description or "", axis)
    return Score(
        sqrt(domain * second),
        domain_terms | {f"~{t}": w for t, w in second_terms.items()},
        detail={"domain": round(domain, 4), axis_name: round(second, 4)},
    )
