"""scorecard supply column and features_daily group rename

Revision ID: 20a954826624
Revises: 50d3359a86d5
Create Date: 2026-08-27 04:00:54.977408

Two Gate B findings from Slice 2, both free to fix only because
`scorecards` and `features_daily` are still empty:

  * `scorecards` had nowhere to store a supply summary, yet Slice 3's
    `gap = demand - supply` needs supply persisted for the gap to be
    reconstructible from stored rows.
  * `features_daily.group` is a SQL keyword. Every hand-written traceability
    query would have to quote it forever.

Autogenerate produced only the first of these — it did not detect the rename at
all — so the `alter_column` below is hand-written. Written as a rename rather
than drop+add so it stays correct if it is ever run against a populated table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20a954826624"
down_revision: str | None = "50d3359a86d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scorecards", schema=None) as batch_op:
        batch_op.add_column(sa.Column("supply", sa.Float(), nullable=True))
    with op.batch_alter_table("features_daily", schema=None) as batch_op:
        batch_op.alter_column("group", new_column_name="metric_group", existing_type=sa.String(24))


def downgrade() -> None:
    with op.batch_alter_table("features_daily", schema=None) as batch_op:
        batch_op.alter_column("metric_group", new_column_name="group", existing_type=sa.String(24))
    with op.batch_alter_table("scorecards", schema=None) as batch_op:
        batch_op.drop_column("supply")
