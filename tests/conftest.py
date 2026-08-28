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
