#!/usr/bin/env python3
"""CLI: read a CSV of answers, write a CSV with Score A / Score B / Outcome C."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scoring import Model, evaluate_batch  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--model", type=Path, default=None)
    args = parser.parse_args()

    model = Model.load(args.model)

    with open(args.input_csv, newline="") as f:
        rows = list(csv.DictReader(f))

    item_ids = [row.get("item_id", "") for row in rows]
    answer_rows = [{k: v for k, v in row.items() if k != "item_id" and v != ""} for row in rows]
    # Outcome C is intentionally batch-order-dependent -- see KNOWN_ISSUES.md --
    # so the whole file is scored together, not row by row.
    results = evaluate_batch(model, answer_rows)

    out_rows = [
        {
            "item_id": item_id,
            "score_a": round(result["score_a"], 6),
            "score_b": round(result["score_b"], 6),
            "outcome_c": result["outcome_c"],
            "certainty": round(result["certainty"], 6),
        }
        for item_id, result in zip(item_ids, results)
    ]

    out = sys.stdout if args.output is None else open(args.output, "w", newline="")
    writer = csv.DictWriter(out, fieldnames=["item_id", "score_a", "score_b", "outcome_c", "certainty"])
    writer.writeheader()
    writer.writerows(out_rows)
    if args.output is not None:
        out.close()


if __name__ == "__main__":
    main()
