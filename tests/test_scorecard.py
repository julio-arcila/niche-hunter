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
    assert card.stage is None


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
