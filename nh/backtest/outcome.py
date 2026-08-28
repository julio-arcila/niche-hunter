"""What actually happened, at 90 and 180 days.

`outcome.growth_180d` is defined in docs/METRICS.md, written before any of this
code existed so it could not be chosen after seeing results. This computes it.

The defining limitation is survivorship and it is not a caveat: YouNiverse holds
only channels that had crossed 10,000 subscribers by its 2019 crawl, so every
channel here succeeded and a channel that stayed small was never collected. This
measures **relative growth among successes**, never emergence, and no sampling
recovers the missing negative class. `reports/backtest_*.md` leads with that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from nh.db.models import ChannelSnapshot
from nh.features.inputs import member_channels

#: How far a snapshot may sit from the date asked for and still be used. YouNiverse
#: is weekly and channels have gaps, so an exact-date match would discard nearly
#: everything; a fortnight admits at least one weekly reading in the normal case
#: while still refusing to call a six-month-old number "the value at t".
#:
#: Asymmetric by direction, and that asymmetry is the anti-leakage rule: the start
#: reading may only be taken from *before* the decision date, and the end reading
#: only from *at or after* the horizon. Never the reverse — a start taken after `t`
#: would be information the decision could not have had.
TOLERANCE_DAYS = 14


@dataclass(slots=True)
class Outcome:
    value: float | None
    channels: int
    contributing: int
    #: Mean days the snapshot actually used landed *after* the horizon asked for.
    #: Never negative — an early reading is refused, not averaged in.
    mean_lag: float | None
    reason: str | None = None

    @property
    def confidence(self) -> float:
        return self.contributing / self.channels if self.channels else 0.0


def _reading(
    session: Session, channels: set[str], lo: date, hi: date, *, prefer: str
) -> dict[str, tuple[int, date]]:
    """`channel -> (subs, the day that reading was taken)` inside `[lo, hi]`.

    A window at both ends, never an open-ended "latest before". An open-ended
    lookup silently reuses a channel's *starting* reading as its endpoint when the
    series stops — which scores a channel that went dark as flat growth, the exact
    shape of data rule 9: absent read as a value. Measured on the first version of
    this file, that turned one dead channel into `log(1) = 0` and moved a two-channel
    median from 0.693 to 0.347.

    `prefer` picks which end of the window wins: "latest" for the reading before the
    decision date, "earliest" for the first one at or after the horizon.
    """
    aggregate = sa.func.max if prefer == "latest" else sa.func.min
    chosen = (
        sa.select(
            ChannelSnapshot.channel_id,
            aggregate(ChannelSnapshot.observed_date).label("observed_date"),
        )
        .where(
            ChannelSnapshot.channel_id.in_(channels),
            ChannelSnapshot.observed_date >= lo,
            ChannelSnapshot.observed_date <= hi,
            ChannelSnapshot.subs.is_not(None),
        )
        .group_by(ChannelSnapshot.channel_id)
        .subquery()
    )
    rows = session.execute(
        sa.select(ChannelSnapshot.channel_id, ChannelSnapshot.subs, ChannelSnapshot.observed_date)
        .join(
            chosen,
            sa.and_(
                chosen.c.channel_id == ChannelSnapshot.channel_id,
                chosen.c.observed_date == ChannelSnapshot.observed_date,
            ),
        )
        .where(ChannelSnapshot.subs > 0)
    ).all()
    return {channel_id: (subs, observed) for channel_id, subs, observed in rows}


def growth(session: Session, cluster_id: str, t: date, horizon_days: int = 180) -> Outcome:
    """Median log growth in subscribers across a niche's member channels.

    Log because growth is multiplicative — a channel going 1k→2k and one going
    100k→200k did the same thing. Median because one viral channel must not define
    a niche's outcome.

    Membership is taken **as of `t`**, not as of today: a channel that joined the
    niche later did not exist to be chosen at the decision date, and including it
    would be the same leak the feature layer was audited for.
    """
    members = set(member_channels(session, cluster_id, t))
    if not members:
        return Outcome(None, 0, 0, None, "no member channel at the decision date")

    end_date = t + timedelta(days=horizon_days)
    start = _reading(session, members, t - timedelta(days=TOLERANCE_DAYS), t, prefer="latest")
    end = _reading(
        session, members, end_date, end_date + timedelta(days=TOLERANCE_DAYS), prefer="earliest"
    )

    ratios, lags = [], []
    for channel_id, (before, _) in start.items():
        landed = end.get(channel_id)
        if landed is None:
            continue
        after, observed = landed
        if before <= 0 or after <= 0:
            continue
        ratios.append(math.log(after / before))
        lags.append((observed - end_date).days)  # positive = the reading landed late
    if not ratios:
        return Outcome(
            None,
            len(members),
            0,
            None,
            f"no member channel has subs at both t and t+{horizon_days}d",
        )
    ratios.sort()
    middle = len(ratios) // 2
    median = ratios[middle] if len(ratios) % 2 else (ratios[middle - 1] + ratios[middle]) / 2
    return Outcome(median, len(members), len(ratios), sum(lags) / len(lags))
