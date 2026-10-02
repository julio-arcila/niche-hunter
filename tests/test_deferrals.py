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


def test_rss_acceleration_is_manual_and_names_the_rule_it_would_break():
    """ADR-0064. Its `query` trigger counted DAYS and fired on 2026-09-27 while the
    prototype needs a per-VIDEO series across ages, so the register announced work
    that the data rules forbid in that shape. A re-defer that did not say which rule
    would be broken would invite the same port again."""
    entry = next(d for d in DEFERRALS if d.metric == "openness.rss_acceleration")
    assert entry.kind == "manual"
    assert "rule 9" in entry.blocker
    assert "video_velocity" in entry.blocker
    assert "AGE-anchored" in entry.trigger
    # Not a date and not a query: either would re-fire on its own, which is the
    # failure this entry just caused.
    assert entry.kind not in {"date", "query"}


def test_the_channel_reach_entry_waits_on_a_person_not_a_date():
    """The reads are rendered; what is left is a human recording H1's verdict. A
    `date` entry would keep reporting UNBLOCKED forever, which is how three entries
    in this register were caught lying."""
    entry = next(d for d in DEFERRALS if d.metric.startswith("channel-reach H1"))
    assert entry.kind == "manual"
    assert "CHANNEL_REACH_H1_VALIDATED" in entry.blocker
    assert "CHANNEL_REACH_H1_VALIDATED" in entry.trigger
    # The licence is the registered one, and it is the thing a later reader will
    # over-read: channels, never a niche, and Gate E stands.
    assert "CHANNELS" in entry.trigger
    assert "Gate E" in entry.trigger


def test_no_discharged_read_entry_is_left_in_the_register():
    """Both scheduled reads of ADR-0060 are rendered. A discharged `date` entry
    cannot be marked done — `fires()` reports a passed date as UNBLOCKED — so it has
    to leave the register entirely."""
    assert not [d for d in DEFERRALS if "INTERIM read" in d.metric]
    assert not [d for d in DEFERRALS if "PRIMARY read" in d.metric]


def test_the_relevance_validation_deferral_names_slice_7_not_slice_6():
    """It was deferred deliberately, and the boundary is the decision. Slice 6 can
    run on an unvalidated relevance rule because a threshold-sensitivity pass
    substitutes for the check; Slice 7 cannot, because it would build a product
    surface on an unvalidated definition of "niche"."""
    validation = next(d for d in DEFERRALS if "human validation" in d.metric)
    assert "SLICE 7" in validation.trigger
    assert validation.kind == "manual"
    assert "kappa" in validation.blocker
