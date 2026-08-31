"""The alerts feed.

Three rules, and the page says so — INSIGHT_RULES.md lists what is refused and why, and a
feed that looked comprehensive while running three rules would misrepresent its own
coverage. Ordered by when, never by severity: a feed sorted by badness is a ranking of
niches arrived at sideways, and ADR-0029 forbids that however it is reached.
"""

from __future__ import annotations

import streamlit as st

from nh.api import queries
from nh.web.shared import session

BADGE = {"info": "🔵", "watch": "🟠", "act": "🔴"}


def render() -> None:
    st.title("Alerts")
    st.caption(
        "Three rules run: demand breakout, definition step, evidence collapse. "
        "Newest first — not ranked by severity, which would rank the niches. "
        "See docs/INSIGHT_RULES.md for the rules that are refused and why."
    )

    with session() as s:
        feed = queries.alerts_feed(s)

    if not feed:
        st.info(
            "No alerts. The rules run as the last nightly phase; a fresh database has "
            "none until two days of features exist for something to change between."
        )
        return

    for line in feed:
        with st.expander(
            f"{BADGE.get(line.severity, '·')} {line.fired_on} · {line.cluster_id} · {line.rule}"
        ):
            st.json(line.evidence)
