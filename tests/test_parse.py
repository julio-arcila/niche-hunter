"""Absent data is NULL, never 0 (.claude/rules/data.md rule 6)."""

from __future__ import annotations

import pytest

from nh.collectors.parse import as_bool, as_float, as_int, as_utc, iso_duration_s


@pytest.mark.parametrize("missing", [None, "", "not-a-number", {}])
def test_absent_numbers_are_none_not_zero(missing):
    assert as_int(missing) is None
    assert as_float(missing) is None


def test_hidden_subscriber_count_stays_null():
    """The prototype's int(st.get("subscriberCount", 0)) turned a channel that
    hides its subs into a channel with zero subs — a real number that poisons
    every views-per-sub ratio computed from it."""
    stats = {"viewCount": "120", "hiddenSubscriberCount": True}
    assert as_int(stats.get("subscriberCount")) is None
    assert as_int(stats.get("viewCount")) == 120


def test_zero_is_preserved_when_genuinely_reported():
    assert as_int(0) == 0
    assert as_int("0") == 0


def test_iso_duration():
    assert iso_duration_s("PT8M31S") == 511
    assert iso_duration_s("PT1H2M3S") == 3723
    assert iso_duration_s("PT45S") == 45
    assert iso_duration_s(None) is None
    assert iso_duration_s("garbage") is None


def test_as_utc_normalizes_z_suffix():
    parsed = as_utc("2026-08-27T04:05:06Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.hour == 4
    assert as_utc("nonsense") is None


def test_as_bool_is_tristate():
    assert as_bool("true") is True
    assert as_bool("false") is False
    assert as_bool(None) is None
    assert as_bool("maybe") is None
