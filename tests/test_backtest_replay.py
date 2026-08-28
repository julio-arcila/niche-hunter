"""The replay: production feature code run at historical decision dates.

The gate's whole claim rests on this module computing nothing of its own. If the
backtest scored with its own arithmetic it would measure the backtest, not the
product — so the first tests here are structural, and they are the ones that would
catch the failure quietly.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from nh.backtest import replay as replay_module
from nh.backtest.load import RefusingLiveDatabase
from nh.backtest.replay import (
    BACKTEST_METRICS,
    Pairing,
    as_series,
    decision_dates,
    pair,
    replay,
)
from nh.db.models import Cluster, FeatureDaily, Scorecard
from nh.db.session import session_scope
from tests.conftest_features import CLUSTER, RUN, add_channel, make_cluster

SOURCE_FILE = Path(replay_module.__file__)
AT = datetime(2026, 8, 27, tzinfo=UTC)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names |= {f"{node.module}.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
    return names


# --------------------------------------------------------------------------
# Structural: what the replay may and may not do
# --------------------------------------------------------------------------


def test_the_replay_never_imports_the_job_runner():
    """`run_phases` runs clustering, which mutates and commits: `assign_videos`
    overwrites every video's relevance and `at`, and `retire_empty` writes
    `retired_on = day` — so replaying 2019 through it would stamp
    `retired_on = 2019-01-01` onto live clusters."""
    imported = _imports(SOURCE_FILE)

    assert not any("run_phases" in name for name in imported)
    assert not any(name.startswith("nh.jobs") for name in imported)


def test_the_replay_uses_the_production_feature_functions():
    """Every backtest metric is the same object the nightly calls, not a copy."""
    from nh.features import demand, openness, supply

    production = {
        demand.wiki_weekly_views,
        demand.wiki_momentum_28d,
        demand.wiki_yoy,
        demand.wiki_volatility_365d,
        supply.uploads_per_week,
        supply.views_per_new_video,
        supply.on_niche_share,
        supply.top10_concentration,
        openness.winner_age_years,
    }

    assert set(BACKTEST_METRICS) == production


def test_the_backtest_metric_set_is_a_subset_of_nothing_it_invented():
    """A reduced set, not a reimplementation. Every entry must be a real function
    from nh.features, so no metric can be quietly redefined for the backtest."""
    for metric in BACKTEST_METRICS:
        assert metric.__module__.startswith("nh.features.")


def test_it_refuses_to_replay_into_a_database_not_named_backtest(engine):
    with pytest.raises(RefusingLiveDatabase):
        replay(engine, [date(2019, 1, 1)], run_id=RUN, at=AT)


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------


def test_decision_dates_are_weekly_and_inclusive():
    days = decision_dates(date(2018, 1, 1), date(2018, 1, 29))

    assert days == [
        date(2018, 1, 1),
        date(2018, 1, 8),
        date(2018, 1, 15),
        date(2018, 1, 22),
        date(2018, 1, 29),
    ]


def test_an_inverted_range_yields_nothing():
    assert decision_dates(date(2019, 1, 1), date(2018, 1, 1)) == []


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


def test_a_replay_writes_features_and_scorecards_dated_to_the_decision_day(backtest_engine):
    """`day` says what the row describes; `at` says when it was written. Conflating
    them would make the replay's output indistinguishable from real collection."""
    make_cluster(backtest_engine)
    add_channel(backtest_engine, "UCa", subs=1000, videos=5, day=date(2017, 1, 1))
    day = date(2018, 1, 1)

    rows, _ = replay(backtest_engine, [day], run_id=RUN, at=AT)

    with session_scope(backtest_engine) as session:
        stored = session.execute(
            sa.select(FeatureDaily.day, FeatureDaily.at, FeatureDaily.source).limit(1)
        ).one()
    assert rows == len(BACKTEST_METRICS)
    assert stored.day == day
    assert stored.at.date() == AT.date()
    assert stored.source == "backtest"


def test_replaying_the_same_day_twice_is_idempotent(backtest_engine):
    make_cluster(backtest_engine)
    day = date(2018, 1, 1)

    replay(backtest_engine, [day], run_id=RUN, at=AT)
    with session_scope(backtest_engine) as session:
        before = session.scalar(sa.select(sa.func.count()).select_from(FeatureDaily))

    replay(backtest_engine, [day], run_id=RUN, at=AT)

    with session_scope(backtest_engine) as session:
        after = session.scalar(sa.select(sa.func.count()).select_from(FeatureDaily))
    assert before == after


def test_a_retired_cluster_stops_accruing_rows(backtest_engine):
    make_cluster(backtest_engine)
    with session_scope(backtest_engine) as session:
        session.execute(sa.update(Cluster).values(active=False))

    rows, cards = replay(backtest_engine, [date(2018, 1, 1)], run_id=RUN, at=AT)

    assert rows == 0
    assert cards == 0


# --------------------------------------------------------------------------
# Pairing
# --------------------------------------------------------------------------


def _card(engine, cluster_id, day, gap):
    with session_scope(engine) as session:
        session.add(
            Scorecard(cluster_id=cluster_id, day=day, gap=gap, source="backtest", run_id=RUN, at=AT)
        )


def test_a_cluster_with_no_outcome_is_dropped_not_zeroed(backtest_engine):
    """Treating a NULL outcome as zero would rank a niche that could not be measured
    against one that shrank, and the correlation would then partly measure which
    niches had enough data."""
    make_cluster(backtest_engine)
    day = date(2018, 1, 1)
    _card(backtest_engine, CLUSTER, day, 0.5)

    pairings = pair(backtest_engine, [day])

    assert pairings == []


def test_a_date_with_fewer_than_three_pairs_carries_no_correlation(backtest_engine):
    make_cluster(backtest_engine)
    day = date(2018, 1, 1)
    _card(backtest_engine, CLUSTER, day, 0.5)

    assert pair(backtest_engine, [day]) == []


def test_as_series_carries_the_niche_ids_the_global_null_needs():
    """The permutation relabels niches globally, which is only expressible if each
    date knows which niche each number belongs to."""
    pairing = Pairing(
        day=date(2018, 1, 1),
        clusters=["a", "b", "c"],
        scores=[0.1, 0.2, 0.3],
        outcomes=[1.0, 2.0, 3.0],
        sizes=[10, 20, 30],
    )

    series = as_series([pairing])

    assert series == [("2018-01-01", ["a", "b", "c"], [0.1, 0.2, 0.3], [1.0, 2.0, 3.0])]


def test_sizes_are_carried_for_the_partial_correlation():
    """Without the size control a pass cannot be told apart from "big niches grow",
    which needs no pipeline to reproduce."""
    pairing = Pairing(day=date(2018, 1, 1))
    assert pairing.sizes == []
    assert hasattr(pairing, "sizes")
