# Exposition axis — the replacement draw, and the two-pass criterion

Executes the draw pre-registered in **ADR-0042**, which re-specifies ADR-0041's
labelling procedure and leaves its bar untouched. Written **before any label exists**.
Everything here is fixed; a change is a new ADR and a re-label.

## Why there is a second draw

The 2026-08-29 sample is **retired unlabelled**. Two reasons, both recorded in ADR-0042:
it was drawn under the superseded single-pass procedure, and it was read and judged
row-by-row by a model whose judgements survive in a session transcript. A fresh draw
under a new seed removes any question of a machine opinion travelling into a human pass.

`reports/exposition_labelling_2026-08-29.jsonl` and its key remain on disk as history.
**They are not the live sample.** The live one is dated 2026-08-30.

## The draw

Condition met: **11 of 11** exposition domains carry above-threshold videos (required
≥ 6), for a capped draw of **165** (required ≥ 80). Frame at draw time: 7,259 eligible
rows.

| parameter | value | why |
|---|---|---|
| frame | `cluster_members`, `item_type='video'`, `relevance >= 0.55`, `AXES` family `exposition` | ADR-0041, unchanged |
| n | **99** | 9 × 11 domains. Target 100; an even split is what the cap and the coverage rule jointly imply |
| per domain | 9 | under the cap of 15, so no head-start domain dominates (`trading` 1,917 eligible against `anthropocene-anthropology` 184) |
| seed | `20260830` | fixed and recorded; `random.Random(seed)`, domains sorted, frame sorted by `video_id` |
| order | globally shuffled | domain-blocked labelling anchors: after eight straight yeses the ninth is not independent |
| relevance span | 0.577 – 0.764 | the drawn rows are neither clustered at the threshold nor all at the top |

**The draw is reproducible this time.** `scripts/draw_exposition_sample.py` takes the
seed and rebuilds the sample; the 2026-08-29 draw was done inline, so only its output
could be checked, not the draw. Verified: re-running with `--seed 20260830` produces a
byte-identical key file.

Two files, and the split is the point:

- `exposition_draw_key_2026-08-30.jsonl` — row, domain, `video_id`, relevance. **The
  record of what was drawn. Do not open it while labelling.**
- `exposition_labelling_2026-08-30.jsonl` — row, domain, title, description, and empty
  `subject` / `exposition` / `note`. No relevance, no band, no `detail.matched`.

## The criterion, fixed now — two passes

Label the sample **twice**, each pass one question over all 99 rows.

**Pass A — SUBJECT.** Is this video substantially *about* the named domain?

- **yes**: a lecture on the domain's actual subject matter; exam-prep or coursework whose
  syllabus topic **is** the domain; a video in any language — language is not this question.
- **no**: the domain's vocabulary as metaphor or decoration; a merely adjacent topic
  (corporate finance under `macro-economy`); explaining what science *found* under
  `philosophy-of-science`; a scientist's biography, which is history of science.

**Pass B — EXPOSITION.** Does it explain, analyse, teach, or argue a position?

- **yes**: explains a mechanism; teaches a method; argues a thesis; analyses a case,
  including a market or a conflict.
- **no**: reports a thing happened without saying why it matters; a personal story with no
  general lesson; an advert or affiliate pitch, however fluent — the archetypal false
  positive on record is a law firm's citizenship advert scoring as `landmark court cases`;
  a listicle or quote compilation; a **live performance**, since trading live or
  channelling is doing rather than explaining; a roadmap for a series that has not happened.

`label = 1` iff **both** passes are yes.

**`unsure` is a real answer**, recorded per pass rather than folded into 0. It still
scores 0 in the precision arithmetic — the quantity measured is "the scorer put this above
the threshold, was it right?", and a row nobody can verify is not evidence that it was.
Recording it separately makes ADR-0041's ">10% is itself a finding" measurable on each
axis rather than only on the pair.

## The bar — unchanged

Precision = share of rows labelled 1. The axis ships iff the **95% Wilson lower bound
≥ 0.70**, i.e. **79 of 99**. ADR-0042 changed how a row is judged and nothing about what
must be cleared. Parity with EVENT's 0.781 was considered and rejected as undecidable at
this n; do not relitigate it.

Nothing about this ships a ranking either way: `scorecards.value`, `sustainability` and
`opportunity` stay NULL behind Gate E (ADR-0029), which this test does not touch.

## How to label

```sh
uv run python scripts/label_exposition.py            # runs the next unfinished pass
uv run python scripts/label_exposition.py --status   # progress, and the final counts
```

One row per screen with the pass's archetypes on screen; `y` / `n` / `?` / `s` skip /
`b` back / `q` save & quit. Saves after every keystroke and resumes where you stopped.

**Do not read the 2026-08-30 session transcript before labelling.** It contains a model's
row-by-row judgements of the retired sample, drawn from this same frame, and a remembered
machine call is exactly the anchor the title-and-description-only rule exists to prevent.
