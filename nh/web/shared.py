"""Rendering helpers shared by the views, and the one rule they all obey.

Kept out of the views so the rule is stated once: **a number is rendered with what it
means, or it is not rendered.** `cli.py::_provenance` learned this the hard way — a COP
bid printed under a heading called "money" is a four-orders-of-magnitude misreading
available at a glance, and a low confidence beside it does not prevent that (ADR-0031).
The web layer renders the same facts, so it repeats the same rule rather than a subset.

No queries here. Everything reads through `nh.api`, which is the boundary that keeps a
rendering library out of the nightly.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from nh.api import basis as basis_mod
from nh.db.session import get_engine, session_scope
from nh.features import inputs as feature_inputs


def session():
    """A scoped session for one render. Streamlit reruns the whole script per interaction,
    so this is per-interaction rather than cached — a cached session would hand a stale
    identity map to a page whose whole job is showing what is in the database now."""
    return session_scope(get_engine())


def fmt(value: float | None, places: int = 2) -> str:
    """`—` for absent, never `0`. Data rule 7 at the presentation layer: a hidden value
    rendered as zero poisons the reader's arithmetic the same way it poisons a median."""
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.{places}f}"


def metric_caption(name: str, detail: dict | None) -> str:
    """The line under a number: what it counts, in what market, in what currency.

    Every key here changes what the number MEANS, which is the test for belonging on this
    line. `currency` and `geo` are on it because they were missed once each.
    """
    detail = detail or {}
    bits = [basis_mod.basis(name, detail)]
    if (window := detail.get("window")) is not None:
        bits.append(f"{window[0]}..{window[1]}")
    if (currency := detail.get("currency")) is not None:
        bits.append(f"bids in {currency}")
    if (definition := detail.get("definition")) is not None:
        bits.append(f"def {definition}")
    return " · ".join(str(b) for b in bits)


def ballast_banner() -> None:
    """The one place the page reads the clock, and it reads the same one `inputs` does.

    ADR-0050 reverts `supply.*` to `v2-on-niche` on the sunset date unless the recall
    sample is labelled, so displayed values will step that day. `inputs.py` maintains an
    inventory of exactly one clock read; adding a second here to compute the same fact
    would make that inventory wrong.
    """
    if feature_inputs.BALLAST_VALIDATED is not None:
        return
    remaining = (feature_inputs.BALLAST_SUNSET - date.today()).days
    if remaining < 0:
        st.warning(
            f"**Supply definition reverted to `v2-on-niche`** on "
            f"{feature_inputs.BALLAST_SUNSET}: ADR-0047's ballast exclusion was never "
            f"validated. Values before that date were computed under `v3` and are not "
            f"comparable across the step."
        )
        return
    st.info(
        f"**`supply.*` is on a clock.** ADR-0047 excludes 585 ballast channels. Held "
        f"against the SAME day's corpus, `history-of-ideas on_niche_share` reads 0.0758 "
        f"without the exclusion and 0.2273 with it, on an identical numerator of 230 — so "
        f"the whole difference is denominator removal, and it is unvalidated. (The stored "
        f"night-over-night step is 0.0781 → 0.2273; the numerator moved 154 → 230 there, "
        f"because the corpus also grew.) Unless "
        f"the recall sample is labelled, this reverts to `v2-on-niche` on "
        f"{feature_inputs.BALLAST_SUNSET} ({remaining} days): "
        f"`uv run python scripts/label_exposition.py --sample recall`"
    )


def rows_table(headers: list[str], rows: list[tuple]) -> None:
    """A table of raw rows, with `None` shown as `—` rather than as an empty cell.

    An empty cell reads as a rendering gap; `—` reads as a fact about the data, which is
    what it is.
    """
    if not rows:
        st.caption("no input rows")
        return
    st.dataframe(
        [
            {h: ("—" if v is None else v) for h, v in zip(headers, row, strict=False)}
            for row in rows
        ],
        width="stretch",
        hide_index=True,
    )
