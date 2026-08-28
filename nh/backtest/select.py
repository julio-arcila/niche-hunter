"""Which channels belong to which backtest niche, and which niches survive.

Two decisions, both made with thresholds fixed in `niches.py` **before the scan
ran**, so neither can be tuned once the counts are visible:

  * a channel joins a niche with at least `MIN_ON_NICHE_VIDEOS` on-niche videos;
  * a niche enters the backtest with at least `MIN_MEMBER_CHANNELS` members.

A niche below the floor is **dropped and reported with its count**, never rescued
by widening its lexicon. That would be tuning the definition of the population
against the population, which is the thing `niches.py` was committed early to make
impossible.

One channel, one niche — the same partition rule ADR-0013 argues for the live
pipeline. A channel counted toward two niches would put its uploads and views in
two supply denominators, and the niches would stop being comparable because they
share evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nh.backtest.niches import MIN_MEMBER_CHANNELS, MIN_ON_NICHE_VIDEOS, by_slug
from nh.backtest.scan import ChannelCounts


@dataclass(slots=True)
class Selection:
    #: slug -> the channels that belong to it
    members: dict[str, set[str]] = field(default_factory=dict)
    #: (slug, member count) for niches that fell below the floor
    dropped: list[tuple[str, int]] = field(default_factory=list)
    #: channels that qualified for more than one niche, and were assigned to one
    contested: int = 0

    @property
    def kept(self) -> list[str]:
        return sorted(self.members)


def dominant_niche(
    counts: dict[tuple[str, str], ChannelCounts], channel_id: str, slugs: list[str]
) -> str | None:
    """The one niche a channel belongs to, or None if it clears no floor.

    Ranked by on-niche video count, then by slug so the tie-break is deterministic
    and a re-run never reshuffles. `trivial.dominant_seed` breaks its ties the same
    way and for the same reason.
    """
    qualified = [
        (counts[(channel_id, slug)].on_niche, slug)
        for slug in slugs
        if (channel_id, slug) in counts
        and counts[(channel_id, slug)].on_niche >= MIN_ON_NICHE_VIDEOS
    ]
    if not qualified:
        return None
    best = max(qualified, key=lambda pair: (pair[0], [-ord(c) for c in pair[1]]))
    return best[1]


def select(counts: dict[tuple[str, str], ChannelCounts]) -> Selection:
    """Assign channels to niches, then drop niches that stayed too small."""
    slugs = sorted(by_slug())
    channels = {channel_id for channel_id, _ in counts}
    selection = Selection()
    assigned: dict[str, set[str]] = {slug: set() for slug in slugs}

    for channel_id in sorted(channels):
        qualified = sum(
            1
            for slug in slugs
            if (channel_id, slug) in counts
            and counts[(channel_id, slug)].on_niche >= MIN_ON_NICHE_VIDEOS
        )
        if qualified > 1:
            selection.contested += 1
        winner = dominant_niche(counts, channel_id, slugs)
        if winner is not None:
            assigned[winner].add(channel_id)

    for slug in slugs:
        members = assigned[slug]
        if len(members) >= MIN_MEMBER_CHANNELS:
            selection.members[slug] = members
        else:
            selection.dropped.append((slug, len(members)))
    return selection
