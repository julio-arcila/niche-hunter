"""Supply metrics: the volume and reach of content already in the niche."""

from __future__ import annotations

from datetime import timedelta

import pytest
import sqlalchemy as sa

import nh.features.inputs as inputs
from nh.db.session import session_scope
from nh.features.inputs import BALLAST_DECIDED, member_channels, numerator_coverage
from nh.features.supply import (
    DEFINITION,
    DEFINITION_PRE_BALLAST,
    geo_concentration,
    median_views,
    on_niche_share,
    uploads_per_week,
    views_per_new_video,
)
from tests.conftest_features import CLUSTER, DAY, RUN, add_channel, make_cluster, session_for


def test_uploads_per_week_sums_channel_rates_not_a_channel_average(engine):
    """A cluster total: supply is the volume a newcomer competes against.

    Each channel's oldest known video is 23 days old, so each is a rate over its
    24-day observed span (data rule 9): 4 / (24/7) = 7/6 per channel. The total is
    the sum, 7/3 — a per-channel average would halve it.
    """
    make_cluster(engine)
    add_channel(engine, "a", videos=4, age_days=20)
    add_channel(engine, "b", videos=4, age_days=20)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == pytest.approx(7 / 3)


def test_uploads_outside_the_window_are_not_counted(engine):
    make_cluster(engine)
    add_channel(engine, "recent", videos=4, age_days=20)  # observed span 24d -> 4/(24/7)
    add_channel(engine, "stale", videos=40, age_days=200)  # all outside; contributes 0
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == pytest.approx(7 / 6)


def test_a_niche_that_published_nothing_is_a_confident_zero_not_null(engine):
    """The distinction the whole NULL discipline exists for: we looked, and the
    answer was zero. That is a finding about the niche, not missing data."""
    make_cluster(engine)
    add_channel(engine, "dormant", videos=3, age_days=300)
    result = uploads_per_week(session_for(engine), CLUSTER, DAY)
    assert result.value == 0.0
    assert result.confidence > 0


def test_a_cluster_with_no_channels_is_null_not_zero(engine):
    make_cluster(engine)
    result = uploads_per_week(session_for(engine), CLUSTER, DAY)
    assert result.value is None
    assert result.confidence == 0.0


def test_unknown_format_videos_are_excluded_from_supply(engine):
    make_cluster(engine)
    add_channel(engine, "unenriched", videos=8, age_days=1, is_short=None)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == 0.0


def test_shorts_are_excluded_from_supply(engine):
    make_cluster(engine)
    add_channel(engine, "shorts", videos=8, age_days=1, is_short=True)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).value == 0.0


def test_median_views_pools_across_channels(engine):
    """Pooled, not median-of-medians: a 500-sub channel should not weigh as much
    as a 30M one when measuring the field you compete against."""
    make_cluster(engine)
    add_channel(engine, "small", videos=1, views=[10])
    add_channel(engine, "big", videos=3, views=[1_000, 2_000, 3_000])
    # pool is [10, 1000, 2000, 3000]; the small channel is one vote, not half the weight
    assert median_views(session_for(engine), CLUSTER, DAY).value == 1_500


def test_videos_younger_than_the_age_floor_are_excluded(engine):
    """Views on a very fresh upload have not settled; comparing one against an
    older video measures age rather than performance."""
    make_cluster(engine)
    add_channel(engine, "fresh", videos=3, views=[1, 2, 3], age_days=2)
    result = median_views(session_for(engine), CLUSTER, DAY)
    assert result.value is None
    assert "age" in result.detail["reason"] or "eligible" in result.detail["reason"]


def test_only_snapshots_up_to_the_day_are_read(engine):
    """The anti-leakage property Slice 6's backtest depends on: a feature must
    never see a row that did not exist at the decision date."""
    make_cluster(engine)
    add_channel(engine, "a", videos=1, views=[500])
    past = median_views(session_for(engine), CLUSTER, DAY - timedelta(days=1))
    assert past.value is None  # the snapshot is dated DAY, so a day earlier sees nothing


def test_confidence_falls_when_the_metric_sees_little_of_the_niche(engine):
    """74 contributing channels of 197 must not report full confidence just
    because 74 clears the adequacy bar."""
    make_cluster(engine)
    add_channel(engine, "contributes", videos=5, views=100)
    for i in range(9):
        add_channel(engine, f"silent{i}", videos=0)
    result = median_views(session_for(engine), CLUSTER, DAY)
    assert result.confidence < 0.2  # 1 of 10 channels, and 1 is far below n=30


# -- geo_concentration -------------------------------------------------------


def _seeded_cluster(engine, geo="US"):
    from nh.db.models import Cluster, NicheSeed

    with session_scope(engine) as s:
        s.add(NicheSeed(id=1, slug=CLUSTER, label="Aviation", keywords=[], geo=geo))
        s.flush()
        s.add(Cluster(cluster_id=CLUSTER, seed_id=1, source="clustering", run_id=RUN))


def _country(engine, channel_id, country):
    from nh.db.models import Channel

    with session_scope(engine) as s:
        s.execute(
            sa.update(Channel).where(Channel.channel_id == channel_id).values(country=country)
        )
        s.commit()


def test_geo_concentration_is_the_share_from_the_stated_market(engine):
    _seeded_cluster(engine, geo="US")
    for name, country in (("UCa", "US"), ("UCb", "US"), ("UCc", "IN"), ("UCd", "GB")):
        add_channel(engine, name, videos=1)
        _country(engine, name, country)

    with session_scope(engine) as s:
        result = geo_concentration(s, CLUSTER, DAY)

    assert result.value == 0.5
    assert result.detail["seed_geo"] == "US"


def test_an_unknown_country_lowers_confidence_rather_than_counting_as_foreign(engine):
    """Data rule 7. 236 of 955 real channels report no country; treating them as
    "not local" would understate every niche by a quarter."""
    _seeded_cluster(engine, geo="US")
    add_channel(engine, "UCknown", videos=1)
    _country(engine, "UCknown", "US")
    add_channel(engine, "UCunknown", videos=1)  # country stays NULL

    with session_scope(engine) as s:
        result = geo_concentration(s, CLUSTER, DAY)

    assert result.value == 1.0  # the one channel we can place is local
    assert result.confidence == 0.5  # but we could only place half of them
    assert result.inputs_n == 1


def test_a_seed_with_no_stated_geo_has_nothing_to_diverge_from(engine):
    _seeded_cluster(engine, geo=None)
    add_channel(engine, "UCa", videos=1)
    _country(engine, "UCa", "US")

    with session_scope(engine) as s:
        result = geo_concentration(s, CLUSTER, DAY)

    assert result.value is None
    assert "states no geo" in result.detail["reason"]


def test_it_reports_where_the_supply_actually_is(engine):
    """The detail is the point: a low value is only actionable if you can see which
    market the supply came from instead."""
    _seeded_cluster(engine, geo="US")
    for name, country in (("UCa", "IN"), ("UCb", "IN"), ("UCc", "IN"), ("UCd", "US")):
        add_channel(engine, name, videos=1)
        _country(engine, name, country)

    with session_scope(engine) as s:
        result = geo_concentration(s, CLUSTER, DAY)

    assert result.value == 0.25
    assert result.detail["top_countries"][0] == ("IN", 3)


# -- pressure_index ----------------------------------------------------------


def test_pressure_index_is_the_mean_of_two_ranks_not_a_weighted_blend(engine):
    """Mean of ranks invents no weights. Any coefficient on "how big are the
    winners" versus "how much arrives" would be a fabricated constant with nothing
    to calibrate it against until Gate E."""
    from functools import partial

    from nh.db.provenance import stamp
    from nh.db.types import utcnow
    from nh.features.run import compute

    make_cluster(engine, "a")
    make_cluster(engine, "b")
    # `a` wins on median_views, `b` wins on uploads — the ranks should cancel.
    add_channel(engine, "UCa", cluster_id="a", videos=6, views=10_000, age_days=20)
    add_channel(engine, "UCb1", cluster_id="b", videos=6, views=10, age_days=20)
    add_channel(engine, "UCb2", cluster_id="b", videos=6, views=10, age_days=20)

    mark = partial(stamp, source="features", run_id="t", at=utcnow())
    with session_scope(engine) as s:
        compute(s, DAY, mark)
        rows = dict(
            s.execute(
                sa.text("SELECT cluster_id, value FROM features_daily WHERE name='pressure_index'")
            ).all()
        )
    assert set(rows) == {"a", "b"}
    # Two clusters, opposite ranks on the two components -> both land at 0.5.
    assert rows["a"] == pytest.approx(0.5)
    assert rows["b"] == pytest.approx(0.5)


def test_pressure_index_records_its_components_and_population(engine):
    """A rank is only meaningful against the set it was taken over, so the set is
    part of the row."""
    from functools import partial

    from nh.db.provenance import stamp
    from nh.db.types import utcnow
    from nh.features.run import compute

    make_cluster(engine, "a")
    make_cluster(engine, "b")
    add_channel(engine, "UCa", cluster_id="a", videos=6, views=10_000, age_days=20)
    add_channel(engine, "UCb", cluster_id="b", videos=6, views=10, age_days=20)

    mark = partial(stamp, source="features", run_id="t", at=utcnow())
    with session_scope(engine) as s:
        compute(s, DAY, mark)
        detail = s.execute(
            sa.text(
                "SELECT detail FROM features_daily WHERE name='pressure_index' AND cluster_id='a'"
            )
        ).scalar()
    import json

    detail = json.loads(detail) if isinstance(detail, str) else detail
    assert set(detail["components"]) == {"median_views", "uploads_per_week"}
    assert detail["ranked_over"] == ["a", "b"]


# -- views_per_new_video: the replayable supply analogue ---------------------


def _weekly(engine, channel_id, points, *, start=DAY):
    """`points` is [(total_views, video_count), ...], one per week going back."""
    from datetime import timedelta

    from nh.db.models import ChannelSnapshot

    with session_scope(engine) as s:
        for i, (views, videos) in enumerate(reversed(points)):
            s.add(
                ChannelSnapshot(
                    channel_id=channel_id,
                    observed_date=start - timedelta(days=7 * i),
                    subs=1_000,
                    total_views=views,
                    video_count=videos,
                    source="youniverse",
                    run_id=RUN,
                )
            )


def test_views_per_new_video_differences_the_stocks(engine):
    """10,000 new views over 2 new videos is 5,000 per video."""
    make_cluster(engine)
    add_channel(engine, "UCa", videos=1, age_days=40)
    _weekly(engine, "UCa", [(100_000, 10), (105_000, 11), (110_000, 12)])

    with session_scope(engine) as s:
        result = views_per_new_video(s, CLUSTER, DAY)

    assert result.value == 5_000
    assert result.detail["contributing_channels"] == 1


def test_a_channel_that_published_nothing_is_excluded_not_zeroed(engine):
    """A week with no upload says nothing about reach per upload (data rule 7).
    Counting it as zero would drag every niche's median toward zero in proportion
    to how quiet its channels are."""
    make_cluster(engine)
    add_channel(engine, "UCquiet", videos=1, age_days=40)
    add_channel(engine, "UCbusy", videos=1, age_days=40)
    _weekly(engine, "UCquiet", [(500_000, 40), (500_900, 40)])  # views, no new video
    _weekly(engine, "UCbusy", [(10_000, 5), (14_000, 7)])  # 4,000 over 2 -> 2,000

    with session_scope(engine) as s:
        result = views_per_new_video(s, CLUSTER, DAY)

    assert result.value == 2_000
    assert result.inputs_n == 1
    assert result.confidence == 0.5  # one of two members could contribute


def test_it_reads_nothing_after_the_decision_date(engine):
    """The property that makes it usable in a replay at all."""
    from datetime import timedelta

    make_cluster(engine)
    add_channel(engine, "UCa", videos=1, age_days=40)
    _weekly(engine, "UCa", [(100_000, 10), (110_000, 12)])
    _weekly(engine, "UCa", [(900_000, 13)], start=DAY + timedelta(days=7))

    with session_scope(engine) as s:
        assert views_per_new_video(s, CLUSTER, DAY).value == 5_000


def test_it_is_empty_when_nothing_can_be_differenced(engine):
    make_cluster(engine)
    add_channel(engine, "UCa", videos=1, age_days=40)
    _weekly(engine, "UCa", [(100_000, 10)])  # a single snapshot has no delta

    with session_scope(engine) as s:
        result = views_per_new_video(s, CLUSTER, DAY)

    assert result.value is None
    assert "between two snapshots" in result.detail["reason"]


# -- numerator decisiveness: what bounds trust in a VOLUME ---------------------
# The inversion these protect against shipped untested: on run a6d35aee,
# Spearman(value, confidence) across the eleven live clusters was -0.346, because
# `known == members` everywhere made confidence reduce exactly to
# `relevance_coverage` and a confidently REJECTED video therefore raised
# confidence in a volume it contributes nothing to.
# See reports/supply_audit_2026-08-30.md.


def test_numerator_coverage_counts_the_three_undecided_states_together(engine):
    """`judgeable` is everything not decided off-niche, so it must hold the
    on-niche, the undecided-NULL and the mid-band alike — the three states are not
    two, exactly as `on_niche_join` insists when it excludes them."""
    make_cluster(engine)
    add_channel(engine, "a", videos=2, relevant=True)
    add_channel(engine, "b", videos=3, relevant=False)
    add_channel(engine, "c", videos=4, relevant=None)
    on_niche, judgeable, total = numerator_coverage(session_for(engine), CLUSTER, DAY)
    assert (on_niche, judgeable, total) == (2, 6, 9)


def test_rejecting_a_video_does_not_raise_confidence_in_a_volume(engine):
    """The whole point. Two clusters with the SAME on-niche numerator, differing
    only in how many off-niche videos the scorer confidently rejected.

    Both clusters hold two channels, two on-niche videos and two unscorable ones,
    so adequacy and coverage are identical by construction and only the third leg
    can move. The second cluster adds eight videos the scorer confidently rejected.

    Under the old `decided/total` leg those eight lifted it from 0.5 to 10/12 = 0.833,
    because rejection counted as knowledge. A rejected video is not in this volume
    and cannot make it more certain, so the two must now agree exactly.

    Eight and not forty: at ten decided with no on-niche the channel becomes ballast
    (ADR-0047) and leaves the cluster entirely, which would confound this test by
    changing the adequacy leg as well. The two rules interact and the fixture has to
    stay on one side of it."""
    make_cluster(engine)
    add_channel(engine, "a", videos=2, relevant=True)
    add_channel(engine, "b", videos=2, relevant=None)
    lean = uploads_per_week(session_for(engine), CLUSTER, DAY).confidence

    make_cluster(engine, "other")
    add_channel(engine, "c", videos=2, cluster_id="other", relevant=True)
    rejected = [False] * (BALLAST_DECIDED - 2)  # derived: must stay below the ballast bar
    add_channel(
        engine, "d", videos=2 + len(rejected), cluster_id="other", relevant=[None, None, *rejected]
    )
    padded = uploads_per_week(session_for(engine), "other", DAY).confidence

    assert padded == pytest.approx(lean)


def test_deciding_a_cluster_off_niche_beats_being_unable_to_read_it(engine):
    """The case the coverage leg's own comment defends, arriving through the new
    leg. Both clusters have one channel, five videos and a zero volume, so adequacy
    and coverage are identical and only the third leg can move.

    Every video DECIDED off-niche is full decisiveness — the zero is earned. Every
    video UNSCORABLE is the opposite: nothing was judged, so the same zero is worth
    nothing. `is_noise` records only the decided case, and that distinction is the
    whole reason the three relevance states are not two."""
    make_cluster(engine)
    add_channel(engine, "a", videos=5, relevant=False)
    decided = uploads_per_week(session_for(engine), CLUSTER, DAY)

    make_cluster(engine, "unreadable")
    add_channel(engine, "b", videos=5, cluster_id="unreadable", relevant=None)
    unreadable = uploads_per_week(session_for(engine), "unreadable", DAY)

    assert decided.value == unreadable.value == 0.0
    assert decided.confidence > unreadable.confidence
    assert unreadable.confidence == 0.0


def test_a_cluster_with_no_videos_at_all_is_not_confident(engine):
    """Distinct from the case above and must not collapse into it: there was
    nothing to be decisive about, so 0/0 reads 0.0 rather than 1.0."""
    make_cluster(engine)
    add_channel(engine, "a", videos=0)
    assert uploads_per_week(session_for(engine), CLUSTER, DAY).confidence == 0.0


def test_censoring_is_reported_over_the_channels_that_reach_the_value(engine):
    """Data rule 9 names this counter as the attribution marker for the span-rate
    bump, so it has to range over the population the value is summed from. The
    older `channels_span_censored` ranges over every known channel and is kept
    beside it, unchanged, so rows on both sides of 2026-08-30 stay readable."""
    make_cluster(engine)
    add_channel(engine, "publisher", videos=3, age_days=5)
    add_channel(engine, "quiet", videos=2, age_days=200)
    detail = uploads_per_week(session_for(engine), CLUSTER, DAY).detail
    assert detail["contributing_span_censored"] == 1
    assert detail["channels_span_censored"] == 1
    assert detail["contributing_span_censored"] <= detail["channels_publishing_in_window"]


# --- ADR-0050's sunset -------------------------------------------------------------
#
# ADR-0047 changed a published number threefold on machine judgement alone, and the
# sample that can test it is drawn and unlabelled. The sunset is what stops that state
# from becoming permanent by inattention, so it is the mechanism these pin — not the
# date, which an ADR may move, but the two properties a later edit could break without
# anyone noticing: that the switch actually reverts the predicate, and that the stored
# row never claims a cut that did not happen.


def test_the_sunset_reverts_the_predicate_and_leaves_the_numerator_alone(engine, monkeypatch):
    """Past the sunset, ballast rows come back into the denominator and only there.

    Numerator invariance is ADR-0047's load-bearing claim, so it is asserted on BOTH
    sides of the switch rather than once: a ballast channel has no video above the
    threshold, so flipping the rule can only ever move a denominator.
    """
    make_cluster(engine)
    add_channel(engine, "real", videos=3, relevant=True)
    add_channel(engine, "ballast", videos=BALLAST_DECIDED, relevant=False)
    session = session_for(engine)

    on_v3, judgeable_v3, total_v3 = numerator_coverage(session, CLUSTER, DAY)
    monkeypatch.setattr(inputs, "BALLAST_SUNSET", DAY - timedelta(days=1))
    on_v2, judgeable_v2, total_v2 = numerator_coverage(session, CLUSTER, DAY)

    assert on_v3 == on_v2 == 3
    # `total` is where the revert shows, and `judgeable` is where it must not:
    # `judgeable` counts what is not decided off-niche, and every ballast row is
    # decided off-niche by construction, so it is unmoved on both sides.
    assert total_v3 == 3
    assert total_v2 == 3 + BALLAST_DECIDED
    assert judgeable_v3 == judgeable_v2 == 3


def test_the_definition_tag_moves_in_the_same_instant_as_the_predicate(engine, monkeypatch):
    """A row stamped v3 while the predicate is inert is worse than either state."""
    make_cluster(engine)
    add_channel(engine, "real", videos=3, relevant=True)
    add_channel(engine, "ballast", videos=BALLAST_DECIDED, relevant=False)
    session = session_for(engine)

    before = on_niche_share(session, CLUSTER, DAY).detail
    assert before["definition"] == DEFINITION
    assert before["ballast"] == {
        "active": True,
        "n": BALLAST_DECIDED,
        "channels": 1,
        "rows": BALLAST_DECIDED,
    }

    monkeypatch.setattr(inputs, "BALLAST_SUNSET", DAY - timedelta(days=1))
    after = on_niche_share(session, CLUSTER, DAY).detail
    assert after["definition"] == DEFINITION_PRE_BALLAST
    assert after["ballast"] == {"active": False, "n": BALLAST_DECIDED, "channels": 0, "rows": 0}
    assert after["on_niche"] == before["on_niche"]
    assert after["decided"] > before["decided"]


def test_a_recorded_result_overrides_the_date_in_both_directions(engine, monkeypatch):
    """`BALLAST_VALIDATED` is the human's verdict and outranks the calendar.

    Both directions, because only one of them is the happy path: a sample that comes
    back FAILING must revert immediately, not wait for a date that is still in the
    future. ADR-0050 commits to both branches, so both are pinned.
    """
    from datetime import date

    monkeypatch.setattr(inputs, "BALLAST_VALIDATED", True)
    assert inputs.ballast_active(date(2099, 1, 1)) is True

    monkeypatch.setattr(inputs, "BALLAST_VALIDATED", False)
    assert inputs.ballast_active(date(2000, 1, 1)) is False


def test_the_sunset_is_the_operators_calendar_not_the_decision_date(engine, monkeypatch):
    """`day` must not reach the switch.

    `inputs.py` promises a feature never sees a row that did not exist at its decision
    date, and ADR-0047 was redesigned around exactly that. A sunset keyed on `day`
    would put it straight back: a 2025 replay would silently run under v2 while today's
    nightly runs under v3, and the two series would differ for a reason no stored row
    records.
    """
    from datetime import date

    monkeypatch.setattr(inputs, "BALLAST_SUNSET", date(2026, 9, 14))
    assert inputs.ballast_active(date(2026, 9, 13)) is True
    assert inputs.ballast_active(date(2026, 9, 14)) is False
    # The feature's `day` is a different argument entirely and cannot reach it.
    assert "day" not in inputs.ballast_active.__code__.co_varnames


def test_the_sunset_reaches_the_channel_population_too(engine, monkeypatch):
    """`member_channels` must revert with everything else.

    It did not. It called `_ballast_channels` directly rather than going through the
    switch, so after the sunset it went on excluding ballast channels while
    `views_per_new_video` — computed from exactly those channels — stamped
    `v2-on-niche` on the row. Measured on the live corpus before the fix: members
    stayed at 110 across the flip while the definition tag moved. A row that lies about
    its own definition is the failure ADR-0050 exists to prevent, reproduced inside
    ADR-0050 by the change that was meant to prevent it.
    """
    make_cluster(engine)
    add_channel(engine, "real", videos=3, relevant=True)
    add_channel(engine, "ballast", videos=BALLAST_DECIDED, relevant=False)
    session = session_for(engine)

    assert member_channels(session, CLUSTER, DAY) == ["real"]
    monkeypatch.setattr(inputs, "BALLAST_SUNSET", DAY - timedelta(days=1))
    assert sorted(member_channels(session, CLUSTER, DAY)) == ["ballast", "real"]


def test_nothing_calls_the_ballast_subquery_around_the_switch():
    """The durable half of the fix above, and the reason it is a test.

    The defect arrived because someone added a second call site and every review read
    the diff instead of the call graph. `_ballast_channels` may be reached only from
    `exclude_ballast`, which consults `ballast_active()`, and from `_ballast_detail`,
    which guards itself and reports zeros when the switch is off. A third call site is
    a bug by construction, so this fails on one rather than waiting for a reviewer to
    notice the population and the tag disagreeing.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "nh"
    allowed = {
        ("features/inputs.py", "exclude_ballast"),
        ("features/supply.py", "_ballast_detail"),
    }
    found = set()
    for path in sorted(root.rglob("*.py")):
        src = path.read_text()
        function = None
        for line in src.splitlines():
            if match := re.match(r"^def (\w+)", line):
                function = match.group(1)
            if "_ballast_channels(" in line and not line.lstrip().startswith("def "):
                found.add((str(path.relative_to(root)), function))

    assert found == allowed, f"unexpected _ballast_channels call site(s): {sorted(found - allowed)}"


def test_a_run_cannot_cross_the_sunset_half_way_through(engine, monkeypatch):
    """`pinned_ballast` resolves once and holds (ADR-0050).

    A nightly starting at 23:58 on 2026-09-13 would otherwise compute its first
    clusters under v3 and the rest under v2, inside one `run_id` — which is the
    mixed-day defect ADR-0044's addendum had to delete rows to repair, arriving on a
    schedule nobody chose. The clock is moved here MID-BLOCK, which is the only way to
    test the property that matters.
    """
    from datetime import date

    monkeypatch.setattr(inputs, "BALLAST_SUNSET", date(2026, 9, 14))
    with inputs.pinned_ballast() as active:
        assert active is True
        monkeypatch.setattr(inputs, "BALLAST_SUNSET", date(2000, 1, 1))
        assert inputs.ballast_active() is True, "the pin must survive the clock moving"
    assert inputs.ballast_active() is False, "and must not outlive the run"


def test_an_explicit_pin_lets_history_be_replayed_under_a_chosen_definition(engine, monkeypatch):
    """What makes the v2/v3 comparison possible at all.

    Three of nine `BACKTEST_METRICS` route through the ballast predicate, so the two
    definitions give different numbers for the same historical day. Comparing them
    requires choosing one deliberately rather than waiting for a date to arrive.
    """
    make_cluster(engine)
    add_channel(engine, "real", videos=3, relevant=True)
    add_channel(engine, "ballast", videos=BALLAST_DECIDED, relevant=False)
    session = session_for(engine)

    with inputs.pinned_ballast(True):
        v3 = on_niche_share(session, CLUSTER, DAY)
    with inputs.pinned_ballast(False):
        v2 = on_niche_share(session, CLUSTER, DAY)

    assert v3.detail["definition"] == DEFINITION
    assert v2.detail["definition"] == DEFINITION_PRE_BALLAST
    assert v3.detail["on_niche"] == v2.detail["on_niche"]  # numerator invariance, again
    assert v2.detail["decided"] > v3.detail["decided"]
    assert v2.value < v3.value


def test_a_nested_pin_restores_the_outer_one(engine, monkeypatch):
    """The phase loop pins, and a replay inside a test may pin again. Leaking the inner
    value would silently change every later run in the same process — the class of bug
    that only shows up as a test passing alone and failing in a suite."""
    with inputs.pinned_ballast(True):
        with inputs.pinned_ballast(False):
            assert inputs.ballast_active() is False
        assert inputs.ballast_active() is True
