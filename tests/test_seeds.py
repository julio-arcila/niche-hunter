from __future__ import annotations

import sqlalchemy as sa

from nh.db.models import NicheSeed, SeedTerm
from nh.db.session import session_scope
from nh.seeds import SEEDS, apply_seeds, apply_terms, search_budget


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
        s.execute(
            sa.update(NicheSeed)
            .where(NicheSeed.slug == "landmark-court-cases")
            .values(active=False)
        )
    apply_seeds(engine)
    with session_scope(engine) as s:
        assert (
            s.scalar(sa.select(NicheSeed.active).where(NicheSeed.slug == "landmark-court-cases"))
            is False
        )


def test_keywords_round_trip_as_a_list(engine):
    apply_seeds(engine)
    with session_scope(engine) as s:
        row = s.scalar(sa.select(NicheSeed).where(NicheSeed.slug == "aviation-disasters"))
    assert isinstance(row.keywords, list)
    assert "plane crash investigation" in row.keywords


def test_geo_states_the_market_the_niche_is_about(engine):
    """Reverses `test_geo_is_null_not_invented` (Slice 5), and the distinction is
    the whole point. That test was right that an invented geo must not become a
    *request parameter* — `seed_terms.geo` still carries that and is still ''.
    `niche_seeds.geo` is a different thing: a stated intent that nothing sends
    anywhere, and which `supply.geo_concentration` measures divergence from.
    Measured, 234 of 719 channels are Indian against 290 US. That gap is invisible
    unless the seed says what it meant."""
    apply_seeds(engine)
    apply_terms(engine)
    with session_scope(engine) as s:
        assert all(g for g in s.scalars(sa.select(NicheSeed.geo)))
        # The request-driving field is untouched.
        assert all(g == "" for g in s.scalars(sa.select(SeedTerm.geo)))


def test_search_budget_counts_both_sort_orders():
    """Both orders are structural: `date` is the breakthrough-rate denominator,
    `viewCount` the numerator. The x2 is not a tunable."""
    queries = sum(len(s["keywords"]) for s in SEEDS if s["active"])
    assert search_budget(SEEDS, pages=1) == queries * 2 * 100
    assert search_budget(SEEDS, pages=2) == queries * 2 * 2 * 100


def test_a_deactivated_seed_costs_no_search_quota():
    """The point of deactivating one. `landmark-court-cases` went inactive on
    2026-08-28 (ADR-0028) after one nightly had already spent ~600 units on it."""
    live = tuple(s for s in SEEDS if s["active"])

    assert search_budget(SEEDS) == search_budget(live)
    assert len(live) < len(SEEDS)


def test_the_default_seed_set_fits_the_daily_budget():
    assert search_budget(SEEDS, pages=1) < 9_500
