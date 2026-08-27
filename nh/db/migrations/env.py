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
