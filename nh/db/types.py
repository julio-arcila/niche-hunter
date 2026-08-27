"""Column types and helpers shared by every model."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# JSONB on Postgres, plain JSON on SQLite. Raw payloads and any bag-of-fields
# column uses this so the Postgres swap (ADR-0002) is a URL change, not a migration.
JSONVariant = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def utcnow() -> datetime:
    """Timezone-aware UTC now. Every `at` in the schema is this."""
    return datetime.now(UTC)


# Naming convention so Alembic autogenerate produces stable, named constraints
# instead of database-assigned ones that differ between SQLite and Postgres.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
