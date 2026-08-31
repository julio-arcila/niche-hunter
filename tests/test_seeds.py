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
    *request parameter* — `seed_terms.geo` still carries that rule, and stays ''
    for every source that sends it anywhere.
    `niche_seeds.geo` is a different thing: a stated intent that nothing sends
    anywhere, and which `supply.geo_concentration` measures divergence from.
    Measured, 234 of 719 channels are Indian against 290 US. That gap is invisible
    unless the seed says what it meant.

    Keyword Planner went through both wrong answers before landing here
    (ADR-0038). Its collector never reads `seed_terms` — the geo comes from the
    `--geo` argument — so first the terms defaulted to "" against a
    (keyword, geo, lang) match report, which read 0/30; then they were stamped
    "US" to satisfy that report, which made a GB export match 96/162 and would
    have needed 66 duplicate rows per market. The conflation was in the JOIN:
    a seed term asserts "this niche cares about this keyword", which is
    geo-independent, while `keyword_metrics.geo` records which export a number
    came from. So KP terms carry "" like every other source — here it means
    "curation, no market" rather than "worldwide observation" — and features
    join on (term, lang), choosing the market against `keyword_metrics.geo`."""
    apply_seeds(engine)
    apply_terms(engine)
    with session_scope(engine) as s:
        assert all(g for g in s.scalars(sa.select(NicheSeed.geo)))
        # The request-driving field is untouched — for the sources that actually
        # drive requests with it. `trends.py:144` passes `geo=term.geo` straight
        # into the API call and `wikipedia.py:118` reads the column, so an invented
        # geo there becomes a request parameter, which is what ADR-0024 forbids.
        driven = s.scalars(
            sa.select(SeedTerm.geo).where(SeedTerm.source.in_(("wikipedia", "trends")))
        )
        assert all(g == "" for g in driven)
        # Keyword Planner terms are geo-independent curation (ADR-0038): the geo
        # of a NUMBER lives on keyword_metrics, never on the term that claims it.
        kp = set(s.scalars(sa.select(SeedTerm.geo).where(SeedTerm.source == "keyword_planner")))
        assert kp == {""}


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


def test_every_active_domain_keeps_a_query_outside_the_explained_register():
    """ADR-0051's floor. Measured 2026-08-31: **25 of 30** active queries carried an
    explained-register token and six domains were at 3/3, so discovery was searching for
    a *format* almost as much as for a subject — and the exposition lexicon then scores
    what that format returns, which is a preimage of the query set rather than an
    independent measurement of it.

    A test and not a note, because the pressure runs one way: every yield measurement
    rewards the register that yields, so the floor would erode query by query with each
    step looking locally correct.

    **One exemption, and it is the awkward one.** ADR-0049 holds
    `logic-linguistics-gnoseology` completely untouched as a control for query CHANGE,
    and its yield is re-measured a week after 2026-08-31; swapping a query into it now
    would destroy the only baseline that measurement has. It is itself 3/3 "explained",
    so it is explicitly **not** a control for register and cannot detect this drift even
    in principle — which is the finding, not a defence. The exemption is listed rather
    than filtered so that adding a second one has to be a deliberate edit to this
    literal, and it expires when ADR-0049's re-measure lands.
    """
    register = {"explained", "explainer", "explain", "explaining"}
    held = {"logic-linguistics-gnoseology"}  # ADR-0049's control; expires on its re-measure

    thin = {
        seed["slug"]
        for seed in SEEDS
        if seed["active"]
        and not any(not (register & set(k.lower().split())) for k in seed["keywords"])
    }
    assert thin == held, f"register floor broken in: {sorted(thin - held)}"
