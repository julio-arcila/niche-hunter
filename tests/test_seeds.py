from __future__ import annotations

import sqlalchemy as sa

from nh.db.models import NicheSeed
from nh.db.session import session_scope
from nh.seeds import SEEDS, apply_seeds, search_budget


def _slugs(engine) -> list[str]:
    with session_scope(engine) as s:
        return list(s.scalars(sa.select(NicheSeed.slug).order_by(NicheSeed.slug)))


def test_seeding_writes_every_niche(engine):
    apply_seeds(engine)
    assert _slugs(engine) == sorted(s["slug"] for s in SEEDS)


def test_seeding_twice_does_not_duplicate(engine):
    apply_seeds(engine)
    apply_seeds(engine)
    assert len(_slugs(engine)) == len(SEEDS)


def test_reseeding_updates_keywords_in_place(engine):
    apply_seeds(engine)
    edited = ({**SEEDS[0], "keywords": ["a new keyword"]},)
    apply_seeds(engine, edited)
    with session_scope(engine) as s:
        row = s.scalar(sa.select(NicheSeed).where(NicheSeed.slug == SEEDS[0]["slug"]))
        assert row.keywords == ["a new keyword"]
    assert len(_slugs(engine)) == len(SEEDS)


def test_reseeding_does_not_reactivate_a_disabled_seed(engine):
    """`active` is outside the update set, so turning a niche off by hand survives
    the next `nh seed` — otherwise a routine re-run silently restarts collection
    on a niche someone deliberately stopped."""
    apply_seeds(engine)
    with session_scope(engine) as s:
        s.execute(sa.update(NicheSeed).where(NicheSeed.slug == "court-cases").values(active=False))
    apply_seeds(engine)
    with session_scope(engine) as s:
        assert s.scalar(sa.select(NicheSeed.active).where(NicheSeed.slug == "court-cases")) is False


def test_keywords_round_trip_as_a_list(engine):
    apply_seeds(engine)
    with session_scope(engine) as s:
        row = s.scalar(sa.select(NicheSeed).where(NicheSeed.slug == "aviation-disasters"))
    assert isinstance(row.keywords, list)
    assert "plane crash investigation" in row.keywords


def test_geo_is_null_not_invented(engine):
    """These niches are global-English. An invented 'US' would be a fabricated
    value that Trends and Keyword Planner would later treat as real (rule 6)."""
    apply_seeds(engine)
    with session_scope(engine) as s:
        assert all(g is None for g in s.scalars(sa.select(NicheSeed.geo)))


def test_search_budget_counts_both_sort_orders():
    """Both orders are structural: `date` is the breakthrough-rate denominator,
    `viewCount` the numerator. The x2 is not a tunable."""
    assert search_budget(SEEDS, pages=1) == 15 * 2 * 100
    assert search_budget(SEEDS, pages=2) == 15 * 2 * 2 * 100


def test_the_default_seed_set_fits_the_daily_budget():
    assert search_budget(SEEDS, pages=1) < 9_500
