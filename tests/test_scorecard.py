"""Scorecards: what is real, NULL for the rest."""

from __future__ import annotations

from datetime import date
from functools import partial

import sqlalchemy as sa

from nh.db.models import FeatureDaily, Scorecard
from nh.db.provenance import stamp
from nh.db.session import session_scope
from nh.db.types import utcnow
from nh.scoring.scorecard import build, percentile_rank

DAY = date(2026, 8, 27)


def _mark():
    return partial(stamp, source="scoring", run_id="test", at=utcnow())


def _feature(engine, cluster_id, name, value, group="openness"):
    with session_scope(engine) as s:
        s.add(
            FeatureDaily(
                cluster_id=cluster_id,
                day=DAY,
                metric_group=group,
                name=name,
                value=value,
                confidence=1.0,
                inputs_n=10,
                source="features",
                run_id="test",
            )
        )


def test_the_demand_side_stays_null_until_slice_three(engine):
    """No placeholder numbers: a figure that looks like a score invites being
    trusted, and there is no demand side to compute a gap from yet."""
    _feature(engine, "a", "breakthrough_rate_cohort", 0.3)
    with session_scope(engine) as s:
        build(s, DAY, _mark())
        card = s.scalars(sa.select(Scorecard)).one()
    assert card.openness == 0.3
    assert card.gap is None
    assert card.value is None
    assert card.opportunity is None
    # Slice 5: `unknown` with a reason, not NULL. Same principle as
    # `FeatureResult.empty` — a missing card says scoring never ran, an `unknown`
    # says it ran and could not decide, and only the second is a fact about the
    # niche. Still no fabricated score, which is what this test is really about.
    assert card.stage == "unknown"
    assert card.stage_confidence is None
    assert "no momentum" in card.detail["reason"]


def test_openness_is_carried_through_unmodified(engine):
    """Already 0-1. Rescaling would produce a number nobody can trace back."""
    _feature(engine, "a", "breakthrough_rate_cohort", 0.42)
    with session_scope(engine) as s:
        build(s, DAY, _mark())
        assert s.scalar(sa.select(Scorecard.openness)) == 0.42


def test_supply_is_a_cross_cluster_rank(engine):
    for cid, v in (("a", 100.0), ("b", 500.0), ("c", 900.0)):
        _feature(engine, cid, "median_views", v, group="supply")
    with session_scope(engine) as s:
        build(s, DAY, _mark())
        ranks = dict(s.execute(sa.select(Scorecard.cluster_id, Scorecard.supply)).all())
    assert ranks == {"a": 0.0, "b": 0.5, "c": 1.0}


def test_a_null_metric_gives_a_null_score_not_a_default_rank(engine):
    _feature(engine, "a", "median_views", None, group="supply")
    _feature(engine, "b", "median_views", 500.0, group="supply")
    with session_scope(engine) as s:
        build(s, DAY, _mark())
        ranks = dict(s.execute(sa.select(Scorecard.cluster_id, Scorecard.supply)).all())
    assert ranks["a"] is None


def test_a_lone_cluster_ranks_in_the_middle():
    """With nothing to compare against, any other answer invents information."""
    assert percentile_rank({"only": 5.0}) == {"only": 0.5}


def test_one_row_per_cluster_per_day_however_often_it_runs(engine):
    _feature(engine, "a", "breakthrough_rate_cohort", 0.3)
    with session_scope(engine) as s:
        build(s, DAY, _mark())
        build(s, DAY, _mark())
        assert s.scalar(sa.select(sa.func.count()).select_from(Scorecard)) == 1


# -- gap (Slice 3) -----------------------------------------------------------


def _demand(engine, cluster_id, value, confidence=1.0):
    _feature(engine, cluster_id, "wiki_weekly_views", value, group="demand")
    with session_scope(engine) as s:
        s.execute(
            sa.update(FeatureDaily)
            .where(FeatureDaily.cluster_id == cluster_id, FeatureDaily.name == "wiki_weekly_views")
            .values(confidence=confidence)
        )


def test_gap_is_demand_rank_minus_supply_rank(engine):
    """Ranks rather than raw units: pageviews and video views share no currency,
    and any exchange rate between them would be a fabricated constant."""
    for cid, demand, supply in (("a", 100.0, 900.0), ("b", 900.0, 100.0)):
        _demand(engine, cid, demand)
        _feature(engine, cid, "median_views", supply, group="supply")
    with session_scope(engine) as s:
        build(s, DAY, _mark())
        gaps = dict(s.execute(sa.select(Scorecard.cluster_id, Scorecard.gap)).all())
    assert gaps == {"a": -1.0, "b": 1.0}


def test_gap_is_null_when_either_side_is_missing(engine):
    _demand(engine, "a", 100.0)  # demand only, no supply
    with session_scope(engine) as s:
        build(s, DAY, _mark())
        card = s.scalars(sa.select(Scorecard)).one()
    assert card.demand is not None
    assert card.gap is None
    assert card.gap_confidence is None


def test_gap_confidence_is_the_weaker_leg(engine):
    _demand(engine, "a", 100.0, confidence=0.9)
    _feature(engine, "a", "median_views", 100.0, group="supply")
    with session_scope(engine) as s:
        s.execute(
            sa.update(FeatureDaily)
            .where(FeatureDaily.name == "median_views")
            .values(confidence=0.2)
        )
        build(s, DAY, _mark())
        card = s.scalars(sa.select(Scorecard)).one()
    assert card.gap_confidence == 0.2


def test_the_demand_rank_is_stored_so_the_gap_is_reconstructible(engine):
    """The same reason `supply` is stored: a score nobody can take apart is a
    score nobody can check."""
    _demand(engine, "a", 100.0)
    _feature(engine, "a", "median_views", 100.0, group="supply")
    with session_scope(engine) as s:
        build(s, DAY, _mark())
        card = s.scalars(sa.select(Scorecard)).one()
    assert card.gap == card.demand - card.supply


def test_a_lone_cluster_gaps_at_zero(engine):
    """Both ranks land mid-scale, because with nothing to compare against any
    other answer would be inventing information."""
    _demand(engine, "a", 100.0)
    _feature(engine, "a", "median_views", 100.0, group="supply")
    with session_scope(engine) as s:
        build(s, DAY, _mark())
        assert s.scalar(sa.select(Scorecard.gap)) == 0.0


def test_tied_values_share_a_rank():
    """Without this, equal values get distinct ranks resolved by `sorted`'s
    stability over whatever order the database returned rows in — so two clusters
    could swap positions between two runs of the same day, and `gap` is a
    difference of these ranks."""
    ranks = percentile_rank({"a": 10.0, "b": 10.0, "c": 30.0})
    assert ranks["a"] == ranks["b"] == 0.25
    assert ranks["c"] == 1.0


def test_ranking_does_not_depend_on_input_order():
    forward = percentile_rank({"a": 5.0, "b": 5.0, "c": 5.0, "d": 9.0})
    backward = percentile_rank({"d": 9.0, "c": 5.0, "b": 5.0, "a": 5.0})
    assert forward == backward


def test_an_all_tied_set_ranks_everything_at_the_midpoint():
    ranks = percentile_rank({"a": 1.0, "b": 1.0, "c": 1.0})
    assert set(ranks.values()) == {0.5}


def test_the_stage_records_the_basis_it_was_decided_on(engine):
    """Supply momentum arrives in a few weeks and stages will move. The move has to
    be attributable to the axes that changed rather than mysterious."""
    _feature(engine, "a", "median_views", 100.0)
    _feature(engine, "b", "median_views", 900.0)
    _feature(engine, "a", "wiki_weekly_views", 900.0)
    _feature(engine, "b", "wiki_weekly_views", 100.0)
    _feature(engine, "a", "wiki_yoy", 0.25)
    _feature(engine, "b", "wiki_yoy", -0.25)

    with session_scope(engine) as s:
        build(s, DAY, _mark())
        cards = {c.cluster_id: c for c in s.scalars(sa.select(Scorecard))}

    # `a` has the higher demand rank and the lower supply rank, so a positive gap.
    assert cards["a"].stage == "emerging"
    assert cards["b"].stage == "saturated"
    for card in cards.values():
        assert card.detail["basis"] == ["gap", "momentum"]
        assert card.detail["thresholds"]


def test_a_cluster_with_no_momentum_is_unknown_rather_than_saturated(engine):
    """Defaulting a missing axis to 0 would classify every un-measured cluster as
    saturated, which reads as a finding."""
    _feature(engine, "a", "median_views", 100.0)
    _feature(engine, "b", "median_views", 900.0)
    _feature(engine, "a", "wiki_weekly_views", 900.0)
    _feature(engine, "b", "wiki_weekly_views", 100.0)

    with session_scope(engine) as s:
        build(s, DAY, _mark())
        cards = {c.cluster_id: c for c in s.scalars(sa.select(Scorecard))}

    assert all(c.stage == "unknown" for c in cards.values())
    # The gap is still computed; an unknown stage does not null the rest of the card.
    assert cards["a"].gap is not None


def test_wiki_momentum_28d_is_evidence_not_an_input(engine):
    """It is carried into detail for traceability and must never decide a stage —
    three of four niches peak in September, so a late-August month-over-month
    reading is the school calendar."""
    _feature(engine, "a", "median_views", 100.0)
    _feature(engine, "a", "wiki_weekly_views", 900.0)
    _feature(engine, "a", "wiki_yoy", 0.25)
    _feature(engine, "a", "wiki_momentum_28d", -0.31)

    with session_scope(engine) as s:
        build(s, DAY, _mark())
        card = s.scalars(sa.select(Scorecard)).one()

    assert card.detail["wiki_momentum_28d"] == -0.31
    assert card.detail["basis"] == ["gap", "momentum"]  # not three axes
    assert card.stage in ("emerging", "contested")  # the negative 28d did not decide it
