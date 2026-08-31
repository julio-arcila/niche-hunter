"""The reports viewer.

Forty-odd markdown files are the repo's actual findings — the backtest that failed, the
pre-registrations that failed with it, the audits that turned into ADRs. They are readable
in the repo; this makes them readable beside the numbers they are about.

Markdown only, and `nh/api/reports.py` says why: the validation draws live in the same
directory and their key files carry each row's `relevance`.
"""

from __future__ import annotations

import streamlit as st

from nh.api import reports


def render() -> None:
    st.title("Reports")
    st.caption(
        "The written record. Validation draws live in `reports/` too and are deliberately "
        "not listed — their key files carry the relevance a labeller must not see."
    )

    rows = reports.listing()
    if not rows:
        st.info("No reports found.")
        return

    labels = {f"{r.day or '—'} · {r.title}": r.name for r in rows}
    choice = st.selectbox("Report", list(labels), help="Newest first.")
    text = reports.read(labels[choice])
    if text is None:
        st.error("That report could not be read.")
        return
    st.markdown(text)
