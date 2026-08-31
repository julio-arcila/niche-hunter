#!/usr/bin/env python3
"""Draw the ballast recall sample, per ADR-0050.

    uv run python scripts/draw_recall_sample.py --seed 20260901 --dry-run

ADR-0041 samples *above* the threshold and measures precision. ADR-0047 excludes
whole channels on the strength of the scorer's *rejections*, and ADR-0041 says in
its own text that the rejected stratum is "unsampled by construction" — so the
sample already drawn cannot validate ballast even by passing. This is the missing
instrument, and it is the only one: ballast can err only by omission, and every
possible omission is by construction a lexicon false negative on an excluded row.

**Frame.** Decided-noise rows on ballast channels, in the active clusters —
`is_noise IS TRUE` and `Video.channel_id IN _ballast_channels(cluster)`. Not the
whole below-threshold population: mid-band undecided rows test where the threshold
sits, which nothing in ADR-0042..0049 touched. Measured 2026-08-31: 9,585 rows over
585 channels across ten clusters.

**Two caps, and the second one is the one that matters.** 15 per domain, as
ADR-0041. And **2 per channel**: the claim under test is at channel grain ("this
channel publishes nothing this cluster can read"), so an uncapped row draw is
channel-clustered and its effective n is smaller than it looks. Every domain has
at least 32 rows drawable under the channel cap, so the cap binds the draw, not
the frame.

**The criterion is ADR-0042's, unchanged, both passes.** `relevance` is the
geometric mean of a domain axis and an exposition axis, so a row clears the
threshold only if BOTH fire — which makes a false negative exactly ADR-0042's
`label = 1` (Pass A yes AND Pass B yes). Same instrument, same archetypes, same
`unsure` recording, same title-and-description-only blinding, opposite stratum.

Two files, same split as the exposition draw:

  recall_draw_key_<date>.jsonl        row, domain, video_id, channel_id, relevance.
                                      Do not open it while labelling.
  recall_labelling_<date>.jsonl       row, domain, title, description, and empty
                                      `subject` / `exposition` / `note`.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from datetime import date
from pathlib import Path

import sqlalchemy as sa

from nh.db.models import ClusterMember, NicheSeed, Video
from nh.db.session import get_engine, session_scope

# Imported, never restated: the frame has to be the same set of rows the metric
# removes, and a second copy of the predicate is a second thing to keep in step.
from nh.features.inputs import _ballast_channels

TARGET_N = 100
CAP_DOMAIN = 15
CAP_CHANNEL = 2
MIN_N = 80  # As ADR-0041: below this the draw is postponed, never shrunk.
MIN_DOMAINS = 8


def frame(session) -> dict[str, list[tuple[str, str, float | None, str, str]]]:
    """Eligible rows per active cluster: decided noise on a ballast channel.

    Sorted by `(channel_id, video_id)` so the pool is stable across runs and the
    channel cap walks a deterministic order before the seed shuffles it.
    """
    domains = sorted(session.scalars(sa.select(NicheSeed.slug).where(NicheSeed.active)))
    out: dict[str, list[tuple[str, str, float | None, str, str]]] = {}
    for domain in domains:
        rows = session.execute(
            sa.select(
                Video.channel_id,
                ClusterMember.item_id,
                ClusterMember.relevance,
                Video.title,
                Video.description,
            )
            .join(ClusterMember, ClusterMember.item_id == Video.video_id)
            .where(
                ClusterMember.item_type == "video",
                ClusterMember.cluster_id == domain,
                ClusterMember.is_noise.is_(True),
                Video.channel_id.in_(_ballast_channels(domain)),
            )
            .order_by(Video.channel_id, ClusterMember.item_id)
        ).all()
        out[domain] = [tuple(r) for r in rows]
    return out


def _capacity(rows: list[tuple], cap_channel: int) -> int:
    """How many rows a domain can yield under the per-channel cap."""
    counts = Counter(r[0] for r in rows)
    return sum(min(cap_channel, n) for n in counts.values())


def allocate(pool: dict[str, list], target: int) -> dict[str, int]:
    """Even split, shortfall redistributed round-robin. Pre-registered, deterministic.

    Even because no domain has a prior claim on the test. The redistribution rule is
    written down before the draw rather than improvised after it, for the reason
    ADR-0042 gives about goalposts — with ten domains and a target of 100 it happens
    to be a no-op today (every domain clears 32), and it exists for the day a domain
    is retired mid-week and the draw must still reach n without a judgement call.
    """
    domains = sorted(pool)
    capacity = {d: min(CAP_DOMAIN, _capacity(pool[d], CAP_CHANNEL)) for d in domains}
    base = target // len(domains) if domains else 0
    alloc = {d: min(base, capacity[d]) for d in domains}
    short = target - sum(alloc.values())
    while short > 0:
        headroom = [d for d in domains if alloc[d] < capacity[d]]
        if not headroom:
            break
        for d in headroom:
            if short == 0:
                break
            alloc[d] += 1
            short -= 1
    return alloc


def draw(pool: dict[str, list], seed: int, alloc: dict[str, int]) -> list[dict]:
    rng = random.Random(seed)
    picked: list[dict] = []
    for domain in sorted(pool):  # sorted: the draw must not depend on dict order
        if alloc[domain] <= 0:
            continue
        rows = list(pool[domain])
        rng.shuffle(rows)
        taken: Counter[str] = Counter()
        for channel_id, video_id, relevance, title, description in rows:
            if taken[channel_id] >= CAP_CHANNEL:
                continue
            taken[channel_id] += 1
            picked.append(
                {
                    "domain": domain,
                    "channel_id": channel_id,
                    "video_id": video_id,
                    "relevance": None if relevance is None else round(float(relevance), 4),
                    "title": title,
                    "description": description or "",
                }
            )
            if sum(taken.values()) >= alloc[domain]:
                break
    # Globally shuffled, as the exposition draw: domain-blocked labelling anchors.
    rng.shuffle(picked)
    for n, row in enumerate(picked, start=1):
        row["row"] = n
    return picked


def write(picked: list[dict], out_dir: Path, day: date) -> tuple[Path, Path]:
    key_path = out_dir / f"recall_draw_key_{day}.jsonl"
    lab_path = out_dir / f"recall_labelling_{day}.jsonl"
    key_path.write_text(
        "".join(
            json.dumps(
                {
                    "row": r["row"],
                    "domain": r["domain"],
                    "video_id": r["video_id"],
                    "channel_id": r["channel_id"],
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
    ap.add_argument("--target", type=int, default=TARGET_N)
    ap.add_argument("--out", type=Path, default=Path("reports"))
    ap.add_argument("--day", type=date.fromisoformat, default=date.today())
    ap.add_argument("--dry-run", action="store_true", help="report the frame, write nothing")
    args = ap.parse_args()

    with session_scope(get_engine()) as session:
        pool = frame(session)

    alloc = allocate(pool, args.target)
    total_rows = sum(len(v) for v in pool.values())
    total_ch = len({r[0] for rows in pool.values() for r in rows})
    covered = [d for d in pool if alloc[d] > 0]
    print(f"frame: {total_rows} rows, {total_ch} channels, {len(pool)} domains")
    for domain in sorted(pool):
        chans = len({r[0] for r in pool[domain]})
        print(
            f"  {domain:30} rows={len(pool[domain]):>5} channels={chans:>4} "
            f"cap={_capacity(pool[domain], CAP_CHANNEL):>4} draw={alloc[domain]:>3}"
        )
    if len(covered) < MIN_DOMAINS or sum(alloc.values()) < MIN_N:
        print(f"DRAW POSTPONED: needs >= {MIN_DOMAINS} domains and >= {MIN_N} drawable.")
        return 1

    picked = draw(pool, args.seed, alloc)
    print(f"\ndrawn: {len(picked)} rows, seed {args.seed}")
    per_channel = Counter((r["domain"], r["channel_id"]) for r in picked)
    print(
        f"  distinct channels {len({r['channel_id'] for r in picked})}, "
        f"max rows per channel {max(per_channel.values())}"
    )
    if args.dry_run:
        print("(dry run — nothing written)")
        return 0
    key_path, lab_path = write(picked, args.out, args.day)
    print(f"  key       -> {key_path}")
    print(f"  labelling -> {lab_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
