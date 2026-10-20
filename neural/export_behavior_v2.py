#!/usr/bin/env python3
"""Embed a hierarchical behavior-clone model into a standalone QuickJS policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from competition_rules import load_and_check_rules  # noqa: E402


def matrix(value: dict, key: str, rows: int, columns: int) -> None:
    data = value.get(key)
    if not isinstance(data, list) or len(data) != rows or any(not isinstance(row, list) or len(row) != columns for row in data):
        raise SystemExit(f"{key} dimension mismatch")


def vector(value: dict, key: str, size: int) -> None:
    data = value.get(key)
    if not isinstance(data, list) or len(data) != size:
        raise SystemExit(f"{key} dimension mismatch")


def main() -> None:
    rules = load_and_check_rules()
    parser = argparse.ArgumentParser(description="导出分层行为克隆 v2 为单文件扑克策略")
    parser.add_argument("--model", type=Path, default=ROOT / "neural" / "artifacts" / "behavior-v2" / "model.json")
    parser.add_argument("--template", type=Path, default=ROOT / "neural" / "submission_behavior_v2.template.js")
    parser.add_argument("--output", type=Path, default=ROOT / "submission_behavior_v2.js")
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    if model.get("format") != "agx-poker-bc-v2" or model.get("feature_version") != "public-replay-features-v2":
        raise SystemExit("model is not a supported behavior clone v2")
    input_size = int(model.get("input_size", 0))
    hidden1 = int(model.get("hidden1_size", 0))
    hidden2 = int(model.get("hidden2_size", 0))
    family_actions = model.get("family_actions")
    size_actions = model.get("size_actions")
    if input_size != 232 or family_actions != ["fold", "check", "call", "raise", "allin"]:
        raise SystemExit("model family/input schema is incompatible with runtime")
    if size_actions != ["0.33", "0.50", "0.75", "1.00", "1.50", "2.00"]:
        raise SystemExit("model raise-size schema is incompatible with runtime")
    matrix(model, "trunk_w1", hidden1, input_size)
    vector(model, "trunk_b1", hidden1)
    matrix(model, "trunk_w2", hidden2, hidden1)
    vector(model, "trunk_b2", hidden2)
    matrix(model, "family_w", len(family_actions), hidden2)
    vector(model, "family_b", len(family_actions))
    matrix(model, "size_w", len(size_actions), hidden2)
    vector(model, "size_b", len(size_actions))

    template = args.template.read_text(encoding="utf-8")
    placeholder = "__MODEL_JSON__"
    if template.count(placeholder) != 1:
        raise SystemExit("template must contain exactly one model placeholder")
    source = template.replace(placeholder, json.dumps(model, ensure_ascii=False, separators=(",", ":")))
    encoded = source.encode("utf-8")
    if len(encoded) > rules["limits"]["sourceBytes"]:
        raise SystemExit(f"export exceeds {rules['limits']['sourceBytes']} bytes")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    print(f"exported: {args.output}")
    print(f"bytes: {len(encoded)}")


if __name__ == "__main__":
    main()
