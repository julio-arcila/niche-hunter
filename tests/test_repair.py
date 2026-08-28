"""Clearing Alembic batch leftovers, and refusing to clear anything else.

The safety argument for this module is entirely the prefix check, so that is what
these tests are mostly about. A shell `DROP TABLE` is blocked by a hook because a
mistyped table name is unrecoverable; the same protection has to hold here, and it
holds by construction rather than by care.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from nh.db.models import Video
from nh.db.repair import NotABatchTemp, drop_batch_leftover, find_batch_leftovers
from nh.db.session import session_scope
from nh.db.types import utcnow


def _leftover(engine, name="_alembic_tmp_seed_terms", rows=0):
    with engine.begin() as connection:
        connection.execute(sa.text(f'CREATE TABLE "{name}" (id INTEGER)'))
        for i in range(rows):
            connection.execute(sa.text(f'INSERT INTO "{name}" VALUES ({i})'))


def test_a_clean_database_has_no_leftovers(engine):
    assert find_batch_leftovers(engine) == []


def test_it_finds_a_leftover(engine):
    _leftover(engine)
    assert find_batch_leftovers(engine) == ["_alembic_tmp_seed_terms"]


def test_it_drops_a_leftover_and_reports_what_it_held(engine):
    _leftover(engine, rows=3)

    assert drop_batch_leftover("_alembic_tmp_seed_terms", engine) == 3

    assert find_batch_leftovers(engine) == []


def test_it_refuses_a_real_table(engine):
    """The whole safety argument. This must raise rather than return falsy — a
    caller that ignores a return code must not be able to turn it into a silent
    no-op that looks like success."""
    with session_scope(engine) as s:
        s.add(Video(video_id="v1", channel_id="c1", source="t", run_id="t", at=utcnow()))

    with pytest.raises(NotABatchTemp, match="not an Alembic batch leftover"):
        drop_batch_leftover("videos", engine)

    with session_scope(engine) as s:
        assert s.get(Video, "v1") is not None


@pytest.mark.parametrize(
    "name",
    [
        "video_snapshots",
        "demand_snapshots",
        "alembic_version",
        "tmp_alembic_seed_terms",  # prefix in the wrong place
        "seed_terms_alembic_tmp_",  # suffix, not prefix
        "",
    ],
)
def test_it_refuses_everything_that_is_not_prefixed(engine, name):
    with pytest.raises(NotABatchTemp):
        drop_batch_leftover(name, engine)


def test_the_prefix_is_the_one_alembic_actually_uses():
    """If Alembic ever renames its temp tables this module silently stops finding
    them, and the failure mode is a migration that breaks weeks later."""
    from nh.db.repair import BATCH_TEMP_PREFIX

    assert BATCH_TEMP_PREFIX == "_alembic_tmp_"
