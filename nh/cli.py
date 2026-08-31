"""`nh` — the operator-facing entry point."""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import typer

from nh.collectors.registry import REGISTRY
from nh.config import get_settings
from nh.jobs import nightly as nightly_job

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def _parse_only(only: str | None) -> list[str] | None:
    return [s.strip() for s in only.split(",") if s.strip()] if only else None


@app.command()
def nightly(
    dry_run: bool = typer.Option(False, "--dry-run", help="List what would run, then exit."),
    only: str | None = typer.Option(None, "--only", help="Comma-separated collector names."),
    since: datetime | None = typer.Option(None, "--since", formats=["%Y-%m-%d"]),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run every configured collector, then features and scoring."""
    _setup_logging(verbose)
    selected = _parse_only(only)
    since_date: date | None = since.date() if since else None

    try:
        if dry_run:
            items = nightly_job.plan(selected)  # resolve names before printing a header
            typer.echo(f"{'COLLECTOR':<18}{'RUN?':<7}{'CADENCE':<34}REASON")
            for item in items:
                mark = "yes" if item.will_run else "no"
                typer.echo(f"{item.spec.source:<18}{mark:<7}{item.spec.cadence:<34}{item.reason}")
            raise typer.Exit(0)
        result = nightly_job.run_nightly(selected, since_date)
    except KeyError as exc:
        # An unknown --only value is operator error, not a crash. Show the
        # valid names rather than a traceback.
        typer.echo(str(exc).strip("\"'"), err=True)
        typer.echo(f"known: {', '.join(s.source for s in REGISTRY)}", err=True)
        raise typer.Exit(2) from None

    typer.echo(f"run_id={result.run_id}")
    for source, status in result.statuses.items():
        typer.echo(f"  {status:<8} {source}")
    raise typer.Exit(0 if result.ok else 1)


@app.command()
def sources() -> None:
    """Show every known source, whether it is ported, and whether it is configured."""
    settings = get_settings()
    typer.echo(f"{'SOURCE':<18}{'PORTED':<9}{'CONFIGURED':<13}{'QUOTA':<9}PROTOTYPE")
    for spec in REGISTRY:
        cls = spec.load() if spec.ported else None
        budget = getattr(cls, "quota_budget", None) if cls else "-"
        typer.echo(
            f"{spec.source:<18}"
            f"{'yes' if spec.ported else 'no':<9}"
            f"{'yes' if settings.configured(spec.source) else 'no':<13}"
            f"{budget or '-'!s:<9}"
            f"{spec.prototype}"
        )


@app.command()
def status(
    check: bool = typer.Option(
        False, "--check", help="Exit non-zero unless the latest nightly actually collected."
    ),
    days: int = typer.Option(7, "--days", help="How far back to show."),
) -> None:
    """Show recent runs, or gate on whether the last one worked.

    `--check` is what the cron script pings healthchecks on. A dead-man switch
    only knows whether a run happened; this knows whether it collected anything.
    """
    from nh.jobs import status as st

    if check:
        result = st.check()
        for warning in result.warnings:
            typer.echo(f"warn  {warning}", err=True)
        for problem in result.problems:
            typer.echo(f"FAIL  {problem}", err=True)
        if result.ok:
            typer.echo(f"ok    latest nightly {result.run_id} collected")
        raise typer.Exit(0 if result.ok else 1)

    runs = st.recent_runs(days=days)
    if not runs:
        typer.echo("no nightly runs recorded yet")
        raise typer.Exit(0)
    typer.echo(f"{'DAY':<12}{'SOURCE':<18}{'STATUS':<10}{'QUOTA':<14}SNAPSHOTS")
    for line in runs:
        quota = f"{line.quota_used:,}/{line.quota_budget:,}" if line.quota_budget else "-"
        typer.echo(
            f"{line.day!s:<12}{line.source:<18}{line.status:<10}{quota:<14}"
            f"{line.snapshots if line.snapshots is not None else '-'}"
        )
    typer.echo(f"\n{'DAY':<12}{'SOURCE':<18}VIDEO SNAPSHOTS")
    for day, source, count in st.snapshots_by_day(days=days + 1):
        typer.echo(f"{day!s:<12}{source:<18}{count:,}")


@app.command()
def seed(
    show: bool = typer.Option(False, "--show", help="List seeds and the nightly cost, no writes."),
) -> None:
    """Write the hand-picked niche seeds. Idempotent — re-run after editing nh/seeds.py."""
    import sqlalchemy as sa

    from nh.db.models import NicheSeed
    from nh.db.session import get_engine, session_scope
    from nh.seeds import SEEDS, TERMS, apply_seeds, apply_terms, search_budget

    settings = get_settings()
    cost = search_budget(pages=settings.yt_search_pages)
    if not show:
        apply_seeds()
        apply_terms()
    with session_scope(get_engine()) as session:
        rows = session.scalars(sa.select(NicheSeed).order_by(NicheSeed.slug)).all()
        rows = [(r.slug, r.lang, len(r.keywords), r.active) for r in rows]

    typer.echo(f"{'SLUG':<24}{'LANG':<7}{'KEYWORDS':<11}ACTIVE")
    for slug, lang, n_keywords, active in rows:
        typer.echo(f"{slug:<24}{lang or '-':<7}{n_keywords:<11}{'yes' if active else 'no'}")
    typer.echo(
        f"\n{len(SEEDS)} seeds · {len(TERMS)} demand terms · "
        f"{settings.yt_search_pages} page(s) per query per sort order"
        f"\nsearch.list cost: {cost:,} of {settings.yt_quota_budget:,} units "
        f"({100 * cost // settings.yt_quota_budget}% of budget)"
    )
    if cost > settings.yt_quota_budget:
        typer.echo("this seed set does not fit the daily budget", err=True)
        raise typer.Exit(1)


cluster_app = typer.Typer(help="Inspect and calibrate cluster membership.")
app.add_typer(cluster_app, name="cluster")


@cluster_app.command("sample")
def cluster_sample(
    out: Path = typer.Option(Path("reports/relevance_sample.jsonl"), "--out"),
    per_cluster: int = typer.Option(60, "--per-cluster", help="Videos sampled per cluster."),
    seed: int = typer.Option(20260827, "--seed", help="Reproducibility, not decoration."),
) -> None:
    """Write a stratified blind sample to label.

    Fill in `"label": true|false` on each line (null to skip), then `nh cluster
    labels import`. The scorer's output is deliberately absent from the file — the
    thresholds are chosen against these labels, so seeing the score first would make
    the measurement circular.
    """
    from nh.jobs.labelling import export_sample

    out.parent.mkdir(parents=True, exist_ok=True)
    result = export_sample(out, per_cluster=per_cluster, seed=seed)
    typer.echo(f"wrote {result.written} unlabelled rows to {result.path}")
    for cluster_id, n in sorted(result.per_cluster.items()):
        typer.echo(f"  {cluster_id:<24}{n:>5}")


@cluster_app.command("inspect")
def cluster_inspect(
    slug: str = typer.Argument(..., help="Cluster id, e.g. aviation-disasters"),
    n: int = typer.Option(8, "--n", help="Rows shown per band."),
) -> None:
    """Show what the relevance rule decided, and why.

    The two lists that matter are the weakest video it kept and the strongest it
    dropped: those are where the threshold actually sits, and reading them is how
    you find out the lexicon is wrong before a metric does.
    """
    from nh.clustering.inspect import inspect_cluster
    from nh.db.session import session_scope

    with session_scope() as session:
        view = inspect_cluster(session, slug, n)
    if view is None:
        typer.secho(f"no cluster {slug!r}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.echo(f"{view.cluster_id}  ({'active' if view.active else 'RETIRED'})")
    typer.echo(f"  videos          {view.total:,}")
    for name, count in view.bands:
        share = count / view.total if view.total else 0.0
        typer.echo(f"  {name:<15} {count:>6,}  {share:>6.1%}")
    typer.echo(f"\nweakest kept (just above {view.threshold}):")
    for row in view.weakest_kept:
        _echo_video(row)
    typer.echo("\nstrongest dropped (just below):")
    for row in view.strongest_dropped:
        _echo_video(row)


def _echo_video(row) -> None:
    matched = ", ".join((row.detail or {}).get("matched", [])[:5])
    typer.echo(f"  {row.relevance:.2f}  {(row.title or '')[:62]}")
    typer.echo(f"        {matched}")


@cluster_app.command("calibrate")
def cluster_calibrate() -> None:
    """Measure the relevance rule against the stored hand labels.

    Reports the held-out half separately, because the threshold was chosen on the
    other one and a precision quoted from the half you tuned on is not a
    measurement. See reports/relevance_*.md.
    """
    from nh.clustering.calibrate import evaluate
    from nh.clustering.relevance import RELEVANCE_HIGH
    from nh.db.session import session_scope

    with session_scope() as session:
        tuning, held_out, unscorable, unscorable_positive = evaluate(session)
    if not tuning.n and not held_out.n:
        typer.secho("no labels stored — run `nh cluster sample` first", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    typer.echo(f"threshold RELEVANCE_HIGH = {RELEVANCE_HIGH}\n")
    typer.echo(f"{'half':<10}{'n':>6}{'base':>8}{'precision':>11}{'recall':>9}")
    for half in (tuning, held_out):
        typer.echo(
            f"{half.name:<10}{half.n:>6}{_pct(half.base_rate):>8}"
            f"{_pct(half.precision):>11}{_pct(half.recall):>9}"
        )
    typer.echo("\nband rates (share truly on-niche):")
    typer.echo(f"{'band':<12}" + "".join(f"{h.name:>14}" for h in (tuning, held_out)))
    for i, name in enumerate(("on-niche", "undecided", "noise")):
        cells = "".join(
            f"{_pct(h.bands[i].rate) + f' (n={h.bands[i].n})':>14}" for h in (tuning, held_out)
        )
        typer.echo(f"{name:<12}{cells}")
    typer.echo(
        f"\nunscorable: {unscorable} labelled row(s), of which truly on-niche: "
        f"{unscorable_positive}"
    )
    if held_out.precision is not None and held_out.precision < 0.90:
        typer.secho(
            f"\nheld-out precision {held_out.precision:.3f} is below the 0.90 target; "
            "every metric built on this must say so",
            fg=typer.colors.YELLOW,
        )


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


@cluster_app.command("import")
def cluster_import(
    path: Path = typer.Argument(..., help="The labelled JSONL."),
    labeller: str = typer.Option(..., "--labeller", help="Who judged. Recorded per row."),
) -> None:
    """Store hand labels. Re-importing a corrected file overwrites."""
    from nh.jobs.labelling import import_labels

    typer.echo(f"stored {import_labels(path, labeller=labeller)} label(s)")


@app.command()
def deferrals() -> None:
    """Every unimplemented metric, its blocker, and what would unblock it.

    Exits non-zero when a trigger has fired, so a stale deferral cannot sit in the
    register unnoticed — the same reason `nh status --check` exists.
    """
    from datetime import date as _date

    from nh.jobs.deferrals import DEFERRALS, fires

    today = _date.today()
    unblocked = []
    typer.echo(f"{'STATUS':<12}{'METRIC':<52}TRIGGER")
    for deferral in DEFERRALS:
        state = fires(deferral, today)
        label = {True: "UNBLOCKED", False: "blocked", None: "manual"}[state]
        colour = {True: typer.colors.GREEN, False: None, None: typer.colors.YELLOW}[state]
        typer.secho(f"{label:<12}{deferral.metric[:50]:<52}{deferral.trigger}", fg=colour)
        typer.echo(f"            {deferral.blocker[:100]}")
        if state:
            unblocked.append(deferral)

    if unblocked:
        typer.secho(
            f"\n{len(unblocked)} deferral(s) have come unblocked — implement or "
            "re-defer with a new reason",
            fg=typer.colors.GREEN,
        )
        raise typer.Exit(1)
    typer.echo(f"\n{len(DEFERRALS)} deferral(s), none unblocked")


@app.command()
def backfill(
    what: str = typer.Argument(..., help="What to recover. Currently only: descriptions"),
    limit: int = typer.Option(None, "--limit", help="Stop after this many videos."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only, write nothing."),
) -> None:
    """Re-derive stored columns from `raw_records`. No network, no quota.

    Data rule 2: re-normalizing history is a query, never a re-fetch. `descriptions`
    recovers `videos.description` for videos collected before that column existed —
    text that otherwise only survives until the next `nh prune` (ADR-0017).
    """
    from nh.jobs.backfill import backfill_descriptions

    if what != "descriptions":
        typer.secho(f"unknown backfill target {what!r}", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    result = backfill_descriptions(limit=limit, dry_run=dry_run)
    verb = "would write" if result.dry_run else "wrote"
    typer.echo(
        f"scanned {result.scanned:,} raw payloads; "
        f"{verb} {result.found:,} description(s), {result.written:,} row(s) upserted"
    )


@app.command()
def prune(
    days: int = typer.Option(None, "--days", help="Retention window. Default from settings."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only, delete nothing."),
    force: bool = typer.Option(False, "--force", help="Prune even if it orphans descriptions."),
) -> None:
    """Drop aged bulk raw payloads and report storage.

    Touches `raw_records` only. Snapshots are never pruned — they are the
    unbackfillable asset and are kept forever (ADR-0010). Refuses to delete the last
    copy of a video description unless forced (ADR-0017).
    """
    from nh.db.retention import BULK_KINDS, LastCopyRefused, prune_raw_records, storage_report

    settings = get_settings()
    window = days if days is not None else settings.raw_retention_days

    typer.echo(f"{'KIND':<13}{'CODEC':<7}{'ROWS':>8}{'MB':>9}")
    total = 0
    for kind, codec, rows, size in storage_report():
        typer.echo(f"{kind:<13}{codec:<7}{rows:>8,}{size / 1048576:>9.1f}")
        total += size
    typer.echo(f"{'total':<13}{'':<7}{'':>8}{total / 1048576:>9.1f}")

    try:
        result = prune_raw_records(days=window, dry_run=dry_run, force=force)
    except LastCopyRefused as exc:
        typer.secho(f"\nrefused: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    verb = "would delete" if result.dry_run else "deleted"
    typer.echo(
        f"\n{verb} {result.deleted:,} {'/'.join(BULK_KINDS)} payloads older than {window} days"
    )
    if result.orphaned_descriptions:
        typer.secho(
            f"forced past {result.orphaned_descriptions:,} video(s) whose description "
            "was not stored; that text is gone",
            fg=typer.colors.YELLOW,
        )
    if not result.dry_run and result.deleted:
        typer.echo("run `sqlite3 <db> VACUUM;` to return the pages to the filesystem")


@app.command()
def compute(
    day: datetime | None = typer.Option(None, "--day", formats=["%Y-%m-%d"]),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Recompute clustering, features and scoring for a day, without collecting.

    Recorded as job="partial" so it never disturbs `nh status --check`, which
    judges the latest full nightly (ADR-0014).
    """
    from uuid import uuid4

    from nh.jobs.phases import run_phases

    _setup_logging(verbose)
    target = day.date() if day else date.today()
    statuses = run_phases(str(uuid4()), target, job="partial")
    for phase, status in statuses.items():
        typer.echo(f"  {status:<8} {phase}")
    raise typer.Exit(0 if all(v == "ok" for v in statuses.values()) else 1)


@app.command("web")
def web(
    port: int = typer.Option(8501, "--port"),
) -> None:
    """Serve the evidence surface (ADR-0052). Requires the `web` extra.

    Execs `streamlit run` rather than importing it: Streamlit owns its own process model,
    and re-implementing that here would be a second way to start the same app.
    """
    import os
    import shutil
    from pathlib import Path

    if shutil.which("streamlit") is None:
        typer.echo(
            "streamlit is not installed — `uv sync --extra web` (kept optional so the "
            "nightly never depends on a rendering library)",
            err=True,
        )
        raise typer.Exit(2)
    page = Path(__file__).parent / "web" / "app.py"
    # Fixed argv, no shell, no user-supplied path.
    os.execvp("streamlit", ["streamlit", "run", str(page), "--server.port", str(port)])


niche_app = typer.Typer(no_args_is_help=True, help="Inspect one niche.")
app.add_typer(niche_app, name="niche")


def _fmt(value: float | None) -> str:
    """A dash is 'not computable'; a printed number is a measurement.

    The distinction is the point: 0.00 means we looked and the answer was zero,
    which is a finding. An em dash means we could not look.
    """
    if value is None:
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


@niche_app.command("show")
def niche_show(
    slug: str = typer.Argument(..., help="Cluster id, e.g. aviation-disasters."),
    day: datetime | None = typer.Option(None, "--day", formats=["%Y-%m-%d"]),
    unvalidated: bool = typer.Option(
        False,
        "--unvalidated",
        help="Show metrics whose relevance rule has no human labels yet (ADR-0052).",
    ),
) -> None:
    """Every metric for one niche, with confidence and where it came from."""
    from nh.jobs import niche as niche_job

    try:
        view = niche_job.load(slug, day.date() if day else None, include_unvalidated=unvalidated)
    except niche_job.UnknownCluster:
        typer.echo(f"unknown niche: {slug}", err=True)
        typer.echo(
            f"known: {', '.join(niche_job.known_clusters()) or '(none — run nh nightly)'}", err=True
        )
        raise typer.Exit(2) from None

    header = f"{view.cluster_id}" + (f" — {view.label}" if view.label else "")
    typer.echo(header)
    if not view.metrics:
        typer.echo("no features computed yet — run `nh compute`")
        raise typer.Exit(0)
    run = (view.run_id or "")[:8]
    typer.echo(f"day {view.day} · run {run}… · {view.member_channels} member channels\n")

    typer.echo(f"{'GROUP':<10}{'METRIC':<28}{'VALUE':>12}{'CONF':>7}{'N':>8}")
    last_group = None
    for m in view.metrics:
        group = m.group if m.group != last_group else ""
        last_group = m.group
        if not m.shown:
            # The value, the confidence and `inputs_n` are all withheld together. `n` alone
            # would not be a citation, but a table with one column blanked reads as a bug
            # rather than as a decision, and the decision is the point.
            typer.echo(f"{group:<10}{m.name:<28}{'·':>12}{'·':>7}{'·':>8}")
            typer.echo(f"          {m.withheld}")
            continue
        typer.echo(
            f"{group:<10}{m.name:<28}{_fmt(m.value):>12}"
            f"{_fmt(m.confidence):>7}"
            f"{f'{m.inputs_n:,}' if m.inputs_n is not None else '—':>8}"
        )
        typer.echo(f"          {_provenance(m)}")

    if view.scorecard:
        parts = " ".join(f"{k}={_fmt(v)}" for k, v in view.scorecard.items())
        typer.echo(f"\nscorecard {view.day}: {parts}")
    elif view.scorecard_withheld:
        typer.echo(f"\nscorecard {view.day}: {view.scorecard_withheld}")
    if any(not m.shown for m in view.metrics) or view.scorecard_withheld:
        typer.echo(
            "\n· means withheld, not missing: computed but unvalidated (ADR-0052). "
            "`--unvalidated` shows them."
        )
    typer.echo(
        "\n— means not computable; a printed number is a measurement. "
        "value/opportunity await the Slice 5 composites."
    )


@niche_app.command("trace")
def niche_trace(
    slug: str = typer.Argument(..., help="Cluster id, e.g. history-of-ideas."),
    metric: str = typer.Argument(..., help="Metric name, e.g. wiki_yoy."),
    day: datetime | None = typer.Option(None, "--day", formats=["%Y-%m-%d"]),
    limit: int = typer.Option(20, "--limit", help="Rows to print."),
) -> None:
    """The input rows behind one number — Slice 7's exit criterion, from a terminal.

    "Every displayed number reaches its input rows" is a promise a surface can appear to
    keep by linking to a plausible query nobody ran, so the registry behind this is tested
    to return non-empty rows for every registered metric. This command is that registry's
    first consumer, and it works before any page is drawn.
    """
    from nh.api import basis as basis_mod
    from nh.api import drilldown, gates, queries
    from nh.db.session import get_engine, session_scope

    with session_scope(get_engine()) as session:
        on = day.date() if day else queries.latest_day(session, slug)
        if on is None:
            typer.echo(f"no features for {slug} — run `nh compute`", err=True)
            raise typer.Exit(2)
        headers, rows = drilldown.rows_behind(session, metric, slug, on)

    if not headers:
        typer.echo(f"no drilldown registered for {metric}", err=True)
        typer.echo(f"known: {', '.join(sorted(drilldown.REGISTRY))}", err=True)
        raise typer.Exit(2)

    typer.echo(f"{metric} · {slug} · {on}")
    typer.echo(f"population: {basis_mod.basis(metric)}")
    # The rows are NOT gated even when the metric is, and the asymmetry is deliberate:
    # `gates` withholds the scorer's aggregate CLAIM, while these are the observations a
    # person needs in order to judge whether that claim is any good. Withholding the audit
    # trail would make the thing unvalidatable, which is the opposite of the intent.
    #
    # There is a real cost and it is named rather than assumed away: a video-grain row
    # carries `relevance`, so anyone about to label ADR-0041's or ADR-0050's sample should
    # not browse it first. That is the same contamination rule ADR-0042 wrote for the
    # 2026-08-30 transcript.
    if not gates.citable(metric, slug):
        typer.echo(
            "note: this metric's VALUE is withheld (ADR-0052); its input rows are shown "
            "so the scorer can be checked. Do not read them before labelling a sample."
        )
    # The count is the honest part: `LIMIT` caps what the query returned, and the metric's
    # own `inputs_n` states the true n. Saying "showing X of the first Y" rather than
    # "of N" avoids implying this is the whole population when it is not.
    typer.echo(f"showing {min(limit, len(rows))} of {len(rows)} fetched\n")
    typer.echo(" · ".join(str(h) for h in headers))
    for row in rows[:limit]:
        typer.echo(" · ".join("—" if v is None else str(v) for v in row))


def _provenance(m) -> str:
    """The one-line trail under each metric: why this number, from what."""
    detail = m.detail or {}
    if m.value is None:
        return f"no data: {detail.get('reason', 'not computed')}"
    bits = []
    if (n := detail.get("contributing_channels")) is not None:
        bits.append(f"{n} channels contributed")
    if (n := detail.get("cohort_channels")) is not None:
        bits.append(f"cohort of {n}")
    if (n := detail.get("channels_with_breakout")) is not None:
        bits.append(f"{n} broke through")
    if (w := detail.get("window")) is not None:
        bits.append(f"window {w[0]}..{w[1]}")
    # A detail key that changes what a number MEANS has to be rendered here, or the
    # number reads as something it is not. `currency` was missed once: a COP bid of
    # 64,083 printed under a heading called "money" in a repo whose convention says
    # USD is a four-orders-of-magnitude misreading available at a glance, and a low
    # confidence beside it does not prevent that (ADR-0031). `geo` is the same shape
    # of bug — the four sources measure four different populations (ADR-0035), so a
    # number that describes one market must say which.
    if (g := detail.get("geo")) is not None:
        bits.append(f"geo {g or 'worldwide'}")
    if (c := detail.get("currency")) is not None:
        bits.append(f"bids in {c}")
    if (p := detail.get("p90_views")) is not None:
        bits.append(f"p90={p:,.0f}")
    tables = ", ".join(detail.get("inputs", {}).get("tables", []))
    if tables:
        bits.append(f"from {tables}")
    return " · ".join(bits) or "—"


@app.command()
def doctor(
    repair: bool = typer.Option(
        False, "--repair", help="Clear leftovers from an interrupted batch migration."
    ),
) -> None:
    """Check that the database is reachable and the schema is present."""
    import sqlalchemy as sa

    from nh.db.models import Base
    from nh.db.repair import drop_batch_leftover, find_batch_leftovers
    from nh.db.session import get_engine

    settings = get_settings()
    typer.echo(f"database_url : {settings.database_url}")
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(sa.text("SELECT 1"))
    present = set(sa.inspect(engine).get_table_names())
    expected = set(Base.metadata.tables)
    typer.echo(f"dialect      : {engine.dialect.name}")
    typer.echo(f"tables       : {len(present & expected)}/{len(expected)} present")
    if missing := sorted(expected - present):
        typer.echo(f"missing      : {', '.join(missing)}")
        typer.echo("run: uv run alembic upgrade head")
        raise typer.Exit(1)

    # An active seed with no lexicon collects and can never score. Silent until
    # 2026-08-28, when two such seeds were found spending 600 units a night.
    from nh.clustering.phase import lexicon_gaps
    from nh.db.session import get_sessionmaker

    unscorable, orphaned = lexicon_gaps(get_sessionmaker(engine)())
    if unscorable:
        typer.secho(f"seeds without a lexicon : {', '.join(unscorable)}", fg=typer.colors.RED)
        typer.echo("  these collect quota and can never score a video")
        typer.echo("  add them to nh/clustering/lexicon.py::LEXICONS, or deactivate the seed")
    if orphaned:
        typer.echo(f"lexicons without a seed : {', '.join(orphaned)} (harmless)")

    # An interrupted batch migration leaves `_alembic_tmp_*` behind. Everything
    # keeps working until the next schema change to that table, which then fails
    # with "already exists" — so it is worth saying out loud while it is harmless.
    if leftovers := find_batch_leftovers(engine):
        typer.secho(f"batch leftovers : {', '.join(leftovers)}", fg=typer.colors.YELLOW)
        if not repair:
            typer.echo("  these will break the next batch migration on those tables")
            typer.echo("  run: uv run nh doctor --repair")
            raise typer.Exit(1)
        for name in leftovers:
            held = drop_batch_leftover(name, engine)
            typer.echo(f"  dropped {name} ({held} row(s))")


backtest_app = typer.Typer(
    no_args_is_help=True,
    help="Gate E: replay the scorer over 2015-2019 and correlate with what happened.",
)
app.add_typer(backtest_app, name="backtest")


def _backtest_engine():
    """The engine, having refused anything not named as a backtest database.

    The load writes ~30 fake clusters and millions of 2019 rows; in the live corpus
    `nh nightly` would then RSS-poll channels that stopped uploading in 2019 and rank
    live niches against phantom ones. Set
    `NH_DATABASE_URL=sqlite:///data/backtest.db`.
    """
    from nh.backtest.load import refuse_live
    from nh.db.session import get_engine

    engine = get_engine()
    refuse_live(engine)
    return engine


@backtest_app.command("scan")
def backtest_scan(
    metadata: Path = typer.Option(
        Path("data/youniverse/yt_metadata_en.jsonl.gz"), help="The 13.6 GB video dump."
    ),
    out: Path = typer.Option(Path("data/backtest/hits.jsonl.gz"), help="Where hits are written."),
    selection_out: Path = typer.Option(
        Path("data/backtest/selection.json"), help="Where the niche assignment is written."
    ),
    limit: int = typer.Option(0, help="Stop after N videos. 0 scans the file."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Score 73M video titles against the backtest lexicons. One pass, keeps almost none of it."""
    _setup_logging(verbose)
    from nh.backtest.scan import scan
    from nh.backtest.select import select

    result = scan(metadata, out, limit=limit or None)
    typer.echo(f"videos read   : {result.videos_read:,}")
    typer.echo(f"videos scored : {result.videos_scored:,} ({result.hits:,} hits)")

    selection = select(result.counts)
    selection.save(selection_out)
    typer.echo(f"niches kept   : {len(selection.kept)} (written to {selection_out})")
    typer.echo(f"contested     : {selection.contested:,} channels qualified for more than one")
    for slug, n in selection.dropped:
        typer.echo(f"  dropped {slug}: {n} member channels")


@backtest_app.command("seed")
def backtest_seed(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    """Write the 36 backtest niches and their Wikipedia articles into the backtest DB.

    Run this BEFORE the scan. The Wikipedia backfill that follows it is a ~1.6-hour
    quota-free network job and the scan is a multi-hour pass over 13.6 GB; they need
    nothing from each other, so running them in sequence costs an afternoon for no
    reason.

        NH_DATABASE_URL=sqlite:///data/backtest.db uv run alembic upgrade head
        NH_DATABASE_URL=sqlite:///data/backtest.db uv run nh backtest seed
        NH_DATABASE_URL=sqlite:///data/backtest.db NH_WIKI_BACKFILL_DAYS=4100 \
            uv run nh nightly --only wikipedia
    """
    _setup_logging(verbose)
    from nh.backtest.load import seed

    engine = _backtest_engine()
    typer.echo(f"seeded {seed(engine)} backtest niches with their topic articles")


@backtest_app.command("load")
def backtest_load(
    hits: Path = typer.Option(Path("data/backtest/hits.jsonl.gz")),
    selection_path: Path = typer.Option(Path("data/backtest/selection.json")),
    channels: Path = typer.Option(Path("data/youniverse/df_channels_en.tsv.gz")),
    timeseries: Path = typer.Option(Path("data/youniverse/df_timeseries_en.tsv.gz")),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Materialise the selected population into the backtest database."""
    _setup_logging(verbose)
    import uuid
    from datetime import UTC

    from nh.backtest.load import load
    from nh.backtest.select import Selection

    engine = _backtest_engine()
    report = load(
        engine,
        selection=Selection.load(selection_path),
        hits=hits,
        channels_path=channels,
        timeseries_path=timeseries,
        run_id=str(uuid.uuid4()),
        at=datetime.now(UTC),
    )
    typer.echo(f"clusters      : {report.clusters}")
    typer.echo(f"channels      : {report.channels:,}")
    typer.echo(f"channel weeks : {report.channel_weeks:,}")
    typer.echo(f"videos        : {report.videos:,} ({report.video_members:,} memberships)")
    if report.channels_without_metadata:
        typer.secho(
            f"no metadata for {len(report.channels_without_metadata)} selected channel(s)",
            fg=typer.colors.YELLOW,
        )


@backtest_app.command("replay")
def backtest_replay(
    start: datetime = typer.Option(..., formats=["%Y-%m-%d"]),
    end: datetime = typer.Option(..., formats=["%Y-%m-%d"]),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Compute features and scorecards at every weekly decision date in the window."""
    _setup_logging(verbose)
    import uuid

    from nh.backtest.replay import decision_dates, replay

    engine = _backtest_engine()
    dates = decision_dates(start.date(), end.date())
    typer.echo(f"decision dates: {len(dates)}")
    rows, cards = replay(engine, dates, run_id=str(uuid.uuid4()))
    typer.echo(f"feature rows  : {rows:,}")
    typer.echo(f"scorecards    : {cards:,}")


@backtest_app.command("score")
def backtest_score(
    start: datetime = typer.Option(..., formats=["%Y-%m-%d"]),
    end: datetime = typer.Option(..., formats=["%Y-%m-%d"]),
    horizon: int = typer.Option(180, help="Outcome horizon in days."),
    out: Path = typer.Option(None, help="Report path. Defaults to reports/backtest_<today>.md"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Pair scores with outcomes, run the pre-registered test, write the report."""
    _setup_logging(verbose)
    from nh.backtest.niches import by_slug
    from nh.backtest.replay import as_series, decision_dates, pair
    from nh.backtest.report import Findings, Variant, render, verdict
    from nh.backtest.stats import evaluate, evaluate_partial, spearman

    engine = _backtest_engine()
    pairings = pair(engine, decision_dates(start.date(), end.date()), horizon_days=horizon)
    if not pairings:
        typer.secho("no date has three scored niches with outcomes", fg=typer.colors.RED)
        raise typer.Exit(1)

    aggregate, per_date = evaluate(as_series(pairings))
    # The size baseline. A score that ranks niches by how big they are needs no
    # pipeline to reproduce, so the primary is tested against that alternative rather
    # than merely reported beside it: `evaluate_partial` runs the same global
    # label-permutation null on the size-partialled statistic. Amended 2026-08-28,
    # before any result existed — survival used to be a bare sign check, and a
    # residual of +0.03 is not survival.
    controlled, _ = evaluate_partial(
        [
            (p.day.isoformat(), p.clusters, p.scores, p.outcomes, [float(n) for n in p.sizes])
            for p in pairings
        ]
    )
    outcomes = [o for p in pairings for o in p.outcomes]
    sizes = [float(n) for p in pairings for n in p.sizes]

    findings = Findings(
        day=date.today(),
        primary=Variant(
            label="gap",
            stratum="topic",
            supply_from="views_per_new_video",
            threshold=0.55,
            horizon_days=horizon,
            aggregate=aggregate,
        ),
        niches_selected=aggregate.n_median,
        niches_committed=len(by_slug()),
        per_date=per_date,
        size_rho=spearman(sizes, outcomes),
        size_controlled_rho=controlled.rho,
        size_controlled_p=controlled.p_value,
    )
    label, reason = verdict(findings)
    path = out or Path(f"reports/backtest_{date.today().isoformat()}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(findings))
    typer.echo(f"wrote {path}")
    colour = typer.colors.GREEN if label == "PASS" else typer.colors.YELLOW
    typer.secho(f"{label} — {reason}", fg=colour)


kp_app = typer.Typer(no_args_is_help=True, help="Keyword Planner — manual CSV import.")
app.add_typer(kp_app, name="kp")


@kp_app.command("ingest")
def kp_ingest(
    csv_path: Path = typer.Argument(..., help="The 'Historical metrics' export."),
    geo: str = typer.Option(
        "", "--geo", help="Geo the export was run for, e.g. US. '' = worldwide."
    ),
    lang: str = typer.Option("en", "--lang"),
    period_end: datetime = typer.Option(
        None,
        "--period-end",
        formats=["%Y-%m-%d"],
        help="Last day of the period the numbers describe. Only needed when the "
        "export's own date line is in a locale the parser does not read.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Import a Keyword Planner export.

    Manual by design: this source has no network fetch, so `nh nightly` will not run
    it (ADR-0030). `raise_on_error=True` because a human is at the keyboard — the
    outage-survival semantics that keep a nightly alive would only hide a bad file.
    """
    _setup_logging(verbose)
    from uuid import uuid4

    import sqlalchemy as sa

    from nh.collectors.keyword_planner import KeywordPlannerCollector
    from nh.db.models import KeywordMetric, SeedTerm
    from nh.db.session import get_engine, session_scope

    if not csv_path.exists():
        typer.secho(f"no such file: {csv_path}", fg=typer.colors.RED)
        raise typer.Exit(1)

    engine = get_engine()
    collector = KeywordPlannerCollector(
        str(uuid4()),
        engine=engine,
        path=csv_path,
        geo=geo,
        lang=lang,
        period_end=period_end.date() if period_end else None,
    )
    run = collector.run(job="kp_import", raise_on_error=True)
    typer.echo(f"  status        : {run.status}")
    typer.echo(f"  raw payloads  : {run.raw_written}")
    # snapshots_written, not rows_upserted: KeywordMetric is append-only, so rows
    # arrive via the snapshot path and a re-ingest correctly reports 0 new.
    typer.echo(f"  keyword rows  : {run.snapshots_written} new")

    # Matching is reported, never enforced: everything the export carries is stored,
    # and which keywords a niche claims is a feature-time question whose honesty
    # lives in `inputs_n`. A keyword Google reshaped into a close variant should not
    # be dropped at ingest.
    #
    # The check matches on (keyword, lang) — the join the features will actually
    # use (ADR-0038): a seed term is geo-independent curation, and the market a
    # number was measured in is `keyword_metrics.geo`, chosen per feature call.
    # The principle stands from the earlier correction — a match report weaker OR
    # STRONGER than the real join is a false signal. The previous key,
    # (keyword, geo, lang), was stronger: it required seed_terms to duplicate per
    # market, and reported 96/162 on the first two-geo ingest for rows the join
    # would in fact have attributed.
    with session_scope(engine) as session:
        seeded = {
            (t.lower(), ln)
            for t, ln in session.execute(
                sa.select(SeedTerm.term, SeedTerm.lang).where(SeedTerm.source == "keyword_planner")
            )
        }
        stored = list(
            session.execute(sa.select(KeywordMetric.keyword, KeywordMetric.geo, KeywordMetric.lang))
        )
    matched = sum(1 for k, _, ln in stored if (k.lower(), ln) in seeded)
    by_geo: dict[str, list[int]] = {}
    for k, g, ln in stored:
        hit = (k.lower(), ln) in seeded
        counts = by_geo.setdefault(g or "worldwide", [0, 0])
        counts[0] += hit
        counts[1] += 1
    typer.echo(f"  matched a seed term: {matched}/{len(stored)}  (on keyword+lang; ADR-0038)")
    for g, (hit, total) in sorted(by_geo.items()):
        typer.echo(f"    geo {g}: {hit}/{total}")
    if matched < len(stored):
        typer.echo("  unmatched keywords are stored anyway; features decide what counts")


if __name__ == "__main__":  # pragma: no cover
    app()
