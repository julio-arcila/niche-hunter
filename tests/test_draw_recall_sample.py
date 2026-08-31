"""The recall draw's invariants (ADR-0050), pinned so they cannot quietly lapse.

There is no test for the exposition draw and this is not that test: what is pinned
here is the part of ADR-0050 that a later edit could break without anyone noticing —
the per-channel cap, determinism from the seed alone, and the fact that the labelling
file carries no signal from the scorer. The frame query itself is exercised against
the live corpus by `--dry-run`, not here; `tests/conftest.py` blocks sockets and the
database this draws from is not a fixture.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "draw_recall_sample.py"


def _module():
    spec = importlib.util.spec_from_file_location("draw_recall_sample", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def draw_mod():
    return _module()


def _pool(domains: int, channels: int, per_channel: int) -> dict[str, list]:
    """A synthetic frame: `channels` channels per domain, `per_channel` rows each."""
    return {
        f"d{d}": [
            (f"d{d}c{c}", f"d{d}c{c}v{v}", 0.0, f"title {d}-{c}-{v}", "desc")
            for c in range(channels)
            for v in range(per_channel)
        ]
        for d in range(domains)
    }


def test_channel_cap_holds(draw_mod):
    """Two rows per channel, however many that channel has in the frame.

    Five channels per domain against an allocation of ten forces the cap to be the
    binding constraint: the only way to reach 100 is exactly two from every channel.
    An earlier version of this used twenty channels per domain, where a capless draw
    can satisfy `<= 2` by luck — it passed with `CAP_CHANNEL` mutated to 999, which
    makes it a test of nothing.
    """
    pool = _pool(domains=10, channels=5, per_channel=50)
    alloc = draw_mod.allocate(pool, 100)
    picked = draw_mod.draw(pool, seed=20260901, alloc=alloc)

    assert len(picked) == 100
    counts: dict[tuple[str, str], int] = {}
    for row in picked:
        key = (row["domain"], row["channel_id"])
        counts[key] = counts.get(key, 0) + 1
    assert len(counts) == 50  # every channel in the frame, none skipped
    assert set(counts.values()) == {draw_mod.CAP_CHANNEL}


def test_channel_cap_binds_when_one_channel_owns_the_domain(draw_mod):
    """The cap must bite hardest exactly where the frame is most concentrated.

    One channel with 500 rows would otherwise supply a whole domain's allocation and
    make the effective n a tenth of the printed one — the failure the cap exists for.
    """
    pool = _pool(domains=2, channels=1, per_channel=500)
    alloc = draw_mod.allocate(pool, 100)
    picked = draw_mod.draw(pool, seed=1, alloc=alloc)
    assert len(picked) == 4  # 2 domains x 1 channel x cap 2 — short of target, not over
    assert alloc == {"d0": 2, "d1": 2}


def test_draw_is_reproducible_from_the_seed(draw_mod):
    pool = _pool(domains=10, channels=20, per_channel=5)
    alloc = draw_mod.allocate(pool, 100)
    first = draw_mod.draw(pool, seed=20260901, alloc=alloc)
    second = draw_mod.draw(pool, seed=20260901, alloc=alloc)
    assert [r["video_id"] for r in first] == [r["video_id"] for r in second]

    other = draw_mod.draw(pool, seed=20260902, alloc=alloc)
    assert [r["video_id"] for r in first] != [r["video_id"] for r in other]


def test_pool_order_does_not_change_the_draw(draw_mod):
    """`sorted(pool)` is load-bearing: dict order must not reach the sample."""
    pool = _pool(domains=6, channels=10, per_channel=4)
    reversed_pool = dict(reversed(list(pool.items())))
    alloc = draw_mod.allocate(pool, 60)
    a = draw_mod.draw(pool, seed=7, alloc=alloc)
    b = draw_mod.draw(reversed_pool, seed=7, alloc=alloc)
    assert sorted(r["video_id"] for r in a) == sorted(r["video_id"] for r in b)


def test_allocation_redistributes_a_shortfall(draw_mod):
    """A thin domain releases its shortfall; the rest absorb it up to the domain cap."""
    pool = _pool(domains=4, channels=20, per_channel=5)
    pool["d0"] = pool["d0"][:2]  # one channel, two rows -> capacity 2
    alloc = draw_mod.allocate(pool, 40)
    assert alloc["d0"] == 2
    assert sum(alloc.values()) == 40
    assert max(alloc.values()) <= draw_mod.CAP_DOMAIN


def test_allocation_never_exceeds_the_domain_cap(draw_mod):
    """Even when the target could be met by one fat domain."""
    pool = _pool(domains=2, channels=200, per_channel=5)
    alloc = draw_mod.allocate(pool, 100)
    assert max(alloc.values()) == draw_mod.CAP_DOMAIN
    assert sum(alloc.values()) == 2 * draw_mod.CAP_DOMAIN  # short of 100, and says so


def test_labelling_file_carries_no_signal_from_the_scorer(draw_mod, tmp_path):
    """The blinding rule, as a file assertion rather than a promise in a docstring."""
    pool = _pool(domains=10, channels=20, per_channel=5)
    picked = draw_mod.draw(pool, seed=20260901, alloc=draw_mod.allocate(pool, 100))
    from datetime import date

    key_path, lab_path = draw_mod.write(picked, tmp_path, date(2026, 8, 31))

    lab = [json.loads(line) for line in lab_path.read_text().splitlines()]
    assert len(lab) == 100
    for row in lab:
        assert set(row) == {
            "row",
            "domain",
            "title",
            "description",
            "subject",
            "exposition",
            "note",
        }
        assert row["subject"] is None and row["exposition"] is None
    assert [r["row"] for r in lab] == list(range(1, 101))

    key = [json.loads(line) for line in key_path.read_text().splitlines()]
    assert {k["row"] for k in key} == {r["row"] for r in lab}
    assert all("relevance" in k and "channel_id" in k for k in key)
