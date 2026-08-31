#!/usr/bin/env python3
"""Draw the exposition validation sample, per ADR-0042.

    uv run python scripts/draw_exposition_sample.py --seed 20260830

The 2026-08-29 draw was done inline and only its OUTPUT was recorded, so the draw
itself could not be re-run and checked. This script exists so the replacement is
reproducible from the seed alone: same seed and same frame give the same rows.

Two files, and the split is the point (ADR-0041, kept by ADR-0042):

  <stem>_key_<date>.jsonl        row, domain, video_id, relevance — what was drawn.
                                 Do not open it while labelling.
  <stem>_labelling_<date>.jsonl  row, domain, title, description, and empty
                                 `subject` / `exposition` / `note`. No relevance,
                                 no band, no detail.matched: a labeller who sees
                                 the terms that fired is scoring the lexicon's
                                 reasoning rather than the video.

ADR-0042 replaced ADR-0041's single compound judgement with two passes, so the
labelling file carries two empty fields rather than one.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date
from pathlib import Path

import sqlalchemy as sa

from nh.clustering.lexicon import AXES
from nh.clustering.relevance import RELEVANCE_HIGH
from nh.db.models import ClusterMember, Video
from nh.db.session import get_engine, session_scope

PER_DOMAIN = 9  # 9 x 11 domains = 99; target 100, and an even split is what the
#                 per-domain cap and the coverage rule jointly imply (ADR-0041).
CAP = 15  # ADR-0041: no head-start domain may become the whole test.
MIN_N = 80  # Below this the draw is postponed, never shrunk.
MIN_DOMAINS = 6


def frame(session) -> dict[str, list[tuple[str, float, str, str]]]:
    """Eligible rows per exposition domain, sorted by video_id so the draw is stable."""
    domains = sorted(slug for slug, axis in AXES.items() if axis == "exposition")
    rows = session.execute(
        sa.select(
            ClusterMember.cluster_id,
            ClusterMember.item_id,
            ClusterMember.relevance,
            Video.title,
            Video.description,
        )
        .join(Video, Video.video_id == ClusterMember.item_id)
        .where(
            ClusterMember.item_type == "video",
            ClusterMember.relevance >= RELEVANCE_HIGH,
            ClusterMember.cluster_id.in_(domains),
        )
        .order_by(ClusterMember.cluster_id, ClusterMember.item_id)
    ).all()
    out: dict[str, list[tuple[str, float, str, str]]] = {d: [] for d in domains}
    for cluster_id, video_id, relevance, title, description in rows:
        out[cluster_id].append((video_id, relevance, title, description))
    return out


def draw(pool: dict[str, list], seed: int, per_domain: int) -> list[dict]:
    rng = random.Random(seed)
    picked: list[dict] = []
    for domain in sorted(pool):  # sorted: the draw must not depend on dict order
        eligible = pool[domain]
        take = min(per_domain, CAP, len(eligible))
        for video_id, relevance, title, description in rng.sample(eligible, take):
            picked.append(
                {
                    "domain": domain,
                    "video_id": video_id,
                    "relevance": round(float(relevance), 4),
                    "title": title,
                    "description": description,
                }
            )
    # Globally shuffled: domain-blocked labelling anchors, and after eight straight
    # yeses the ninth is not an independent judgement.
    rng.shuffle(picked)
    for n, row in enumerate(picked, start=1):
        row["row"] = n
    return picked


def write(picked: list[dict], out_dir: Path, day: date) -> tuple[Path, Path]:
    key_path = out_dir / f"exposition_draw_key_{day}.jsonl"
    lab_path = out_dir / f"exposition_labelling_{day}.jsonl"
    key_path.write_text(
        "".join(
            json.dumps(
                {
                    "row": r["row"],
                    "domain": r["domain"],
                    "video_id": r["video_id"],
                    "relevance": r["relevance"],
                },
                ensure_ascii=False,
            )
            + "\n"
            for r in picked
        )
    )
    lab_path.write_text(
        "".join(
            json.dumps(
                {
                    "row": r["row"],
                    "domain": r["domain"],
                    "title": r["title"],
                    "description": r["description"],
                    "subject": None,
                    "exposition": None,
                    "note": "",
                },
                ensure_ascii=False,
            )
            + "\n"
            for r in picked
        )
    )
    return key_path, lab_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--per-domain", type=int, default=PER_DOMAIN)
    ap.add_argument("--out", type=Path, default=Path("reports"))
    ap.add_argument("--day", type=date.fromisoformat, default=date.today())
    ap.add_argument("--dry-run", action="store_true", help="report the frame, write nothing")
    args = ap.parse_args()

    with session_scope(get_engine()) as session:
        pool = frame(session)

    covered = [d for d, rows in pool.items() if len(rows) >= 1]
    drawable = sum(min(CAP, len(rows)) for rows in pool.values())
    print(
        f"frame: {sum(len(v) for v in pool.values())} eligible rows, "
        f"{len(covered)} domains, capped draw {drawable}"
    )
    for domain in sorted(pool):
        print(f"  {domain:30} {len(pool[domain]):>6}")
    if len(covered) < MIN_DOMAINS or drawable < MIN_N:
        print(f"DRAW POSTPONED: needs >= {MIN_DOMAINS} domains and >= {MIN_N} drawable.")
        return 1

    picked = draw(pool, args.seed, args.per_domain)
    print(f"\ndrawn: {len(picked)} rows, seed {args.seed}")
    if args.dry_run:
        print("(dry run — nothing written)")
        return 0
    key_path, lab_path = write(picked, args.out, args.day)
    print(f"  key       -> {key_path}")
    print(f"  labelling -> {lab_path}")
    rels = sorted(r["relevance"] for r in picked)
    print(f"  relevance span {rels[0]:.3f} - {rels[-1]:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
