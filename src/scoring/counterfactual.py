"""Minimal-change search: given a scored item, find the smallest set of
answer changes that flips Outcome C to a target option.

Fully generic over model.json -- no domain knowledge beyond the formula
mini-language already supported by interpreter.py.
"""

from __future__ import annotations

import datetime as _dt
import itertools
import re

from . import interpreter
from .model import Model
from .pipeline import evaluate

_CHOOSE_RE = re.compile(r"\{(?:\"opt\d+\",?)+\}")
_NUM_RE = re.compile(r"\{v\}\s*(?:>=|>|<=|<)\s*-?\d+(?:\.\d+)?")
_NUM_EXTRACT_RE = re.compile(r"\{v\}\s*(?:>=|>|<=|<)\s*(-?\d+(?:\.\d+)?)")
_YEAR_RE = re.compile(r"YEAR\(TODAY\(\)\)-\{v\}")
_YEARFRAC_RE = re.compile(r"YEARFRAC\(\{v\},TODAY\(\)\)")


def enumerate_levels(field: dict) -> list[tuple[object, float]]:
    """Return [(raw_value, resulting_score), ...] for every score this
    field can take, deduplicated by score (first probe value wins)."""
    formula = field.get("formula")
    if not formula:
        return []

    flat = formula.replace("\n", " ")
    probes: list[object] = []

    if _CHOOSE_RE.search(flat):
        n = flat.count('"opt')
        probes = [f"opt{i}" for i in range(1, n + 1)]
    elif _YEAR_RE.search(flat):
        this_year = _dt.date.today().year
        probes = [this_year - off for off in (1, 3, 6, 11, 21)]
    elif _YEARFRAC_RE.search(flat):
        today = _dt.date.today()
        probes = [(today - _dt.timedelta(days=d)).isoformat() for d in (30, 400, 1200, 3000, 4500)]
    elif _NUM_RE.search(flat):
        nums = [float(n) for n in _NUM_EXTRACT_RE.findall(flat)]
        for n in sorted(set(nums)):
            probes += [n, n + 1, n - 1 if n == int(n) else round(n - 0.01, 2)]
        probes.append(0)
    else:
        # yes/no (possibly inverted) -- the only remaining pattern in this model
        probes = ["yes", "no"]

    seen: dict[float, object] = {}
    for raw in probes:
        try:
            score = interpreter.evaluate(formula, raw)
        except interpreter.FormulaError:
            continue
        if score not in seen:
            seen[score] = raw
    return [(raw, score) for score, raw in seen.items()]


def _current_score(field: dict, current_raw) -> float | None:
    formula = field.get("formula")
    if not formula or current_raw in (None, ""):
        return None
    try:
        return interpreter.evaluate(formula, current_raw)
    except interpreter.FormulaError:
        return None


def _candidate_changes(model: Model, answers: dict) -> list[tuple[str, object, object, float, float]]:
    """All (field_id, old_raw, new_raw, old_score, new_score) that differ."""
    out = []
    for field in model.fields.values():
        if not field.get("formula"):
            continue
        fid = field["id"]
        old_raw = answers.get(fid)
        old_score = _current_score(field, old_raw)
        for new_raw, new_score in enumerate_levels(field):
            if new_score != old_score:
                out.append((fid, old_raw, new_raw, old_score, new_score))
    return out


def find_min_changes(
    model: Model,
    answers: dict,
    target_option: str,
    max_depth: int = 3,
    beam_width: int = 25,
) -> dict:
    """Breadth-first search over answer changes, cheapest depth first.

    Returns {"depth": n or None, "solutions": [...]}. Each solution is a
    list of (field_id, old_value, new_value, old_score, new_score). Stops
    at the first depth with any solution. Depth 2+ is narrowed to the
    ``beam_width`` single changes with the best individual effect on the
    target option's margin, to keep the search tractable.
    """
    baseline = evaluate(model, answers)
    if baseline["outcome_c"] == target_option:
        return {"depth": 0, "solutions": [], "message": "already at target"}

    candidates = _candidate_changes(model, answers)

    depth1_hits = []
    leverage = []  # (margin, candidate) for ranking into deeper search
    for cand in candidates:
        fid, old_raw, new_raw, old_score, new_score = cand
        trial = dict(answers)
        trial[fid] = new_raw
        result = evaluate(model, trial)
        target_score = result["option_scores"][target_option]
        best_other = max(v for k, v in result["option_scores"].items() if k != target_option)
        leverage.append((target_score - best_other, cand))
        if result["outcome_c"] == target_option:
            depth1_hits.append([cand])

    if depth1_hits:
        return {"depth": 1, "solutions": depth1_hits}

    leverage.sort(key=lambda x: x[0], reverse=True)
    shortlist = [cand for _, cand in leverage[:beam_width]]

    depth = 2
    while depth <= max_depth:
        hits = []
        for combo in itertools.combinations(shortlist, depth):
            trial = dict(answers)
            for fid, _, new_raw, _, _ in combo:
                trial[fid] = new_raw
            result = evaluate(model, trial)
            if result["outcome_c"] == target_option:
                hits.append(list(combo))
        if hits:
            return {"depth": depth, "solutions": hits}
        depth += 1

    return {
        "depth": None,
        "solutions": [],
        "message": f"no solution found within depth {max_depth} / beam {beam_width}",
    }
