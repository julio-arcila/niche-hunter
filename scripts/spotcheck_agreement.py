"""Compare an independent spot-check against the stored labels.

Run after filling in `label` in reports/spotcheck_50.jsonl:

    uv run python scripts/spotcheck_agreement.py reports/spotcheck_50.jsonl

Prints raw agreement and Cohen's kappa. Kappa matters more than the raw rate here:
the base rate is ~28%, so two labellers who both said "no" to everything would
agree 72% of the time and have learned nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import sqlalchemy as sa

from nh.db.models import RelevanceLabel
from nh.db.session import session_scope


def main(path: Path) -> int:
    with session_scope() as session:
        mine = dict(session.execute(sa.select(RelevanceLabel.video_id, RelevanceLabel.label)).all())
    pairs = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("label") is None or row["video_id"] not in mine:
            continue
        pairs.append((bool(mine[row["video_id"]]), bool(row["label"])))
    if not pairs:
        print("no overlapping labels — fill in the `label` field first")
        return 1

    n = len(pairs)
    agree = sum(1 for a, b in pairs if a == b)
    both = sum(1 for a, b in pairs if a and b)
    neither = sum(1 for a, b in pairs if not a and not b)
    p_mine = sum(1 for a, _ in pairs if a) / n
    p_yours = sum(1 for _, b in pairs if b) / n
    expected = p_mine * p_yours + (1 - p_mine) * (1 - p_yours)
    observed = agree / n
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0

    print(f"n = {n}")
    print(f"raw agreement   {observed:.1%}  ({agree}/{n})")
    print(f"  both on-niche      {both}")
    print(f"  both off-niche     {neither}")
    print(f"  disagreed          {n - agree}")
    print(f"positive rate   mine {p_mine:.1%}   yours {p_yours:.1%}")
    print(f"Cohen's kappa   {kappa:.3f}")
    print(
        "\ninterpretation: <0.40 poor, 0.40-0.60 moderate, 0.60-0.80 substantial,\n"
        ">0.80 almost perfect. Below 0.60 and the 0.781 precision in\n"
        "reports/relevance_2026-08-27.md should be withdrawn, not caveated."
    )
    if n - agree:
        print("\ndisagreements:")
        for line in path.read_text().splitlines():
            row = json.loads(line) if line.strip() else None
            if not row or row.get("label") is None or row["video_id"] not in mine:
                continue
            if bool(mine[row["video_id"]]) != bool(row["label"]):
                verdict = (
                    "I said ON, you said OFF"
                    if mine[row["video_id"]]
                    else "I said OFF, you said ON"
                )
                print(f"  [{row['niche'][:12]:<12}] {verdict}: {row['title'][:56]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
