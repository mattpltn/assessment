# Fixed issues

## RESOLVED: Outcome C depended on batch order (bug inherited from the original Excel file)

**Status: fixed, and fixed by default** as of the `fixed`/`useOwnBlend`
options added to `evaluate_batch()`. This section documents what was
actually wrong in the source spreadsheet, how it was proven, and how the
fix works -- kept for the record rather than as an open issue.

### What Outcome C is supposed to do

For each item, Outcome C picks one of six candidate options by blending
four groups of signed weights against: the item's own group-A scores,
group-D scores, raw field scores, and a "group B" block that is supposed
to be *that same item's* Score A plus its own group-B scores.

### What was actually wrong in the original Excel file

The original workbook computes an item's Score A and Score B on one sheet,
independently per item. So far so good. But a *second* sheet needs those
same Score A / group-B values again to compute Outcome C, and rather than
looking the item back up by name, it does this:

1. It looks up the item's row position in the (unsorted) input table --
   call this position `i`.
2. It then reads the Score A / group-B values out of that first sheet *at
   that same row position `i`* -- `INDEX(ScoreTable, i, ...)`.

The problem: that first sheet is independently sorted by Score B,
descending (for its own display purposes). So row position `i` in that
sheet is *not* the same item as row position `i` in the input table, unless
every item happens to already be in Score-B-descending order. Whenever the
sort order differs from the input order, Outcome C for item `i` gets
blended against a *different item's* Score A / group-B values -- picked
purely by where that other item happens to rank by Score B, with no
connection to the item actually being scored.

### How this was proven (not just suspected)

The source tool's own cached Outcome C certainty for an item could only be
reproduced by deliberately blending that item against the Score A /
group-B values of whichever item ranked at the same position in the
Score-B-descending order -- an exact match once that substitution is made,
and off otherwise. That confirms the row-position theory precisely.

Score A and Score B themselves are unaffected by any of this -- they're
each computed from an item's own answers only, with no cross-sheet lookup.
Only the Outcome C blend (and therefore the `certainty` figure, and
potentially which option wins in a close call) was affected.

### Practical symptom

- Scoring one item alone was always fine -- with nothing else to rank
  against, position 0 always mapped to itself.
- Scoring a batch of items could give a *different* Outcome C for an item
  purely because another, unrelated item was added to or removed from the
  same batch, or because the batch was given in a different row order --
  even though the item's own answers never changed.

### The fix

Blend each item against its own Score A and group-B scores -- look it up
by identity, not by a sort position in another table. That's the default
behavior now:

- Python: `evaluate_batch(model, answer_rows)` -- fixed by default. Pass
  `fixed=False` to reproduce the original (buggy) behavior instead, e.g.
  for comparison (`src/scoring/pipeline.py`).
- JS: `Scoring.evaluateBatch(model, answerRows)` -- fixed by default. Pass
  `{ useOwnBlend: false }` for the original behavior
  (`docs/scoring.js`).
- Web demo: results are shown fixed by default. Click **"Compare to
  original Excel tool (pre-fix)"** after scoring a file to render a second
  table underneath using the original buggy blend, for side-by-side
  comparison on the same upload.

`tests/test_pipeline.py` pins both behaviors against values computed by
the reference Excel workbook on the synthetic fixture items: `fixed=False`
against the workbook with its original lookup (so that compatibility mode
never silently drifts), and the default (`fixed=True`) against the
corrected workbook and against scoring each item alone, which is
unaffected by batch composition by construction. In the fixture, item 2's
Outcome C differs between the two (Option 1 pre-fix, Option 2 fixed).
