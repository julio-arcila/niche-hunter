"""Shared fixtures.

The `no_network` fixture is autouse and non-negotiable: .claude/rules/data.md
forbids live API calls in tests. Any test that reaches for a socket fails with a
message pointing at tests/fixtures/ instead of quietly hitting a real quota.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine

from nh.config import Settings
from nh.db.models import Base
from nh.db.session import make_engine


class NetworkAccessDenied(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*args, **kwargs):
        raise NetworkAccessDenied(
            "tests must not touch the network — record a fixture into "
            "tests/fixtures/<source>/ and replay it with `responses` instead"
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture(autouse=True)
def operator_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the operator's calendar to the suite's DAY.

    `inputs.ballast_active()` decides which definition is in force from the wall clock,
    while every feature test computes against a fixed DAY. Nothing pinned the clock, so
    the whole ballast surface passed by riding it — until 2026-09-15, the morning after
    `BALLAST_SUNSET`, when twelve tests flipped from v3 to v2 with no code change. That is
    the RUNBOOK's "a test's verdict depends on live state" defect, realised on the day it
    could first bite.

    Tests that need the post-sunset world move `BALLAST_SUNSET` relative to DAY, as the
    sunset tests already do. None may read the real date. An explicit `today=` argument
    still wins, as does `pinned_ballast()`.
    """
    from nh.features import inputs
    from tests.conftest_features import DAY

    monkeypatch.setattr(inputs, "operator_today", lambda: DAY)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", yt_api_key="test-key")


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    eng = make_engine(settings)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def backtest_engine(tmp_path) -> Iterator[Engine]:
    """A database whose *name* marks it as the backtest corpus.

    `nh.backtest.load._refuse_live` requires "backtest" in the URL, so this fixture
    is not cosmetic: without it every loader test would hit the guard, and with it
    the guard stays testable against the ordinary `engine` fixture.
    """
    eng = make_engine(Settings(database_url=f"sqlite:///{tmp_path / 'backtest.db'}"))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def engine_b(tmp_path) -> Iterator[Engine]:
    """A second, independent database.

    For differential tests: build the same world twice, differing in one thing, and
    assert a metric answers identically. One engine cannot do that — the difference
    has to be a difference between databases, not a mutation of one.
    """
    eng = make_engine(Settings(database_url=f"sqlite:///{tmp_path / 'test_b.db'}"))
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
