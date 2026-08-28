"""The whole backtest chain on synthetic data: scan, select, load, replay, score.

Every other backtest test checks one module against hand-built inputs. This one
checks that the modules actually fit together, which is where a five-hour scan
followed by a silent zero would otherwise be discovered. It uses the real lexicons,
the real relevance scorer, the real feature functions and the real scorecard builder
— only the corpus is synthetic.

It deliberately does NOT assert a correlation. Six invented channels cannot produce
a finding, and a test that asserted one would be asserting the fixture.
"""

from __future__ import annotations

import gzip
import itertools
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa

from nh.backtest.load import load
from nh.backtest.niches import MIN_MEMBER_CHANNELS, MIN_ON_NICHE_VIDEOS, by_slug
from nh.backtest.replay import as_series, decision_dates, pair, replay
from nh.backtest.report import Findings, Variant, render
from nh.backtest.scan import scan
from nh.backtest.select import Selection, select
from nh.backtest.stats import evaluate
from nh.db.models import ClusterMember, DemandSnapshot, FeatureDaily, Scorecard
from nh.db.session import session_scope

SLUG = "nuclear-accidents"
RUN = "e2e"
AT = datetime(2026, 8, 27, tzinfo=UTC)
START = date(2017, 1, 1)

#: On-niche titles for `nuclear-accidents`. Each carries both a domain term and an
#: event term, because the relevance rule is a geometric mean of the two axes: a
#: title with only domain vocabulary scores exactly 0, which is the property Slice 4
#: was built for. All eight clear RELEVANCE_HIGH, and there are eight rather than
#: five so a channel still clears MIN_ON_NICHE_VIDEOS if the lexicon is later
#: retuned — a fixture sitting exactly on a floor fails for reasons unrelated to
#: what it tests.
ON_NICHE = [
    "Chernobyl reactor meltdown explained: the coolant failure",
    "Fukushima disaster timeline: containment breach and evacuation",
    "Three Mile Island: how the cooling system failed",
    "Radiation leak disaster inside the reactor exclusion zone",
    "Steam explosion at the reactor pressure vessel: the fatal error",
    "Spent fuel accident: the criticality emergency at the power plant",
    "Coolant failure and core damage: the reactor accident explained",
    "Radioactive fallout after the nuclear plant explosion",
]
OFF_NICHE = ["My morning routine", "Best pasta recipe ever", "Unboxing a new phone"]


def _video(channel_id: str, title: str, index: int, day: date) -> dict:
    return {
        "display_id": f"{channel_id}-v{index}",
        "channel_id": channel_id,
        "title": title,
        "description": "",
        "upload_date": f"{day.isoformat()} 00:00:00",
    }


def _corpus(path: Path, channels: list[str]) -> Path:
    rows = []
    for c, channel_id in enumerate(channels):
        for i, title in enumerate(ON_NICHE):
            rows.append(_video(channel_id, title, i, START - timedelta(days=200 + c)))
        for i, title in enumerate(OFF_NICHE):
            rows.append(_video(channel_id, f"off{i}", 100 + i, START - timedelta(days=200)))
            rows[-1]["title"] = title
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return path


def _tsvs(tmp_path: Path, channels: list[str]) -> tuple[Path, Path]:
    header_c = (
        "category_cc\tjoin_date\tchannel\tname_cc\tsubscribers_cc\tvideos_cc\t"
        "subscriber_rank_sb\tweights\n"
    )
    rows_c = [
        f"Education\t2014-01-01\t{cid}\tChannel {i}\t50000\t120\t{i + 1}.0\t1.0\n"
        for i, cid in enumerate(channels)
    ]
    header_w = (
        "channel\tcategory\tdatetime\tviews\tdelta_views\tsubs\tdelta_subs\tvideos\t"
        "delta_videos\tactivity\n"
    )
    rows_w = []
    for i, cid in enumerate(channels):
        # Every channel STARTS at the same size and grows at its own rate. Scaling
        # the start with the rate instead would make log(after/before) identical for
        # every channel — growth is multiplicative — and the outcome would be
        # constant across niches, which makes the rank correlation undefined rather
        # than zero. That is a fixture bug that looks exactly like a null result.
        subs, views, videos = 1000.0, 50000.0, 20
        week = START - timedelta(days=365)
        for _ in range(120):
            rows_w.append(
                f"{cid}\tEducation\t{week.isoformat()} 00:00:00\t{views}\t1000.0\t"
                f"{subs}\t{10.0 * (i + 1)}\t{videos}\t1\t1\n"
            )
            week += timedelta(days=7)
            subs += 10 * (i + 1)
            views += 1000
            videos += 1
    channels_path = tmp_path / "df_channels_en.tsv.gz"
    weeks_path = tmp_path / "df_timeseries_en.tsv.gz"
    with gzip.open(channels_path, "wt", encoding="utf-8") as h:
        h.write(header_c + "".join(rows_c))
    with gzip.open(weeks_path, "wt", encoding="utf-8") as h:
        h.write(header_w + "".join(rows_w))
    return channels_path, weeks_path


def test_the_chain_runs_from_a_video_dump_to_a_rendered_report(backtest_engine, tmp_path):
    channels = [f"UC{i:022d}" for i in range(MIN_MEMBER_CHANNELS)]
    metadata = _corpus(tmp_path / "yt_metadata_en.jsonl.gz", channels)
    hits = tmp_path / "hits.jsonl.gz"

    # 1. Scan: the real lexicons and the real relevance scorer.
    result = scan(metadata, hits)
    assert result.videos_read == len(channels) * (len(ON_NICHE) + len(OFF_NICHE))
    assert result.hits > 0

    # 2. Select: the real membership floors.
    selection = select(result.counts)
    assert SLUG in selection.kept
    assert len(selection.members[SLUG]) == len(channels)
    assert result.counts[(channels[0], SLUG)].on_niche >= MIN_ON_NICHE_VIDEOS

    # 3. Load into a database whose name marks it as the backtest corpus.
    channels_path, weeks_path = _tsvs(tmp_path, channels)
    report = load(
        backtest_engine,
        selection=selection,
        hits=hits,
        channels_path=channels_path,
        timeseries_path=weeks_path,
        run_id=RUN,
        at=AT,
    )
    assert report.clusters == 1
    assert report.channels == len(channels)
    assert report.channel_weeks == len(channels) * 120
    assert report.videos > 0

    # 4. Replay the production feature layer at weekly decision dates.
    dates = decision_dates(START, START + timedelta(days=28))
    rows, cards = replay(backtest_engine, dates, run_id=RUN, at=AT)
    assert rows > 0
    assert cards == len(dates)

    # 5. Pair, score, render. No correlation is asserted: six invented channels
    #    cannot produce a finding, and asserting one would assert the fixture.
    pairings = pair(backtest_engine, dates)
    aggregate, per_date = evaluate(as_series(pairings)) if pairings else (None, [])

    findings = Findings(
        day=date(2026, 8, 27),
        primary=Variant(
            label="gap",
            stratum="topic",
            supply_from="views_per_new_video",
            threshold=0.55,
            horizon_days=180,
            aggregate=aggregate or evaluate([])[0],
        ),
        niches_selected=len(selection.kept),
        niches_committed=36,
        per_date=per_date,
    )
    body = render(findings)
    assert "Survivorship" in body
    assert "n/a" in body or "rho" in body


#: Three niches from three different families, so no channel is contested and each
#: cluster's lexicon claims its own titles alone.
TRIO = ("bridge-collapses", "data-breaches", "missing-persons")


def _titles_for(slug: str) -> list[str]:
    """Eight unambiguous on-niche titles built from the niche's OWN lexicon.

    Generated rather than hand-written, so the fixture cannot drift away from the
    lexicon it is supposed to exercise. Both properties are asserted here rather than
    assumed: every title must clear the frozen threshold, and must claim this slug
    alone — otherwise the test would be measuring the contested-assignment path
    without saying so.
    """
    from nh.backtest.scan import _EVENTS, _WEIGHTS, candidates
    from nh.clustering.relevance import RELEVANCE_HIGH, score

    terms = [t for t in by_slug()[slug]["lexicon"] if " " not in t][:12]
    titles = [
        f"{a} {b} disaster explained"
        for a, b in list(itertools.combinations(terms, 2))[: len(ON_NICHE)]
    ]
    for title in titles:
        assert score(title, "", _WEIGHTS[slug], _EVENTS).value >= RELEVANCE_HIGH
        assert candidates(title, "") == [slug]
    return titles


def _demand(engine, dates_from: date, days: int = 500) -> None:
    """Daily Wikipedia readings for each niche's topic articles.

    Without these `gap` is NULL for every niche and the chain runs cleanly while
    computing nothing — which is the failure the caller is testing for, so it has to
    be excluded here deliberately rather than by omission. Each niche is given a
    different level so the demand ranking is not flat.
    """
    rows = []
    for n, slug in enumerate(TRIO):
        for article in by_slug()[slug]["wiki_topic"]:
            for i in range(days):
                rows.append(
                    DemandSnapshot(
                        term=article,
                        geo="",
                        observed_date=dates_from + timedelta(days=i),
                        value=float(100 * (n + 1) + i),
                        source="wikipedia",
                        run_id=RUN,
                        at=AT,
                    )
                )
    with session_scope(engine) as session:
        session.add_all(rows)


def test_three_niches_produce_a_correlation_the_whole_chain_carried(backtest_engine, tmp_path):
    """The silent-zero test. Every stage can succeed on its own and still hand the
    next one nothing; this asserts a real per-date rank correlation comes out the
    far end, which is only possible if membership, features, scorecards, outcomes
    and the pairing all agree on the same niches and dates."""
    channels, rows = [], []
    for n, slug in enumerate(TRIO):
        for c in range(MIN_MEMBER_CHANNELS):
            channel_id = f"UC{n:02d}{c:020d}"
            channels.append(channel_id)
            for i, title in enumerate(_titles_for(slug)):
                row = _video(channel_id, title, i, START - timedelta(days=200 + c))
                rows.append(row)
    metadata = tmp_path / "yt_metadata_en.jsonl.gz"
    with gzip.open(metadata, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    hits = tmp_path / "hits.jsonl.gz"

    selection = select(scan(metadata, hits).counts)
    assert sorted(selection.kept) == sorted(TRIO)
    assert selection.contested == 0

    channels_path, weeks_path = _tsvs(tmp_path, channels)
    load(
        backtest_engine,
        selection=selection,
        hits=hits,
        channels_path=channels_path,
        timeseries_path=weeks_path,
        run_id=RUN,
        at=AT,
    )
    _demand(backtest_engine, START - timedelta(days=400))
    dates = decision_dates(START, START + timedelta(days=28))
    replay(backtest_engine, dates, run_id=RUN, at=AT)

    pairings = pair(backtest_engine, dates)

    assert pairings, "no date produced three scored niches with outcomes"
    for pairing in pairings:
        assert len(pairing.clusters) == len(TRIO)
        assert len(pairing.scores) == len(pairing.outcomes) == len(pairing.sizes)
    aggregate, per_date = evaluate(as_series(pairings), draws=200)
    assert aggregate.rho is not None
    assert aggregate.p_value is not None
    assert all(r.n == len(TRIO) for r in per_date)


def test_off_niche_videos_do_not_become_members(backtest_engine, tmp_path):
    """78% of the live corpus was off-niche before Slice 4. The chain must carry the
    relevance cut all the way into `cluster_members`, not just compute it."""
    channels = [f"UC{i:022d}" for i in range(MIN_MEMBER_CHANNELS)]
    metadata = _corpus(tmp_path / "yt_metadata_en.jsonl.gz", channels)
    hits = tmp_path / "hits.jsonl.gz"
    selection = select(scan(metadata, hits).counts)
    channels_path, weeks_path = _tsvs(tmp_path, channels)

    load(
        backtest_engine,
        selection=selection,
        hits=hits,
        channels_path=channels_path,
        timeseries_path=weeks_path,
        run_id=RUN,
        at=AT,
    )

    with session_scope(backtest_engine) as session:
        titles = list(
            session.scalars(
                sa.select(ClusterMember.item_id).where(ClusterMember.item_type == "video")
            )
        )
    # Only the six on-niche titles per channel ever score above zero, so only they
    # reach the hit file and therefore the membership table.
    assert len(titles) == len(channels) * len(ON_NICHE)


def test_a_replay_writes_nothing_dated_after_the_decision_date(backtest_engine, tmp_path):
    """The whole slice in one assertion."""
    channels = [f"UC{i:022d}" for i in range(MIN_MEMBER_CHANNELS)]
    metadata = _corpus(tmp_path / "yt_metadata_en.jsonl.gz", channels)
    hits = tmp_path / "hits.jsonl.gz"
    channels_path, weeks_path = _tsvs(tmp_path, channels)
    load(
        backtest_engine,
        selection=select(scan(metadata, hits).counts),
        hits=hits,
        channels_path=channels_path,
        timeseries_path=weeks_path,
        run_id=RUN,
        at=AT,
    )
    day = START

    replay(backtest_engine, [day], run_id=RUN, at=AT)

    with session_scope(backtest_engine) as session:
        assert set(session.scalars(sa.select(FeatureDaily.day))) == {day}
        assert set(session.scalars(sa.select(Scorecard.day))) == {day}


def test_a_selection_below_the_floor_produces_no_cluster(backtest_engine, tmp_path):
    """A niche with too few channels is dropped, not shipped with a thin number."""
    channels = [f"UC{i:022d}" for i in range(MIN_MEMBER_CHANNELS - 1)]
    metadata = _corpus(tmp_path / "yt_metadata_en.jsonl.gz", channels)

    selection = select(scan(metadata, tmp_path / "hits.jsonl.gz").counts)

    assert selection.kept == []
    assert (SLUG, MIN_MEMBER_CHANNELS - 1) in selection.dropped
    assert isinstance(selection, Selection)
