"""The Keyword Planner CSV import.

The fixture is a real export, not a hand-built one — the first non-HTTP fixture in
this repo, which is the right shape for a file source: its fixture *is* the file.
`tests/fixtures/keyword_planner/keyword_stats_2026-08-28_us.csv` is byte-identical to
what the browser downloaded on 2026-08-28 (original name
`Keyword Stats 2026-08-28 at 13_23_11.csv`, renamed to ASCII).

Three of these tests exist because the legacy prototype got the same things wrong, and
porting a defect is worse than porting nothing: it never skipped its preamble, it
turned every absent value into a zero, and it needed pandas to do so.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa

from nh.collectors.keyword_planner import (
    KeywordPlannerCollector,
    KeywordPlannerError,
    _number,
    _percent,
    decode,
    parse_period,
    rows,
)
from nh.db.models import KeywordMetric, RawRecord
from nh.db.session import session_scope

FIXTURE = Path(__file__).parent / "fixtures" / "keyword_planner" / "keyword_stats_2026-08-28_us.csv"
RUN = "kp-test-run"

#: Coverage of the first US export, measured 2026-08-28. Pinned so a parser change
#: that silently starts dropping or inventing values fails loudly.
ROWS = 30
WITH_VOLUME = 22
WITH_INDEX = 20
WITH_BIDS = 7
#: The export's own `Todo` and `Estados Unidos` aggregate rows both carry this, and
#: it equals the sum of the 30 keyword rows exactly. A free end-to-end check that the
#: parser neither drops a row nor counts an aggregate row as a keyword.
TOTAL_VOLUME = 179_300


# --------------------------------------------------------------------------
# Pure parsing — no database
# --------------------------------------------------------------------------


def test_the_export_is_utf16_and_decodes_by_sniffing_the_bom():
    assert FIXTURE.read_bytes()[:2] == b"\xff\xfe"
    assert "Keyword" in decode(FIXTURE)


def test_the_header_is_found_by_content_not_by_skipping_lines():
    """The prototype wrote `skiprows=lambda i: i < 2 and False`, which is always
    False and therefore never skipped its two preamble lines. Locating the header by
    its first cell makes the preamble's length irrelevant."""
    text = decode(FIXTURE)
    assert not text.splitlines()[0].startswith("Keyword\t")  # there IS a preamble
    assert len(list(rows(text))) == ROWS


def test_a_file_without_a_header_row_says_so(tmp_path):
    bad = tmp_path / "forecast.csv"
    bad.write_text("Some other export\n\nDate\tImpressions\n2026-01-01\t5\n")
    with pytest.raises(KeywordPlannerError, match="no header row"):
        list(rows(bad.read_text()))


def test_aggregate_rows_are_not_keywords():
    """The export carries `Todo` and one row per location with a blank Keyword. They
    are kept in the file-level raw payload, never counted as keywords."""
    text = decode(FIXTURE)
    assert all(row["Keyword"].strip() for row in rows(text))
    assert sum(1 for line in text.splitlines() if line.split("\t")[0].strip() == "") >= 2


def test_the_period_line_parses_from_spanish():
    assert parse_period("1 de agosto de 2025 - 31 de julio de 2026") == (
        parse_period("1 de agosto de 2025 - 31 de julio de 2026")
    )
    period = parse_period("1 de agosto de 2025 - 31 de julio de 2026")
    assert period.start == date(2025, 8, 1)
    assert period.end == date(2026, 7, 31)


def test_an_unreadable_period_returns_none_rather_than_guessing():
    """A guessed `observed_date` would file a whole export against the wrong twelve
    months, silently. The caller must supply --period-end instead."""
    assert parse_period("1 août 2025 - 31 juillet 2026") is None
    assert parse_period("") is None


def test_quoted_decimal_comma_bids_parse():
    assert _number('"4043,23"') == pytest.approx(4043.23)
    assert _number('"27968,37"') == pytest.approx(27968.37)
    assert _number("50000.0") == 50000.0


def test_an_absent_value_is_none_and_never_zero():
    """Data rule 7, and the prototype's exact defect: `int(num(x) or 0)` made every
    missing cell a zero. A keyword with no measured volume is unknown, not a keyword
    nobody searches for — and the difference poisons every mean built on it."""
    for empty in ("", "   ", "-", "—", None):
        assert _number(empty) is None
    assert _percent("") is None


def test_percent_cells_become_fractions_and_infinity_becomes_none():
    assert _percent("-90%") == pytest.approx(-0.90)
    assert _percent("0%") == 0.0
    assert _percent("+∞") is None  # the export's own sentinel


# --------------------------------------------------------------------------
# The collector
# --------------------------------------------------------------------------


def _ingest(engine, **kw):
    collector = KeywordPlannerCollector(RUN, engine=engine, path=FIXTURE, geo="US", **kw)
    return collector.run(job="kp_import", raise_on_error=True)


def test_ingest_writes_raw_before_normalized(engine):
    run = _ingest(engine)

    with session_scope(engine) as s:
        kinds = dict(
            s.execute(sa.select(RawRecord.kind, sa.func.count()).group_by(RawRecord.kind)).all()
        )
    assert run.status == "ok"
    assert kinds == {"keyword_csv": 1, "keyword": ROWS}


def test_every_row_carries_provenance(engine):
    _ingest(engine)

    with session_scope(engine) as s:
        missing = s.scalar(
            sa.select(sa.func.count())
            .select_from(KeywordMetric)
            .where(
                sa.or_(
                    KeywordMetric.source.is_(None),
                    KeywordMetric.run_id.is_(None),
                    KeywordMetric.at.is_(None),
                )
            )
        )
    assert missing == 0


def test_coverage_matches_the_measured_export(engine):
    _ingest(engine)

    with session_scope(engine) as s:
        total = s.scalar(sa.select(sa.func.count()).select_from(KeywordMetric))
        volume = s.scalar(
            sa.select(sa.func.count()).where(KeywordMetric.avg_monthly_searches.is_not(None))
        )
        index = s.scalar(
            sa.select(sa.func.count()).where(KeywordMetric.competition_index.is_not(None))
        )
        bids = s.scalar(sa.select(sa.func.count()).where(KeywordMetric.bid_high.is_not(None)))
    assert (total, volume, index, bids) == (ROWS, WITH_VOLUME, WITH_INDEX, WITH_BIDS)


def test_the_volume_sum_equals_the_exports_own_aggregate_row(engine):
    """179,300 appears twice in the file, as `Todo` and as `Estados Unidos`. If the
    parser dropped a keyword row or counted an aggregate row as one, this moves."""
    _ingest(engine)

    with session_scope(engine) as s:
        total = s.scalar(sa.select(sa.func.sum(KeywordMetric.avg_monthly_searches)))
    assert int(total) == TOTAL_VOLUME


def test_a_keyword_with_no_data_is_stored_as_null(engine):
    _ingest(engine)

    with session_scope(engine) as s:
        row = s.scalar(sa.select(KeywordMetric).where(KeywordMetric.keyword == "bankruptcy"))
    assert row is not None, "the row exists — absence of data is not absence of the keyword"
    assert row.avg_monthly_searches is None
    assert row.bid_low is None and row.bid_high is None
    assert row.competition_index is None


def test_bids_keep_the_accounts_currency(engine):
    """No FX constant may convert these (ADR-0031). COP in, COP out."""
    _ingest(engine)

    with session_scope(engine) as s:
        row = s.scalar(
            sa.select(KeywordMetric).where(KeywordMetric.keyword == "air traffic control")
        )
    assert row.currency == "COP"
    assert row.bid_low == pytest.approx(4043.23)
    assert row.bid_high == pytest.approx(27968.37)


def test_observed_date_is_the_period_end_with_the_window_explicit(engine):
    """ADR-0027's third reading of `observed_date` — the period the value covers,
    landed on its final day — extended from a week to twelve months."""
    _ingest(engine)

    with session_scope(engine) as s:
        row = s.scalar(sa.select(KeywordMetric).limit(1))
    assert row.observed_date == date(2026, 7, 31)
    assert row.period_start == date(2025, 8, 1)


def test_re_ingesting_the_same_export_writes_nothing_new(engine):
    """`KeywordMetric` is append-only, so the first reading of a period survives and
    a repeated import is a no-op — not an overwrite."""
    first = _ingest(engine)
    second = _ingest(engine)

    with session_scope(engine) as s:
        total = s.scalar(sa.select(sa.func.count()).select_from(KeywordMetric))
    assert first.snapshots_written == ROWS
    assert second.snapshots_written == 0
    assert total == ROWS


def test_a_missing_file_is_reported_not_guessed(engine, tmp_path):
    collector = KeywordPlannerCollector(RUN, engine=engine, path=tmp_path / "nope.csv")
    run = collector.run(job="kp_import")

    assert run.status == "skipped"
