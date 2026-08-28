"""Score 73M YouNiverse videos against 36 niche lexicons, once.

Naively that is 2.6 billion `relevance.score()` calls. The saving is a prefilter,
and a prefilter is only safe if it is a **provable necessary condition** for a
non-zero score — otherwise "efficient ingest" quietly becomes "a different scorer",
and the backtest stops measuring the product. `tests/test_backtest_scan.py::
test_prefilter_is_exact` is what holds that line, checked against the real scorer
over every video in a sample.

The derivation, from `nh/clustering/relevance.py`:

  * `score()` returns `sqrt(domain * event)`, so `relevance > 0` requires a hit on
    **both** axes. A video with no event-axis term scores zero for every niche, and
    most videos are that.
  * `_matches` skips any term whose weight is `<= 0`, so zero-weight terms —
    `BACKTEST_COMMON`, and anything present in every lexicon of a family — can
    never produce a hit and are excluded from the prefilter.
  * a single-word term hits iff `_singular(term)` is in the token set; a phrase
    hits iff `" term "` is in the padded text. Both are computable from one
    normalisation, which is the expensive part and is done once per video.

So: normalise once, test the event axis, and only for niches whose domain axis can
possibly hit do we call the real scorer. Nothing is approximated — the prefilter
only ever skips work whose answer is provably zero.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from nh.backtest.niches import backtest_weights, by_slug
from nh.clustering.lexicon import event_weights
from nh.clustering.relevance import RELEVANCE_HIGH, _singular, normalise, score


@dataclass(slots=True)
class ChannelCounts:
    """What a channel looks like to one niche. The membership decision reads this."""

    videos: int = 0
    on_niche: int = 0
    scorable: int = 0


@dataclass(slots=True)
class ScanResult:
    videos_read: int = 0
    videos_scored: int = 0
    hits: int = 0
    #: (channel_id, slug) -> counts
    counts: dict[tuple[str, str], ChannelCounts] = field(default_factory=dict)


def _index(weights: dict[str, dict[str, float]]) -> dict[str, tuple[set[str], list[str]]]:
    """Per niche: the singular forms of its weighted single words, and its phrases.

    Zero-weight terms are dropped here rather than at match time, because
    `_matches` skips them anyway — including them would make the prefilter admit
    videos the scorer will always score zero.
    """
    index = {}
    for slug, terms in weights.items():
        singles = {_singular(t) for t, w in terms.items() if w > 0 and " " not in t}
        phrases = [t for t, w in terms.items() if w > 0 and " " in t]
        index[slug] = (singles, phrases)
    return index


def _axis_can_hit(tokens: set[str], padded: str, singles: set[str], phrases: list[str]) -> bool:
    """Exactly `_matches(...) != {}`, without building the dict."""
    if tokens & singles:
        return True
    return any(f" {phrase} " in padded for phrase in phrases)


def candidates(title: str, description: str) -> list[str]:
    """Niches whose score for this text can possibly exceed zero.

    An INVERTED INDEX rather than 36 separate set intersections. Measured on 5,000
    real videos, those intersections were 63% of the prefilter's cost — the index
    turns "for each niche, does any of its terms appear" into "for each token,
    which niches claim it", which is one pass over the video instead of 36 passes
    over the lexicons.

    Public because the exactness test calls it directly against the real scorer.
    """
    normalised = normalise(f"{title} {description}")
    words = normalised.split()
    tokens = set(words)
    tokens |= {_singular(w) for w in words}
    padded = f" {normalised} "

    event_singles, event_phrases = _EVENT_INDEX
    if tokens.isdisjoint(event_singles) and not any(
        f" {phrase} " in padded for phrase in event_phrases
    ):
        # No event-axis term anywhere: sqrt(domain * 0) == 0 for every niche. This
        # rejects 54% of real videos outright and is the single biggest saving.
        return []

    hit: set[str] = set()
    for token in tokens:
        claimed = _TERM_TO_SLUGS.get(token)
        if claimed:
            hit |= claimed
    # A phrase " a b " can only match if its first word is a token, so the substring
    # scan runs only for phrases that could possibly hit. Without this the loop
    # scanned every phrase against every video and cost more than the 36 set
    # intersections it replaced — measured, the first version was no faster at all.
    for word in tokens:
        for phrase, slugs in _PHRASE_BY_FIRST.get(word, ()):
            if not slugs <= hit and f" {phrase} " in padded:
                hit |= slugs
    return sorted(hit)


def _build_indexes() -> None:
    global _DOMAIN_INDEX, _EVENT_INDEX, _WEIGHTS, _EVENTS
    global _TERM_TO_SLUGS, _PHRASE_BY_FIRST
    _WEIGHTS = backtest_weights()
    _EVENTS = event_weights()
    _DOMAIN_INDEX = _index(_WEIGHTS)
    _TERM_TO_SLUGS = {}
    by_phrase: dict[str, set[str]] = {}
    for slug, (singles, phrases) in _DOMAIN_INDEX.items():
        for term in singles:
            _TERM_TO_SLUGS.setdefault(term, set()).add(slug)
        for phrase in phrases:
            by_phrase.setdefault(phrase, set()).add(slug)
    _PHRASE_BY_FIRST = {}
    for phrase, slugs in by_phrase.items():
        _PHRASE_BY_FIRST.setdefault(phrase.split()[0], []).append((phrase, slugs))
    singles = {_singular(t) for t, w in _EVENTS.items() if w > 0 and " " not in t}
    phrases = [t for t, w in _EVENTS.items() if w > 0 and " " in t]
    _EVENT_INDEX = (singles, phrases)


_WEIGHTS: dict[str, dict[str, float]] = {}
_EVENTS: dict[str, float] = {}
_DOMAIN_INDEX: dict[str, tuple[set[str], list[str]]] = {}
_EVENT_INDEX: tuple[set[str], list[str]] = (set(), [])
#: Inverted: a token -> the niches whose lexicon contains it; and a phrase's FIRST
#: word -> the phrases starting with it, so a phrase is only scanned when it could
#: possibly match.
_TERM_TO_SLUGS: dict[str, set[str]] = {}
_PHRASE_BY_FIRST: dict[str, list[tuple[str, set[str]]]] = {}
_build_indexes()


def rows(path: Path) -> Iterator[dict]:
    """Stream the gzip. Never decompressed to disk — 13.6 GB becomes ~90 GB."""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def scan(path: Path, out: Path, *, limit: int | None = None) -> ScanResult:
    """One pass: score what can score, write the hits, tally per channel.

    Writes `(video_id, channel_id, slug, upload_date, relevance)` for every
    non-zero score. Descriptions are never stored — the three relevance thresholds
    are read-time cuts on the stored score, so nothing needs the text again.
    """
    result = ScanResult()
    out.parent.mkdir(parents=True, exist_ok=True)
    known = set(by_slug())
    with gzip.open(out, "wt", encoding="utf-8") as sink:
        for row in rows(path):
            if limit is not None and result.videos_read >= limit:
                break
            result.videos_read += 1
            title = row.get("title") or ""
            description = row.get("description") or ""
            channel_id = row.get("channel_id")
            if not channel_id:
                continue
            possible = candidates(title, description)
            for slug in known:
                counts = result.counts.setdefault((channel_id, slug), ChannelCounts())
                counts.videos += 1
            if not possible:
                continue
            result.videos_scored += 1
            for slug in possible:
                value = score(title, description, _WEIGHTS[slug], _EVENTS).value
                if not value:
                    continue
                result.hits += 1
                counts = result.counts[(channel_id, slug)]
                counts.scorable += 1
                if value >= RELEVANCE_HIGH:
                    counts.on_niche += 1
                sink.write(
                    json.dumps(
                        {
                            "video_id": row.get("display_id"),
                            "channel_id": channel_id,
                            "slug": slug,
                            "upload_date": (row.get("upload_date") or "")[:10],
                            "relevance": round(value, 4),
                        }
                    )
                    + "\n"
                )
    return result
