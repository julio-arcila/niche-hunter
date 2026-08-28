"""The prefilter must be a necessary condition, not a heuristic.

Scoring 73M videos against 36 lexicons is 2.6 billion `score()` calls, so the scan
skips niches whose score cannot exceed zero. That is safe only if "cannot exceed
zero" is provably true — otherwise the backtest is measuring a scorer that is not
the product, and the whole exercise is unattributable.

`test_prefilter_is_exact` is the load-bearing one: for every text, the set of
niches the prefilter admits must be a superset of the niches that actually score
above zero. It is checked against the real `relevance.score`, never a
reimplementation of it.
"""

from __future__ import annotations

import gzip
import json

import pytest

from nh.backtest.niches import BACKTEST_NICHES, backtest_weights, by_slug
from nh.backtest.scan import candidates, scan
from nh.clustering.lexicon import event_weights
from nh.clustering.relevance import score

WEIGHTS = backtest_weights()
EVENTS = event_weights()
SLUGS = sorted(by_slug())


def _truth(title: str, description: str) -> set[str]:
    """What the real scorer says, for every niche. The thing being approximated."""
    return {
        slug
        for slug in SLUGS
        if (score(title, description, WEIGHTS[slug], EVENTS).value or 0.0) > 0.0
    }


#: Deliberately varied: on-niche for one family, on-niche for another, domain
#: without event, event without domain, empty, non-Latin, and a phrase-only hit.
TEXTS = [
    ("Reactor 4 disaster explained", "The core was destroyed and radiation killed workers."),
    ("The bridge collapsed under load", "A fatigue crack in the gusset plate failed."),
    ("How a Ponzi scheme unravels", "Investors demanded redemption and the fund collapsed."),
    ("Ransomware crippled the hospital", "The attackers demanded payment in bitcoin."),
    ("A tour of a nuclear reactor", "No incident, just an explainer about the core."),
    ("Tragic fire kills three", "No domain vocabulary at all here."),
    ("", ""),
    ("क्या पंखा आपको ज्यादा गरमी", "non-Latin script"),
    ("Inside mission control", "The launch was scrubbed after an anomaly report."),
    (
        "Level crossing collision investigation",
        "The signal passed at danger and the train derailed.",
    ),
]


@pytest.mark.parametrize(("title", "description"), TEXTS, ids=lambda t: str(t)[:28])
def test_the_prefilter_admits_everything_that_actually_scores(title, description):
    """A false negative here silently drops a niche from a video, which biases
    membership and therefore every supply metric downstream."""
    admitted = set(candidates(title, description))
    assert _truth(title, description) <= admitted


def test_the_prefilter_is_not_vacuous():
    """A prefilter that admits everything is exact and useless. It has to actually
    reject, or the 2.6 billion calls are still being made."""
    rejected = [t for t in TEXTS if not candidates(*t)]
    assert rejected, "the prefilter never rejects anything"
    narrowed = [t for t in TEXTS if 0 < len(candidates(*t)) < len(SLUGS)]
    assert narrowed, "the prefilter never narrows to a subset"


def test_a_domain_event_word_missing_from_EVENT_is_rejected():
    """A real limitation, pinned so it is a known quantity rather than a surprise.

    `meltdown` is in the nuclear-accidents DOMAIN lexicon but not in the shared
    EVENT list, so a video titled "Reactor meltdown explained" scores zero unless it
    also carries a generic event word. EVENT is deliberately NOT extended here: it
    is an input to the live scorer, whose 0.781 precision was measured against the
    current list, and METRICS.md forbids re-tuning it against a metric. The effect
    is a recall floor on the backtest, and it belongs in the report.
    """
    assert "meltdown" not in event_weights()
    assert candidates("Reactor meltdown explained", "The core was destroyed.") == []


def test_a_video_with_no_event_term_is_rejected_outright():
    """`score` is sqrt(domain * event), so no event term means zero for every
    niche — the single biggest saving, and the one most worth asserting."""
    assert candidates("A tour of a nuclear reactor core", "Routine explainer.") == []


def test_a_zero_weight_term_cannot_admit_a_video():
    """`_matches` skips terms weighing 0, so the genre words must not admit anything
    — otherwise the prefilter passes work the scorer will always score zero."""
    assert candidates("documentary analysis explained", "story history investigation") == []


def test_scan_writes_one_row_per_scoring_pair(tmp_path):
    source = tmp_path / "meta.jsonl.gz"
    with gzip.open(source, "wt") as handle:
        for i in range(3):
            handle.write(
                json.dumps(
                    {
                        "display_id": f"v{i}",
                        "channel_id": "UCa",
                        "title": "Reactor disaster explained",
                        "description": "Radiation killed workers after the accident.",
                        "upload_date": "2018-03-04 00:00:00",
                    }
                )
                + "\n"
            )

    out = tmp_path / "scores.jsonl.gz"
    result = scan(source, out)

    assert result.videos_read == 3
    assert result.videos_scored == 3
    with gzip.open(out, "rt") as handle:
        written = [json.loads(line) for line in handle]
    assert written and all(row["relevance"] > 0 for row in written)
    assert {row["video_id"] for row in written} == {"v0", "v1", "v2"}
    assert all(row["upload_date"] == "2018-03-04" for row in written)


def test_scan_counts_every_video_against_every_niche(tmp_path):
    """The membership denominator: a channel's video count must not depend on which
    niches happened to match, or `on_niche_share` is computed over a moving base."""
    source = tmp_path / "meta.jsonl.gz"
    with gzip.open(source, "wt") as handle:
        handle.write(
            json.dumps(
                {
                    "display_id": "v1",
                    "channel_id": "UCa",
                    "title": "A cooking video",
                    "description": "Nothing relevant.",
                    "upload_date": "2018-01-01 00:00:00",
                }
            )
            + "\n"
        )

    result = scan(source, tmp_path / "out.jsonl.gz")

    assert len(result.counts) == len(BACKTEST_NICHES)
    assert all(c.videos == 1 and c.on_niche == 0 for c in result.counts.values())


def test_prefilter_is_exact_over_the_live_corpus():
    """The load-bearing test, run over real text rather than ten hand-written
    strings. Hand-written cases test what I thought of; 3,000 real titles and
    descriptions test what I did not.

    For every video, the niches the prefilter admits must be a superset of the
    niches that actually score above zero — checked against `relevance.score`
    itself, never a reimplementation.
    """
    import sqlite3
    from pathlib import Path

    db = Path("data/niche_hunter.db")
    if not db.exists():  # pragma: no cover - only on a fresh clone
        pytest.skip("no live corpus to sample")

    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    sample = connection.execute(
        "SELECT title, description FROM videos WHERE title IS NOT NULL ORDER BY video_id LIMIT 3000"
    ).fetchall()
    connection.close()
    assert len(sample) > 500, "sample too small to be worth running"

    missed = []
    narrowed = 0
    for title, description in sample:
        description = description or ""
        admitted = set(candidates(title, description))
        actual = _truth(title, description)
        if not actual <= admitted:
            missed.append((title[:60], sorted(actual - admitted)))
        if len(admitted) < len(SLUGS):
            narrowed += 1

    assert not missed, f"prefilter dropped niches that score: {missed[:5]}"
    # And it has to be doing real work, or the exactness is trivially satisfied.
    assert narrowed / len(sample) > 0.9
