# Known issues

## Outcome C is sensitive to batch order (inherited from the reference model)

Outcome C blends four groups of signed weights against: the item's own
group-A scores, group-D scores, raw field scores, and a "group B" block that
is supposed to be the item's own Score A plus its own group-B scores.

The reference model this was ported from computes that last block by
re-sorting all scored items by Score B (descending) into a side table, then
reading the blend values back out *by row position* rather than by looking
the item back up by name. Score A and Score B are unaffected (they're
computed from each item's own answers only), but whenever an item's rank in
that sort doesn't match its position in the original input, Outcome C ends
up blended against a *different item's* group-B block.

This repo's `evaluate_batch()` reproduces that behavior intentionally, so
that results match the reference model exactly on known data (see
`tests/test_pipeline.py`, which is a golden-value test against the
reference model's own cached outputs). Concretely: given an input file of N
items, item at position `i` (0-indexed) gets blended against whichever item
is ranked `i`-th by Score B, not necessarily itself.

Practically this means:
- Scoring a single item on its own (`evaluate()`) is unaffected -- with
  nothing else to rank against, position 0 always maps to itself.
- Re-ordering rows in a batch, or adding/removing an unrelated item, can
  change another item's Outcome C even though none of its own answers
  changed.

**The fix** is to blend each item against its own Score A and group-B
scores (look up by identity, not by sort position) instead. This is now
available as an opt-in rather than the default, so the two behaviors stay
directly comparable against the same reference data:

- Python: `evaluate_batch(model, answer_rows, fixed=True)`
  (`src/scoring/pipeline.py`).
- JS: `Scoring.evaluateBatch(model, answerRows, { useOwnBlend: true })`
  (`docs/scoring.js`).
- Web demo: after scoring a file, click **"Bug fix version 2"** to render a
  second results table underneath using the corrected blend, so both can
  be compared side by side for the same upload.

The default behavior (no flag/option passed) is unchanged -- still
reproduces the reference model's quirk exactly, which is what the
golden-value test in `tests/test_pipeline.py` checks against.
