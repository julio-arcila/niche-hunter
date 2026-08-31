"""Per-niche vocabulary, and how much each term is worth as evidence.

A frozen literal, curated the same way `nh/seeds.py::SEEDS` and `TERMS` are. It is
data, not code, and it is the thing a reviewer should argue with — every supply
number now depends on it, so a definition that lived only inside a scoring function
could not be reviewed at all.

**Weights are a pure function of this file, never of the corpus.** The obvious
alternative, IDF over the collected videos, is rejected deliberately: it drifts as
the corpus grows, so the same video would score differently on two different days
and a Slice 6 replay of a historical date could not reproduce the decision that was
actually made. Discriminative weight here is instead a function of how many lexicons **in the
family being computed** contain the term — 16 of them today, five when this was
written, and the number is a parameter rather than a constant precisely so it can
change without anyone editing this paragraph:

    k = 1 (unique to one niche)  -> 1.00    strong evidence
    k = 2                        -> 0.50    half a vote
    k = 3                        -> 0.33
    ...
    k = every lexicon in family  -> 0.00    genre vocabulary, no evidence

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

LEXICON_VERSION = "2026-08-28.3"

#: Failure and case markers, shared by all five niches by construction.
#:
#: This is the second axis, and it was added because the first one alone did not
#: work. Measured against 298 hand labels, a domain-only scorer topped out at
#: precision 0.62 (F1-optimal) and every false positive had the same shape:
#: on-domain, off-niche. "Changi Airport Plane Spotting", "Why Concrete Needs
#: Steel Reinforcement", "Settlement vs Adjudication", "What's Swiggy's Secret" —
#: all squarely inside their niche's vocabulary and squarely outside the niche,
#: because **the niche is domain AND event**, and a domain lexicon can only see
#: half of it.
#:
#: Note the tension these terms sit in, which is the whole reason they need their
#: own axis: they carry no power to tell one niche from another (that is why
#: `_COMMON` weighs them zero), and decisive power to tell a failure from a
#: tutorial. Two different questions, so two different vocabularies.
EVENT: tuple[str, ...] = (
    "crash",
    "crashed",
    "collapse",
    "collapsed",
    "sank",
    "sunk",
    "sinking",
    "wreck",
    "wreckage",
    "explosion",
    "exploded",
    "blast",
    "fire",
    "burned",
    "disaster",
    "catastrophe",
    "catastrophic",
    "tragedy",
    "tragic",
    "accident",
    "incident",
    "killed",
    "died",
    "death",
    "deaths",
    "dead",
    "fatal",
    "fatality",
    "victims",
    "survivors",
    "survived",
    "doomed",
    "deadly",
    "lost",
    "failure",
    "failed",
    "fault",
    "flaw",
    "defect",
    "defective",
    "malfunction",
    "emergency",
    "mayday",
    "distress",
    "rescue",
    "evacuation",
    "aftermath",
    "investigation",
    "investigators",
    "inquiry",
    "inquest",
    "probe",
    "cause",
    "blame",
    "responsible",
    "negligence",
    "warning",
    "ignored",
    "mistake",
    "error",
    "cover up",
    "coverup",
    "whistleblower",
    "fraud",
    "scandal",
    "scam",
    "swindle",
    "bankruptcy",
    "bankrupt",
    "insolvent",
    "collapsed",
    "ruin",
    "downfall",
    "convicted",
    "guilty",
    "verdict",
    "sentenced",
    "trial",
    "lawsuit",
    "charges",
    "indicted",
    "sued",
    "prosecuted",
)

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
    # Replaced `court-cases` on 2026-08-28 (ADR-0028). ADR-0024 split that seed
    # because its demand articles were civics and its supply was contemporary trial
    # coverage; this is the half the supply actually was. The civics half
    # (`landmark-court-cases`) is deactivated, so its vocabulary — lawsuit, supreme
    # court, precedent, statute, constitutional, appeal, plaintiff, settlement,
    # damages, injunction, legal, law, litigation, landmark case — is deliberately
    # NOT re-homed here: importing it would rebuild the civil-litigation
    # false-positive shape ADR-0018 recorded.
    #
    # Also deliberately absent, and load-bearing: `fraud`, `embezzlement`,
    # `whistleblower` and `scandal` all sit in `corporate-collapse` at weight 1.00,
    # so adding any of them here would halve it for both. A white-collar trial
    # belongs to the niche that owns that vocabulary. Likewise absent is crime-NEWS
    # vocabulary — police, crime, criminal, killer, victim, arrest — which produces
    # the on-domain/off-niche shape: a Boeing "criminal investigation" video must
    # not clear this niche's domain axis.
    #
    # Five terms (trial, verdict, guilty, convicted, sentenced) are also in `EVENT`
    # and therefore satisfy both axes alone. That is precedented and intended —
    # every live lexicon overlaps EVENT (2 to 8 terms) and the retired court-cases
    # entry overlapped on four of these five. It is why "plane crash" scores from
    # two words.
    "true-crime-trials": (
        "court",
        "courtroom",
        "trial",
        "judge",
        "jury",
        "juror",
        "verdict",
        "guilty",
        "acquitted",
        "conviction",
        "convicted",
        "sentence",
        "sentenced",
        "sentencing",
        "mistrial",
        "arraignment",
        "deliberation",
        "bail",
        "prosecutor",
        "attorney",
        "lawyer",
        "defence",
        "defense",
        "defendant",
        "testimony",
        "witness",
        "evidence",
        "hearing",
        "indictment",
        "plea",
        "cross examination",
        "subpoena",
        "murder",
        "homicide",
        "manslaughter",
        "true crime",
        "detective",
        "forensic",
        "interrogation",
        "confession",
        "bodycam",
    ),
    # --- the eleven-domain pivot (ADR-0033) ---------------------------------
    "philosophy-of-science": (
        "falsification",
        "falsifiability",
        "paradigm",
        "popper",
        "kuhn",
        "hypothesis",
        "empirical",
        "experiment",
        "theory",
        "scientific method",
        "induction",
        "deduction",
        "demarcation",
        "replication",
        "reproducibility",
        "peer review",
        "positivism",
        "realism",
        "instrumentalism",
        "underdetermination",
        "observation",
        "empirical evidence",
        "causation",
        "explanation",
        "prediction",
        "law of nature",
        "scientific revolution",
        "incommensurability",
        "bayesian",
        "confirmation",
        "anomaly",
        "methodology",
        "objectivity",
    ),
    "esoterism-spirituality": (
        "occult",
        "esoteric",
        "hermetic",
        "hermeticism",
        "alchemy",
        "kabbalah",
        "gnostic",
        "gnosticism",
        "mysticism",
        "mystic",
        "initiation",
        "ritual",
        "magic",
        "magick",
        "tarot",
        "astrology",
        "theosophy",
        "rosicrucian",
        "arcane",
        "symbolism",
        "archetype",
        "spirit",
        "spiritual",
        "meditation",
        "consciousness",
        "enlightenment",
        "divination",
        "sigil",
        "thelema",
        "occultism",
        "sacred",
        "transcendence",
        "esoterica",
        "initiate",
    ),
    "metaphysical-battles": (
        "worldview",
        "materialism",
        "idealism",
        "dualism",
        "monism",
        "physicalism",
        "naturalism",
        "supernatural",
        "theism",
        "atheism",
        "ontology",
        "being",
        "substance",
        "essence",
        "existence",
        "reality",
        "free will",
        "determinism",
        "emergence",
        "panpsychism",
        "reductionism",
        "teleology",
        "cosmology",
        "first cause",
        "necessity",
        "contingency",
        "universals",
        "nominalism",
        "phenomenology",
        "transcendental",
        "immanence",
        "metaphysical",
        "mind body",
        "consciousness",
    ),
    "logic-linguistics-gnoseology": (
        "logic",
        "syllogism",
        "inference",
        "premise",
        "conclusion",
        "validity",
        "soundness",
        "fallacy",
        "propositional",
        "predicate",
        "quantifier",
        "modal",
        "semantics",
        "syntax",
        "pragmatics",
        "grammar",
        "morphology",
        "phonology",
        "linguistics",
        "language",
        "meaning",
        "reference",
        "truth value",
        "knowledge",
        "justification",
        "belief",
        "epistemic",
        "gettier",
        "skepticism",
        "a priori",
        "a posteriori",
        "analytic",
        "synthetic",
        "proposition",
    ),
    "history-of-ideas": (
        "intellectual history",
        "enlightenment",
        "renaissance",
        "scholasticism",
        "humanism",
        "romanticism",
        "modernity",
        "postmodernism",
        "zeitgeist",
        "canon",
        "tradition",
        "genealogy",
        "historiography",
        "thinker",
        "treatise",
        "manuscript",
        "salon",
        "academy",
        "movement",
        "school of thought",
        "reception",
        "influence",
        "precursor",
        "periodization",
        "secularization",
        "discourse",
        "episteme",
        "milieu",
        "doctrine",
        "philosopher",
        "idea",
        "corpus",
        "commentary",
        "polemic",
    ),
    "anthropocene-anthropology": (
        "anthropology",
        "ethnography",
        "fieldwork",
        "kinship",
        "culture",
        "cultural",
        "society",
        "tribe",
        "indigenous",
        "archaeology",
        "artifact",
        "hominin",
        "prehistory",
        "holocene",
        "anthropocene",
        "climate",
        "extinction",
        "biodiversity",
        "ecosystem",
        "sustainability",
        "planetary boundary",
        "geology",
        "strata",
        "human impact",
        "deforestation",
        "carbon",
        "epoch",
        "civilization",
        "ritual",
        "material culture",
        "subsistence",
        "urbanization",
    ),
    "macro-economy": (
        "macroeconomics",
        "inflation",
        "deflation",
        "gdp",
        "monetary policy",
        "fiscal policy",
        "central bank",
        "interest rate",
        "recession",
        "unemployment",
        "stagflation",
        "currency",
        "exchange rate",
        "debt",
        "deficit",
        "bond",
        "yield",
        "quantitative easing",
        "liquidity",
        "trade balance",
        "tariff",
        "keynesian",
        "business cycle",
        "output gap",
        "productivity",
        "sovereign debt",
        "credit",
        "money supply",
        "economy",
        "economic growth",
        "stimulus",
        "austerity",
    ),
    "trading": (
        "trading",
        "trader",
        "day trading",
        "swing trading",
        "scalping",
        "stop loss",
        "take profit",
        "leverage",
        "margin",
        "futures",
        "options",
        "derivatives",
        "candlestick",
        "chart",
        "technical analysis",
        "indicator",
        "moving average",
        "rsi",
        "macd",
        "support",
        "resistance",
        "breakout",
        "backtest",
        "algorithmic",
        "order book",
        "liquidity",
        "volatility",
        "risk management",
        "portfolio",
        "drawdown",
        "entry",
        "exit",
        "position sizing",
    ),
    "ai-and-software": (
        "machine learning",
        "neural network",
        "deep learning",
        "transformer",
        "training",
        "inference",
        "dataset",
        "gradient",
        "backpropagation",
        "llm",
        "embedding",
        "fine tuning",
        "prompt",
        "token",
        "gpu",
        "algorithm",
        "software",
        "code",
        "programming",
        "framework",
        "api",
        "deployment",
        "agent",
        "benchmark",
        "overfitting",
        "parameter",
        "architecture",
        "open source",
        "compiler",
        "artificial intelligence",
        "agi",
        "model",
    ),
    "biohacking": (
        "biohacking",
        "nootropic",
        "supplement",
        "longevity",
        "healthspan",
        "lifespan",
        "fasting",
        "ketogenic",
        "metabolic",
        "mitochondria",
        "sleep",
        "circadian",
        "glucose",
        "insulin",
        "peptide",
        "sarms",
        "testosterone",
        "cortisol",
        "microbiome",
        "epigenetic",
        "methylation",
        "senescence",
        "telomere",
        "wearable",
        "protocol",
        "stack",
        "dosage",
        "biomarker",
        "optimization",
        "recovery",
        "hormesis",
        "supplementation",
    ),
    "geopolitics": (
        "geopolitics",
        "geopolitical",
        "sovereignty",
        "alliance",
        "nato",
        "sanctions",
        "diplomacy",
        "treaty",
        "border",
        "territory",
        "hegemony",
        "multipolar",
        "sphere of influence",
        "strategic",
        "military",
        "deterrence",
        "proliferation",
        "energy security",
        "energy pipeline",
        "chokepoint",
        "realpolitik",
        "balance of power",
        "containment",
        "insurgency",
        "conflict",
        "war",
        "statecraft",
        "intelligence",
        "great power",
        "foreign policy",
        "bloc",
        "escalation",
    ),
}


#: The second axis for **topic** families, and the counterpart to `EVENT` above.
#:
#: `EVENT` asks "did something fail". Measured 2026-08-28 against 120 real discovered
#: videos from the pivot domains, it matches **1 of 120** titles — and `score()` is a
#: geometric mean, so 119 of 120 scored 0.0 however well their domain axis fitted
#: (ADR-0033). Philosophy, trading, geopolitics and biohacking are not about things
#: failing. This axis asks the question that does transfer: **is this explaining
#: something**.
#:
#: Every marker traces to a clause of `reports/labelling_criterion_topic_domains_v4.md`,
#: which was written before any row was labelled, so the labelled rows were a test set
#: rather than a training set. Held-out on 107 labels (base rate 0.523), `domain x
#: exposition` scored P 0.866 / R 0.736 / F1 0.794 against a domain-alone baseline of
#: 0.549 / 0.807 / 0.652, winning 168 of 200 splits; replicated under a second rule and
#: rater at kappa 0.845. Reproduce with `scripts/eval_topic_axis.py`.
#:
#: **These were MACHINE labels.** `EVENT`'s 0.781 rests on 298 human ones. The two
#: figures are also at different base rates (0.286 vs 0.523) and are not comparable.
#: That gap is why every consumer of this axis is inactive — see the deferral register.
#:
#: The negative markers that the criterion leans on hardest — selling, tool tutorials,
#: signals — are deliberately NOT here. Measured, adding them buys 0.035 precision for
#: 0.051 recall and loses on F1 (0.777 vs 0.794), because an exposition signal already
#: excludes most of what they catch. Recorded so it is not re-litigated.
EXPOSITION: tuple[str, ...] = (
    "explained",
    "explain",
    "explains",
    "explaining",
    "why",
    "how",
    "what is",
    "what are",
    "introduction",
    "intro to",
    "lecture",
    "analysis",
    "analyse",
    "analyzed",
    "critique",
    "debate",
    "understanding",
    "understand",
    "theory",
    "evidence",
    "research",
    "study",
    "mechanism",
    "framework",
    "breakdown",
    "deep dive",
    "discussion",
    "essay",
    "guide",
    "history of",
    "meaning",
    "argument",
    "case for",
    "case against",
    "review of",
)

#: Which second axis each niche is scored against. **Total over `LEXICONS` by test**, so
#: a new lexicon cannot land without declaring its family.
#:
#: A registry rather than a seed field or an inference, and both alternatives were
#: rejected on evidence. A **seed field** would put part of the scoring definition in a
#: database row applied by `nh seed`, where it could drift out from under
#: `LEXICON_VERSION` — and the backtest niches have no seeds at all yet must be scorable.
#: **Inferring** the family from lexicon content fails on this repo's own data: the live
#: lexicons deliberately share 2-8 terms with `EVENT`, so any overlap rule is a silent
#: flip waiting on an innocent vocabulary edit.
#:
#: There is no default. A niche whose family is unset is skipped loudly at the phase
#: boundary, never guessed: defaulting to `event` would reproduce ADR-0033's measured
#: failure invisibly — every video marked noise, the cluster retired as empty, and a
#: pipeline that collects nothing while looking like one that works.
AXES: dict[str, str] = {
    # The five live niches. `EVENT` measured against 298 human labels, held-out
    # precision 0.781 (reports/relevance_2026-08-27.md).
    "aviation-disasters": "event",
    "maritime-disasters": "event",
    "corporate-collapse": "event",
    "engineering-failures": "event",
    "true-crime-trials": "event",
    # `landmark-court-cases` is deliberately absent: ADR-0028 removed its lexicon when
    # it was retired, and this registry is keyed on LEXICONS, not on seeds. A retired
    # niche with no lexicon has nothing to score and so has no axis to declare.
    # The eleven-domain pivot. `EXPOSITION`, 107 machine labels, held-out 0.866.
    # ACTIVE and collecting since ADR-0040 — an earlier version of this comment said
    # "all inactive pending human validation (ADR-0034)", which stopped being true the
    # day they were activated. The validation itself is still outstanding: a human
    # labels a 99-row sample under ADR-0042's two-pass criterion, and until it clears a
    # 95% Wilson lower bound of 0.70 these scores ship nothing.
    "philosophy-of-science": "exposition",
    "esoterism-spirituality": "exposition",
    "metaphysical-battles": "exposition",
    "logic-linguistics-gnoseology": "exposition",
    "history-of-ideas": "exposition",
    "anthropocene-anthropology": "exposition",
    "macro-economy": "exposition",
    "trading": "exposition",
    "ai-and-software": "exposition",
    "biohacking": "exposition",
    "geopolitics": "exposition",
}


def second_axis(slug: str) -> tuple[str, dict[str, float]]:
    """`(axis_name, weights)` for one niche. Raises `KeyError` if the family is unset.

    Loud rather than defaulting, for the reason in `AXES`: a guessed axis is the one
    failure mode that looks exactly like a working pipeline.
    """
    name = AXES[slug]
    return name, {"event": event_weights, "exposition": exposition_weights}[name]()


def exposition_weights() -> dict[str, float]:
    """Every exposition marker weighs 1.0, for the same reason `event_weights` does.

    The axis asks a binary question about the video — is this an explanation — not a
    comparison between niches, so there is nothing for a term to be discriminative
    *against*. It is also how the 0.866 was measured: graded weights would put an
    unmeasured scorer behind a measured citation.

    Deliberately not routed through `weights()`. Axis vocabularies are shared by every
    niche in their family by construction, so `1/k` would drive every term to 0.0 and
    collapse the axis entirely.
    """
    return dict.fromkeys(EXPOSITION, 1.0)


def event_weights() -> dict[str, float]:
    """Every event marker weighs 1.0.

    No discriminative weighting here, and deliberately so: the question this axis
    answers is "did something fail" — a binary about the video, not a comparison
    between niches — so there is nothing for a term to be discriminative *against*.
    """
    return dict.fromkeys(EVENT, 1.0)


def weights(
    lexicons: dict[str, tuple[str, ...]] | None = None,
    common: tuple[str, ...] | None = None,
) -> dict[str, dict[str, float]]:
    """`cluster_id -> {term: weight}`, computed WITHIN one family of lexicons.

    A term's weight is `1/k` where k counts how many lexicons in the family contain
    it, and 0 when every one does. That arithmetic is why the family is a parameter
    rather than a global read of `LEXICONS`.

    **Adding lexicons to the family silently re-weights the existing ones.** Slice 6
    needs ~30 backtest niches, and putting them in `LEXICONS` would have done this,
    measured:

        term     five lexicons    with 30 more
        crash    1.00             0.032
        runway   1.00             1.00

    `crash` is a core aviation term; dividing its weight by 31 guts that niche's
    relevance scores. Every live `supply.*` number would move, and `LEXICON_VERSION`
    would not necessarily be bumped, because nobody edited a live lexicon. Note it
    is the shared DOMAIN terms that dilute — `_COMMON` stays at 0.0, because
    `weights()` unions it into every lexicon so `shared[term] == total` still holds.

    So backtest families pass their own dict and never touch the live one.
    """
    lexicons = LEXICONS if lexicons is None else lexicons
    common = _COMMON if common is None else common
    if len(lexicons) < 2:
        # Every term would be in every lexicon, so `shared == total` for all of
        # them and the whole family scores 0.0 — the domain axis collapses and
        # every relevance score becomes 0, silently. There is nothing for a
        # discriminative weight to discriminate against with one lexicon.
        raise ValueError(
            f"a lexicon family needs at least two members to weigh terms against "
            f"each other; got {len(lexicons)}"
        )
    lexicons = {slug: set(terms) | set(common) for slug, terms in lexicons.items()}
    total = len(lexicons)
    shared: dict[str, int] = {}
    for terms in lexicons.values():
        for term in terms:
            shared[term] = shared.get(term, 0) + 1
    return {
        slug: {term: 0.0 if shared[term] == total else 1.0 / shared[term] for term in terms}
        for slug, terms in lexicons.items()
    }
