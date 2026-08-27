"""The hand-picked starting points. Everything downstream hangs off a seed.

Each niche was chosen so that a free, dense **primary source** already exists for
it, so that `cost_risk.*` would have real material rather than niches picked for
Slice 1's convenience. `docs/SOURCES.md` lists `primary/` (ntsb, edgar,
courtlistener) under "Planned"; no such collector exists yet.

That premise held for two of the five. Tested live 2026-08-27: CourtListener's
REST API works unauthenticated and carries `dateFiled`; SEC EDGAR's submissions
and full-text endpoints work unauthenticated; NTSB's CAROL query API is reachable
but rejects documented-looking payloads and its shape is undocumented; USCG
returns 403; NIST has no API. Per-seed findings live in `NicheSeed.primary_sources`
so the research is dated and reviewable rather than folded into a score (ADR-0020).

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

#: geo stays NULL on the seed. Resolved in Slice 3: geo lives per-term on
#: `seed_terms`, where it actually drives a request, rather than on the seed where
#: it would be a guess (ADR-0015).
SEEDS: tuple[dict[str, Any], ...] = (
    {
        "slug": "aviation-disasters",
        "label": "Aviation disasters",
        "keywords": [
            "aviation disasters documentary",
            "plane crash investigation",
            "air crash analysis",
        ],
        "lang": "en",
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
        "lang": "en",
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
        "lang": "en",
        "notes": "Primary source: SEC EDGAR filings.",
    },
    {
        "slug": "engineering-failures",
        "label": "Engineering failures",
        "keywords": [
            "engineering disaster documentary",
            "structural failure analysis",
            "bridge collapse investigation",
        ],
        "lang": "en",
        "notes": "Primary source: NIST investigations, NTSB.",
    },
    {
        "slug": "court-cases",
        "label": "Landmark court cases",
        "keywords": [
            "famous court case documentary",
            "trial analysis",
            "legal case explained",
        ],
        "lang": "en",
        "notes": "Primary source: CourtListener opinions and dockets.",
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
        "slug": "court-cases",
        "source": "wikipedia",
        "term": "List_of_landmark_court_decisions_in_the_United_States",
        "notes": "reference-heavy: carries school-calendar traffic, see METRICS.md failure mode",
    },
    {
        "slug": "court-cases",
        "source": "wikipedia",
        "term": "Supreme_Court_of_the_United_States",
        "notes": "broad — may measure civics rather than the niche; revisit once inspectable",
    },
    {"slug": "court-cases", "source": "wikipedia", "term": "Landmark_case"},
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
        "slug": "court-cases",
        "source": "trends",
        "term": "court case",
        "notes": "provisional — untested",
    },
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
            update=["label", "keywords", "lang", "notes"],
        )


def search_budget(seeds: tuple[dict[str, Any], ...] = SEEDS, pages: int = 1) -> int:
    """Units `search.list` will cost per night for this seed set.

    Discovery issues both sort orders per query — `date` for the unbiased pool
    that is the breakthrough-rate denominator, `viewCount` for the numerator — so
    the multiplier of 2 is structural, not a setting to tune away.
    """
    queries = sum(len(s["keywords"]) for s in seeds if s.get("active", True))
    return queries * 2 * pages * 100
