"""The migration chain must actually build the schema the models describe.

Two failures this catches, both observed for real in Slice 5 and both silent:

1. **Partial application reported as success.** An `env.py` that issued
   `PRAGMA foreign_keys=OFF` against an already-open connection opened an implicit
   transaction; `alembic upgrade head` then logged all seven revisions as applied
   and produced 15 tables where 19 were expected. Nothing failed. Nothing warned.
2. **Model/migration drift.** A column added to `nh/db/models.py` without a
   migration works forever on a database that was upgraded incrementally, and
   breaks the first time anyone builds from scratch — which is exactly what the
   Postgres swap will do.

`alembic upgrade head` from empty is the only thing that proves either. It is also
the closest thing this suite has to a rehearsal for that swap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from nh.db.models import Base

REPO_ROOT = Path(__file__).resolve().parent.parent


def _config(url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "nh" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def fresh(tmp_path):
    """A database that has never existed, and its alembic config."""
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    return url, _config(url)


def test_upgrade_head_builds_every_table_the_models_declare(fresh):
    url, config = fresh

    command.upgrade(config, "head")

    built = set(inspect(create_engine(url)).get_table_names()) - {"alembic_version"}
    assert built == set(Base.metadata.tables)


def test_upgrade_head_leaves_no_batch_temp_tables(fresh):
    """Batch mode rewrites tables through `_alembic_tmp_*`. One left behind means a
    batch operation aborted half way, and it blocks every later migration on that
    table with `table _alembic_tmp_x already exists`."""
    url, config = fresh

    command.upgrade(config, "head")

    tables = inspect(create_engine(url)).get_table_names()
    assert [t for t in tables if t.startswith("_alembic_tmp")] == []


def test_the_chain_downgrades_all_the_way_back(fresh):
    url, config = fresh
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    remaining = set(inspect(create_engine(url)).get_table_names()) - {"alembic_version"}
    assert remaining == set()


def test_downgrade_survives_a_populated_database(fresh):
    """The one that was actually broken. Batch mode drops the original table, and
    with `PRAGMA foreign_keys=ON` — which the application sets, correctly — that
    raises `FOREIGN KEY constraint failed` as soon as any row exists. Empty
    databases round-trip fine, which is why nothing caught it.
    """
    url, config = fresh
    command.upgrade(config, "head")
    engine = create_engine(url)
    from nh.seeds import apply_seeds, apply_terms

    apply_seeds(engine)
    apply_terms(engine)

    command.downgrade(config, "-1")
    command.upgrade(config, "head")

    with engine.connect() as connection:
        from sqlalchemy import func, select

        from nh.db.models import SeedTerm

        assert connection.execute(select(func.count()).select_from(SeedTerm)).scalar() > 0


def test_a_migration_does_not_mute_the_applications_loggers(fresh):
    """Alembic's `fileConfig` disables every logger that already exists unless told not
    to, and `env.py` runs it on any in-process `command.upgrade`.

    This cost half an afternoon on 2026-09-17. `Collector.__init__` creates
    `nh.collectors.<source>` lazily, so whether a logger was alive when a migration ran
    depended on file order: the suite's first two log assertions passed alone, passed in
    their own file, passed in either half of the suite, and failed only in the whole one,
    with an empty `caplog` and no other symptom. Nothing in `nh/` runs alembic
    in-process, so no nightly line was ever lost — but a suite that cannot observe a log
    line cannot hold one, which is why there were no log assertions to break until now.
    """
    import logging

    _, config = fresh
    logger = logging.getLogger("nh.collectors.canary")
    assert not logger.disabled

    command.upgrade(config, "head")

    assert not logger.disabled, "alembic's fileConfig muted an existing nh logger"
