"""The evidence surface (ADR-0052).

    uv run nh web

**Not a dashboard, and the distinction is the slice.** Gate E returned a null on
2026-08-28, so "a radar that predicts emerging niches" is retired and nothing here is
ranked. What this shows is evidence: the demand series, the corpus, the source feed, and
every metric with `value / confidence / n / population / definition` and the rows it was
computed from. None of that claims to predict, which is why it survives the null.

Two rules the pages inherit rather than restate:

1. **A metric the scorer decided is withheld for an unvalidated axis** (`nh/api/gates.py`).
   The gate lives in the read layer, not here, because this is the second presenter and a
   rule enforced per-presenter is a rule the next one forgets.
2. **Nothing is sorted by a number.** ADR-0029 forbids a ranked surface, and a list
   ordered by quality is a ranking however it is captioned.

`nh/api/` is import-free of Streamlit so nothing here can reach the nightly.
"""

from __future__ import annotations

import streamlit as st

from nh.api import queries
from nh.web.shared import session
from nh.web.views import niche as niche_view
from nh.web.views import niches as niches_view


def main() -> None:
    st.set_page_config(page_title="Niche Hunter — evidence", layout="wide")

    with session() as s:
        clusters = [n.cluster_id for n in queries.niche_list(s)]

    with st.sidebar:
        st.markdown("### Niche Hunter")
        st.caption("Evidence surface. Nothing here is ranked (ADR-0029, ADR-0052).")
        choice = st.selectbox(
            "View",
            ["All niches", *clusters],
            help="Alphabetical. The order is not a claim.",
        )

    if choice == "All niches" or choice not in clusters:
        niches_view.render()
    else:
        niche_view.render(choice)


if __name__ == "__main__":
    main()
