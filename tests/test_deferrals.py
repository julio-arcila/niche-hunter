"""The deferral register, and the triggers that make it a work queue not a wall.

The one that matters most is the date trigger. ADR-0016 started a four-week clock
on Google Ads access and enforced it with a sentence in an ADR — the same class of
problem ADR-0003 solved for provenance by making the rule mechanical. A clock
nothing checks is a clock that expires unnoticed.
"""

from __future__ import annotations

from datetime import date

import pytest

from nh.db.types import utcnow
from nh.jobs.deferrals import DEFERRALS, Deferral, fires


def _by_kind(kind):
    return [d for d in DEFERRALS if d.kind == kind]


def test_every_deferral_carries_all_four_things():
    """Blocker, trigger, consumer, cost. Any one missing and it is a wall."""
    for deferral in DEFERRALS:
        assert deferral.blocker and deferral.trigger
        assert deferral.consumer and deferral.cost


def test_the_tier1_trigger_needs_both_geo_classes(engine):
    """`tier1_cpc_ratio` compares tier-1 against the rest, so one class is not enough.

    This replaces the Keyword Planner date clock, which died with the last `date`
    deferral. The clock was the wrong instrument in the end: a `date` kind never looks
    at the database, so it went on reporting "blocked" for four months while the data
    it waited on sat ingested. An evidence trigger cannot drift that way.
    """
    from nh.db.models import KeywordMetric
    from nh.db.session import session_scope

    tier1 = next(d for d in DEFERRALS if d.metric == "money.tier1_cpc_ratio")

    def _row(keyword: str, geo: str) -> KeywordMetric:
        return KeywordMetric(
            keyword=keyword,
            geo=geo,
            lang="en",
            observed_date=date(2026, 7, 31),
            source="keyword_planner",
            run_id="t",
            at=utcnow(),
        )

    assert fires(tier1, date(2026, 8, 29), engine) is False, "empty database"

    with session_scope(engine) as s:
        s.add(_row("a", "US"))
        s.add(_row("b", "GB"))
    assert fires(tier1, date(2026, 8, 29), engine) is False, "two tier-1 geos are still one class"

    with session_scope(engine) as s:
        s.add(_row("c", "CO"))
    assert fires(tier1, date(2026, 8, 29), engine) is True, "a non-tier-1 geo completes the pair"


def test_a_setting_trigger_reads_the_settings(monkeypatch):
    reddit = next(d for d in DEFERRALS if d.kind == "setting")
    assert fires(reddit, date(2026, 8, 27)) is False

    from nh.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("NH_REDDIT_CLIENT_ID", "abc123")
    assert isinstance(Settings(), Settings)
    assert fires(reddit, date(2026, 8, 27)) is True
    get_settings.cache_clear()


def test_a_manual_trigger_says_so_rather_than_never_firing():
    """A trigger no machine can answer must report `None`, not `False` — otherwise
    it is indistinguishable from one that is simply never true."""
    for deferral in _by_kind("manual"):
        assert fires(deferral, date(2030, 1, 1)) is None


def test_query_triggers_are_evaluated_against_real_data(engine):
    for deferral in _by_kind("query"):
        assert fires(deferral, date(2026, 8, 27), engine) is False  # empty db, nothing fires


def test_an_unrecognised_query_trigger_returns_none_not_false(engine):
    """Better to say "I cannot check this" than to report a condition unmet."""
    unknown = Deferral(
        metric="x",
        blocker="b",
        kind="query",
        trigger="something nobody wrote code for",
        consumer="c",
        cost="d",
    )
    assert fires(unknown, date(2026, 8, 27), engine) is None


@pytest.mark.parametrize("deferral", DEFERRALS, ids=lambda d: d.metric[:30])
def test_no_deferral_is_silently_unblocked_today(deferral):
    """If this fails, something became implementable and nobody noticed — which is
    the whole point of the register."""
    assert fires(deferral, date(2026, 8, 27)) is not True


def test_the_relevance_validation_deferral_names_slice_7_not_slice_6():
    """It was deferred deliberately, and the boundary is the decision. Slice 6 can
    run on an unvalidated relevance rule because a threshold-sensitivity pass
    substitutes for the check; Slice 7 cannot, because it would build a product
    surface on an unvalidated definition of "niche"."""
    validation = next(d for d in DEFERRALS if "human validation" in d.metric)
    assert "SLICE 7" in validation.trigger
    assert validation.kind == "manual"
    assert "kappa" in validation.blocker


def test_the_ballast_deferral_fires_the_day_ballast_reverts():
    """The register and the code must name the same day, and they use opposite
    comparisons to do it.

    `fires()` is `today > trigger` for every dated deferral; `inputs.ballast_active()`
    is `today < BALLAST_SUNSET`. So the trigger is the last day still blocked, one
    before the constant. Written the obvious way first, the register said "still
    blocked" on the morning the revert had already happened — a one-day lie about the
    one deferral that enforces itself. Pinned here rather than in a comment, because
    this repo's own history is that a rule and the code it describes drift apart and the
    prose is what gets believed.
    """
    from datetime import timedelta

    from nh.features.inputs import BALLAST_SUNSET

    ballast = next(d for d in DEFERRALS if "ballast exclusion" in d.metric)
    assert ballast.kind == "date"
    assert date.fromisoformat(ballast.trigger) == BALLAST_SUNSET - timedelta(days=1)

    day_before, day_of = BALLAST_SUNSET - timedelta(days=1), BALLAST_SUNSET
    assert fires(ballast, day_before) is False
    assert fires(ballast, day_of) is True
