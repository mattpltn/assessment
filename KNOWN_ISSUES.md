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

**This should be fixed** by blending each item against its own Score A and
group-B scores (look up by identity, not by sort position). That is a
one-line change: in `evaluate_batch()` (`src/scoring/pipeline.py`), replace
the `blend_source[i]` lookup with `(items[i]["score_a"],
items[i]["group_b_scores"])` directly, and the `order`/`blend_source`
machinery can be deleted entirely. Left as-is for now so the two
implementations are directly comparable against the same reference data.
