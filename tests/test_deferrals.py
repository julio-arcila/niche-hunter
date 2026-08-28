"""The deferral register, and the triggers that make it a work queue not a wall.

The one that matters most is the date trigger. ADR-0016 started a four-week clock
on Google Ads access and enforced it with a sentence in an ADR — the same class of
problem ADR-0003 solved for provenance by making the rule mechanical. A clock
nothing checks is a clock that expires unnoticed.
"""

from __future__ import annotations

from datetime import date

import pytest

from nh.jobs.deferrals import DEFERRALS, Deferral, fires


def _by_kind(kind):
    return [d for d in DEFERRALS if d.kind == kind]


def test_every_deferral_carries_all_four_things():
    """Blocker, trigger, consumer, cost. Any one missing and it is a wall."""
    for deferral in DEFERRALS:
        assert deferral.blocker and deferral.trigger
        assert deferral.consumer and deferral.cost


def test_the_keyword_planner_clock_fires_after_it_expires():
    """ADR-0016's expiry, made mechanical."""
    kp = next(d for d in DEFERRALS if "2026-09-24" in d.trigger)
    assert fires(kp, date(2026, 9, 23)) is False
    assert fires(kp, date(2026, 9, 25)) is True


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
