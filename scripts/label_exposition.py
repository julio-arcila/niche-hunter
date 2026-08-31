#!/usr/bin/env python3
"""Label the pre-registered exposition sample, one row at a time.

    uv run python scripts/label_exposition.py            # label
    uv run python scripts/label_exposition.py --status   # progress only

The sample is fixed by ADR-0041 and drawn in reports/exposition_draw_2026-08-29.md.
This tool exists to make labelling fast; it must not make it different. So it
deliberately shows **only** what the drawn file carries — domain, title,
description — and never relevance, the band, or `detail.matched`. A labeller who
sees the terms that fired is scoring the lexicon's reasoning rather than the
video, which is the machine-label problem wearing a human face.

Rows are presented in file order, which is globally shuffled on purpose:
domain-blocked labelling anchors, and after eight straight yeses the ninth is not
an independent judgement.

**A model must not run this.** The whole objection ADR-0041 answers is that the
existing evidence is 107 machine labels from one model family, and agreement
between two raters of that family cannot detect a bias they share.
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

SAMPLE = Path("reports/exposition_labelling_2026-08-29.jsonl")

CRITERION = """\
Label 1 only when BOTH hold:
  1. SUBJECT     — substantially *about* the named domain. Not merely using its
                   vocabulary, not mentioning it in passing.
  2. EXPOSITION  — it explains, analyses, teaches, or argues a position. A bare
                   event report, a vlog, a promotion, or entertainment that
                   happens to touch the subject is 0 even when the subject is right.
Otherwise 0.  Watch for marketing that uses the vocabulary fluently — that is the
archetypal false positive on record."""

KEYS = "  [1] on-niche   [0] off-niche   [u] unjudgeable (scores 0)   [s] skip   [b] back   [q] save & quit"


def _getch() -> str:
    """One keystroke, no Enter. Falls back to line input when stdin is not a tty."""
    if not sys.stdin.isatty():
        return (sys.stdin.readline().strip() or "\n")[:1]
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def save(path: Path, rows: list[dict]) -> None:
    """Atomic, and called after every keystroke: a crash must never cost work.

    Written to a sibling temp file and renamed, so the sample is never observed
    half-written — the same reason the collectors upsert rather than rewrite.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(path)


def counts(rows: list[dict]) -> tuple[int, int, int]:
    done = sum(1 for r in rows if r.get("label") in (0, 1))
    ones = sum(1 for r in rows if r.get("label") == 1)
    unjudgeable = sum(1 for r in rows if r.get("note") == "unjudgeable")
    return done, ones, unjudgeable


def render(rows: list[dict], i: int) -> None:
    width = min(shutil.get_terminal_size((100, 40)).columns, 100)
    done, _, _ = counts(rows)
    row = rows[i]
    print("\033[2J\033[H", end="")
    print("=" * width)
    print(
        f"  row {row['row']} of {len(rows)}      labelled {done}/{len(rows)}      "
        f"file position {i + 1}"
    )
    print("=" * width)
    print(f"\n  DOMAIN: {row['domain']}\n")
    for line in textwrap.wrap(row["title"], width - 4):
        print(f"  \033[1m{line}\033[0m")
    print()
    for line in textwrap.wrap(str(row.get("description") or ""), width - 4)[:14]:
        print(f"  {line}")
    print("\n" + "-" * width)
    print(CRITERION)
    print("-" * width)
    existing = row.get("label")
    if existing in (0, 1):
        print(
            f"  (currently labelled {existing}"
            f"{' — unjudgeable' if row.get('note') == 'unjudgeable' else ''})"
        )
    print(KEYS)


def report(rows: list[dict]) -> None:
    done, ones, unjudgeable = counts(rows)
    print(f"\nlabelled {done}/{len(rows)}   ones {ones}   unjudgeable {unjudgeable}")
    if done < len(rows):
        print(f"{len(rows) - done} still unlabelled — rerun to continue where you left off.")
        return
    print("\nComplete. Hand back to Claude to compute the Wilson interval and write the")
    print("result report. The bar is a 95% lower bound >= 0.70, i.e. 79 of 99 (ADR-0041).")
    if unjudgeable > len(rows) * 0.10:
        print(f"NOTE: unjudgeable is {unjudgeable}/{len(rows)} (>10%) — the draw says that is")
        print("itself a finding and belongs in the result report.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true", help="print progress and exit")
    ap.add_argument("--file", type=Path, default=SAMPLE)
    args = ap.parse_args()

    if not args.file.exists():
        print(f"not found: {args.file}", file=sys.stderr)
        return 1
    rows = load(args.file)
    if args.status:
        report(rows)
        return 0

    # Resume at the first unlabelled row rather than the top.
    i = next((n for n, r in enumerate(rows) if r.get("label") not in (0, 1)), 0)
    while 0 <= i < len(rows):
        render(rows, i)
        key = _getch().lower()
        if key == "q":
            break
        if key == "b":
            i = max(0, i - 1)
            continue
        if key == "s":
            i += 1
            continue
        if key in ("1", "0", "u"):
            rows[i]["label"] = 1 if key == "1" else 0
            rows[i]["note"] = "unjudgeable" if key == "u" else rows[i].get("note", "")
            save(args.file, rows)
            i += 1
        # any other key: redraw, cheaper than an error message

    save(args.file, rows)
    report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
