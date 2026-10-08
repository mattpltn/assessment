# Weighted Scorecard

Live demo: **https://mattpltn.github.io/assessment/**

Turns a CSV of per-item answers into three outputs:

- **Score A** -- a 0-4 weighted-average readiness-style score.
- **Score B** -- a 0-100 weighted-average priority-style score (built in
  part from Score A).
- **Outcome C** -- one of six candidate categories (`Option 1`..`Option 6`),
  picked by blending several weighted criteria groups and raw answers, plus
  a `certainty` figure (how far ahead the winning option was).

The whole thing is a static weighted multi-criteria scoring model -- no
machine learning, nothing probabilistic. Every weight, formula, and
threshold lives in [`model/model.json`](model/model.json) as data; the code
just applies it.

A batch-order bug in how Outcome C was computed in the original Excel file
has been found, proven, and fixed here (on by default) -- see
[`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) for the full writeup, including how to
reproduce the original behavior for comparison.

## Structure

```
model/model.json             weight tables + per-field scoring formulas (the data)
src/scoring/                 the scoring pipeline (the code)
  interpreter.py                tiny evaluator for the formula mini-language
  model.py                      loads model.json
  pipeline.py                   normalize -> group scores -> Score A/B -> Outcome C
  counterfactual.py             minimal-change search for a target Outcome C
scripts/
  run.py                        CLI: CSV in, CSV out
  counterfactual.py             CLI: minimal-change search
tests/                        golden-value tests + a verified sample CSV
docs/                         static web demo (same logic, ported to JS)
  index.html                    the page
  scoring.js                    pipeline, ported
  counterfactual.js             minimal-change search, ported
  kobo.js / kobo_map.json       raw survey-export ingestion (see below)
KNOWN_ISSUES.md               resolved-issue writeup: the Outcome C batch-order bug
```

## CSV format

One row per item, one column per input field (`item_id, Q01, Q02, ... Q69`).
Not every `Q` field is used in scoring -- some are free-text and ignored.
Leave a cell blank if you don't have an answer; blank fields are simply
excluded from any weighted average they would have contributed to.

See [`tests/fixtures_input.csv`](tests/fixtures_input.csv) for a worked
example (also used as the golden-value test fixture).

## CLI

```bash
python3 -m venv .venv && .venv/bin/pip install -e .   # or just add src/ to PYTHONPATH
.venv/bin/python scripts/run.py tests/fixtures_input.csv
```

Outputs a CSV with `item_id, score_a, score_b, outcome_c, certainty`.

## "What's the fastest way to flip this outcome?"

```bash
.venv/bin/python scripts/counterfactual.py tests/fixtures_input.csv --item item1 --target "Option 1"
```

Searches for the smallest set of answer changes that would flip a given
item's Outcome C to a target option, trying 1 change, then 2, then 3 (each
exhaustive at depth 1; depth 2+ narrows to the most impactful single
changes to stay fast) and stopping at the first depth with any solution.
Prints every minimal solution found at that depth, each with the exact
field, old/new answer, and old/new score. See
[`src/scoring/counterfactual.py`](src/scoring/counterfactual.py).

Depth 1 is always exact (every possible single change is tried). Depth 2+
narrows the search to the `beam_width` most individually-impactful changes
rather than trying every combination, to stay fast -- for the one case
this was checked against, an exhaustive (non-beam) search confirmed the
beam result was a genuine minimum, but that isn't a guarantee for every
input. Raising `--beam-width` trades speed for a more thorough search.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests/
```

The golden-value test scores the bundled sample CSV and asserts the result
matches the reference model's own cached output exactly.

## Web demo

`docs/index.html` + `docs/scoring.js` are a dependency-free port of the
same pipeline to the browser (fetches `docs/model.json`, no backend). Open
`docs/index.html` directly, or serve the repo root with GitHub Pages
(Settings -> Pages -> Deploy from branch -> `main` / `/docs`) and use the
"Try sample data" button or upload your own CSV.

The page also accepts a raw survey-tool export directly -- semicolon- or
comma-delimited, quoted fields, the tool's own bookkeeping columns
(`_id`, `_uuid`, `__version__`, ...), original field codes rather than
`Q01..Q69`. `docs/kobo.js` auto-detects this shape and converts it in the
browser before scoring, using the field-code and option-label lookup table
in `docs/kobo_map.json`.

**Note:** `docs/kobo_map.json` contains the real-world field names and
answer-option wording needed to recognize those raw answers. This was a
deliberate, explicit choice to prioritize one-upload convenience over
keeping that wording out of the public page -- everywhere else in this
repo (`model/model.json`, the CSV format above, Score A/B/Outcome C
themselves) stays fully anonymized.

After scoring a file, the page also offers "Compare to original Excel tool
(pre-fix)" (renders the pre-fix numbers in a second table, see
`KNOWN_ISSUES.md`) and a "Fastest path to a different outcome" panel --
pick an item and a target option to run the same minimal-change search as
`scripts/counterfactual.py`, in the browser (`docs/counterfactual.js`).
