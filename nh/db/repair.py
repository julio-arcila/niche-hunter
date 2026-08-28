"""Clearing leftovers from an interrupted batch migration.

SQLite cannot ALTER most things in place, so Alembic's batch mode rewrites the
whole table: create `_alembic_tmp_<name>`, copy the rows, drop the original,
rename. If that sequence aborts part way — a failed constraint, an interrupted
run — the temp table survives, and every later batch operation on that table dies
with `table _alembic_tmp_<name> already exists`. Nothing else notices: the
nightly runs, `nh doctor` reports every table present, and the damage only
appears the next time someone changes the schema.

**Why this exists rather than a shell `DROP TABLE`.** Dropping tables from a
shell is blocked, deliberately — snapshot history cannot be re-collected and a
mistyped table name is unrecoverable. So the safety is enforced here instead,
exactly as `nh.db.retention` does for the one other deliberate deletion in the
codebase: this function is hard-coded to the `_alembic_tmp_` prefix and refuses
anything else, so it *cannot* name a real table however it is called.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from nh.db.session import get_engine

#: The only prefix this module will ever drop. Alembic's own naming.
BATCH_TEMP_PREFIX = "_alembic_tmp_"


class NotABatchTemp(ValueError):
    """Raised when asked to drop something that is not an Alembic batch leftover."""


def find_batch_leftovers(engine: Engine | None = None) -> list[str]:
    """Tables an interrupted batch migration left behind. Usually empty."""
    engine = engine or get_engine()
    return sorted(
        name for name in sa.inspect(engine).get_table_names() if name.startswith(BATCH_TEMP_PREFIX)
    )


def drop_batch_leftover(name: str, engine: Engine | None = None) -> int:
    """Drop one leftover. Returns the row count it held, for the record.

    The prefix check is the whole safety argument, so it is first and it raises
    rather than returning a falsy value — a caller that ignores a return code must
    not be able to turn this into a silent no-op on a real table.
    """
    if not name.startswith(BATCH_TEMP_PREFIX):
        raise NotABatchTemp(
            f"{name!r} is not an Alembic batch leftover; this function only drops "
            f"tables named {BATCH_TEMP_PREFIX}*"
        )
    engine = engine or get_engine()
    with engine.begin() as connection:
        held = connection.execute(sa.text(f'SELECT count(*) FROM "{name}"')).scalar() or 0
        connection.execute(sa.text(f'DROP TABLE "{name}"'))
    return held
