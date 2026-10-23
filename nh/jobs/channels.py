"""The ranked channel list ADR-0060's H1 licenses — the first ranked surface in this project.

H1 PASSED on 2026-10-02: `views_per_sub` predicts a channel's 14-day reach, rho +0.470,
p 0.0001, top-decile lift 2.59, on 665 channels within cluster. That is the whole licence
and this module is deliberately shaped by its edges:

* **Within ONE cluster.** No cross-cluster page, no aggregation to a cluster number. ADR-0068
  measured that aggregate as undetectable at ten clusters, so a "best niches" view built from
  these rows would be a claim the evidence cannot carry.
* **Ranked on the RAW predictor**, not a residual. The registered lift was computed on the
  top decile of raw `views_per_sub` (`backtest.stats.top_decile_lift`), so raw is the
  quantity that was validated. A reader reads a list from the top; the lift is what its top
  gets them.
* **Withheld until a person records the verdict.** `gates.channel_rank_citable()` decides,
  and `load` withholds by DEFAULT, so forgetting the argument fails safe (ADR-0052's shape).

What it is NOT: a score. No column is called one. The rank is the rank, the evidence sits
beside it, and the licence line travels with the list so it cannot be read as more than it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from nh.api.gates import Verdict, channel_rank_citable
from nh.collectors.youtube_rss import FAIL_LIMIT
from nh.db.models import Channel, Cluster, FeedState
from nh.db.session import session_scope
from nh.features import inputs
from nh.jobs.niche import UnknownCluster

#: The one-line provenance every rendering of this list must carry, verbatim. Kept here
#: rather than in a presenter so two surfaces cannot drift into two different claims.
LICENCE = (
    "ADR-0060 H1 PASS 2026-10-02 — rho +0.470, p 0.0001, top-decile lift 2.59, 665 channels, "
    "within cluster. Reach persists at 14 days. Says NOTHING about any niche "
    "(reports/channel_reach_2026-10-02.md)."
)


@dataclass(frozen=True, slots=True)
class ChannelRow:
    """One channel's rank and the evidence to check it."""

    rank: int
    channel_id: str
    title: str | None
    views_per_sub: float
    median_views: int
    subs: int
    n_elig: int
    newest_reading: date | None


@dataclass(frozen=True, slots=True)
class ChannelList:
    cluster_id: str
    day: date
    rows: tuple[ChannelRow, ...]
    verdict: Verdict
    #: Channels excluded because their feed is dead, and the count is shown rather than
    #: quietly dropped — a list that silently omits is a list that misleads about its own
    #: denominator.
    dead_excluded: int
    licence: str = LICENCE

    @property
    def withheld(self) -> bool:
        return not self.verdict


def _dead_channels(session: Session) -> set[str]:
    """Channels whose feed has hit `FAIL_LIMIT` on a 404 — terminated, not merely quiet.

    Measured 2026-10-04: all 158 feeds at the cap were `last_status = 404`, growing ~7/day,
    and 86 were active-cluster members. They stay in `cluster_members` and in the supply
    metrics by decision (the date of the first 404 is not stored, so an exclusion applied to
    a replay of an earlier day would leak information from after it). **A recommendation is
    different from a metric**: telling someone to study a channel that no longer exists is
    simply wrong, so this surface filters them and says how many.
    """
    rows = session.execute(
        sa.select(FeedState.channel_id).where(
            sa.func.coalesce(FeedState.fail_count, 0) >= FAIL_LIMIT,
            FeedState.last_status == 404,
        )
    )
    return {channel_id for (channel_id,) in rows}


def load(
    cluster_id: str,
    day: date | None = None,
    engine: Engine | None = None,
    *,
    include_unvalidated: bool = False,
) -> ChannelList:
    """The ranked list for one cluster, withheld unless H1's verdict is recorded.

    `include_unvalidated` is a human asking once, at the moment of asking, and records
    nothing — the same distinction `jobs.niche.load` draws and for the same reason. It is not
    the stored setting ADR-0050 forbids, and the web layer never passes it.
    """
    verdict = channel_rank_citable()
    with session_scope(engine) as session:
        if session.get(Cluster, cluster_id) is None:
            raise UnknownCluster(cluster_id)
        target = day or date.today()
        if not verdict and not include_unvalidated:
            return ChannelList(cluster_id, target, (), verdict, 0)

        # `inputs.cohort`, NOT `eligible_videos` + `latest_subs`. This is the registered
        # population and the distinction is not pedantry: H1 was measured on the frozen
        # cohort — subscribers visible and in (0, COHORT_MAX_SUBS], at least
        # COHORT_MIN_VIDEOS eligible videos, `order=date` discovery lineage — so a list
        # built on the wider pool ranks channels the test never saw.
        #
        # The first version of this module did exactly that, and the live output said so
        # immediately: channels with ONE to five subscribers held the top of the list,
        # because `views_per_sub` divides by a tiny denominator and noise wins. "Invester
        # 666", median 348 views, 1 subscriber, ranked second of 1,707. Applying a
        # validated result to a population it was not validated on is the error class this
        # repository spends most of its documentation on, and the surface built to show
        # the one passing test committed it on its first live run.
        pool = inputs.cohort(session, cluster_id, target)
        subs = inputs.latest_subs(session, cluster_id, target)
        dead = _dead_channels(session)
        titles = dict(
            session.execute(
                sa.select(Channel.channel_id, Channel.title).where(
                    Channel.channel_id.in_(list(pool))
                )
            ).all()
        )


        scored: list[tuple[float, str, int, int, int]] = []
        excluded = 0
        for channel_id, view_list in pool.items():
            if channel_id in dead:
                excluded += 1
                continue
            s = subs.get(channel_id)
            views = sorted(view_list)
            if not s or s <= 0 or not views:
                continue
            median = views[len(views) // 2]
            if median <= 0:
                # A zero median is absent and counted, never scored — the rule
                # `channel_reach.freeze_date` applies to the same quantity.
                continue
            scored.append((median / s, channel_id, median, s, len(views)))

        scored.sort(key=lambda row: (-row[0], row[1]))
        rows = tuple(
            ChannelRow(
                rank=i + 1,
                channel_id=channel_id,
                title=titles.get(channel_id),
                views_per_sub=vps,
                median_views=median,
                subs=s,
                n_elig=n,
                newest_reading=target,
            )
            for i, (vps, channel_id, median, s, n) in enumerate(scored)
        )
    return ChannelList(cluster_id, target, rows, verdict, excluded)
