"""Membership, and the floors that decide which niches survive.

The floors are fixed in `niches.py` before the scan runs. These tests pin the
properties that make that discipline mean something — most importantly that a
niche below the floor is dropped and counted, never quietly rescued.
"""

from __future__ import annotations

from nh.backtest.niches import MIN_MEMBER_CHANNELS, MIN_ON_NICHE_VIDEOS
from nh.backtest.scan import ChannelCounts
from nh.backtest.select import dominant_niche, select

A, B = "nuclear-accidents", "mining-disasters"


def _counts(**spec: dict[str, int]) -> dict[tuple[str, str], ChannelCounts]:
    """`_counts(UCa={A: 9, B: 2})` -> counts with those on-niche tallies."""
    out: dict[tuple[str, str], ChannelCounts] = {}
    for channel_id, per_slug in spec.items():
        for slug, on_niche in per_slug.items():
            out[(channel_id, slug)] = ChannelCounts(
                videos=100, on_niche=on_niche, scorable=on_niche
            )
    return out


def _enough(slug: str, start: int = 0) -> dict[tuple[str, str], ChannelCounts]:
    counts: dict[tuple[str, str], ChannelCounts] = {}
    for i in range(MIN_MEMBER_CHANNELS):
        counts[(f"UC{slug}{start + i}", slug)] = ChannelCounts(
            videos=100, on_niche=MIN_ON_NICHE_VIDEOS, scorable=MIN_ON_NICHE_VIDEOS
        )
    return counts


def test_a_channel_below_the_video_floor_joins_nothing():
    counts = _counts(UCa={A: MIN_ON_NICHE_VIDEOS - 1})
    assert dominant_niche(counts, "UCa", [A, B]) is None


def test_a_channel_at_the_floor_joins():
    counts = _counts(UCa={A: MIN_ON_NICHE_VIDEOS})
    assert dominant_niche(counts, "UCa", [A, B]) == A


def test_a_channel_belongs_to_exactly_one_niche():
    """ADR-0013's partition rule. A channel in two niches puts its uploads in two
    supply denominators, and the niches stop being comparable because they share
    evidence."""
    counts = _counts(UCa={A: 9, B: 20})
    assert dominant_niche(counts, "UCa", [A, B]) == B


def test_ties_break_deterministically():
    """A re-run must not reshuffle membership, or nothing downstream is
    reproducible."""
    counts = _counts(UCa={A: 7, B: 7})
    first = dominant_niche(counts, "UCa", [A, B])
    assert first == dominant_niche(counts, "UCa", [B, A])
    assert first == dominant_niche(counts, "UCa", [A, B])


def test_a_niche_below_the_channel_floor_is_dropped_and_counted():
    """Dropped WITH ITS COUNT. The report says how many niches fell out and how
    close each came — silently keeping them would be selection on the outcome."""
    counts = {**_enough(A), **_counts(UCb={B: 99})}

    selection = select(counts)

    assert A in selection.members
    assert B not in selection.members
    assert (B, 1) in selection.dropped


def test_a_niche_at_the_channel_floor_survives():
    selection = select(_enough(A))
    assert selection.members[A] and len(selection.members[A]) == MIN_MEMBER_CHANNELS


def test_contested_channels_are_counted():
    """How often a channel qualifies for more than one niche is a property of the
    lexicons, and a high number means the families overlap more than intended."""
    counts = {**_enough(A), **_counts(UCx={A: 9, B: 9})}
    assert select(counts).contested == 1


def test_selection_is_reproducible():
    counts = {**_enough(A), **_enough(B, start=100)}
    assert select(counts).members == select(counts).members
