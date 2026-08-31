"""The evidence surface, rendered in-process.

`streamlit.testing.v1.AppTest` runs the page's script in this process with no server and
no socket, so these satisfy `conftest.py`'s network block rather than being exempted from
it. `importorskip` keeps the core suite green for anyone who has not installed the `web`
extra — the same posture the collectors' optional dependencies take.

What is asserted is the two rules the pages inherit: **a scorer-decided number is withheld
for an unvalidated axis**, and **nothing is ordered by a score**. Those are the constraints
that would be quietly lost in a rendering change; the layout is not.
"""

from __future__ import annotations

import pathlib
from datetime import date

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from nh.db.models import Cluster, FeatureDaily, NicheSeed, Scorecard
from nh.db.session import session_scope

DAY = date(2026, 8, 27)
# Absolute: AppTest resolves a relative path against the FILE THAT CALLS IT, which is this
# one, so "nh/web/app.py" would look under tests/.
APP = str(pathlib.Path(__file__).resolve().parents[1] / "nh" / "web" / "app.py")


@pytest.fixture
def surface(engine, monkeypatch):
    """One exposition cluster with a gated metric, an ungated one, and a scorecard.

    `history-of-ideas` rather than an invented slug: the gate reads
    `clustering.lexicon.AXES`, so a made-up cluster has no axis, is not gated, and the
    test would pass while testing nothing.
    """
    monkeypatch.setattr("nh.db.session.get_engine", lambda: engine)
    monkeypatch.setattr("nh.jobs.niche.session_scope", lambda _=None: session_scope(engine))
    monkeypatch.setattr("nh.web.shared.get_engine", lambda: engine)
    with session_scope(engine) as s:
        s.add(NicheSeed(id=1, slug="history-of-ideas", label="History of ideas", keywords=[]))
        s.flush()
        s.add(
            Cluster(
                cluster_id="history-of-ideas",
                seed_id=1,
                label="History of ideas",
                source="clustering",
                run_id="r",
            )
        )
        s.add_all(
            [
                FeatureDaily(
                    cluster_id="history-of-ideas",
                    day=DAY,
                    metric_group="supply",
                    name="on_niche_share",
                    value=0.4242,
                    confidence=0.61,
                    inputs_n=1_012,
                    detail={"definition": "v3-non-ballast-members"},
                    source="features",
                    run_id="r",
                ),
                FeatureDaily(
                    cluster_id="history-of-ideas",
                    day=DAY,
                    metric_group="demand",
                    name="wiki_yoy",
                    value=-0.1834,
                    confidence=1.0,
                    inputs_n=504,
                    detail={},
                    source="features",
                    run_id="r",
                ),
            ]
        )
        s.add(
            Scorecard(
                cluster_id="history-of-ideas",
                day=DAY,
                demand=0.80,
                supply=0.30,
                gap=0.50,
                source="features",
                run_id="r",
            )
        )
    return engine


def _text(app: AppTest) -> str:
    """Everything the page rendered as text, across the element types these pages use."""
    parts = []
    for collection in (
        app.markdown,
        app.title,
        app.header,
        app.subheader,
        app.caption,
        app.info,
        app.warning,
        app.error,
        app.text,
    ):
        parts.extend(str(element.value) for element in collection)
    parts.extend(str(e.label) for e in app.expander)
    return "\n".join(parts)


def _run(page_choice: str | None = None) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    if page_choice is not None:
        app.sidebar.selectbox[0].set_value(page_choice).run()
    return app


def test_the_list_page_renders_and_says_it_is_not_ranked(surface):
    app = _run()
    assert not app.exception
    text = _text(app)
    assert "Niches" in text
    assert "Alphabetical" in text and "ADR-0029" in text


def test_the_niche_page_withholds_a_scorer_dependent_metric(surface):
    """The load-bearing assertion of the whole slice.

    Asserted on the metric's own expander label rather than on the whole page, and the
    fixture value is deliberately distinctive. A first version checked `"0.227" not in
    text` and failed on the BALLAST BANNER, which quotes `0.076 → 0.227` as documentation
    of the move ADR-0050 exists to test. That was the assertion being wrong, not the page
    — but a substring search over a page that legitimately discusses numbers is a bad
    test either way.
    """
    app = _run("history-of-ideas")
    assert not app.exception

    labels = [e.label for e in app.expander if "on_niche_share" in e.label]
    assert labels, "named, not hidden — a vanished metric reads as a pipeline gap"
    assert "withheld" in labels[0]
    assert "0.4242" not in labels[0] and "0.42" not in labels[0]
    assert "0.4242" not in _text(app)


def test_the_niche_page_shows_a_scorer_independent_metric(surface):
    """The gate is about the scorer, not about the cluster: Wikipedia pageviews are
    measured the same way whatever a lexicon does."""
    app = _run("history-of-ideas")
    text = _text(app)
    assert "wiki_yoy" in text and "-0.18" in text


def test_the_scorecard_is_withheld_whole(surface):
    """`gap` is demand minus supply; serving one side invites reconstruction."""
    app = _run("history-of-ideas")
    text = _text(app)
    assert "0.50" not in text and "0.80" not in text
    assert "label_exposition.py" in text


def test_the_page_names_the_ballast_sunset(surface):
    """A number whose definition is on a clock has to say so — several values step on
    2026-09-14 unless the recall sample is labelled (ADR-0050)."""
    app = _run("history-of-ideas")
    text = _text(app)
    assert "2026-09-14" in text and "recall" in text


def test_a_validated_axis_renders_everything(surface, monkeypatch):
    """The gate is a state, not a posture. Labelling the sample lifts it."""
    monkeypatch.setattr("nh.api.gates.EXPOSITION_VALIDATED", True)
    app = _run("history-of-ideas")
    labels = [e.label for e in app.expander if "on_niche_share" in e.label]
    assert labels and "0.42" in labels[0]
    assert "withheld" not in _text(app)


def test_no_page_imports_streamlit_into_the_read_layer():
    """`nh/api/` must stay free of rendering imports, or the nightly acquires a dependency
    on a web framework by transitivity. Asserted on the source, because an import that
    only fires at render time would not show up in a smoke test."""
    import pathlib

    api = pathlib.Path(__file__).resolve().parents[1] / "nh" / "api"
    for path in api.rglob("*.py"):
        assert "streamlit" not in path.read_text(), f"{path.name} imports the renderer"


def test_the_alerts_page_renders_and_is_not_ranked_by_severity(surface):
    """A feed sorted by badness is a ranking of niches arrived at sideways."""
    app = _run("Alerts")
    assert not app.exception
    text = _text(app)
    assert "Alerts" in text
    assert "Newest first" in text and "not ranked by severity" in text
    assert "INSIGHT_RULES" in text, "a three-rule feed must say what it does not cover"


def test_an_empty_alerts_feed_explains_itself(surface):
    """Zero alerts on a fresh database is the normal state, not a fault — and a blank page
    reads as a broken one."""
    app = _run("Alerts")
    assert "No alerts" in _text(app)


def test_the_reports_page_renders_and_hides_the_draws(surface):
    """The page reads the real `reports/` directory, so this is the end-to-end check that
    no answer key reaches a screen."""
    app = _run("Reports")
    assert not app.exception
    text = _text(app)
    assert "Reports" in text
    assert "deliberately" in text and "relevance a labeller must not see" in text
    assert "draw_key" not in str(app.selectbox[1].options if len(app.selectbox) > 1 else [])
