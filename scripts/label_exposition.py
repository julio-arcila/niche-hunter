#!/usr/bin/env python3
"""Label the exposition validation sample, one question at a time (ADR-0042).

    uv run python scripts/label_exposition.py                    # next unfinished pass
    uv run python scripts/label_exposition.py --pass subject
    uv run python scripts/label_exposition.py --status
    uv run python scripts/label_exposition.py --sample recall    # ADR-0050's sample

**Two passes, not one compound judgement.** ADR-0041 asked whether a video was
about the domain AND explanatory in a single call, and a labeller unsure which
half was failing could answer neither. Pass A asks only about SUBJECT, pass B only
about EXPOSITION, each over the whole sample. `label = 1` iff both are yes.

The cost is a second read; the gains are that each pass is one consistent question
— which is what calibration needs — and that a failure becomes diagnosable, since
subject-failures and exposition-failures say different things about the lexicon.

Shows **only** domain, title and description. Never relevance, the band, or
`detail.matched`: a labeller who sees the terms that fired is scoring the lexicon's
reasoning rather than the video.

**Two samples, one criterion (ADR-0050).** `--sample exposition` is ADR-0041's draw
from ABOVE the threshold and measures precision. `--sample recall` is ADR-0050's draw
of decided-noise rows on ballast channels and measures the false negative rate there —
the stratum ADR-0041 says it cannot reach, and the only thing that can validate
ADR-0047. The questions, the archetypes and the `unsure` rule are identical; only the
frame differs, so the standard in the labeller's head does not have to change between
them. Label them in either order, ideally in one sitting.

**A model must not run this.** The objection ADR-0041 answers is that the existing
evidence is 107 machine labels from one model family, and agreement between two
raters of that family cannot detect a bias they share. Relatedly: do not read the
2026-08-30 session transcript before labelling — it contains a model's row-by-row
judgements of the retired sample, drawn from this same frame.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import termios
import textwrap
import tty
from pathlib import Path

#: The two samples this tool labels, and the order they are offered in. Both use the
#: SAME ADR-0042 criterion and the same two passes, which is why one tool serves both:
#: `relevance` is the geometric mean of a domain axis and an exposition axis, so a row
#: clears the threshold iff both passes are yes — and a row below it fails iff at least
#: one is no. `exposition` samples ABOVE the threshold and measures precision (ADR-0041);
#: `recall` samples decided-noise rows on ballast channels and measures the lexicon's
#: false negative rate there (ADR-0050). Opposite strata, one instrument.
SAMPLES = {
    "exposition": "exposition_labelling_*.jsonl",
    "recall": "recall_labelling_*.jsonl",
}


def _newest_sample(kind: str = "exposition") -> Path | None:
    """The most recent draw of `kind`, by the date in its filename.

    Hardcoded to one date until 2026-08-31, which was a trap: two samples had been
    drawn and spent by then, and a stale default silently resumes a spent file
    rather than starting the fresh one. Filenames are ISO-dated, so lexical max is
    chronological max.

    Keyed on kind rather than globbing both, added with ADR-0050. A single glob over
    two samples would resolve by date, so drawing one would silently redirect the
    other's `--status` and its next unfinished pass — and the two answer different
    questions about the same lexicon. Which sample is being labelled is a decision,
    not something a filename sort should make.
    """
    found = sorted(Path("reports").glob(SAMPLES[kind]))
    return found[-1] if found else None


SAMPLE = _newest_sample()
VALUES = {"y": 1, "n": 0, "?": "unsure"}

PASSES = {
    "subject": {
        "order": 1,
        "question": "Is this video substantially ABOUT the named domain?",
        "card": """\
  YES  a lecture on the domain's actual subject matter
       exam-prep or coursework whose syllabus topic IS the domain
       a video in any language — language is not the question here
  NO   the domain's vocabulary used as metaphor or decoration
       a topic merely adjacent to it (corporate finance under macro-economy)
       explaining what science FOUND, under philosophy-of-science
       a scientist's biography — that is history of science""",
    },
    "exposition": {
        "order": 2,
        "question": "Does it EXPLAIN, ANALYSE, TEACH, or ARGUE a position?",
        "card": """\
  YES  explains a mechanism; teaches a method; argues a thesis
       analyses a case, including a market or a conflict
  NO   reports a thing happened without saying why it matters
       a personal story with no general lesson
       an advert or affiliate pitch, however fluent the vocabulary
       a listicle or quote compilation
       a LIVE PERFORMANCE — trading live, or channelling, is doing not explaining
       a roadmap for a series that has not happened yet""",
    },
}
KEYS = "  [y] yes   [n] no   [?] unsure   [s] skip   [b] back   [q] save & quit"


def _getch() -> str:
    """One keystroke, no Enter. Falls back to line input when stdin is not a tty.

    End of input reads as "q" rather than as an unrecognised key. Without that the
    loop redraws forever on an exhausted pipe and on ctrl-D — an infinite spin that
    only shows up when the tool is driven non-interactively, which is exactly how
    it gets tested.
    """
    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        return "q" if line == "" else (line.strip() or "\n")[:1]
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1) or "q"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def save(path: Path, rows: list[dict]) -> None:
    """Atomic, and called after every keystroke: a crash must never cost work."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(path)


def done_in(rows: list[dict], field: str) -> int:
    return sum(1 for r in rows if r.get(field) is not None)


def render(rows: list[dict], i: int, field: str) -> None:
    width = min(shutil.get_terminal_size((100, 40)).columns, 100)
    spec, row = PASSES[field], rows[i]
    print("\033[2J\033[H", end="")
    print("=" * width)
    print(
        f"  PASS {spec['order']} of 2 — {field.upper()}        "
        f"{done_in(rows, field)}/{len(rows)} done        row {row['row']}"
    )
    print(f"  {spec['question']}")
    print("=" * width)
    print(f"\n  DOMAIN: {row['domain']}\n")
    for line in textwrap.wrap(row["title"], width - 4):
        print(f"  \033[1m{line}\033[0m")
    print()
    for line in textwrap.wrap(str(row.get("description") or ""), width - 4)[:12]:
        print(f"  {line}")
    print("\n" + "-" * width)
    print(spec["card"])
    print("-" * width)
    if row.get(field) is not None:
        print(f"  (currently {row[field]!r})")
    print(KEYS)


def report(rows: list[dict]) -> None:
    n = len(rows)
    subj, expo = done_in(rows, "subject"), done_in(rows, "exposition")
    print(f"\npass 1 SUBJECT    {subj}/{n}")
    print(f"pass 2 EXPOSITION {expo}/{n}")
    if subj < n or expo < n:
        print("\nRerun to continue; each pass resumes where you left off.")
        return
    ones = sum(1 for r in rows if r["subject"] == 1 and r["exposition"] == 1)
    unsure = {f: sum(1 for r in rows if r[f] == "unsure") for f in ("subject", "exposition")}
    print(f"\nboth-yes (label 1): {ones}/{n}")
    print(f"unsure: subject {unsure['subject']}, exposition {unsure['exposition']}")
    print("\nComplete. Hand back to compute the Wilson interval and write the result")
    print("report. The bar is a 95% lower bound >= 0.70, unchanged (ADR-0042).")
    for field, count in unsure.items():
        if count > n * 0.10:
            print(f"NOTE: {field} unsure is {count}/{n} (>10%) — itself a finding, per ADR-0041.")


def run_pass(rows: list[dict], field: str, path: Path) -> None:
    i = next((n for n, r in enumerate(rows) if r.get(field) is None), 0)
    while 0 <= i < len(rows):
        render(rows, i, field)
        key = _getch().lower()
        if key == "q":
            break
        if key == "b":
            i = max(0, i - 1)
        elif key == "s":
            i += 1
        elif key in VALUES:
            rows[i][field] = VALUES[key]
            save(path, rows)
            i += 1
    save(path, rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pass", dest="which", choices=sorted(PASSES), default=None)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--sample", choices=sorted(SAMPLES), default="exposition")
    ap.add_argument("--file", type=Path, default=None)
    args = ap.parse_args()

    target = args.file or _newest_sample(args.sample)
    if target is None:
        print(f"no {args.sample} sample drawn yet", file=sys.stderr)
        return 1
    args.file = target
    if not args.file.exists():
        print(f"not found: {args.file}", file=sys.stderr)
        return 1
    print(f"sample: {args.file}\n")
    rows = load(args.file)
    if args.status:
        report(rows)
        return 0

    which = args.which
    if which is None:  # default to the first pass that is not finished
        which = next(
            (
                f
                for f in sorted(PASSES, key=lambda k: PASSES[k]["order"])
                if done_in(rows, f) < len(rows)
            ),
            None,
        )
        if which is None:
            report(rows)
            return 0
    run_pass(rows, which, args.file)
    report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
