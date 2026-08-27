"""`nh` — the operator-facing entry point."""

from __future__ import annotations

import logging
from datetime import date, datetime

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


@app.command()
def prune(
    days: int = typer.Option(None, "--days", help="Retention window. Default from settings."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report only, delete nothing."),
) -> None:
    """Drop aged bulk raw payloads and report storage.

    Touches `raw_records` only. Snapshots are never pruned — they are the
    unbackfillable asset and are kept forever (ADR-0010).
    """
    from nh.db.retention import BULK_KINDS, prune_raw_records, storage_report

    settings = get_settings()
    window = days if days is not None else settings.raw_retention_days

    typer.echo(f"{'KIND':<13}{'CODEC':<7}{'ROWS':>8}{'MB':>9}")
    total = 0
    for kind, codec, rows, size in storage_report():
        typer.echo(f"{kind:<13}{codec:<7}{rows:>8,}{size / 1048576:>9.1f}")
        total += size
    typer.echo(f"{'total':<13}{'':<7}{'':>8}{total / 1048576:>9.1f}")

    result = prune_raw_records(days=window, dry_run=dry_run)
    verb = "would delete" if result.dry_run else "deleted"
    typer.echo(
        f"\n{verb} {result.deleted:,} {'/'.join(BULK_KINDS)} payloads older than {window} days"
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
) -> None:
    """Every metric for one niche, with confidence and where it came from."""
    from nh.jobs import niche as niche_job

    try:
        view = niche_job.load(slug, day.date() if day else None)
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
        typer.echo(
            f"{group:<10}{m.name:<28}{_fmt(m.value):>12}"
            f"{_fmt(m.confidence):>7}"
            f"{f'{m.inputs_n:,}' if m.inputs_n is not None else '—':>8}"
        )
        typer.echo(f"          {_provenance(m)}")

    if view.scorecard:
        parts = " ".join(f"{k}={_fmt(v)}" for k, v in view.scorecard.items())
        typer.echo(f"\nscorecard {view.day}: {parts}")
    typer.echo(
        "\n— means not computable; a printed number is a measurement. "
        "value/opportunity await the Slice 5 composites."
    )


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
    if (p := detail.get("p90_views")) is not None:
        bits.append(f"p90={p:,.0f}")
    tables = ", ".join(detail.get("inputs", {}).get("tables", []))
    if tables:
        bits.append(f"from {tables}")
    return " · ".join(bits) or "—"


@app.command()
def doctor() -> None:
    """Check that the database is reachable and the schema is present."""
    import sqlalchemy as sa

    from nh.db.models import Base
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


if __name__ == "__main__":  # pragma: no cover
    app()
