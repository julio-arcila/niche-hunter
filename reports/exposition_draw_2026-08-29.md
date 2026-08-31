# Exposition axis — the drawn sample, and the criterion

Executes the draw pre-registered in **ADR-0041**. Written **before any label exists**.
Everything here is fixed; a change is a new ADR and a re-label.

## The draw

Condition met on 2026-08-29 after the nightly's clustering phase: **11 of 11** exposition
domains carry above-threshold videos (required ≥ 6), for a capped draw of 165 (required
≥ 80).

| parameter | value | why |
|---|---|---|
| frame | `cluster_members`, `item_type='video'`, `relevance >= 0.55`, cluster family `exposition` | ADR-0041 |
| n | **99** | 9 × 11 domains. Target was 100; an even allocation across 11 is what the cap and the coverage rule jointly imply, and manufacturing a 100th row needs an arbitrary tie-break. 99 ≥ the pre-registered minimum of 80. |
| per domain | 9 | under the cap of 15, so no head-start domain (`trading` 1,374 eligible) dominates a thin one (`anthropocene-anthropology` 146) |
| seed | `20260829` | fixed, recorded, reproducible — `random.Random(seed)`, domains in sorted order, frame sorted by `video_id` |
| order | globally shuffled | domain-blocked labelling anchors: after eight straight yeses the ninth is not an independent judgement |
| relevance span | 0.577 – 0.778 | the drawn rows are not clustered at the threshold, nor all at the top |

Two files, and the split is the point:

- `exposition_draw_key_2026-08-29.jsonl` — row, domain, `video_id`, relevance. **The
  record of what was drawn.** Do not open it while labelling.
- `exposition_labelling_2026-08-29.jsonl` — row, domain, title, description, and empty
  `label` / `note`. **No relevance, no band, and no `detail.matched`** — a labeller who
  sees the terms that fired is scoring the lexicon's reasoning rather than the video,
  which is the machine-label problem wearing a human face (ADR-0041).

## The criterion, fixed now

Label **1** (on-niche) when **both** hold:

1. **Subject**: the video is substantially *about* the named domain — not merely using
   its vocabulary, and not mentioning it in passing.
2. **Exposition**: it explains, analyses, teaches, or argues a position. This is the
   axis being tested. A bare event report, a vlog, a promotion, or entertainment that
   happens to touch the subject is **0** even when the subject is right.

Label **0** otherwise. The archetypal false positive is already on record from the
2026-08-27 spotcheck: a law firm's citizenship-services advert scored as `landmark
court cases` because it used the vocabulary fluently. Marketing is the failure mode to
watch for.

**Unjudgeable rows count as 0.** Decided now rather than after: the quantity measured is
"the scorer put this above the threshold — was it right?", and a row a human cannot
verify as on-niche is not evidence the scorer was right. If unjudgeable rows exceed 10%
of the sample, that is itself a finding and goes in the result report — it would mean
title and description are too thin a basis for this test, not that the axis failed.

## The bar

Precision = share labelled 1. The axis ships iff the **95% Wilson lower bound ≥ 0.70**,
which at n=99 needs **79 of 99** correct (0.80 observed). Parity with EVENT's 0.781 was
considered and rejected as undecidable at this n — see ADR-0041 for the arithmetic.

Nothing about this ships a ranking either way: `scorecards.value`, `sustainability` and
`opportunity` stay NULL behind Gate E (ADR-0029), which this test does not touch.

## How to label

Fill `label` with `1` or `0` in `exposition_labelling_2026-08-29.jsonl`, leaving `note`
free for anything surprising. ~99 rows at title-plus-description depth is roughly 45
minutes. Work top to bottom; the file is already shuffled, so do not sort it.
