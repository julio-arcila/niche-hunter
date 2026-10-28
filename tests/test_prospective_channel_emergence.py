"""The channel-emergence test (ADR-0069): the outcome, the gate's four exits, and the
refusals that keep a registered read honest. Fixtures only — never the live DB.

The module ships before its read date (2026-12-14), so every one of these tests is the only
thing standing between a registered instrument and a surprise in December.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

import pytest

from nh.db.models import ChannelSnapshot
from nh.db.session import session_scope
from nh.prospective import channel_emergence as ce
from nh.prospective.channel_reach import FrozenRow

T = date(2026, 10, 28)


def _frozen(channel: str, cluster: str = "aviation-disasters", **kw) -> FrozenRow:
    """A frozen row with the registered field set. Defaults are a plausible small channel."""
    base = dict(
        t=T.isoformat(),
        channel_id=channel,
        cluster_id=cluster,
        breakout_magnitude=0.5,
        views_per_sub=3.0,
        ln_median=math.log(3_000),
        ln_subs=math.log(1_000),
        catalogue_age=22.0,
        n_elig=5,
    )
    base.update(kw)
    return FrozenRow(**base)


def _subs(engine, rows: list[tuple[str, date, int, str]]) -> None:
    """(channel, observed_date, subs, source) — append-only, as the collector writes them."""
    with session_scope(engine) as s:
        for channel, day, subs, source in rows:
            s.add(
                ChannelSnapshot(
                    channel_id=channel,
                    observed_date=day,
                    subs=subs,
                    source=source,
                    run_id="t",
                )
            )


# --- the outcome ---------------------------------------------------------------------


def test_the_reading_is_the_smallest_date_inside_90_to_97(engine):
    """A channel read on several days in the window contributes the one nearest its
    horizon, which is ADR-0059's rule for the 14-day outcome applied at 90."""
    _subs(
        engine,
        [
            ("UCa", T + timedelta(days=89), 9_000, "youtube_api"),  # before the window
            ("UCa", T + timedelta(days=92), 2_000, "youtube_api"),  # the one
            ("UCa", T + timedelta(days=95), 5_000, "youtube_api"),
        ],
    )
    with session_scope(engine) as s:
        out = ce.subs_growth_90d(s, [_frozen("UCa")], T)
    assert out["UCa"].subs_r == 2_000
    assert out["UCa"].read_on == T + timedelta(days=92)
    assert out["UCa"].value == pytest.approx(math.log(2_000 / 1_000))


def test_the_reading_is_the_max_across_sources_on_that_day(engine):
    _subs(
        engine,
        [
            ("UCa", T + timedelta(days=90), 1_500, "youtube_api"),
            ("UCa", T + timedelta(days=90), 2_500, "other"),
        ],
    )
    with session_scope(engine) as s:
        out = ce.subs_growth_90d(s, [_frozen("UCa")], T)
    assert out["UCa"].subs_r == 2_500


def test_no_reading_in_the_window_is_absent_never_zero(engine):
    """Data rule 7. A terminated channel, or one the nightly missed for eight days, has an
    UNKNOWN outcome — and a zero would read as "lost every subscriber", which is a
    different and false claim."""
    _subs(engine, [("UCa", T + timedelta(days=80), 4_000, "youtube_api")])
    with session_scope(engine) as s:
        out = ce.subs_growth_90d(s, [_frozen("UCa")], T)
    assert out["UCa"].value is None
    assert out["UCa"].subs_r is None


def test_a_null_subs_snapshot_is_not_a_reading(engine):
    """A hidden subscriber count is NULL, never 0 (rule 7), and must not become the
    "smallest day in the window" and turn a later real reading into an absence."""
    with session_scope(engine) as s:
        s.add(
            ChannelSnapshot(
                channel_id="UCa",
                observed_date=T + timedelta(days=90),
                subs=None,
                source="youtube_api",
                run_id="t",
            )
        )
    _subs(engine, [("UCa", T + timedelta(days=93), 2_000, "youtube_api")])
    with session_scope(engine) as s:
        out = ce.subs_growth_90d(s, [_frozen("UCa")], T)
    assert out["UCa"].read_on == T + timedelta(days=93)
    assert out["UCa"].value == pytest.approx(math.log(2.0))


def test_a_flat_channel_scores_zero_rather_than_being_absent(engine):
    """Zero growth is a measurement, not a missing one — and it is the case the tied-share
    guard counts, because YouTube's 3-significant-figure publication floor produces it."""
    _subs(engine, [("UCa", T + timedelta(days=91), 1_000, "youtube_api")])
    with session_scope(engine) as s:
        out = ce.subs_growth_90d(s, [_frozen("UCa")], T)
    assert out["UCa"].value == 0.0


def test_rows_frozen_at_another_date_are_not_scored_here(engine):
    """`subs_growth_90d` is per decision date; the 09-08 cohort's window opens a week
    later and mixing them would read one date's outcome against the other's horizon."""
    _subs(engine, [("UCb", T + timedelta(days=92), 2_000, "youtube_api")])
    with session_scope(engine) as s:
        out = ce.subs_growth_90d(s, [_frozen("UCb", t="2026-09-08")], T)
    assert out == {}


# --- the gate's four exits -----------------------------------------------------------


def _findings(**kw) -> ce.Findings:
    base = dict(
        n_channels=400,
        clusters_at_floor=6,
        n_terminated=3,
        tied=0.05,
        t0e=ce.Hypothesis(0.30, 0.001, None),
        h1e=ce.Hypothesis(0.20, 0.001, 1.40, absolute=300.0),
    )
    base.update(kw)
    return ce.Findings(**base)


def test_a_pass_needs_rho_p_and_the_lift_floor():
    assert ce.verdict(_findings())["H1e"][0] == "PASS"
    A = 300.0
    assert ce.verdict(_findings(h1e=ce.Hypothesis(0.20, 0.001, 1.10, A)))["H1e"][0] == "FAIL"
    assert ce.verdict(_findings(h1e=ce.Hypothesis(-0.20, 0.001, 1.40, A)))["H1e"][0] == "FAIL"
    assert ce.verdict(_findings(h1e=ce.Hypothesis(0.20, 0.40, 1.40, A)))["H1e"][0] == "FAIL"


def test_under_the_floors_is_inconclusive_not_a_fail():
    """The registered n was not reached, so the hypothesis was not tested. Recording that
    as a FAIL would put a measurement failure on the record as a finding."""
    assert "INCONCLUSIVE" in ce.verdict(_findings(n_channels=199))["H1e"][0]
    assert "INCONCLUSIVE" in ce.verdict(_findings(clusters_at_floor=4))["H1e"][0]


def test_a_degenerate_outcome_is_instrument_not_a_fail():
    """Measured 2026-10-22: at least 10% of cohort channels show no movement over 18 days,
    because YouTube publishes 3 significant figures. Past the cap the outcome cannot carry
    a rank, and blaming the predictor for that would be blaming it for the instrument."""
    verdict = ce.verdict(_findings(tied=0.41))["H1e"]
    assert verdict[0].startswith("INSTRUMENT")
    assert "41%" in verdict[1]
    assert ce.verdict(_findings(tied=0.39))["H1e"][0] == "PASS"


def test_a_null_instrument_check_stops_before_h1e():
    """T0e asks whether 14-day reach reaches subscribers at ALL. If it does not, the
    predictor was never given a route to the outcome, so H1e is not evidence either way —
    and the gate must not report the H1e number as a verdict."""
    verdict = ce.verdict(_findings(t0e=ce.Hypothesis(0.01, 0.80, None)))["H1e"]
    assert verdict[0].startswith("INSTRUMENT")
    assert "p 0.8000" in verdict[1]


def test_the_gate_reports_exactly_one_hypothesis():
    """No H2. ADR-0060's was registered at 5% power and its FAIL said nothing; a second
    gated hypothesis here would buy another uninterpretable result."""
    assert set(ce.verdict(_findings())) == {"H1e"}


# --- the refusals --------------------------------------------------------------------


def _key(tmp_path, rows: list[FrozenRow]):
    import hashlib

    path = tmp_path / "key.jsonl"
    body = "".join(
        json.dumps(
            {
                "t": r.t,
                "channel_id": r.channel_id,
                "cluster_id": r.cluster_id,
                "breakout_magnitude": r.breakout_magnitude,
                "views_per_sub": r.views_per_sub,
                "ln_median": r.ln_median,
                "ln_subs": r.ln_subs,
                "catalogue_age": r.catalogue_age,
                "n_elig": r.n_elig,
            },
            sort_keys=True,
        )
        + "\n"
        for r in rows
    )
    path.write_text(body)
    return path, hashlib.sha256(body.encode()).hexdigest()


def test_an_unregistered_test_cannot_be_read(engine, tmp_path, monkeypatch):
    path, _ = _key(tmp_path, [_frozen("UCa")])
    monkeypatch.setattr(ce, "REGISTERED_KEY_SHA256", None)
    with session_scope(engine) as s, pytest.raises(ce.NotRegistered):
        ce.refuse_unless_ready(s, key_path=path)


def test_an_altered_key_is_refused(engine, tmp_path, monkeypatch):
    path, _ = _key(tmp_path, [_frozen("UCa")])
    monkeypatch.setattr(ce, "REGISTERED_KEY_SHA256", "0" * 64)
    with session_scope(engine) as s, pytest.raises(ce.KeyMismatch):
        ce.refuse_unless_ready(s, key_path=path)


def test_a_read_before_its_date_is_collected_is_refused(engine, tmp_path, monkeypatch):
    """Judged from the DATA, not the clock: the outcomes do not all exist until that date's
    nightly has run, and computing one early is a void condition."""
    path, sha = _key(tmp_path, [_frozen("UCa")])
    monkeypatch.setattr(ce, "REGISTERED_KEY_SHA256", sha)
    _subs(engine, [("UCa", ce.READ_DATE - timedelta(days=1), 2_000, "youtube_api")])
    with session_scope(engine) as s, pytest.raises(ce.TooEarly):
        ce.refuse_unless_ready(s, key_path=path)


def test_a_rendered_report_is_not_rendered_twice(engine, tmp_path, monkeypatch):
    path, sha = _key(tmp_path, [_frozen("UCa")])
    monkeypatch.setattr(ce, "REGISTERED_KEY_SHA256", sha)
    monkeypatch.setattr(ce, "REPORT", tmp_path / "already.md")
    (tmp_path / "already.md").write_text("a verdict")
    _subs(engine, [("UCa", ce.READ_DATE, 2_000, "youtube_api")])
    with session_scope(engine) as s, pytest.raises(FileExistsError):
        ce.refuse_unless_ready(s, key_path=path)


def test_a_collected_read_date_and_a_matching_key_is_allowed(engine, tmp_path, monkeypatch):
    """The positive case, so the refusals above are not passing for want of a world."""
    rows = [_frozen("UCa")]
    path, sha = _key(tmp_path, rows)
    monkeypatch.setattr(ce, "REGISTERED_KEY_SHA256", sha)
    monkeypatch.setattr(ce, "REPORT", tmp_path / "not-yet.md")
    _subs(engine, [("UCa", ce.READ_DATE, 2_000, "youtube_api")])
    with session_scope(engine) as s:
        got = ce.refuse_unless_ready(s, key_path=path)
    assert [r.channel_id for r in got] == ["UCa"]


# --- the registration's own constants ------------------------------------------------


def test_the_constants_are_the_registered_ones():
    """The registration document is the authority; these are what the code promises it.
    A drift here is a drift between what was registered and what will be computed."""
    assert ce.REGISTRATION == "reports/channel_emergence_preregistration_2026-10-28.md"
    assert date(2027, 2, 3) == ce.READ_DATE
    assert (date(2026, 10, 28),) == ce.DECISION_DATES
    assert (ce.OUTCOME_MIN_AGE, ce.OUTCOME_MAX_AGE) == (90, 97)
    assert (ce.MIN_CHANNELS, ce.MIN_CLUSTERS, ce.CLUSTER_FLOOR) == (200, 5, 20)
    assert ce.ALPHA == 0.05
    assert ce.MAX_TIED_SHARE == 0.40
    assert ce.SEED == 20270203
    # Its OWN cohort, floored — not ADR-0060's. The floor is why the test exists at all.
    assert ce.COHORT_MIN_SUBS == 500
    assert ce.KEY_PATH.name == "channel_emergence_cohort_draw_key_2026-10-28.jsonl"
    assert ce.REGISTERED_KEY_SHA256 == (
        "ed466f9bfd9845a5a544933e94811140e7f75d68ba4417b7b6205ded78e80243"
    )


def test_the_bar_has_a_relative_and_an_absolute_floor():
    """ADR-0070's correction. A lift is a ratio and therefore satisfiable at any scale,
    including one where the result is worthless — which is how the voided registration's
    bar came to mean two subscribers."""
    assert ce.LIFT_FLOOR == 1.25
    assert ce.ABSOLUTE_FLOOR_SUBS == 50


def test_a_real_lift_on_a_trivial_absolute_gain_fails():
    """The exact failure that voided ADR-0069, now a FAIL instead of a PASS."""
    state, why = ce.verdict(_findings(h1e=ce.Hypothesis(0.20, 0.001, 1.30, 2.0)))["H1e"]
    assert state == "FAIL"
    assert "+2 subscribers is below 50" in why
    assert "ADR-0070" in why


def test_the_frozen_key_matches_its_registration_and_clears_the_floor():
    """A registration whose key has moved is void by its own clause, and this is the
    cheapest check of that. Also asserts every frozen row is above the subscriber floor —
    the property the whole re-registration exists to secure."""
    import math

    rows, sha = ce.load_key(ce.KEY_PATH)
    assert sha == ce.REGISTERED_KEY_SHA256
    assert len(rows) == 1931
    assert {r.t for r in rows} == {"2026-10-28"}
    assert min(math.exp(r.ln_subs) for r in rows) >= ce.COHORT_MIN_SUBS - 1


def test_the_registration_document_exists_and_states_what_it_replaced():
    """A registered constant pointing at a file nobody wrote is not a registration — and
    this one must also carry why its predecessor was void, or the next reader re-makes the
    same bar."""
    from pathlib import Path

    body = Path(ce.REGISTRATION).read_text()
    assert ce.REGISTERED_KEY_SHA256 in body
    assert "2027-02-03" in body and "1.25" in body
    assert "50 subscribers" in body
    assert "ADR-0070" in body and "+2.2 subscribers" in body
    assert "1,480" in body, "the top-decile subscriber median is the number that justifies it"
