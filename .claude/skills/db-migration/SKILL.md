---
name: db-migration
description: Create and apply an Alembic migration safely, with a reversible downgrade. Use for any schema change.
---

# Database migration

1. Edit `nh/db/models.py` first. Time series inherit `AppendOnly` and declare
   `UniqueConstraint(entity, "observed_date", "source")`; measures are nullable.

2. `uv run alembic revision --autogenerate -m "<what changed>"`

3. **Read the generated file.** Autogenerate is a draft, not an answer:
   - Does `downgrade()` actually reverse `upgrade()`? An empty or `pass`
     downgrade is a rejected migration.
   - Did it detect a rename as a drop+add? That silently destroys the column's
     data — rewrite it as `op.alter_column(..., new_column_name=...)`.
   - JSON columns must render as `JSONVariant` (env.py's `render_item` handles
     this; if you see `postgresql.JSONB(astext_type=Text())`, the hook broke).
   - `render_as_batch=True` is on because SQLite cannot ALTER in place.

4. **Test both directions against a scratch database**, never the real one:
   ```
   NH_DATABASE_URL=sqlite:///data/scratch.db uv run alembic upgrade head
   NH_DATABASE_URL=sqlite:///data/scratch.db uv run alembic downgrade -1
   NH_DATABASE_URL=sqlite:///data/scratch.db uv run alembic upgrade head
   rm data/scratch.db
   ```

5. Apply for real: `uv run alembic upgrade head`, then `uv run nh doctor`.

6. Note the revision id in the PR description and in `docs/DECISIONS.md` if the
   change reflects a decision rather than a mechanical addition.

Never `DROP` or `TRUNCATE` a `*_snapshots` table. The hook blocks it, and the
history is unrecoverable because no source serves it retroactively.
