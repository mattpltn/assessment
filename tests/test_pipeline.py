import csv
import math
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scoring import Model
from scoring.pipeline import evaluate, evaluate_batch

FIXTURES = Path(__file__).parent / "fixtures_input.csv"
MODEL_PATH = Path(__file__).resolve().parents[1] / "model" / "model.json"

EXPECTED = {
    "item1": (2.949479138960349, 74.86429272849973, "Option 2"),
    "item2": (2.7173232362489363, 71.25916938688242, "Option 2"),
    "item3": (3.145118723287349, 82.17061500823422, "Option 2"),
}


def _load_rows():
    with open(FIXTURES, newline="") as f:
        return list(csv.DictReader(f))


def test_golden_values_match_reference_model():
    # fixed=False reproduces the original reference model byte-for-byte,
    # including its batch-order-dependent Outcome C bug -- see
    # KNOWN_ISSUES.md. All three fixture rows must be scored together in
    # their original order to reproduce these exact reference values.
    model = Model.load(MODEL_PATH)
    rows = _load_rows()
    assert len(rows) == 3

    item_ids = [row.pop("item_id") for row in rows]
    answer_rows = [{k: v for k, v in row.items() if v != ""} for row in rows]
    results = evaluate_batch(model, answer_rows, fixed=False)

    for item_id, result in zip(item_ids, results):
        exp_a, exp_b, exp_c = EXPECTED[item_id]
        assert math.isclose(result["score_a"], exp_a, rel_tol=1e-9)
        assert math.isclose(result["score_b"], exp_b, rel_tol=1e-9)
        assert result["outcome_c"] == exp_c


def test_default_is_fixed_and_blends_each_item_with_its_own_values():
    # The bug from KNOWN_ISSUES.md is fixed by default (fixed=True): every
    # row gets its OWN Score A / group_b scores to blend against, matching
    # what scoring it alone would give, regardless of batch order/composition.
    model = Model.load(MODEL_PATH)
    rows = _load_rows()
    item_ids = [row.pop("item_id") for row in rows]
    answer_rows = [{k: v for k, v in row.items() if v != ""} for row in rows]

    default_results = evaluate_batch(model, answer_rows)
    solo_results = [evaluate(model, answers) for answers in answer_rows]

    for item_id, default_r, solo_r in zip(item_ids, default_results, solo_results):
        assert math.isclose(default_r["score_a"], solo_r["score_a"], rel_tol=1e-9)
        assert math.isclose(default_r["score_b"], solo_r["score_b"], rel_tol=1e-9)
        assert default_r["outcome_c"] == solo_r["outcome_c"]
        assert math.isclose(default_r["certainty"], solo_r["certainty"], rel_tol=1e-9)


def test_blank_answers_do_not_crash():
    model = Model.load(MODEL_PATH)
    result = evaluate(model, {})
    assert result["score_a"] == 0.0
    assert result["score_b"] == 0.0
    assert result["outcome_c"] in {o["id"] for o in model.options}
