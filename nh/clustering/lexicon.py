"""Per-niche vocabulary, and how much each term is worth as evidence.

A frozen literal, curated the same way `nh/seeds.py::SEEDS` and `TERMS` are. It is
data, not code, and it is the thing a reviewer should argue with — every supply
number now depends on it, so a definition that lived only inside a scoring function
could not be reviewed at all.

**Weights are a pure function of this file, never of the corpus.** The obvious
alternative, IDF over the collected videos, is rejected deliberately: it drifts as
the corpus grows, so the same video would score differently on two different days
and a Slice 6 replay of a historical date could not reproduce the decision that was
actually made. Discriminative weight here is instead a function of how many of the
five lexicons contain the term:

    k = 1 (unique to one niche)  -> 1.00    strong evidence
    k = 2                        -> 0.50    half a vote
    k = 3                        -> 0.33
    k = 4                        -> 0.25
    k = 5 (in every niche)       -> 0.00    genre vocabulary, no evidence

That last row is the point. `documentary`, `investigation`, `analysis`, `explained`,
`disaster` are what these five niches have in common, not what separates them —
they are how the seed keywords were written, and a scorer that rewarded them would
measure documentary-ness and call it topic. Putting them in every lexicon is how
this file says "worth nothing", and it is more honest than a stopword list because
the reason is visible.

Bump `LEXICON_VERSION` on any change: it is recorded in `cluster_members.detail`, so
a row's decision stays attributable to the vocabulary that produced it.
"""

from __future__ import annotations

LEXICON_VERSION = "2026-08-27.1"

#: Terms shared by all five niches, so they weigh zero. Listed once, in one place,
#: rather than repeated five times — but they are genuinely members of every
#: lexicon and `weights()` treats them as such.
_COMMON: tuple[str, ...] = (
    "disaster",
    "documentary",
    "investigation",
    "analysis",
    "explained",
    "story",
    "history",
    "failure",
    "tragedy",
    "inside",
    "truth",
    "happened",
)

#: Multi-word entries are matched as phrases against the normalised text; single
#: words are matched against its token set. Both are lowercase and unpunctuated.
LEXICONS: dict[str, tuple[str, ...]] = {
    "aviation-disasters": (
        "aviation",
        "aircraft",
        "airplane",
        "airliner",
        "plane",
        "jet",
        "flight",
        "airline",
        "airlines",
        "pilot",
        "copilot",
        "cockpit",
        "crash",
        "crashed",
        "runway",
        "airport",
        "takeoff",
        "landing",
        "stall",
        "turbulence",
        "altitude",
        "fuselage",
        "black box",
        "flight recorder",
        "air traffic control",
        "atc",
        "ntsb",
        "faa",
        "boeing",
        "airbus",
        "cessna",
        "mayday",
        "midair",
        "hijack",
        "aviation safety",
        "air crash",
        "flight deck",
        "engine failure",
        "depressurisation",
        "depressurization",
        "wreckage",
        "aircrew",
    ),
    "maritime-disasters": (
        "ship",
        "shipwreck",
        "vessel",
        "boat",
        "sank",
        "sinking",
        "sunk",
        "maritime",
        "nautical",
        "sea",
        "ocean",
        "voyage",
        "captain",
        "crew",
        "hull",
        "capsize",
        "capsized",
        "lifeboat",
        "iceberg",
        "titanic",
        "submarine",
        "submersible",
        "ferry",
        "tanker",
        "freighter",
        "cargo ship",
        "coast guard",
        "harbour",
        "harbor",
        "port",
        "navy",
        "naval",
        "sailor",
        "rogue wave",
        "man overboard",
        "distress call",
        "salvage",
        "shipping",
        "drowned",
        "abandon ship",
    ),
    "corporate-collapse": (
        "company",
        "corporate",
        "corporation",
        "business",
        "ceo",
        "executive",
        "board",
        "shareholder",
        "shareholders",
        "investor",
        "investors",
        "fraud",
        "fraudulent",
        "scandal",
        "bankruptcy",
        "bankrupt",
        "insolvent",
        "collapse",
        "collapsed",
        "accounting",
        "auditor",
        "audit",
        "sec filing",
        "ponzi",
        "embezzlement",
        "insider trading",
        "securities",
        "stock",
        "valuation",
        "startup",
        "ipo",
        "enron",
        "wirecard",
        "theranos",
        "balance sheet",
        "revenue",
        "creditors",
        "liquidation",
        "whistleblower",
        "due diligence",
        "market cap",
    ),
    "engineering-failures": (
        "engineering",
        "engineer",
        "structural",
        "structure",
        "bridge",
        "dam",
        "tower",
        "building",
        "construction",
        "concrete",
        "steel",
        "beam",
        "girder",
        "foundation",
        "collapse",
        "collapsed",
        "buckling",
        "fatigue",
        "load bearing",
        "design flaw",
        "safety factor",
        "stress",
        "corrosion",
        "weld",
        "reinforcement",
        "scaffolding",
        "demolition",
        "blueprint",
        "specification",
        "tolerance",
        "material failure",
        "catastrophic failure",
        "walkway",
        "skyscraper",
        "tunnel",
        "pipeline",
        "reactor",
        "turbine",
        "code violation",
        "inspection",
    ),
    "court-cases": (
        "court",
        "trial",
        "lawsuit",
        "case",
        "judge",
        "jury",
        "verdict",
        "sentence",
        "sentenced",
        "conviction",
        "convicted",
        "acquitted",
        "attorney",
        "lawyer",
        "prosecutor",
        "defence",
        "defense",
        "defendant",
        "plaintiff",
        "testimony",
        "witness",
        "evidence",
        "hearing",
        "appeal",
        "supreme court",
        "ruling",
        "precedent",
        "statute",
        "constitutional",
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
        "landmark case",
    ),
}


def weights() -> dict[str, dict[str, float]]:
    """`cluster_id -> {term: weight}`. Pure, and derived only from this file."""
    lexicons = {slug: set(terms) | set(_COMMON) for slug, terms in LEXICONS.items()}
    total = len(lexicons)
    shared: dict[str, int] = {}
    for terms in lexicons.values():
        for term in terms:
            shared[term] = shared.get(term, 0) + 1
    return {
        slug: {term: 0.0 if shared[term] == total else 1.0 / shared[term] for term in terms}
        for slug, terms in lexicons.items()
    }
