"""The niche list. Alphabetical, and that is a decision rather than a default.

ADR-0029 forbids a ranked surface and Gate E is why: `rho` 0.091, `p` 0.4988, a null on 29
niches. A list sorted by any number is a ranking however it is captioned — put the "best"
niche at the top and a reader will treat the order as a claim, which is exactly the claim
the backtest failed to support. So the sort key is the cluster id, `NicheLine` carries no
score field for a future page to reach for, and a test asserts both.
"""

from __future__ import annotations

import streamlit as st

from nh.api import queries
from nh.web.shared import ballast_banner, session


def render() -> None:
    st.title("Niches")
    st.caption(
        "Alphabetical, deliberately. Nothing here is ranked: Gate E returned a null "
        "(rho 0.091, p 0.4988) and no calibration exists to rank on — see ADR-0029."
    )
    ballast_banner()

    with session() as s:
        rows = queries.niche_list(s)

    active = [n for n in rows if n.active]
    retired = [n for n in rows if not n.active]
    st.write(f"**{len(active)} active**, {len(retired)} retired.")

    for group, label in ((active, "Active"), (retired, "Retired")):
        if not group:
            continue
        st.subheader(label)
        st.dataframe(
            [
                {
                    "niche": n.cluster_id,
                    "label": n.label or "—",
                    "channels": n.member_channels,
                    "videos": n.videos,
                    "last computed": n.latest_day.isoformat() if n.latest_day else "—",
                }
                for n in group
            ],
            width="stretch",
            hide_index=True,
        )
    st.caption(
        "A retired niche keeps its history and its RSS collection; it stops costing "
        "discovery quota and stops accruing new feature rows."
    )
