#!/usr/bin/env python3
"""CLI: find the minimum number of answer changes to flip an item's
Outcome C to a target option.

Usage:
    python3 scripts/counterfactual.py input.csv --item item1 --target "Option 1"
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scoring import Model, evaluate, find_min_changes  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--item", required=True, help="item_id to analyze")
    parser.add_argument("--target", required=True, help='target option, e.g. "Option 1"')
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--beam-width", type=int, default=25)
    parser.add_argument("--model", type=Path, default=None)
    args = parser.parse_args()

    model = Model.load(args.model)

    with open(args.input_csv, newline="") as f:
        rows = list(csv.DictReader(f))
    row = next((r for r in rows if r.get("item_id") == args.item), None)
    if row is None:
        print(f"item_id {args.item!r} not found in {args.input_csv}", file=sys.stderr)
        sys.exit(1)

    answers = {k: v for k, v in row.items() if k != "item_id" and v != ""}

    baseline = evaluate(model, answers)
    print(f"Current outcome: {baseline['outcome_c']}  (target: {args.target})")
    print("Option scores:", {k: round(v, 3) for k, v in baseline["option_scores"].items()})

    if baseline["outcome_c"] == args.target:
        print("Already at target -- nothing to change.")
        return

    result = find_min_changes(
        model, answers, args.target, max_depth=args.max_depth, beam_width=args.beam_width
    )

    if result["depth"] is None:
        print(result["message"])
        return

    print(f"\nMinimum changes needed: {result['depth']}")
    print(f"Found {len(result['solutions'])} way(s) to do it in {result['depth']} change(s):\n")
    for i, sol in enumerate(result["solutions"], 1):
        print(f"Solution {i}:")
        for fid, old, new, old_score, new_score in sol:
            print(f"  {fid}: {old!r} -> {new!r}  (score {old_score} -> {new_score})")
        print()


if __name__ == "__main__":
    main()
