"""Readers for the two YouNiverse tabular files.

Not a collector: no quota, no nightly, no `raw_records`, no `Collector.run()`. A
one-off loader in the spirit of `scripts/select_demand_articles.py`, kept separate
from `nh/collectors/` so nothing here can ever be scheduled.

What the files are (from the dataset's own README, `data/youniverse/README.md`):

- `df_channels_en.tsv.gz` — 136,470 channels, every one with >10k subscribers and
  >10 videos as of the 2019-10-27 `channelcrawler.com` crawl. This is the
  survivorship boundary, and it is the single most important fact about the whole
  backtest.
- `df_timeseries_en.tsv.gz` — 18,872,499 weekly points over 153,550 channels,
  2015-01 to 2019-09. Not every channel has the full span.

Both are streamed. `df_timeseries_en` is 544 MB compressed and expands past 1.7 GB;
nothing here holds more than one row at a time.
"""

from __future__ import annotations

import csv
import gzip
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from nh.collectors.parse import as_float, as_int

#: The dataset's own crawl date. Anything a replay reads must predate it.
CRAWL_DATE = date(2019, 10, 27)
#: csv's default 128 KB field cap is smaller than some channel names + the
#: category string; raised once here rather than per call site.
_FIELD_LIMIT = 1_000_000


@dataclass(slots=True, frozen=True)
class ChannelRow:
    channel_id: str
    name: str | None
    category: str | None
    join_date: date | None
    subscribers: int | None
    videos: int | None


@dataclass(slots=True, frozen=True)
class WeekRow:
    """One channel-week.

    `datetime` in the source names the week the point belongs to, and that is the
    third reading of `observed_date` the project has now (ADR-0027): not "the day we
    looked" and not "the day the value describes", but "the week the value covers",
    landed on its final day. `week_ending` names it so no caller can mistake it for
    a daily reading.
    """

    channel_id: str
    week_ending: date
    subs: int | None
    views: int | None
    videos: int | None
    delta_subs: int | None
    delta_views: int | None
    delta_videos: int | None


def _rows(path: Path) -> Iterator[dict[str, str]]:
    csv.field_size_limit(_FIELD_LIMIT)
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        yield from csv.DictReader(handle, delimiter="\t")


def _count(raw: str | None) -> int | None:
    """A weekly count, rounded. None when absent — never 0.

    The timeseries file stores counts as *floats*: `202494.5555555556` views,
    `650.2222222222222` subscribers. YouNiverse smooths across its crawl cadence, so
    a "week" is an interpolated position rather than a raw reading. `as_int` refuses
    those, correctly — it exists to stop an API returning "3.7" where an integer was
    promised — and using it here silently turned every numeric column in an 18.9M-row
    file into NULL, which the backtest would have reported as "no data" rather than
    as a bug. So the float is parsed and rounded here, at the one place that knows
    the values are smoothed.
    """
    value = as_float(raw)
    return None if value is None else round(value)


def _day(raw: str | None) -> date | None:
    """A date, or None. Never today's date as a stand-in for an unparseable one."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:19]).date()
    except ValueError:
        return None


def channels(path: Path) -> Iterator[ChannelRow]:
    """Stream `df_channels_en.tsv.gz`.

    `subscribers_cc` and `videos_cc` are crawl-time (2019-10) figures for a channel
    the replay may be scoring in 2017. They are loaded onto `channels` for
    provenance and are deliberately *not* used as a snapshot: a 2019 subscriber
    count written at a 2017 `observed_date` is the leak this whole slice exists to
    prevent. Subscriber history comes from `df_timeseries_en` and nowhere else.
    """
    for row in _rows(path):
        channel_id = (row.get("channel") or "").strip()
        if not channel_id:
            continue
        yield ChannelRow(
            channel_id=channel_id,
            name=(row.get("name_cc") or "").strip() or None,
            category=(row.get("category_cc") or "").strip() or None,
            join_date=_day(row.get("join_date")),
            subscribers=as_int(row.get("subscribers_cc")),
            videos=as_int(row.get("videos_cc")),
        )


def weeks(path: Path, *, keep: set[str] | None = None) -> Iterator[WeekRow]:
    """Stream `df_timeseries_en.tsv.gz`, optionally only for `keep`.

    The filter is applied here rather than by the caller because it is the whole
    reason this is affordable: 18.9M rows for every channel against roughly 0.4M for
    the few thousand that ended up in a backtest niche.

    A row with an unparseable week is dropped, not defaulted — `delta_*` columns
    are also passed through as NULL when absent, because a week with no reading is
    not a week with no growth (data rule 7).
    """
    for row in _rows(path):
        channel_id = (row.get("channel") or "").strip()
        if not channel_id or (keep is not None and channel_id not in keep):
            continue
        week = _day(row.get("datetime"))
        if week is None:
            continue
        yield WeekRow(
            channel_id=channel_id,
            week_ending=week,
            subs=_count(row.get("subs")),
            views=_count(row.get("views")),
            videos=_count(row.get("videos")),
            delta_subs=_count(row.get("delta_subs")),
            delta_views=_count(row.get("delta_views")),
            delta_videos=_count(row.get("delta_videos")),
        )
