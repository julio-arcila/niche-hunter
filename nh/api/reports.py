"""The written record: `reports/*.md`, listed and read.

A read layer rather than a page helper, so the rule below is enforced once and testable
without a renderer.

**Markdown only, and that is a safety property rather than a file-type preference.**
`reports/` also holds the validation draws, and `exposition_draw_key_*.jsonl` and
`recall_draw_key_*.jsonl` carry each row's `relevance` — the exact thing ADR-0041's
blinding rule keeps away from a labeller, and ADR-0042 extended into a contamination rule
covering session transcripts. A viewer that globbed the directory would put the answer key
on screen next to the sample. So the glob is `*.md`, `read()` refuses anything else, and a
test asserts no draw file is reachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[2] / "reports"

#: Never served, whatever the extension. Belt and braces beside the `*.md` glob: the two
#: guards fail independently, and the thing being guarded is an evidence standard.
FORBIDDEN_STEMS = ("_draw_key_", "_labelling_")


@dataclass(frozen=True, slots=True)
class ReportLine:
    name: str
    title: str
    day: date | None
    bytes: int


def _title_of(path: Path) -> str:
    """The first `# heading`, or the filename. Read lazily — a listing should not cost a
    full read of forty files."""
    with path.open() as handle:
        for line in handle:
            if line.startswith("# "):
                return line[2:].strip()
            if line.strip():
                break
    return path.stem


def _day_of(path: Path) -> date | None:
    tail = path.stem[-10:]
    try:
        return date.fromisoformat(tail)
    except ValueError:
        return None


def listing(root: Path | None = None) -> list[ReportLine]:
    """Every report, newest dated first, then alphabetically."""
    root = root or REPORTS
    if not root.is_dir():
        return []
    rows = [
        ReportLine(p.name, _title_of(p), _day_of(p), p.stat().st_size)
        for p in sorted(root.glob("*.md"))
        if not any(stem in p.name for stem in FORBIDDEN_STEMS)
    ]
    return sorted(rows, key=lambda r: (r.day is None, -(r.day.toordinal() if r.day else 0), r.name))


def read(name: str, root: Path | None = None) -> str | None:
    """One report's text, or `None` if it is not a servable report.

    Resolved and re-checked against the directory rather than joined and trusted: `name`
    reaches this from a page, and `../../.env` is a path a join would happily build.
    """
    root = (root or REPORTS).resolve()
    if any(stem in name for stem in FORBIDDEN_STEMS) or not name.endswith(".md"):
        return None
    path = (root / name).resolve()
    if path.parent != root or not path.is_file():
        return None
    return path.read_text()
