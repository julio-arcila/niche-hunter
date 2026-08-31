"""One niche: its metrics, what each counts, and the rows behind each one.

The page Slice 7 exists for. Its contract is the slice's exit criterion — every number
reaches its input rows — and its constraint is ADR-0052's gate: a metric the scorer decided
is withheld for an unvalidated axis, replaced by the deferral's own text rather than shown
under a caveat.

Reads through `nh.jobs.niche.load`, which applies the gate. Not through `nh.api.queries`
directly for the metric table: the gate lives in the read layer precisely so a second
presenter cannot forget it, and this is the second presenter.
"""

from __future__ import annotations

import streamlit as st

from nh.api import drilldown, queries
from nh.jobs import niche as niche_job
from nh.web.shared import ballast_banner, fmt, metric_caption, rows_table, session


def render(cluster_id: str) -> None:
    view = niche_job.load(cluster_id)
    st.title(view.label or cluster_id)
    if view.day is None or not view.metrics:
        st.warning("No features computed for this niche yet.")
        return
    st.caption(
        f"`{cluster_id}` · day {view.day} · run `{(view.run_id or '')[:8]}` · "
        f"{view.member_channels} member channels"
    )
    ballast_banner()

    _scorecard(view)
    _metrics(view, cluster_id)
    _demand(cluster_id, view.day)
    _channels(cluster_id, view.day)
    _feed(cluster_id, view.day)


def _scorecard(view) -> None:
    """All or nothing (ADR-0052). `gap` is demand minus supply, so showing one side of a
    withheld row invites the reader to reconstruct the other."""
    if view.scorecard_withheld:
        st.subheader("Scorecard")
        st.info(view.scorecard_withheld)
        return
    if not view.scorecard:
        return
    st.subheader("Scorecard")
    columns = st.columns(len(view.scorecard))
    for column, (field, value) in zip(columns, view.scorecard.items(), strict=False):
        column.metric(field, fmt(value))
    st.caption(
        "`gap` is a difference of within-day percentile RANKS, not of levels — and its "
        "two sides count different populations (ADR-0035). `value` and `opportunity` "
        "stay NULL behind Gate E's null; nothing ranked ships."
    )


def _metrics(view, cluster_id: str) -> None:
    st.subheader("Metrics")
    withheld = [m for m in view.metrics if not m.shown]
    if withheld:
        st.info(f"{len(withheld)} metric(s) withheld: {withheld[0].withheld}")
    for metric in view.metrics:
        if not metric.shown:
            # Named, not hidden. A metric that vanishes reads as a pipeline gap; one shown
            # as withheld reads as the decision it is, and says how to undo it.
            with st.expander(f"· {metric.name} — withheld", expanded=False):
                st.write(metric.withheld)
                _drilldown(cluster_id, view.day, metric.name, gated=True)
            continue
        with st.expander(
            f"{metric.name} — {fmt(metric.value)}  (conf {fmt(metric.confidence)}, "
            f"n {metric.inputs_n if metric.inputs_n is not None else '—'})"
        ):
            st.caption(metric_caption(metric.name, metric.detail))
            if metric.value is None:
                st.write(f"not computable: {(metric.detail or {}).get('reason', 'unknown')}")
            _history(cluster_id, metric.name)
            _drilldown(cluster_id, view.day, metric.name)


def _history(cluster_id: str, name: str) -> None:
    """The stored series, with every definition change marked.

    A step is not noise to smooth over: ADR-0047 moved `on_niche_share` 0.076 -> 0.227
    across one, on an identical numerator. A chart that redrew history under today's
    definition would hide exactly the thing a reader needs to see.
    """
    with session() as s:
        points = queries.metric_history(s, cluster_id, name)
    if len(points) < 2:
        return
    steps = queries.definition_steps(points)
    for day, before, after in steps:
        st.warning(
            f"definition changed on {day}: `{before}` → `{after}`. Values either side "
            f"are not comparable."
        )
    st.line_chart(
        {"value": [p.value for p in points]},
        x_label="day",
        y_label=name,
    )


def _drilldown(cluster_id: str, day, name: str, *, gated: bool = False) -> None:
    """The input rows. Shown even for a gated metric — see `cli.py::niche_trace` for why:
    the aggregate claim is withheld, the evidence to check it is not."""
    with session() as s:
        headers, rows = drilldown.rows_behind(s, name, cluster_id, day)
    if not headers:
        return
    st.markdown("**Input rows**")
    if gated:
        st.caption(
            "The value is withheld; these rows are shown so the scorer can be checked. "
            "Do not read them before labelling a validation sample."
        )
    rows_table(headers, rows[:50])
    if len(rows) > 50:
        st.caption(f"showing 50 of {len(rows)} fetched; the metric's own `n` is the true count")


def _demand(cluster_id: str, day) -> None:
    with session() as s:
        points = queries.demand_series(s, cluster_id, day)
    if not points:
        return
    st.subheader("Demand")
    st.caption("Wikipedia daily pageviews — English readers globally, not a US market.")
    by_day: dict = {}
    for point in points:
        by_day[point.day] = by_day.get(point.day, 0.0) + (point.value or 0.0)
    st.line_chart({"views": [by_day[d] for d in sorted(by_day)]}, x_label="day")


def _channels(cluster_id: str, day) -> None:
    with session() as s:
        channels = queries.channel_table(s, cluster_id, day)
    if not channels:
        return
    st.subheader(f"Channels ({len(channels)})")
    st.caption(
        "The population `openness.*` measures — ballast channels excluded (ADR-0047), "
        "which is the exclusion the recall sample is drawn to test."
    )
    st.dataframe(
        [
            {
                "channel": c.channel_id,
                "title": c.title or "—",
                "country": c.country or "—",
                "subs": c.subs if c.subs is not None else "—",
                "videos": c.videos,
            }
            for c in channels[:100]
        ],
        width="stretch",
        hide_index=True,
    )


def _feed(cluster_id: str, day) -> None:
    with session() as s:
        feed = queries.source_feed(s, cluster_id, day)
    if not feed:
        return
    st.subheader("Source feed")
    st.caption(
        "Newest videos, with the query that surfaced each. Most arrive by RSS from "
        "channels already admitted and carry no query — discovery is 7.5% of member rows."
    )
    st.dataframe(
        [
            {
                "published": str(line.published_at)[:16],
                "title": line.title or "—",
                "query": line.query or "— (RSS)",
                "order": line.order_by or "—",
                "url": line.url,
            }
            for line in feed
        ],
        width="stretch",
        hide_index=True,
        column_config={"url": st.column_config.LinkColumn("watch", display_text="open")},
    )
