"""The reports viewer's read layer, and the one thing it must never serve.

`reports/` holds both the written record and the validation draws. The draw key files
carry each row's `relevance`, which is exactly what ADR-0041's blinding rule keeps away
from a labeller and what ADR-0042 turned into a contamination rule. A viewer that globbed
the directory would put the answer key on screen beside the sample, so the exclusion is
tested from two directions — by extension and by name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nh.api import reports

REAL = Path(__file__).resolve().parents[1] / "reports"


@pytest.fixture
def folder(tmp_path):
    (tmp_path / "backtest_2026-08-28.md").write_text("# Gate E — FAIL\n\nrho 0.091\n")
    (tmp_path / "supply_audit_2026-08-30.md").write_text("# Supply audit\n")
    (tmp_path / "no_heading.md").write_text("just text\n")
    (tmp_path / "exposition_draw_key_2026-08-31.jsonl").write_text('{"relevance": 0.9}\n')
    (tmp_path / "exposition_labelling_2026-08-31.jsonl").write_text('{"row": 1}\n')
    (tmp_path / "secret.env").write_text("TOKEN=x\n")
    return tmp_path


def test_it_lists_the_reports_newest_first(folder):
    rows = reports.listing(folder)
    assert [r.name for r in rows] == [
        "supply_audit_2026-08-30.md",
        "backtest_2026-08-28.md",
        "no_heading.md",
    ]
    assert rows[1].title == "Gate E — FAIL", "the first heading, not the filename"
    assert rows[2].title == "no_heading", "and the filename when there is no heading"


def test_a_draw_file_is_not_listed(folder):
    names = {r.name for r in reports.listing(folder)}
    assert not any("draw_key" in n or "labelling" in n for n in names)


def test_a_draw_file_cannot_be_read_even_by_name(folder):
    """The listing filter is not the guard — someone can pass a name directly, and a page
    that renders whatever it is handed is one refactor away from doing so."""
    assert reports.read("exposition_draw_key_2026-08-31.jsonl", folder) is None
    assert reports.read("exposition_labelling_2026-08-31.jsonl", folder) is None


def test_only_markdown_is_served(folder):
    assert reports.read("secret.env", folder) is None
    assert reports.read("backtest_2026-08-28.md", folder).startswith("# Gate E")


@pytest.mark.parametrize(
    "name",
    ["../.env", "../../etc/passwd", "subdir/../../.env", "/etc/passwd"],
)
def test_a_path_cannot_escape_the_reports_directory(folder, name):
    """`name` reaches this from a page. `root / name` would happily build `../../.env`, so
    the path is resolved and its parent re-checked rather than joined and trusted."""
    assert reports.read(name, folder) is None


def test_a_missing_report_is_none_not_an_exception(folder):
    assert reports.read("never_written.md", folder) is None


def test_the_real_directory_serves_only_markdown_and_hides_every_draw():
    """Against the actual `reports/`, because that is the directory the page reads.

    Measured 2026-08-31: 23 markdown files, and the eight draw and labelling `.jsonl`
    files are none of them.
    """
    listed = {r.name for r in reports.listing()}
    on_disk = {p.name for p in REAL.glob("*.md")}

    assert listed == on_disk, "no markdown report is silently hidden"
    assert all(name.endswith(".md") for name in listed)
    for draw in REAL.glob("*_draw_key_*.jsonl"):
        assert draw.name not in listed
        assert reports.read(draw.name) is None
