"""The hand-picked starting points. Everything downstream hangs off a seed.

Each niche was chosen so that a free, dense **primary source** already exists for
it, so that `cost_risk.*` would have real material rather than niches picked for
Slice 1's convenience. `docs/SOURCES.md` lists `primary/` (ntsb, edgar,
courtlistener) under "Planned"; no such collector exists yet.

That premise held for two of the five. Tested live 2026-08-27: CourtListener's
REST API appeared to work unauthenticated and carries `dateFiled`; SEC EDGAR's
submissions and full-text endpoints work unauthenticated; NTSB's CAROL query API is
reachable but rejects documented-looking payloads and its shape is undocumented;
USCG returns 403; NIST has no API. Per-seed findings live in
`NicheSeed.primary_sources` so the research is dated and reviewable rather than
folded into a score (ADR-0020).

**The CourtListener half of that is no longer true.** Re-tested 2026-08-29
(03:30 UTC): an unauthenticated GET to `/api/rest/v4/dockets/` returns **401
"Authentication credentials were not provided"** with `WWW-Authenticate: Bearer`.
Free Law Project moved API access into memberships on 2026-05-07; free accounts get
5 req/min, 50/hour, **125/day**. The 2026-08-27 "works unauthenticated" claim
postdated that change and cannot be reproduced — either it hit a not-yet-enforced
path or it was wrong. The measurement wins. Details in `docs/SOURCES.md`.

Quota follows directly from what is here: cost is
``seeds x keywords x 2 sort orders x pages x 100 units``. Five seeds of three
keywords at one page is 30 searches, ~3,000 units, 32% of the 9,500 budget.
Adding a sixth seed is a 600-unit decision — see .claude/rules/sources.md.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.db.models import NicheSeed, SeedTerm
from nh.db.session import session_scope
from nh.db.upsert import upsert

#: `geo` is the market a niche is ABOUT, stated rather than inferred (Slice 5).
#: Slice 3 left it NULL on the grounds that geo belongs per-term where it drives a
#: request; that is still true of `seed_terms.geo`, and it turned out to leave a
#: different question unasked. Measured 2026-08-27: 234 of 719 channels are Indian
#: against 290 US, and 27% of corporate-collapse's on-niche videos use India-market
#: vocabulary, while demand is read off English Wikipedia. `supply.geo_concentration`
#: measures that divergence — it cannot be seen at all unless the seed says what it
#: intended.
#:
#: `primary_sources` records what was actually found when the sources were tried,
#: dated, rather than what Slice 1 assumed (ADR-0020).
SEEDS: tuple[dict[str, Any], ...] = (
    {
        "slug": "aviation-disasters",
        "label": "Aviation disasters",
        "keywords": [
            "aviation disasters documentary",
            "plane crash investigation",
            "air crash analysis",
        ],
        "geo": "US",
        "lang": "en",
        "active": True,
        "primary_sources": [
            {
                "name": "NTSB CAROL",
                "url": "https://data.ntsb.gov/carol-main-public/",
                "status": "exists_uncollected",
                "reviewed_on": "2026-08-27",
                "note": "query API reachable but rejects documented-looking payloads; shape undocumented",
            }
        ],
        "notes": "Primary source: NTSB accident dockets. The prototype's default niche.",
    },
    {
        "slug": "maritime-disasters",
        "label": "Maritime disasters",
        "keywords": [
            "shipwreck documentary",
            "maritime disaster investigation",
            "sinking ship analysis",
        ],
        "geo": "US",
        "lang": "en",
        "active": True,
        "primary_sources": [
            {
                "name": "US Coast Guard NCOE",
                "url": "https://www.dco.uscg.mil/",
                "status": "none_found",
                "reviewed_on": "2026-08-27",
                "note": "403 to an ordinary GET; no public API located",
            }
        ],
        "notes": "Primary source: NTSB Marine, US Coast Guard reports.",
    },
    {
        "slug": "corporate-collapse",
        "label": "Corporate collapse",
        "keywords": [
            "company collapse documentary",
            "corporate fraud explained",
            "business failure analysis",
        ],
        "geo": "US",
        "lang": "en",
        "active": True,
        "primary_sources": [
            {
                "name": "SEC EDGAR",
                "url": "https://data.sec.gov/submissions/",
                "status": "exists_uncollected",
                "reviewed_on": "2026-08-27",
                "note": "submissions and full-text search both work unauthenticated",
            }
        ],
        "notes": (
            "Primary source: SEC EDGAR filings. Measured: 27% of this niche's "
            "on-niche videos are India-market (Rajesh Exports, crore, SEBI), so a "
            "US geo understates its supply — see supply.geo_concentration."
        ),
    },
    {
        "slug": "engineering-failures",
        "label": "Engineering failures",
        "keywords": [
            "engineering disaster documentary",
            "structural failure analysis",
            "bridge collapse investigation",
        ],
        "geo": "US",
        "lang": "en",
        "active": True,
        "primary_sources": [
            {
                "name": "NIST investigations",
                "url": "https://www.nist.gov/",
                "status": "none_found",
                "reviewed_on": "2026-08-27",
                "note": "no publications API; reports are prose documents",
            }
        ],
        "notes": "Primary source: NIST investigations, NTSB.",
    },
    # Split from one `court-cases` seed in Slice 5 (ADR-0024). The old seed's label
    # and demand articles were about landmark constitutional decisions; its supply
    # was contemporary true-crime trial streaming — measured, "Lindsay Clancy"
    # appeared in 59 of 520 on-niche titles, then Mario Fernandez Saldana, the
    # Bridegan murder, Karmelo Anthony. `gap` was subtracting a supply rank for one
    # subject from a demand rank for another. Slice 3 predicted exactly this
    # ("Supreme_Court_of_the_United_States ... may be measuring civics rather than
    # the niche") and left it to be revisited once inspectable. It is now.
    {
        # DEACTIVATED 2026-08-28 (ADR-0028). Post-Gate-E its evidence page would be
        # one number and a column of NULLs: reference-article demand — the stratum
        # carrying the school-calendar and curiosity-not-intent confounders (ADR-0022)
        # — over a supply that is empty by this niche's own definition. Reactivation
        # conditions are in the deferral register, not here.
        "slug": "landmark-court-cases",
        "label": "Landmark court cases",
        "keywords": [
            "landmark supreme court case explained",
            "constitutional law case documentary",
            "precedent setting court decision",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,
        "primary_sources": [
            {
                "name": "CourtListener",
                "url": "https://www.courtlistener.com/api/rest/v4/",
                "status": "exists_uncollected",
                "reviewed_on": "2026-08-29",
                "note": (
                    "carries dateFiled, so cadence is a real series — but measured "
                    "2026-08-29 the API returns 401 unauthenticated; a free account "
                    "(125 req/day) is now required. The 2026-08-27 'unauthenticated' "
                    "finding does not reproduce"
                ),
            }
        ],
        "notes": (
            "Keeps the original demand articles. If demand here is real and the "
            "supply is elsewhere, that is the gap the product exists to find — but "
            "it has to be measured against keywords that ask for this subject."
        ),
    },
    {
        "slug": "true-crime-trials",
        "label": "True-crime trials",
        "keywords": [
            "murder trial live coverage",
            "court trial testimony analysis",
            "criminal trial verdict explained",
        ],
        "geo": "US",
        "lang": "en",
        "active": True,
        "primary_sources": [
            {
                "name": "CourtListener",
                "url": "https://www.courtlistener.com/api/rest/v4/",
                "status": "exists_uncollected",
                "reviewed_on": "2026-08-29",
                "note": (
                    "covers opinions; live trial coverage has no primary-source "
                    "equivalent. Measured 2026-08-29: 401 unauthenticated — a free "
                    "account (125 req/day) is now required"
                ),
            }
        ],
        "notes": (
            "What the old court-cases supply actually was. Demand articles are "
            "per-trial, so they are event-stratum by nature — the one niche where "
            "the topic stratum has no natural articles at all."
        ),
    },
    # --- the eleven-domain pivot (ADR-0033) ---------------------------------
    {
        "slug": "philosophy-of-science",
        "label": "Philosophy of science",
        "keywords": [
            "philosophy of science explained",
            "scientific method critique",
            "paradigm shift science",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "esoterism-spirituality",
        "label": "Esoterism and spirituality",
        "keywords": [
            "western esotericism explained",
            "occult history documentary",
            "hermeticism explained",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "metaphysical-battles",
        "label": "Metaphysical battles (clashes between worldviews)",
        "keywords": [
            "materialism vs idealism",
            "free will debate philosophy",
            "consciousness debate philosophy",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "logic-linguistics-gnoseology",
        "label": "Logic, linguistics and gnoseology",
        "keywords": [
            "logic explained philosophy",
            "epistemology explained",
            "philosophy of language explained",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "history-of-ideas",
        "label": "History of ideas",
        "keywords": [
            "history of ideas lecture",
            "intellectual history explained",
            "enlightenment philosophy history",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "anthropocene-anthropology",
        "label": "Anthropocene and anthropology",
        "keywords": [
            "anthropology explained",
            "anthropocene explained",
            "human impact environment documentary",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "macro-economy",
        "label": "Macro economy",
        "keywords": [
            "macroeconomics explained",
            "inflation explained economics",
            "monetary policy explained",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "trading",
        "label": "Trading",
        "keywords": [
            "day trading strategy explained",
            "technical analysis tutorial",
            "algorithmic trading explained",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "ai-and-software",
        "label": "AI and software",
        "keywords": [
            "large language model explained",
            "machine learning explained",
            "ai software engineering",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "biohacking",
        "label": "Biohacking",
        "keywords": [
            "biohacking protocol explained",
            "nootropics explained",
            "longevity research explained",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
    {
        "slug": "geopolitics",
        "label": "Geopolitics",
        "keywords": [
            "geopolitics explained",
            "geopolitical analysis",
            "balance of power explained",
        ],
        "geo": "US",
        "lang": "en",
        "active": False,  # blocked: exposition axis awaits human validation (ADR-0034)
        "primary_sources": [],
        "notes": "Eleven-domain pivot (ADR-0033). No primary source researched yet.",
    },
)


#: Demand-side identifiers, curated per seed. The YouTube keywords above are
#: demand-dead elsewhere — measured, most read literal zero on Trends and
#: `aviation disasters documentary` returns NaN even queried alone — so demand
#: needs its own mapping rather than reusing them (ADR-0015).
#:
#: Wikipedia articles are baskets of three: a single article can be restructured,
#: redirected or renamed and the metric would read that as a demand collapse.
#: All 15 were verified to return >=24 monthly points.
#:
#: Trends terms are broad proxies chosen to clear Trends' volume floor. Some are
#: unverified and will honestly report NULL if they sit at the quantisation floor
#: — that is the metric working, not failing.
TERMS: tuple[dict[str, Any], ...] = (
    # --- wikipedia: absolute demand level and momentum -----------------------
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "term": "Aviation_accidents_and_incidents",
    },
    {"slug": "aviation-disasters", "source": "wikipedia", "term": "Aviation_safety"},
    {"slug": "aviation-disasters", "source": "wikipedia", "term": "Air_traffic_control"},
    {"slug": "maritime-disasters", "source": "wikipedia", "term": "Shipwreck"},
    {"slug": "maritime-disasters", "source": "wikipedia", "term": "List_of_shipwrecks"},
    {"slug": "maritime-disasters", "source": "wikipedia", "term": "Maritime_transport"},
    {"slug": "corporate-collapse", "source": "wikipedia", "term": "Corporate_scandal"},
    {"slug": "corporate-collapse", "source": "wikipedia", "term": "Accounting_scandals"},
    {"slug": "corporate-collapse", "source": "wikipedia", "term": "Bankruptcy"},
    {"slug": "engineering-failures", "source": "wikipedia", "term": "Structural_failure"},
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "term": "List_of_structural_failures_and_collapses",
    },
    {"slug": "engineering-failures", "source": "wikipedia", "term": "Engineering_disasters"},
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "term": "List_of_landmark_court_decisions_in_the_United_States",
        "notes": "reference-heavy: carries school-calendar traffic, see METRICS.md failure mode",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "term": "Supreme_Court_of_the_United_States",
        "notes": (
            "broad — Slice 3 flagged that this may measure civics rather than the "
            "niche. Confirmed in Slice 5: it does, and the niche it was attached to "
            "was really about trials. It stays here, where civics IS the subject."
        ),
    },
    {"slug": "landmark-court-cases", "source": "wikipedia", "term": "Landmark_case"},
    # true-crime-trials had NO topic article until 2026-08-28: ADR-0024's split gave
    # all four civics index pages to `landmark-court-cases` and left the successor
    # with only its Trends proxy phrase ("murder trial"), which is not a Wikipedia
    # title and returned zero rows. Its event stratum worked throughout, which is why
    # the gap was invisible until the niche was reactivated and `demand` came back
    # NULL — taking `gap` and `stage` with it. Index pages about the PROCESS, matching
    # the pattern the other four use: the subject is the trial, not the crime.
    {"slug": "true-crime-trials", "source": "wikipedia", "term": "Trial_(law)"},
    {"slug": "true-crime-trials", "source": "wikipedia", "term": "Jury_trial"},
    {"slug": "true-crime-trials", "source": "wikipedia", "term": "Criminal_procedure"},
    # --- wikipedia, EVENT stratum: named occurrences, not index pages ----------
    #
    # Generated by scripts/select_demand_articles.py --k 20 --seed 20260827 and
    # pasted here, because the output is curation and this is where curation lives.
    # Uniform random sample from a class or category pool, NOT the biggest articles:
    # ranking by pageviews selects for fame, and Chernobyl and the Titanic would win
    # every niche while the real distribution never showed. Fixed K=20 everywhere so
    # `wiki_weekly_views` (a sum) and its confidence (a division by article count)
    # stay comparable across niches of wildly different pool size.
    #
    # The generator differs per niche and that is a confound, recorded rather than
    # smoothed over — three niches had a usable Wikidata class, three fell back to
    # category membership because the class was unpopulated (criminal trial has 19
    # articles) or the endpoint was rate-limiting:
    #   The sample is reproducible from that seed; the pool size is recorded per
    #   aviation-disasters: pool 2017 via wikidata:Q744913
    #   maritime-disasters: pool 104 via wikidata:Q906512
    #   corporate-collapse: pool 380 via category:Category:Corporate scandals
    #   engineering-failures: pool 151 via category:Category:Building and structure collapses
    #   landmark-court-cases: pool 3202 via wikidata:Q19692072
    #   true-crime-trials: pool 594 via category:Category:Trials by country
    #
    # Category pools are noisier by nature — 'Corporate scandals' contains
    # '35_day_month', an accounting concept rather than an event. That is what
    # a pool built from human categorisation looks like, and the sample is not
    # cleaned by hand: doing so would reintroduce exactly the selection the
    # random draw exists to avoid.
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1937_Ostend_Sabena_Junkers_Ju_52_crash",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1948_Lake_Mead_Boeing_B-29_crash",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1953_Skyways_Avro_York_disappearance",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1961_Derby_Aviation_crash",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1967_Air_Ferry_DC-4_accident",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1978_British_Army_Gazelle_downing",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1980_Camarate_plane_crash",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1982_TABA_Fairchild_FH-227_accident",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1996_Air_Africa_Antonov_An-32_crash",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2019_Alaska_mid-air_collision",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Avioimpex_Flight_110",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "China_Airlines_Flight_811",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Kolavia_Flight_348",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Pacific_Western_Airlines_Flight_501",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Philippine_Air_Lines_Flight_158",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Siberia_Airlines_Flight_852",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "South_African_Airways_Flight_201",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "TWA_Flight_427",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Turkish_Airlines_Flight_301",
    },
    {
        "slug": "aviation-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "West_Coast_Airlines_Flight_956",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2007_Malta_migrant_shipwreck",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2009_Libya_migrant_shipwreck",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2010_West_Bengal_ferry_sinking",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2011_Lampedusa_migrant_shipwreck",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2016_Egypt_migrant_shipwreck",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2021_Madagascar_shipwreck",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2023_Tunisia_migrant_boat_disasters",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2024_Lixinsha_Bridge_collapse",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Amoco_Cadiz_oil_spill",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Costa_Concordia_disaster",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Grounding_of_the_Jupiter",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "John_Minturn",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Loss_of_MV_Darlwyne",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Quebec_expedition_(1711)",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Shipwreck_of_Dellys",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Shiun_Maru_disaster",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Sinking_of_RMS_Lusitania",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Sinking_of_SS_Princess_Alice",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Table_Rock_Lake_duck_boat_accident",
    },
    {
        "slug": "maritime-disasters",
        "source": "wikipedia",
        "stratum": "event",
        "term": "USS_Hartford_grounding",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2015_FIFA_corruption_case",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "35_day_month",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Atom_Asset_Exchange",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Autonomy_Corporation",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Bubble_Companies,_etc._Act_1825",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "David_Dingwall",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Depository_Institutions_Deregulation_and_Monetary_Control_Act",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Firestone_and_Ford_tire_controversy",
    },
    {"slug": "corporate-collapse", "source": "wikipedia", "stratum": "event", "term": "Gamefam"},
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Holmes'_Bank",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Lion_Air_Flight_610",
    },
    {"slug": "corporate-collapse", "source": "wikipedia", "stratum": "event", "term": "Lou_Pai"},
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Marvin_L._Warner",
    },
    {"slug": "corporate-collapse", "source": "wikipedia", "stratum": "event", "term": "Monsanto"},
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "NSE_co-location_scam",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Parmalat_bankruptcy_timeline",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Quadriga_(company)",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Satyam_scandal",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "South_Sea_Company_(No._3)_Act_1720",
    },
    {
        "slug": "corporate-collapse",
        "source": "wikipedia",
        "stratum": "event",
        "term": "The_South_Sea_Bubble",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "1978_Holiday_Inn_fire",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2008_Yevpatoria_gas_explosion",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2018_Magnitogorsk_building_collapse",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "2026_Utrecht_explosions",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Black_Saturday_(1903)",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Brooklyn_Theatre_fire",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "CTV_Building",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Collapse_of_the_World_Trade_Center",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Dalsenget_fire",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "El_Colotero",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Georges_Anglade",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Karlslust_dance_hall_fire",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Middle_Collegiate_Church",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "National_Museum_of_Brazil",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "New_Era_Building_(New_York_City)",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "New_York_Crystal_Palace",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Terminal_Hotel_(Atlanta)",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Theogefyro",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Vajont_Dam",
    },
    {
        "slug": "engineering-failures",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Xinjiang_61st_Regiment_Farm_fire",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Aguilar_v._Felton",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Calder_v._Bull",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Cardwell_v._American_Bridge_Co.",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "City_of_Ontario_v._Quon",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Department_of_Homeland_Security_v._Thuraissigiam",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Financial_Oversight_and_Management_Board_for_Puerto_Rico_v._Aurelius_Investment,_LLC",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Gobeille_v._Liberty_Mutual_Insurance_Co.",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Griffin_v._Illinois",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Huddleston_v._United_States",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Kansas_v._Colorado",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Monasky_v._Taglieri",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "North_American_Co._v._SEC",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Rhode_Island_v._Innis",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Schneider_v._Rusk",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Skinner_v._Railway_Labor_Executives_Ass'n",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Taylor_v._Illinois",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Trop_v._Dulles",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "United_States_v._Brignoni-Ponce",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "United_States_v._Clark",
    },
    {
        "slug": "landmark-court-cases",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Yamataya_v._Fisher",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Aleksandr_Nikitin_(environmentalist)",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Arne_Treholt",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Bedok_double_murder",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Crime_of_Fuencarral_street",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Deniz_Feneri_Trials",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Eichmann_trial",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Feldmann_case",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Helao_Shityuwete",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Impeachment_of_Inger_Støjberg",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Islandmagee_witch_trial",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Marey_affair",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Parminder_Singh_Saini",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Pelicot_rape_case",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Racism-Turanism_trials",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Rokotov–Faibishenko_case",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Serge_Atlaoui",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Tommy_Weissbecker",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Trial_of_the_193",
    },
    {
        "slug": "true-crime-trials",
        "source": "wikipedia",
        "stratum": "event",
        "term": "Trial_of_the_Six",
    },
    {"slug": "true-crime-trials", "source": "wikipedia", "stratum": "event", "term": "Vågå_case"},
    # --- trends: shape only, one term per request, no anchor -----------------
    {
        "slug": "aviation-disasters",
        "source": "trends",
        "term": "plane crash",
        "notes": "measured mean 4.2 queried alone",
    },
    {
        "slug": "maritime-disasters",
        "source": "trends",
        "term": "shipwreck",
        "notes": "provisional — measured 0.0 beside a large anchor, untested alone",
    },
    {
        "slug": "corporate-collapse",
        "source": "trends",
        "term": "corporate fraud",
        "notes": "provisional — untested",
    },
    {
        "slug": "engineering-failures",
        "source": "trends",
        "term": "bridge collapse",
        "notes": "measured mean 0.1 — near the quantisation floor, expect NULL momentum",
    },
    {
        "slug": "landmark-court-cases",
        "source": "trends",
        "term": "supreme court",
        "notes": "provisional — untested",
    },
    {
        "slug": "true-crime-trials",
        "source": "trends",
        "term": "murder trial",
        "notes": "provisional — untested",
    },
    # --- keyword planner: the second vocabulary source ------------------------
    #
    # These are the 30 keywords of the 2026-08-28 US export, mapped back to the
    # niche each came from. They exist for two jobs. First, they are what
    # `keyword_metrics` joins against, so without them `nh kp ingest` reports
    # `matched a seed term: 0/30` and no money or demand metric can compute.
    # Second, they are the second vocabulary source ADR-0018 said sub-niche
    # clustering needed — "cluster YouTube titles alone and you have built a topic
    # model, not a demand-supply bridge".
    #
    # Every term is exactly what Google returned, not what was pasted in. Measured
    # 2026-08-28: 29 of 30 round-tripped byte-identically, and the exception is
    # `trial law`, which is `Trial_(law)` with the parentheses removed because the
    # Keyword Planner UI rejects them. Google's close-variant matching can reshape
    # a keyword between export and export, so a future export may not match by
    # exact string; the join normalises rather than relying on equality, and
    # unmatched keywords are stored anyway and reported by the ingest command.
    #
    # `stratum` is left to default: these are topic-level vocabulary, not the
    # named-event sample the wikipedia event stratum carries.
    #
    # `geo` is deliberately '' — curation is geo-independent (ADR-0038). A seed
    # term asserts "this niche cares about this keyword"; which market a number
    # was measured in is a property of the OBSERVATION and lives on
    # `keyword_metrics.geo`, set by `nh kp ingest --geo`. Features join seed terms
    # on (term, lang) and pick the market via a geo argument against
    # keyword_metrics. An earlier fix put geo="US" here so the ingest match report
    # would agree with a (keyword, geo, lang) join — which made the GB export
    # match 96/162 and would have required 66 duplicate rows per market. The
    # conflation, not the default, was the bug.
    {
        "slug": "aviation-disasters",
        "source": "keyword_planner",
        "term": "air crash analysis",
    },
    {
        "slug": "aviation-disasters",
        "source": "keyword_planner",
        "term": "air traffic control",
    },
    {
        "slug": "aviation-disasters",
        "source": "keyword_planner",
        "term": "aviation accidents and incidents",
    },
    {
        "slug": "aviation-disasters",
        "source": "keyword_planner",
        "term": "aviation disasters documentary",
    },
    {
        "slug": "aviation-disasters",
        "source": "keyword_planner",
        "term": "aviation safety",
    },
    {
        "slug": "aviation-disasters",
        "source": "keyword_planner",
        "term": "plane crash investigation",
    },
    {
        "slug": "corporate-collapse",
        "source": "keyword_planner",
        "term": "accounting scandals",
    },
    {"slug": "corporate-collapse", "source": "keyword_planner", "term": "bankruptcy"},
    {
        "slug": "corporate-collapse",
        "source": "keyword_planner",
        "term": "business failure analysis",
    },
    {
        "slug": "corporate-collapse",
        "source": "keyword_planner",
        "term": "company collapse documentary",
    },
    {
        "slug": "corporate-collapse",
        "source": "keyword_planner",
        "term": "corporate fraud explained",
    },
    {
        "slug": "corporate-collapse",
        "source": "keyword_planner",
        "term": "corporate scandal",
    },
    {
        "slug": "engineering-failures",
        "source": "keyword_planner",
        "term": "bridge collapse investigation",
    },
    {
        "slug": "engineering-failures",
        "source": "keyword_planner",
        "term": "engineering disaster documentary",
    },
    {
        "slug": "engineering-failures",
        "source": "keyword_planner",
        "term": "engineering disasters",
    },
    {
        "slug": "engineering-failures",
        "source": "keyword_planner",
        "term": "list of structural failures and collapses",
    },
    {
        "slug": "engineering-failures",
        "source": "keyword_planner",
        "term": "structural failure",
    },
    {
        "slug": "engineering-failures",
        "source": "keyword_planner",
        "term": "structural failure analysis",
    },
    {
        "slug": "maritime-disasters",
        "source": "keyword_planner",
        "term": "list of shipwrecks",
    },
    {
        "slug": "maritime-disasters",
        "source": "keyword_planner",
        "term": "maritime disaster investigation",
    },
    {
        "slug": "maritime-disasters",
        "source": "keyword_planner",
        "term": "maritime transport",
    },
    {"slug": "maritime-disasters", "source": "keyword_planner", "term": "shipwreck"},
    {
        "slug": "maritime-disasters",
        "source": "keyword_planner",
        "term": "shipwreck documentary",
    },
    {
        "slug": "maritime-disasters",
        "source": "keyword_planner",
        "term": "sinking ship analysis",
    },
    {
        "slug": "true-crime-trials",
        "source": "keyword_planner",
        "term": "court trial testimony analysis",
    },
    {
        "slug": "true-crime-trials",
        "source": "keyword_planner",
        "term": "criminal procedure",
    },
    {
        "slug": "true-crime-trials",
        "source": "keyword_planner",
        "term": "criminal trial verdict explained",
    },
    {"slug": "true-crime-trials", "source": "keyword_planner", "term": "jury trial"},
    {
        "slug": "true-crime-trials",
        "source": "keyword_planner",
        "term": "murder trial live coverage",
    },
    {"slug": "true-crime-trials", "source": "keyword_planner", "term": "trial law"},
    # --- the eleven-domain pivot (ADR-0033) ---------------------------------
    {"slug": "philosophy-of-science", "source": "wikipedia", "term": "Philosophy_of_science"},
    {"slug": "philosophy-of-science", "source": "wikipedia", "term": "Scientific_method"},
    {"slug": "philosophy-of-science", "source": "wikipedia", "term": "Falsifiability"},
    {"slug": "philosophy-of-science", "source": "wikipedia", "term": "Paradigm_shift"},
    {"slug": "philosophy-of-science", "source": "wikipedia", "term": "Thomas_Kuhn"},
    {"slug": "philosophy-of-science", "source": "wikipedia", "term": "Karl_Popper"},
    {"slug": "philosophy-of-science", "source": "wikipedia", "term": "Demarcation_problem"},
    {"slug": "philosophy-of-science", "source": "wikipedia", "term": "Replication_crisis"},
    {"slug": "esoterism-spirituality", "source": "wikipedia", "term": "Western_esotericism"},
    {"slug": "esoterism-spirituality", "source": "wikipedia", "term": "Occult"},
    {"slug": "esoterism-spirituality", "source": "wikipedia", "term": "Hermeticism"},
    {"slug": "esoterism-spirituality", "source": "wikipedia", "term": "Alchemy"},
    {"slug": "esoterism-spirituality", "source": "wikipedia", "term": "Kabbalah"},
    {"slug": "esoterism-spirituality", "source": "wikipedia", "term": "Gnosticism"},
    {"slug": "esoterism-spirituality", "source": "wikipedia", "term": "Mysticism"},
    {"slug": "esoterism-spirituality", "source": "wikipedia", "term": "Theosophy"},
    {"slug": "metaphysical-battles", "source": "wikipedia", "term": "Metaphysics"},
    {"slug": "metaphysical-battles", "source": "wikipedia", "term": "Philosophy_of_mind"},
    {"slug": "metaphysical-battles", "source": "wikipedia", "term": "Free_will"},
    {"slug": "metaphysical-battles", "source": "wikipedia", "term": "Determinism"},
    {"slug": "metaphysical-battles", "source": "wikipedia", "term": "Mind–body_problem"},
    {"slug": "metaphysical-battles", "source": "wikipedia", "term": "Panpsychism"},
    {"slug": "metaphysical-battles", "source": "wikipedia", "term": "Materialism"},
    {"slug": "metaphysical-battles", "source": "wikipedia", "term": "Idealism"},
    {"slug": "logic-linguistics-gnoseology", "source": "wikipedia", "term": "Logic"},
    {"slug": "logic-linguistics-gnoseology", "source": "wikipedia", "term": "Epistemology"},
    {"slug": "logic-linguistics-gnoseology", "source": "wikipedia", "term": "Linguistics"},
    {"slug": "logic-linguistics-gnoseology", "source": "wikipedia", "term": "Semantics"},
    {"slug": "logic-linguistics-gnoseology", "source": "wikipedia", "term": "Syllogism"},
    {"slug": "logic-linguistics-gnoseology", "source": "wikipedia", "term": "Gettier_problem"},
    {"slug": "logic-linguistics-gnoseology", "source": "wikipedia", "term": "Mathematical_logic"},
    {
        "slug": "logic-linguistics-gnoseology",
        "source": "wikipedia",
        "term": "Philosophy_of_language",
    },
    {"slug": "history-of-ideas", "source": "wikipedia", "term": "Intellectual_history"},
    {"slug": "history-of-ideas", "source": "wikipedia", "term": "History_of_philosophy"},
    {"slug": "history-of-ideas", "source": "wikipedia", "term": "Age_of_Enlightenment"},
    {"slug": "history-of-ideas", "source": "wikipedia", "term": "Renaissance"},
    {"slug": "history-of-ideas", "source": "wikipedia", "term": "Scholasticism"},
    {"slug": "history-of-ideas", "source": "wikipedia", "term": "Humanism"},
    {"slug": "history-of-ideas", "source": "wikipedia", "term": "Postmodernism"},
    {"slug": "history-of-ideas", "source": "wikipedia", "term": "Historiography"},
    {"slug": "history-of-ideas", "source": "wikipedia", "term": "Zeitgeist"},
    {"slug": "anthropocene-anthropology", "source": "wikipedia", "term": "Anthropology"},
    {"slug": "anthropocene-anthropology", "source": "wikipedia", "term": "Anthropocene"},
    {"slug": "anthropocene-anthropology", "source": "wikipedia", "term": "Ethnography"},
    {"slug": "anthropocene-anthropology", "source": "wikipedia", "term": "Cultural_anthropology"},
    {"slug": "anthropocene-anthropology", "source": "wikipedia", "term": "Archaeology"},
    {"slug": "anthropocene-anthropology", "source": "wikipedia", "term": "Holocene"},
    {"slug": "anthropocene-anthropology", "source": "wikipedia", "term": "Biodiversity_loss"},
    {
        "slug": "anthropocene-anthropology",
        "source": "wikipedia",
        "term": "Human_impact_on_the_environment",
    },
    {"slug": "macro-economy", "source": "wikipedia", "term": "Macroeconomics"},
    {"slug": "macro-economy", "source": "wikipedia", "term": "Inflation"},
    {"slug": "macro-economy", "source": "wikipedia", "term": "Monetary_policy"},
    {"slug": "macro-economy", "source": "wikipedia", "term": "Recession"},
    {"slug": "macro-economy", "source": "wikipedia", "term": "Gross_domestic_product"},
    {"slug": "macro-economy", "source": "wikipedia", "term": "Central_bank"},
    {"slug": "macro-economy", "source": "wikipedia", "term": "Fiscal_policy"},
    {"slug": "macro-economy", "source": "wikipedia", "term": "Quantitative_easing"},
    {"slug": "trading", "source": "wikipedia", "term": "Day_trading"},
    {"slug": "trading", "source": "wikipedia", "term": "Technical_analysis"},
    {"slug": "trading", "source": "wikipedia", "term": "Algorithmic_trading"},
    {"slug": "trading", "source": "wikipedia", "term": "Futures_contract"},
    {"slug": "trading", "source": "wikipedia", "term": "Option_(finance)"},
    {"slug": "trading", "source": "wikipedia", "term": "Volatility_(finance)"},
    {"slug": "trading", "source": "wikipedia", "term": "Risk_management"},
    {"slug": "trading", "source": "wikipedia", "term": "Candlestick_chart"},
    {"slug": "ai-and-software", "source": "wikipedia", "term": "Artificial_intelligence"},
    {"slug": "ai-and-software", "source": "wikipedia", "term": "Machine_learning"},
    {"slug": "ai-and-software", "source": "wikipedia", "term": "Deep_learning"},
    {"slug": "ai-and-software", "source": "wikipedia", "term": "Large_language_model"},
    {"slug": "ai-and-software", "source": "wikipedia", "term": "Neural_network_(machine_learning)"},
    {"slug": "ai-and-software", "source": "wikipedia", "term": "Transformer_(deep_learning)"},
    {"slug": "ai-and-software", "source": "wikipedia", "term": "Software_engineering"},
    {"slug": "ai-and-software", "source": "wikipedia", "term": "Artificial_general_intelligence"},
    {"slug": "biohacking", "source": "wikipedia", "term": "Biohacking"},
    {"slug": "biohacking", "source": "wikipedia", "term": "Nootropic"},
    {"slug": "biohacking", "source": "wikipedia", "term": "Longevity"},
    {"slug": "biohacking", "source": "wikipedia", "term": "Intermittent_fasting"},
    {"slug": "biohacking", "source": "wikipedia", "term": "Ketogenic_diet"},
    {"slug": "biohacking", "source": "wikipedia", "term": "Circadian_rhythm"},
    {"slug": "biohacking", "source": "wikipedia", "term": "Human_microbiome"},
    {"slug": "biohacking", "source": "wikipedia", "term": "Epigenetics"},
    {"slug": "geopolitics", "source": "wikipedia", "term": "Geopolitics"},
    {"slug": "geopolitics", "source": "wikipedia", "term": "Sovereignty"},
    {"slug": "geopolitics", "source": "wikipedia", "term": "NATO"},
    {
        "slug": "geopolitics",
        "source": "wikipedia",
        "term": "Balance_of_power_(international_relations)",
    },
    {"slug": "geopolitics", "source": "wikipedia", "term": "Economic_sanctions"},
    {"slug": "geopolitics", "source": "wikipedia", "term": "Deterrence_theory"},
    {"slug": "geopolitics", "source": "wikipedia", "term": "Hegemony"},
    {"slug": "geopolitics", "source": "wikipedia", "term": "Realpolitik"},
    {"slug": "philosophy-of-science", "source": "trends", "term": "philosophy of science"},
    {"slug": "esoterism-spirituality", "source": "trends", "term": "occult"},
    {"slug": "metaphysical-battles", "source": "trends", "term": "metaphysics"},
    {"slug": "logic-linguistics-gnoseology", "source": "trends", "term": "epistemology"},
    {"slug": "history-of-ideas", "source": "trends", "term": "intellectual history"},
    {"slug": "anthropocene-anthropology", "source": "trends", "term": "anthropology"},
    {"slug": "macro-economy", "source": "trends", "term": "macroeconomics"},
    {"slug": "trading", "source": "trends", "term": "day trading"},
    {"slug": "ai-and-software", "source": "trends", "term": "machine learning"},
    {"slug": "biohacking", "source": "trends", "term": "biohacking"},
    {"slug": "geopolitics", "source": "trends", "term": "geopolitics"},
    {
        "slug": "philosophy-of-science",
        "source": "keyword_planner",
        "term": "philosophy of science",
    },
    {
        "slug": "philosophy-of-science",
        "source": "keyword_planner",
        "term": "scientific method",
    },
    {
        "slug": "philosophy-of-science",
        "source": "keyword_planner",
        "term": "falsifiability",
    },
    {
        "slug": "philosophy-of-science",
        "source": "keyword_planner",
        "term": "paradigm shift",
    },
    {
        "slug": "philosophy-of-science",
        "source": "keyword_planner",
        "term": "epistemology of science",
    },
    {
        "slug": "philosophy-of-science",
        "source": "keyword_planner",
        "term": "karl popper",
    },
    {
        "slug": "esoterism-spirituality",
        "source": "keyword_planner",
        "term": "western esotericism",
    },
    {"slug": "esoterism-spirituality", "source": "keyword_planner", "term": "occult"},
    {
        "slug": "esoterism-spirituality",
        "source": "keyword_planner",
        "term": "hermeticism",
    },
    {"slug": "esoterism-spirituality", "source": "keyword_planner", "term": "alchemy"},
    {
        "slug": "esoterism-spirituality",
        "source": "keyword_planner",
        "term": "gnosticism",
    },
    {
        "slug": "esoterism-spirituality",
        "source": "keyword_planner",
        "term": "mysticism",
    },
    {
        "slug": "metaphysical-battles",
        "source": "keyword_planner",
        "term": "metaphysics",
    },
    {"slug": "metaphysical-battles", "source": "keyword_planner", "term": "free will"},
    {
        "slug": "metaphysical-battles",
        "source": "keyword_planner",
        "term": "determinism",
    },
    {
        "slug": "metaphysical-battles",
        "source": "keyword_planner",
        "term": "philosophy of mind",
    },
    {
        "slug": "metaphysical-battles",
        "source": "keyword_planner",
        "term": "materialism",
    },
    {"slug": "metaphysical-battles", "source": "keyword_planner", "term": "idealism"},
    {
        "slug": "logic-linguistics-gnoseology",
        "source": "keyword_planner",
        "term": "logic",
    },
    {
        "slug": "logic-linguistics-gnoseology",
        "source": "keyword_planner",
        "term": "epistemology",
    },
    {
        "slug": "logic-linguistics-gnoseology",
        "source": "keyword_planner",
        "term": "linguistics",
    },
    {
        "slug": "logic-linguistics-gnoseology",
        "source": "keyword_planner",
        "term": "semantics",
    },
    {
        "slug": "logic-linguistics-gnoseology",
        "source": "keyword_planner",
        "term": "syllogism",
    },
    {
        "slug": "logic-linguistics-gnoseology",
        "source": "keyword_planner",
        "term": "philosophy of language",
    },
    {
        "slug": "history-of-ideas",
        "source": "keyword_planner",
        "term": "intellectual history",
    },
    {
        "slug": "history-of-ideas",
        "source": "keyword_planner",
        "term": "history of philosophy",
    },
    {"slug": "history-of-ideas", "source": "keyword_planner", "term": "enlightenment"},
    {"slug": "history-of-ideas", "source": "keyword_planner", "term": "scholasticism"},
    {"slug": "history-of-ideas", "source": "keyword_planner", "term": "humanism"},
    {"slug": "history-of-ideas", "source": "keyword_planner", "term": "postmodernism"},
    {
        "slug": "anthropocene-anthropology",
        "source": "keyword_planner",
        "term": "anthropology",
    },
    {
        "slug": "anthropocene-anthropology",
        "source": "keyword_planner",
        "term": "anthropocene",
    },
    {
        "slug": "anthropocene-anthropology",
        "source": "keyword_planner",
        "term": "ethnography",
    },
    {
        "slug": "anthropocene-anthropology",
        "source": "keyword_planner",
        "term": "cultural anthropology",
    },
    {
        "slug": "anthropocene-anthropology",
        "source": "keyword_planner",
        "term": "archaeology",
    },
    {
        "slug": "anthropocene-anthropology",
        "source": "keyword_planner",
        "term": "human impact on the environment",
    },
    {"slug": "macro-economy", "source": "keyword_planner", "term": "macroeconomics"},
    {"slug": "macro-economy", "source": "keyword_planner", "term": "inflation"},
    {"slug": "macro-economy", "source": "keyword_planner", "term": "monetary policy"},
    {"slug": "macro-economy", "source": "keyword_planner", "term": "recession"},
    {"slug": "macro-economy", "source": "keyword_planner", "term": "fiscal policy"},
    {
        "slug": "macro-economy",
        "source": "keyword_planner",
        "term": "quantitative easing",
    },
    {"slug": "trading", "source": "keyword_planner", "term": "day trading"},
    {"slug": "trading", "source": "keyword_planner", "term": "technical analysis"},
    {"slug": "trading", "source": "keyword_planner", "term": "algorithmic trading"},
    {"slug": "trading", "source": "keyword_planner", "term": "futures trading"},
    {"slug": "trading", "source": "keyword_planner", "term": "options trading"},
    {"slug": "trading", "source": "keyword_planner", "term": "risk management"},
    {
        "slug": "ai-and-software",
        "source": "keyword_planner",
        "term": "machine learning",
    },
    {
        "slug": "ai-and-software",
        "source": "keyword_planner",
        "term": "large language model",
    },
    {"slug": "ai-and-software", "source": "keyword_planner", "term": "deep learning"},
    {"slug": "ai-and-software", "source": "keyword_planner", "term": "neural network"},
    {
        "slug": "ai-and-software",
        "source": "keyword_planner",
        "term": "artificial general intelligence",
    },
    {
        "slug": "ai-and-software",
        "source": "keyword_planner",
        "term": "software engineering",
    },
    {"slug": "biohacking", "source": "keyword_planner", "term": "biohacking"},
    {"slug": "biohacking", "source": "keyword_planner", "term": "nootropics"},
    {"slug": "biohacking", "source": "keyword_planner", "term": "longevity"},
    {
        "slug": "biohacking",
        "source": "keyword_planner",
        "term": "intermittent fasting",
    },
    {"slug": "biohacking", "source": "keyword_planner", "term": "ketogenic diet"},
    {"slug": "biohacking", "source": "keyword_planner", "term": "epigenetics"},
    {"slug": "geopolitics", "source": "keyword_planner", "term": "geopolitics"},
    {"slug": "geopolitics", "source": "keyword_planner", "term": "sovereignty"},
    {"slug": "geopolitics", "source": "keyword_planner", "term": "economic sanctions"},
    {"slug": "geopolitics", "source": "keyword_planner", "term": "balance of power"},
    {"slug": "geopolitics", "source": "keyword_planner", "term": "deterrence"},
    {"slug": "geopolitics", "source": "keyword_planner", "term": "realpolitik"},
)


def apply_terms(engine: Engine | None = None, terms=TERMS) -> int:
    """Write the demand-term mapping, idempotently on (seed, source, term).

    `active` and `created_at` stay out of the update set for the same reason they
    do on seeds: a term switched off by hand survives the next `nh seed`.
    """
    with session_scope(engine) as session:
        by_slug = dict(session.execute(sa.select(NicheSeed.slug, NicheSeed.id)).all())
        rows = [
            {
                "seed_id": by_slug[t["slug"]],
                "source": t["source"],
                "term": t["term"],
                "stratum": t.get("stratum", "topic"),
                "geo": t.get("geo", ""),
                "lang": t.get("lang", "en"),
                "notes": t.get("notes"),
            }
            for t in terms
            if t["slug"] in by_slug
        ]
        if not rows:
            return 0
        return upsert(
            session,
            SeedTerm,
            rows,
            # `stratum` joins the conflict target because it joined the unique
            # key. SQLite rejects an ON CONFLICT clause that does not match a real
            # unique index outright, so this is not a subtle drift — `nh seed`
            # simply stops working, which is how the omission was caught.
            conflict_on=["seed_id", "source", "term", "stratum"],
            update=["geo", "lang", "notes"],
        )


def apply_seeds(engine: Engine | None = None, seeds: tuple[dict[str, Any], ...] = SEEDS) -> int:
    """Write the seed set, idempotently on `slug`.

    Re-running is safe and is the intended way to edit a niche: change the literal
    above and run `nh seed` again. `active` and `created_at` are deliberately not
    in the update set, so a seed deactivated by hand stays deactivated.
    """
    with session_scope(engine) as session:
        return upsert(
            session,
            NicheSeed,
            list(seeds),
            conflict_on=["slug"],
            # `geo` and `primary_sources` are curation from the literal above, so
            # they belong in the update set — without them an existing row keeps
            # whatever it had when it was first inserted and the literal silently
            # stops being the source of truth. `active` and `created_at` stay out,
            # for the opposite reason: those are hand state and must survive a
            # re-run.
            update=["label", "keywords", "geo", "lang", "primary_sources", "notes"],
        )


def search_budget(seeds: tuple[dict[str, Any], ...] = SEEDS, pages: int = 1) -> int:
    """Units `search.list` will cost per night for this seed set.

    Discovery issues both sort orders per query — `date` for the unbiased pool
    that is the breakthrough-rate denominator, `viewCount` for the numerator — so
    the multiplier of 2 is structural, not a setting to tune away.
    """
    queries = sum(len(s["keywords"]) for s in seeds if s.get("active", True))
    return queries * 2 * pages * 100
