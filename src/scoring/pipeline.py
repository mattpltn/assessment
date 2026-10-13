"""End-to-end scoring pipeline: raw answers -> Score A, Score B, Outcome C.

The model (weight tables + per-field formulas) is purely data-driven, see
model/model.json and model.py. This module only implements the arithmetic:

1. normalize(): each answered field is converted to a 0-4 score via its
   formula (see interpreter.py). Unanswered / unscored fields are None.
2. group_score(): a weighted average of a set of fields' scores, rescaled
   into 0-4. Used for the first-stage groups (group_a, group_b, group_d).
3. Score A: weighted average of the group_a scores.
4. Score B: weighted average of (Score A, group_b[0..10] scores) using the
   group_b weight column, scaled by 25. The value/weight pairing order here
   intentionally follows the model's own column order (Score A takes the
   weight slot of the *last* group_b row) rather than matching by id -- this
   is a quirk of the source model, preserved so results match it exactly.
5. Outcome C: for each candidate option, blend group_a / group_b / group_d /
   raw field scores against that option's signed weights (a negative weight
   flips the contributing score to 4-score), then pick the option with the
   highest blended score.
"""

from __future__ import annotations

from . import interpreter
from .model import Model


def normalize(model: Model, answers: dict[str, object]) -> dict[str, float | None]:
    scores: dict[str, float | None] = {}
    for fid in model.field_order:
        field = model.fields[fid]
        formula = field.get("formula")
        raw = answers.get(fid)
        if not formula or raw is None or raw == "":
            scores[fid] = None
            continue
        try:
            scores[fid] = interpreter.evaluate(formula, raw)
        except interpreter.FormulaError:
            scores[fid] = None
    return scores


def group_score(field_scores: dict[str, float | None], weights: dict[str, float]) -> float | None:
    pairs = [(field_scores[fid], w) for fid, w in weights.items() if field_scores.get(fid) is not None]
    if not pairs:
        return None
    den = sum(abs(w) for _, w in pairs)
    if den == 0:
        return None
    num = sum(v * w for v, w in pairs)
    raw = num / den
    return max(0.0, min(4.0, (raw + 4.0) / 2.0))


def _weighted_avg(scores: list[float | None], weights: list[float]) -> float:
    pairs = [(s, w) for s, w in zip(scores, weights) if s is not None]
    if not pairs:
        return 0.0
    den = sum(w for _, w in pairs)
    if den == 0:
        return 0.0
    num = sum(s * w for s, w in pairs)
    return num / den


def score_a(model: Model, group_a_scores: list[float | None]) -> float:
    weights = [g["weight"] for g in model.group_a]
    return _weighted_avg(group_a_scores, weights)


def score_b(model: Model, score_a_value: float, group_b_scores: list[float | None]) -> float:
    # group_b holds 12 rows: the first 11 are real criteria, the 12th is a
    # placeholder whose only purpose is to carry the weight used to blend
    # Score A into this average. See module docstring for the pairing quirk.
    sequence = [score_a_value] + group_b_scores[:11]
    weights = [g["weight"] for g in model.group_b]
    return _weighted_avg(sequence, weights) * 25


def outcome_c(
    model: Model,
    field_scores: dict[str, float | None],
    group_a_scores: list[float | None],
    group_d_scores: list[float | None],
    score_a_for_blend: float,
    group_b_scores_for_blend: list[float | None],
) -> tuple[str, float, dict[str, float]]:
    """Blend group_a / group_b / group_d / raw field scores against each
    option's signed weights and return the winning option.

    ``score_a_for_blend`` and ``group_b_scores_for_blend`` are the "B block"
    values plugged into this item's Outcome C calculation. For a single
    item scored alone these are just its own Score A and group_b scores --
    see KNOWN_ISSUES.md for why a *batch* of items does not always pass the
    item's own values here.
    """
    a_values = {g["id"]: s for g, s in zip(model.group_a, group_a_scores)}
    b_ids = [g["id"] for g in model.group_b]
    b_sequence = [score_a_for_blend] + group_b_scores_for_blend[:11]
    b_values = {bid: (v if v is not None else 0.0) for bid, v in zip(b_ids, b_sequence)}
    d_values = {g["id"]: s for g, s in zip(model.group_d, group_d_scores)}
    q_values = field_scores

    option_scores: dict[str, float] = {}
    for option in model.options:
        num = 0.0
        den = 0.0
        for fid, weight in option["weights"].items():
            if fid in a_values:
                value = a_values.get(fid)
            elif fid in b_values:
                value = b_values.get(fid)
            elif fid in d_values:
                value = d_values.get(fid)
            else:
                value = q_values.get(fid)
            if value is None:
                value = 0.0
            adjusted = value if weight >= 0 else (4.0 - value)
            num += adjusted * abs(weight)
            den += abs(weight)
        option_scores[option["id"]] = (num / den) if den else 0.0

    ranked = sorted(option_scores.items(), key=lambda kv: kv[1], reverse=True)
    best_id, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    certainty = (best_score - second_score) / 4.0
    return best_id, certainty, option_scores


def _score_one(model: Model, answers: dict[str, object]) -> dict:
    field_scores = normalize(model, answers)
    group_a_scores = [group_score(field_scores, g["fields"]) for g in model.group_a]
    group_b_scores = [group_score(field_scores, g["fields"]) for g in model.group_b[:11]]
    group_d_scores = [group_score(field_scores, g["fields"]) for g in model.group_d]
    a = score_a(model, group_a_scores)
    b = score_b(model, a, group_b_scores)
    return {
        "field_scores": field_scores,
        "group_a_scores": group_a_scores,
        "group_b_scores": group_b_scores,
        "group_d_scores": group_d_scores,
        "score_a": a,
        "score_b": b,
    }


def evaluate_batch(model: Model, answer_rows: list[dict[str, object]], fixed: bool = True) -> list[dict]:
    """Score every row in ``answer_rows`` and return one result dict each.

    Score A and Score B are computed independently per row -- order never
    matters for those. Outcome C's blend used to inherit a batch-order bug
    from the reference model this was ported from -- see KNOWN_ISSUES.md
    for the full writeup. That bug is fixed by default here: each item is
    blended against its own Score A / group_b scores. Pass ``fixed=False``
    to reproduce the original (buggy) reference-model behavior instead,
    e.g. for side-by-side comparison. Scoring a single row in isolation
    gives the same result either way, since there is nothing else to
    reorder against.
    """
    items = [_score_one(model, answers) for answers in answer_rows]

    if fixed:
        blend_source = [(item["score_a"], item["group_b_scores"]) for item in items]
    else:
        # Mirrors the reference model's own re-sorting of this intermediate
        # table by Score B, descending, before it is read back by position.
        order = sorted(range(len(items)), key=lambda i: items[i]["score_b"], reverse=True)
        by_sort_position = [(items[i]["score_a"], items[i]["group_b_scores"]) for i in order]
        blend_source = [by_sort_position[i] for i in range(len(items))]

    results = []
    for i, item in enumerate(items):
        blend_a, blend_b = blend_source[i]
        outcome, certainty, option_scores = outcome_c(
            model,
            item["field_scores"],
            item["group_a_scores"],
            item["group_d_scores"],
            blend_a,
            blend_b,
        )
        results.append(
            {
                "score_a": item["score_a"],
                "score_b": item["score_b"],
                "outcome_c": outcome,
                "certainty": certainty,
                "option_scores": option_scores,
            }
        )
    return results


def evaluate(model: Model, answers: dict[str, object]) -> dict:
    """Score a single row in isolation (Outcome C's batch quirk can't apply)."""
    return evaluate_batch(model, [answers])[0]
