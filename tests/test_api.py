"""The read layer: basis, drilldown, and the queries every surface reads through.

The two exhaustive tests here — every registered metric has a basis, every registered
metric has a drilldown that returns **non-empty** rows — are Slice 7's exit criterion made
executable. "Every displayed number reaches its input rows" is the kind of promise a UI can
appear to keep by linking to a plausible query nobody ran.
"""

from __future__ import annotations

import pytest

from nh.api import basis, drilldown
from nh.api import queries as q
from nh.features.run import METRICS
from tests.conftest_features import CLUSTER, DAY, add_channel, make_cluster, rich_corpus


@pytest.fixture
def corpus(engine):
    return rich_corpus(engine)


# --- basis (ADR-0035) --------------------------------------------------------------


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.__name__)
def test_every_registered_metric_names_its_population(metric):
    """ADR-0035's requirement, as a test rather than as a deferral.

    The `geo_basis` deferral warned the cost was "larger than it looks... `_provenance`
    renders a FIXED list of named keys, so an unrendered key repeats ADR-0031's `currency`
    bug exactly" — a COP bid printed under a heading called money. So the basis is resolved
    from the metric's identity, not from a `detail` key someone must remember to stamp.
    """
    assert basis.source_of(metric.__name__) is not None, (
        f"{metric.__name__} has no population in nh/api/basis.py::SOURCE_OF"
    )
    assert basis.basis(metric.__name__) != basis.UNKNOWN


def test_a_row_that_recorded_its_own_geo_wins():
    """A Keyword Planner number knows which export it came from; the table cannot."""
    assert basis.basis("vw_cpc", {"geo": "GB"}) == "geo GB"
    assert basis.basis("trends_momentum_13w", {"geo": ""}) == "worldwide"


def test_demand_and_supply_are_not_comparable():
    """The whole point of ADR-0035, and the reason `scorecards.gap` carries a caveat:
    Wikipedia counts English readers globally, YouTube counts a US-served search."""
    assert not basis.comparable("wiki_yoy", "on_niche_share")
    assert basis.comparable("wiki_yoy", "wiki_momentum_28d")


def test_an_unknown_metric_says_so_rather_than_guessing():
    assert basis.basis("something_invented") == basis.UNKNOWN


# --- drilldown ---------------------------------------------------------------------


@pytest.mark.parametrize("metric", METRICS, ids=lambda m: m.__name__)
def test_every_registered_metric_has_a_drilldown(metric):
    assert metric.__name__ in drilldown.REGISTRY, (
        f"{metric.__name__} would render with no way to check it"
    )


@pytest.mark.parametrize("name", sorted(drilldown.REGISTRY), ids=str)
def test_every_drilldown_returns_rows(corpus, name):
    """**Non-empty**, and that word is the test.

    An empty result satisfies "returns without raising" forever, which is how a drilldown
    rots into a link that goes nowhere. The leakage fixture's vacuous-pass trap has bitten
    this repo twice; asserting non-empty per metric is the cheap way not to be bitten a
    third time.
    """
    headers, rows = drilldown.rows_behind(corpus, name, CLUSTER, DAY)
    assert headers, f"{name} returned no columns"
    assert rows, f"{name} returned no input rows on the rich corpus"


def test_an_unregistered_metric_returns_empty_rather_than_raising(corpus):
    """A surface asking for a metric that has no drilldown must degrade, not 500."""
    assert drilldown.rows_behind(corpus, "invented", CLUSTER, DAY) == ([], [])


def test_the_video_drilldown_shows_only_on_niche_rows(corpus):
    """It mirrors what the supply metrics counted. A drilldown listing rows the metric
    excluded is a wrong answer wearing an audit trail."""
    _, rows = drilldown.rows_behind(corpus, "on_niche_share", CLUSTER, DAY)
    relevances = [r[-1] for r in rows]
    assert relevances and all(r is not None and r >= 0.55 for r in relevances)


def test_the_channel_drilldown_honours_the_ballast_exclusion(engine):
    """It routes through `member_channels`, so a channel the metric dropped is not shown.

    `tipping` is ballast here — ten decided-noise videos, none on-niche — which is exactly
    the population ADR-0047 removes and ADR-0050 has not yet validated removing.
    """
    from nh.features.inputs import BALLAST_DECIDED

    make_cluster(engine)
    add_channel(engine, "real", videos=3, relevant=True)
    add_channel(engine, "tipping", videos=BALLAST_DECIDED, relevant=False)
    session = __import__("tests.conftest_features", fromlist=["session_for"]).session_for(engine)

    _, rows = drilldown.rows_behind(session, "geo_concentration", CLUSTER, DAY)
    assert {r[0] for r in rows} == {"real"}


# --- queries -----------------------------------------------------------------------


def test_the_niche_list_carries_no_score(corpus):
    """ADR-0029 forbids a ranked surface, and a list sorted by a number is a ranking
    however it is captioned. `NicheLine` has no field a reader could sort on as quality."""
    fields = set(q.NicheLine.__annotations__)
    assert fields == {"cluster_id", "label", "active", "member_channels", "videos", "latest_day"}
    assert not fields & {"value", "gap", "opportunity", "score", "rank"}


def test_the_niche_list_is_alphabetical(corpus):
    rows = q.niche_list(corpus)
    assert [n.cluster_id for n in rows] == sorted(n.cluster_id for n in rows)


def test_the_channel_table_and_the_metrics_agree_on_who_is_a_member(corpus):
    """Two answers to "who is in this cluster" is the drift `supply._confidence`'s clamp
    comment calls a bug in the query rather than a value."""
    from nh.features.inputs import member_channels

    assert {c.channel_id for c in q.channel_table(corpus, CLUSTER, DAY)} == set(
        member_channels(corpus, CLUSTER, DAY)
    )


def test_the_source_feed_includes_videos_no_query_found(corpus):
    """Most of the corpus arrives by RSS from channels already admitted — 5,511 of 73,464
    member rows came from discovery. An inner join would show the 7.5% and misrepresent
    where the corpus comes from."""
    feed = q.source_feed(corpus, CLUSTER, DAY)
    assert feed
    assert any(line.query is None for line in feed)
    assert all(line.url.endswith(line.video_id) for line in feed)


def test_metric_history_carries_the_definition_of_each_point(engine):
    """Per point, off the row, never from today's code — that is what keeps a series
    readable across ADR-0050's sunset instead of silently redrawing history."""
    from datetime import date, timedelta

    from nh.db.models import FeatureDaily
    from nh.db.session import session_scope
    from tests.conftest_features import session_for

    with session_scope(engine) as s:
        for offset, (value, definition) in enumerate(
            [(0.076, "v2-on-niche"), (0.227, "v3-non-ballast-members")]
        ):
            s.add(
                FeatureDaily(
                    cluster_id=CLUSTER,
                    day=date(2026, 8, 29) + timedelta(days=offset * 2),
                    metric_group="supply",
                    name="on_niche_share",
                    value=value,
                    confidence=0.6,
                    inputs_n=10,
                    detail={"definition": definition},
                    source="features",
                    run_id="r",
                )
            )
    points = q.metric_history(session_for(engine), CLUSTER, "on_niche_share")

    assert [p.definition for p in points] == ["v2-on-niche", "v3-non-ballast-members"]
    steps = q.definition_steps(points)
    assert steps == [(date(2026, 8, 31), "v2-on-niche", "v3-non-ballast-members")]


def test_a_series_with_one_definition_reports_no_step(corpus):
    """The rule must not report a step on every series, or a real one stops standing out."""
    points = q.metric_history(corpus, CLUSTER, "on_niche_share")
    assert q.definition_steps(points) == []
