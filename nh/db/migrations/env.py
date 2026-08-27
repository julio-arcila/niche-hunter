from __future__ import annotations

from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context

from nh.config import get_settings
from nh.db.models import Base
from nh.db.session import make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_: str, obj: object, autogen_context) -> str | bool:
    """Render our JSONB/JSON variant as `JSONVariant` in generated migrations.

    Left to itself, autogenerate emits
    ``sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), 'postgresql')``
    without importing Text, so the migration raises NameError on upgrade. Every
    JSON column in nh/db/models.py is JSONVariant, so this substitution is total.
    """
    if type_ == "type" and isinstance(obj, sa.JSON):
        autogen_context.imports.add("from nh.db.types import JSONVariant")
        return "JSONVariant"
    return False


def _disable_sqlite_foreign_keys(engine) -> None:
    """Turn FK enforcement off for migration connections only.

    Batch mode rewrites a table — copy, move rows, drop the original, rename — and
    with `PRAGMA foreign_keys=ON` that drop raises `FOREIGN KEY constraint failed`
    on any populated table something references. `nh.db.session` sets that pragma
    ON for the application, correctly, and `make_engine` is shared, so it has to be
    switched back off here.

    A `connect` listener, not `exec_driver_sql` on the open connection. The pragma
    is per-connection and SQLite silently ignores it inside a transaction, so it has
    to be set as the connection is made; issuing it against an already-open
    connection opens an implicit transaction and leaves migrations partially
    applied — measured, that produced 15 tables where a fresh database should have
    19, with `alembic upgrade head` still reporting success.

    Registered after `make_engine`'s own listener and therefore wins. Scoped to this
    engine, which exists only for the duration of the migration.
    """
    if engine.dialect.name != "sqlite":
        return

    @sa.event.listens_for(engine, "connect")
    def _off(dbapi_connection, _record):  # pragma: no cover - driver callback
        dbapi_connection.execute("PRAGMA foreign_keys=OFF")


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(url=_url())
    _disable_sqlite_foreign_keys(engine)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place; batch mode rewrites the
            # table instead. Harmless on Postgres, essential before the swap.
            render_as_batch=True,
            compare_type=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
