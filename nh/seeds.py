"""The hand-picked starting points. Everything downstream hangs off a seed.

Each niche is chosen so that a free, dense **primary source** already exists for
it. That is deliberate, not incidental: `docs/ARCHITECTURE.md` already names
`nh/collectors/primary/{ntsb,edgar,courtlistener}.py`, and `cost_risk.*` in
Slice 5 scores primary-source density and cadence. Seeding against sources we
intend to collect means that slice has real material instead of niches picked for
Slice 1's convenience.

Quota follows directly from what is here: cost is
``seeds x keywords x 2 sort orders x pages x 100 units``. Five seeds of three
keywords at one page is 30 searches, ~3,000 units, 32% of the 9,500 budget.
Adding a sixth seed is a 600-unit decision — see .claude/rules/sources.md.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import Engine

from nh.db.models import NicheSeed
from nh.db.session import session_scope
from nh.db.upsert import upsert

#: geo is deliberately NULL. These niches are global-English rather than tied to
#: one market, and an invented "US" would be a fabricated value the Trends and
#: Keyword Planner collectors would later treat as real (data rule 6). Set it in
#: Slice 3, when a geo actually drives a request.
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
