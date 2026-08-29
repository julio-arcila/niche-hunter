"""Reproduce the topic-domain second-axis evaluation in reports/relevance_axis_topic_2026-08-28.md.

Committed because that report cited held-out figures for a marker list that lived only in
a session scratchpad. A measurement whose input is not in the repo cannot be checked, and
this repo's reports exist to be checkable. Run:

    uv run python scripts/eval_topic_axis.py

Every marker below traces to a clause of `reports/labelling_criterion_topic_domains_v4.md`,
which was written before any row was labelled -- so the labelled rows are a test set, not
a training set. Nothing here was chosen by inspecting labels.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from nh.clustering.lexicon import EXPOSITION, LEXICONS, weights
from nh.clustering.relevance import _axis

REPORTS = Path(__file__).resolve().parent.parent / "reports"

#: criterion decisions 3, 9, 10, 13 -- selling, tools, signals, branded products
SELLING: tuple[str, ...] = (
    "profit",
    "profitable",
    "made $",
    "$",
    "income",
    "signals",
    "signal",
    "free course",
    "join my",
    "link in bio",
    "subscribe",
    "discount",
    "promo",
    "sponsor",
    "buy now",
    "get rich",
    "millionaire",
    "secret",
    "exposed",
    "shocking",
    "insane",
    "crazy",
)
TOOLING: tuple[str, ...] = (
    "tradingview",
    "setup",
    "tutorial",
    "install",
    "bot",
    "app review",
    "software review",
    "how to use",
)
TEASE: tuple[str, ...] = (
    "what happens next",
    "you won't believe",
    "this changes everything",
    "must watch",
    "gone wrong",
)


def hit(text: str, terms: tuple[str, ...]) -> int:
    haystack = f" {text.lower()} "
    return sum(1 for m in terms if m in haystack)


def load(label_file: str) -> list[dict]:
    rows = {
        int(r["row"]): r
        for r in csv.DictReader(
            (REPORTS / "relevance_axis_sample_2026-08-28.csv").open(encoding="utf-8")
        )
    }
    w = weights(LEXICONS)
    out = []
    for line in (REPORTS / label_file).open(encoding="utf-8"):
        lab = json.loads(line)
        if lab.get("underdetermined") or lab["label"] not in (0, 1):
            continue
        r = rows[int(lab["row"])]
        dom, _ = _axis(r["title"], "", w[r["domain"]])
        out.append(
            {
                "y": int(lab["label"]),
                "dom": dom,
                "exp": hit(r["title"], EXPOSITION),
                "neg": hit(r["title"], SELLING) + hit(r["title"], TOOLING) + hit(r["title"], TEASE),
            }
        )
    return out


CANDIDATES = {
    "A domain alone (baseline)": lambda d: d["dom"],
    "B domain x exposition": lambda d: d["dom"] * (1 if d["exp"] else 0),
    "C domain, neg filter": lambda d: 0.0 if d["neg"] else d["dom"],
    "D B + neg filter": lambda d: 0.0 if d["neg"] else d["dom"] * (1 if d["exp"] else 0),
}
THRESHOLDS = [i / 20 for i in range(20)]


def prf(pred: list[bool], data: list[dict]) -> tuple[float, float, float]:
    tp = sum(1 for p, d in zip(pred, data, strict=True) if p and d["y"])
    fp = sum(1 for p, d in zip(pred, data, strict=True) if p and not d["y"])
    fn = sum(1 for p, d in zip(pred, data, strict=True) if not p and d["y"])
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return prec, rec, (2 * prec * rec / (prec + rec) if prec + rec else 0.0)


def evaluate(data: list[dict], splits: int = 200, seed: int = 20260828) -> None:
    """Each candidate scored on a random half after its threshold is chosen on the other."""
    rng = random.Random(seed)
    base = sum(d["y"] for d in data) / len(data)
    print(f"  n={len(data)}  base rate {base:.3f}")
    for name, fn in CANDIDATES.items():
        rng = random.Random(seed)
        acc = []
        for _ in range(splits):
            idx = list(range(len(data)))
            rng.shuffle(idx)
            fit = [data[i] for i in idx[: len(idx) // 2]]
            held = [data[i] for i in idx[len(idx) // 2 :]]
            best = max(THRESHOLDS, key=lambda t: prf([fn(d) > t for d in fit], fit)[2])
            acc.append(prf([fn(d) > best for d in held], held))
        p = sum(a[0] for a in acc) / len(acc)
        r = sum(a[1] for a in acc) / len(acc)
        f = sum(a[2] for a in acc) / len(acc)
        print(f"    {name:28} P {p:.3f}  R {r:.3f}  F1 {f:.3f}")


if __name__ == "__main__":
    for label_file in (
        "relevance_axis_fable_v4_2026-08-28.jsonl",
        "relevance_axis_fable_v2_2026-08-28.jsonl",
    ):
        print(f"\n{label_file}")
        evaluate(load(label_file))
