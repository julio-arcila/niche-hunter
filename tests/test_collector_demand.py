"""The two demand collectors.

Wikipedia's tests are mostly about *time*: which day a row describes, and which
days are too young to trust. Trends' tests are mostly about *shape*: that a whole
curve is one observation and never appended to.
"""

from __future__ import annotations

import itertools
from datetime import date, timedelta

import responses
import sqlalchemy as sa

from nh.collectors.base import Raw
from nh.collectors.trends import TrendsCollector, window_ratio
from nh.collectors.wikipedia import WikipediaCollector, _chunks, _described_day
from nh.db.models import DemandSeries, DemandSnapshot, NicheSeed, SeedTerm
from nh.db.session import session_scope

RUN = "88888888-8888-8888-8888-888888888888"
DAY = date(2026, 8, 27)


def _term(engine, source, term):
    with session_scope(engine) as s:
        if not s.scalar(sa.select(NicheSeed.id)):
            s.add(NicheSeed(id=1, slug="n", label="N", keywords=[]))
            s.flush()
        s.add(SeedTerm(seed_id=1, source=source, term=term, geo="", active=True))


def _wiki(settings, engine):
    return WikipediaCollector(RUN, settings=settings, engine=engine, observed_at=_at(DAY))


def _at(day):
    from datetime import UTC, datetime, time

    return datetime.combine(day, time(12), tzinfo=UTC)


def _payload(article, start, n, views=100):
    return {
        "items": [
            {
                "article": article,
                "timestamp": f"{(start + timedelta(days=i)):%Y%m%d}00",
                "views": views,
            }
            for i in range(n)
        ]
    }


# -- pure helpers ------------------------------------------------------------


def test_a_timestamp_names_the_day_it_describes():
    assert _described_day("2026082700") == date(2026, 8, 27)


def test_ranges_are_chunked_so_no_single_request_is_unbounded():
    chunks = list(_chunks(date(2020, 1, 1), date(2026, 1, 1)))
    assert len(chunks) == 7
    assert chunks[0][0] == date(2020, 1, 1)
    assert chunks[-1][1] == date(2026, 1, 1)
    # contiguous, no gaps and no overlap
    for (_, end), (start, _) in itertools.pairwise(chunks):
        assert start == end + timedelta(days=1)


def test_window_ratio_drops_points_after_the_day():
    points = [[f"2026-01-{d:02d}", 10.0] for d in range(1, 27)]
    points.append(["2026-12-31", 9999.0])
    value, _ = window_ratio(points, date(2026, 6, 1), window=13)
    assert value == 0.0  # the future point is invisible, so both windows are flat


def test_window_ratio_is_null_when_the_prior_window_is_all_zero():
    points = [["2026-01-01", 0.0]] * 13 + [["2026-06-01", 5.0]] * 13
    value, non_zero = window_ratio(points, date(2026, 12, 1), window=13)
    assert value is None
    assert non_zero == 13


# -- wikipedia ---------------------------------------------------------------


@responses.activate
def test_each_daily_count_lands_on_the_day_it_describes(settings, engine):
    """observed_date is the described day; `at` records the fetch. The one place
    those two readings diverge (ADR-0015)."""
    _term(engine, "wikipedia", "Article_A")
    import re

    responses.add(
        responses.GET,
        re.compile(r".*per-article.*"),
        json=_payload("Article_A", date(2023, 1, 1), 3),
        status=200,
    )
    record = _wiki(settings, engine).run()
    assert record.status == "ok", record.error
    with session_scope(engine) as s:
        rows = s.scalars(sa.select(DemandSnapshot).order_by(DemandSnapshot.observed_date)).all()
        described = [r.observed_date for r in rows]
        fetched = {r.at.date() for r in rows}
    assert described[:3] == [date(2023, 1, 1), date(2023, 1, 2), date(2023, 1, 3)]
    assert fetched == {DAY}


@responses.activate
def test_nothing_within_the_maturation_lag_is_requested(settings, engine):
    """Counts finalise over 24-48h and snapshots are first-write-wins, so an early
    fetch would freeze an undercount permanently."""
    import re

    _term(engine, "wikipedia", "Article_A")
    responses.add(responses.GET, re.compile(r".*per-article.*"), json={"items": []}, status=200)
    _wiki(settings, engine).run()
    latest = max(c.request.url.rsplit("/", 1)[-1][:8] for c in responses.calls)
    assert latest <= (DAY - timedelta(days=settings.wiki_lag_days)).strftime("%Y%m%d")


@responses.activate
def test_requests_ask_for_user_traffic_only(settings, engine):
    """Bots are 19-54% of raw counts and not uniform across articles, so
    all-agents would systematically inflate small niches."""
    import re

    _term(engine, "wikipedia", "Article_A")
    responses.add(responses.GET, re.compile(r".*per-article.*"), json={"items": []}, status=200)
    _wiki(settings, engine).run()
    assert all("/user/" in c.request.url for c in responses.calls)


@responses.activate
def test_a_missing_article_is_recorded_as_no_data_not_a_failure(settings, engine):
    import re

    _term(engine, "wikipedia", "Gone")
    responses.add(responses.GET, re.compile(r".*per-article.*"), json={}, status=404)
    record = _wiki(settings, engine).run()
    assert record.status == "ok"
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(DemandSnapshot)) == 0


@responses.activate
def test_refetching_a_described_day_keeps_the_first_reading(settings, engine):
    import re

    _term(engine, "wikipedia", "Article_A")
    responses.add(
        responses.GET,
        re.compile(r".*per-article.*"),
        json=_payload("Article_A", date(2023, 1, 1), 1, views=100),
        status=200,
    )
    _wiki(settings, engine).run()
    responses.reset()
    responses.add(
        responses.GET,
        re.compile(r".*per-article.*"),
        json=_payload("Article_A", date(2023, 1, 1), 1, views=999),
        status=200,
    )
    _wiki(settings, engine).run()
    with session_scope(engine) as s:
        assert s.scalars(sa.select(DemandSnapshot.value)).all() == [100.0]


# -- trends ------------------------------------------------------------------


def test_the_whole_curve_is_one_row_not_one_per_point(settings, engine):
    """Points cannot be appended across fetches: each fetch renormalises to its
    own peak, so a new peak would silently rescale older points."""
    collector = TrendsCollector(RUN, settings=settings, engine=engine)
    batch = collector.normalize(
        Raw(
            "interest_over_time",
            "plane crash||today 5-y",
            {
                "columns": ["plane crash"],
                "index": ["2026-01-04", "2026-01-11"],
                "data": [[10], [20]],
            },
        )
    )
    assert len(batch.snapshots) == 1
    assert batch.snapshots[0].values["points"] == [["2026-01-04", 10.0], ["2026-01-11", 20.0]]


def test_normalize_needs_no_pandas(settings, engine):
    """It reads the split dict, so features and tests need no optional extra."""
    import sys

    collector = TrendsCollector(RUN, settings=settings, engine=engine)
    before = set(sys.modules)
    collector.normalize(
        Raw(
            "interest_over_time",
            "t||today 5-y",
            {"columns": ["t"], "index": ["2026-01-04"], "data": [[1]]},
        )
    )
    assert "pandas" not in set(sys.modules) - before


def test_a_second_observation_the_same_day_is_skipped(settings, engine):
    """The snapshot unique key is the 24h cache — no separate cache table."""
    _term(engine, "trends", "plane crash")
    with session_scope(engine) as s:
        s.add(
            DemandSeries(
                term="plane crash",
                geo="",
                timeframe="today 5-y",
                observed_date=DAY,
                points=[],
                source="trends",
                run_id="earlier",
            )
        )
    collector = TrendsCollector(RUN, settings=settings, engine=engine, observed_at=_at(DAY))
    assert list(collector.fetch()) == []
