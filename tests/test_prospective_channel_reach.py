"""The channel-reach test (ADR-0060): the frozen side, the outcome side, the gate, and
the refusals that keep a registered read honest. Fixtures only — never the live DB."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta

import pytest

from nh.db.models import Channel, Video, VideoSnapshot
from nh.db.session import session_scope
from nh.features import inputs
from nh.prospective import channel_reach as cr
from tests.conftest_features import CLUSTER, add_channel, make_cluster, session_for

T = date(2026, 9, 1)


def _at(day: date, hh: int = 12, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=UTC)


def _world(engine, videos, snaps):
    """videos: (vid, channel, published, is_short); snaps: (vid, day, views, source)."""
    with session_scope(engine) as s:
        for channel in sorted({v[1] for v in videos}):
            s.add(
                Channel(
                    channel_id=channel, title=channel, first_seen=_at(T), source="t", run_id="t"
                )
            )
        for vid, channel, published, short in videos:
            s.add(
                Video(
                    video_id=vid,
                    channel_id=channel,
                    title=vid,
                    published_at=published,
                    is_short=short,
                    enriched=True,
                    source="t",
                    run_id="t",
                )
            )
        channel_of = {v[0]: v[1] for v in videos}
        for vid, day, views, source in snaps:
            s.add(
                VideoSnapshot(
                    video_id=vid,
                    channel_id=channel_of[vid],
                    observed_date=day,
                    views=views,
                    source=source,
                    run_id="t",
                )
            )


def _reach(engine, channels=("UCa",)):
    return cr.next_reach(session_for(engine), set(channels), T)


# --- the outcome side ---------------------------------------------------------------


def test_the_reading_is_the_smallest_age_inside_14_to_17(engine):
    pub = T + timedelta(days=1)
    _world(
        engine,
        [("v1", "UCa", _at(pub), False)],
        [
            ("v1", pub + timedelta(days=13), 5, "youtube_rss"),
            ("v1", pub + timedelta(days=15), 50, "youtube_rss"),
            ("v1", pub + timedelta(days=16), 80, "youtube_rss"),
        ],
    )
    r = _reach(engine)["UCa"]
    assert r.value == pytest.approx(math.log1p(50)) and (r.n_uploads, r.n_read) == (1, 1)


def test_the_reading_is_the_max_across_sources_on_that_day(engine):
    pub = T + timedelta(days=2)
    _world(
        engine,
        [("v1", "UCa", _at(pub), False)],
        [
            ("v1", pub + timedelta(days=14), 40, "youtube_rss"),
            ("v1", pub + timedelta(days=14), 45, "youtube_api"),
        ],
    )
    assert _reach(engine)["UCa"].value == pytest.approx(math.log1p(45))


def test_a_null_views_snapshot_is_not_a_reading(engine):
    """A NULL must not become the smallest day and turn the real reading after it into
    an absence — the definition was tightened for this before any data existed."""
    pub = T + timedelta(days=3)
    _world(
        engine,
        [("v1", "UCa", _at(pub), False)],
        [
            ("v1", pub + timedelta(days=14), None, "youtube_rss"),
            ("v1", pub + timedelta(days=15), 30, "youtube_api"),
        ],
    )
    assert _reach(engine)["UCa"].value == pytest.approx(math.log1p(30))


def test_no_reading_inside_the_window_is_absent_never_zero(engine):
    pub = T + timedelta(days=1)
    _world(
        engine,
        [("v1", "UCa", _at(pub), False)],
        [
            ("v1", pub + timedelta(days=13), 7, "youtube_rss"),
            ("v1", pub + timedelta(days=18), 9, "youtube_rss"),
        ],
    )
    r = _reach(engine)["UCa"]
    assert r.value is None and (r.n_uploads, r.n_read) == (1, 0)


def test_a_measured_zero_is_a_flop_not_an_absence(engine):
    """ln(1 + views) exists so a video measured at zero views counts. It is the negative
    class this test was built to have."""
    pub = T + timedelta(days=4)
    _world(
        engine,
        [("v1", "UCa", _at(pub), False)],
        [("v1", pub + timedelta(days=14), 0, "youtube_rss")],
    )
    r = _reach(engine)["UCa"]
    assert r.value == 0.0 and r.n_read == 1


def test_the_upload_window_is_civil_days_t_plus_1_through_t_plus_7(engine):
    vids = [
        ("on_t", "UCa", _at(T, 23, 59), False),
        ("first", "UCa", _at(T + timedelta(days=1), 0, 0), False),
        ("last", "UCa", _at(T + timedelta(days=7), 23, 59), False),
        ("after", "UCa", _at(T + timedelta(days=8), 0, 0), False),
    ]
    _world(
        engine, vids, [(v, p.date() + timedelta(days=14), 10, "youtube_rss") for v, _, p, _ in vids]
    )
    assert _reach(engine)["UCa"].n_uploads == 2


def test_shorts_and_unknown_format_are_not_uploads(engine):
    pub = _at(T + timedelta(days=2))
    vids = [("long", "UCa", pub, False), ("short", "UCa", pub, True), ("unknown", "UCa", pub, None)]
    _world(engine, vids, [(v, T + timedelta(days=16), 10, "youtube_rss") for v, *_ in vids])
    assert _reach(engine)["UCa"].n_uploads == 1


def test_a_channel_that_did_not_upload_is_absent_from_the_mapping(engine):
    pub = T + timedelta(days=1)
    _world(
        engine,
        [("v1", "UCa", _at(pub), False), ("old", "UCb", _at(T - timedelta(days=30)), False)],
        [("v1", pub + timedelta(days=14), 10, "youtube_rss")],
    )
    assert set(_reach(engine, ("UCa", "UCb"))) == {"UCa"}


def test_the_value_is_the_mean_over_read_uploads(engine):
    p1, p2 = T + timedelta(days=1), T + timedelta(days=5)
    _world(
        engine,
        [("v1", "UCa", _at(p1), False), ("v2", "UCa", _at(p2), False)],
        [
            ("v1", p1 + timedelta(days=14), 9, "youtube_rss"),
            ("v2", p2 + timedelta(days=17), 99, "youtube_rss"),
        ],
    )
    assert _reach(engine)["UCa"].value == pytest.approx((math.log(10) + math.log(100)) / 2)


# --- the frozen side ----------------------------------------------------------------


def _cohort_world(engine, day=T):
    make_cluster(engine)
    add_channel(
        engine,
        "UCc",
        subs=1_000,
        videos=5,
        age_days=20,
        views=[1_000, 2_000, 3_000, 4_000, 5_000],
        day=day,
    )


def test_frozen_predictors_are_the_registered_quantities(engine):
    _cohort_world(engine)
    rows, absent = cr.freeze_date(session_for(engine), CLUSTER, T)
    (row,) = rows
    assert absent == 0
    assert row.breakout_magnitude == pytest.approx(math.log(5_000 / 3_000))
    assert row.views_per_sub == pytest.approx(3.0)
    assert row.ln_median == pytest.approx(math.log(3_000))
    assert row.ln_subs == pytest.approx(math.log(1_000))
    assert row.n_elig == 5


def test_a_zero_median_is_absent_and_counted_never_scored(engine):
    make_cluster(engine)
    add_channel(engine, "UCz", subs=1_000, videos=5, age_days=20, views=0, day=T)
    rows, absent = cr.freeze_date(session_for(engine), CLUSTER, T)
    assert rows == [] and absent == 1


def test_a_row_dated_after_t_cannot_change_a_frozen_predictor(engine):
    """The anti-leakage property the whole registration rests on."""
    _cohort_world(engine)
    before = cr.freeze_date(session_for(engine), CLUSTER, T)
    with session_scope(engine) as s:
        s.add(
            VideoSnapshot(
                video_id="UCc-v0",
                channel_id="UCc",
                observed_date=T + timedelta(days=3),
                views=10_000_000,
                source="youtube_api",
                run_id="later",
            )
        )
    assert cr.freeze_date(session_for(engine), CLUSTER, T) == before


def test_ballast_cannot_move_a_frozen_predictor(engine):
    _cohort_world(engine)
    with inputs.pinned_ballast(True):
        on = cr.freeze_date(session_for(engine), CLUSTER, T)
    with inputs.pinned_ballast(False):
        off = cr.freeze_date(session_for(engine), CLUSTER, T)
    assert on == off


def test_the_draw_key_is_written_once_and_round_trips(engine, tmp_path):
    _cohort_world(engine)
    rows = cr.freeze(session_for(engine), dates=(T,))
    path = tmp_path / "channel_reach_cohort_draw_key_test.jsonl"
    sha = cr.write_key(rows, path)
    assert cr.load_key(path) == (rows, sha)
    with pytest.raises(FileExistsError):
        cr.write_key(rows, path)


# --- the gate -----------------------------------------------------------------------

GOOD, BAD = cr.Hypothesis(0.3, 0.001, 1.4), cr.Hypothesis(0.05, 0.3, 1.0)
BASE = dict(interim=False, n_channels=600, clusters_at_floor=9, t0=GOOD, h1=GOOD, h2=GOOD)


@pytest.mark.parametrize(
    ("patch", "h1", "h2"),
    [
        ({}, "PASS", "PASS"),
        ({"h2": BAD}, "PASS", "FAIL"),
        ({"h1": BAD}, "FAIL", "NOT TESTED"),
        ({"h1": cr.Hypothesis(0.2, 0.01, 1.1)}, "FAIL", "NOT TESTED"),
        ({"t0": BAD}, "INCONCLUSIVE — INSTRUMENT", "NOT TESTED"),
        ({"n_channels": 150, "t0": BAD}, "INCONCLUSIVE — UNDERPOWERED", "NOT TESTED"),
        ({"clusters_at_floor": 4}, "INCONCLUSIVE — UNDERPOWERED", "NOT TESTED"),
        ({"interim": True}, "INTERIM — not a verdict", "INTERIM — not a verdict"),
    ],
    ids=[
        "both-pass",
        "h2-fails",
        "gate-closed",
        "significant-but-small",
        "instrument",
        "power-before-instrument",
        "too-few-clusters",
        "interim-never-passes",
    ],
)
def test_the_gate_applies_the_registered_order(patch, h1, h2):
    v = cr.verdict(cr.Findings(**{**BASE, **patch}))
    assert (v["H1"][0], v["H2"][0]) == (h1, h2)


# --- the refusals -------------------------------------------------------------------


def _registered_world(engine, tmp_path, monkeypatch, *, latest):
    _cohort_world(engine)
    path = tmp_path / "channel_reach_cohort_draw_key_test.jsonl"
    sha = cr.write_key(cr.freeze(session_for(engine), dates=(T,)), path)
    with session_scope(engine) as s:
        s.add(
            VideoSnapshot(
                video_id="UCc-v0",
                channel_id="UCc",
                observed_date=latest,
                views=1,
                source="youtube_rss",
                run_id="latest",
            )
        )
    return path, sha


def test_an_unregistered_test_cannot_be_read(engine, tmp_path, monkeypatch):
    path, _ = _registered_world(engine, tmp_path, monkeypatch, latest=date(2026, 9, 25))
    monkeypatch.setattr(cr, "REGISTERED_KEY_SHA256", None)
    with pytest.raises(cr.NotRegistered):
        cr.read(session_for(engine), "interim", key_path=path, draws=10)


def test_an_altered_draw_key_is_refused(engine, tmp_path, monkeypatch):
    path, _ = _registered_world(engine, tmp_path, monkeypatch, latest=date(2026, 9, 25))
    monkeypatch.setattr(cr, "REGISTERED_KEY_SHA256", "0" * 64)
    with pytest.raises(cr.KeyMismatch):
        cr.read(session_for(engine), "interim", key_path=path, draws=10)


def test_a_read_before_its_date_is_collected_is_refused(engine, tmp_path, monkeypatch):
    """Judged from the data, not the clock: the outcomes do not all exist until that
    date's nightly has run. Computing them early is one of the void conditions."""
    path, sha = _registered_world(engine, tmp_path, monkeypatch, latest=date(2026, 9, 24))
    monkeypatch.setattr(cr, "REGISTERED_KEY_SHA256", sha)
    with pytest.raises(cr.TooEarly):
        cr.read(session_for(engine), "interim", key_path=path, draws=10)


def test_a_registered_interim_read_renders_and_cannot_pass(engine, tmp_path, monkeypatch):
    path, sha = _registered_world(engine, tmp_path, monkeypatch, latest=date(2026, 9, 25))
    monkeypatch.setattr(cr, "REGISTERED_KEY_SHA256", sha)
    body = cr.read(session_for(engine), "interim", key_path=path, draws=10)
    assert "INTERIM" in body and "**H1: PASS**" not in body
    assert body.index("No niche claim") < body.index("## Verdict"), "caveats precede the verdict"
