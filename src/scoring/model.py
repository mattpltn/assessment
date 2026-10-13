"""Loads model.json and exposes the weight tables used by pipeline.py."""

from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "model" / "model.json"


class Model:
    def __init__(self, data: dict):
        self.fields = {f["id"]: f for f in data["fields"]}
        self.field_order = [f["id"] for f in data["fields"]]
        self.group_a = data["group_a"]
        self.group_b = data["group_b"]
        self.group_d = data["group_d"]
        self.options = data["options"]

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Model":
        path = Path(path) if path else _DEFAULT_PATH
        with open(path) as f:
            return cls(json.load(f))
