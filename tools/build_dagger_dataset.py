#!/usr/bin/env python3
"""Replace mined Top-K training labels with audited policy-teacher labels."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "neural"))
sys.path.insert(0, str(ROOT / "tools"))
from replay_data import ACTIONS, action_bucket  # noqa: E402
from build_replay_dataset import display_path, sha256_file, write_json_atomic  # noqa: E402


def state_key(row: dict) -> str:
    return json.dumps([
        row.get("match_id"), row.get("hand"), row.get("rotation"), row.get("rotation_hand"),
        row.get("seat"), row.get("street"), len(row.get("history", [])), row.get("pot"),
        row.get("stack"), row.get("me_bet"), row.get("invested"), row.get("to_call"),
    ], separators=(",", ":"), ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 Top-K + 困难状态安全重标注数据集")
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--data-version", default="public-replay-top20-dagger1-heuristic-v1")
    args = parser.parse_args()

    replacements: dict[str, dict] = {}
    disagreements = Counter()
    with args.labels.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            label = row.get("dagger_label") or {}
            key = state_key(row)
            if key != label.get("state_key"):
                raise RuntimeError(f"state key mismatch in labels:{line_number}")
            if key in replacements:
                raise RuntimeError(f"duplicate label key: {key}")
            original_family = str((label.get("original_action") or {}).get("type"))
            teacher_family = str((row.get("action") or {}).get("type"))
            if original_family in ("bet", "raise"):
                original_family = "raise"
            if teacher_family in ("bet", "raise"):
                teacher_family = "raise"
            disagreements[f"{original_family}->{teacher_family}"] += 1
            replacements[key] = row
    if not replacements:
        raise RuntimeError("empty policy-label file")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {name: args.output_dir / f"{name}.jsonl" for name in ("train", "validation", "test", "all")}
    temporary = {name: path.with_suffix(path.suffix + ".tmp") for name, path in output_paths.items()}
    handles = {name: path.open("w", encoding="utf-8") for name, path in temporary.items()}
    matched: set[str] = set()
    split_counts = Counter()
    action_counts = Counter()
    try:
        for split in ("train", "validation", "test"):
            source = args.base_dir / f"{split}.jsonl"
            with source.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    base = json.loads(line)
                    if base.get("data_version") != "public-replay-top20-v1":
                        raise RuntimeError(f"unexpected base data version in {source}:{line_number}")
                    key = state_key(base)
                    if split == "train" and key in replacements:
                        row = replacements[key]
                        matched.add(key)
                    else:
                        row = base
                    row = dict(row)
                    row["split"] = split
                    row["data_version"] = args.data_version
                    label, projection = action_bucket(row)
                    row["action_index"] = label
                    row["action_bucket"] = ACTIONS[label]
                    row["action_projection"] = projection
                    encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                    handles[split].write(encoded)
                    handles["all"].write(encoded)
                    split_counts[split] += 1
                    action_counts[ACTIONS[label]] += 1
    finally:
        for handle in handles.values():
            handle.close()

    missing = set(replacements) - matched
    if missing:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        raise RuntimeError(f"{len(missing)} policy labels did not match the Top-K training split")
    for name, path in temporary.items():
        path.replace(output_paths[name])

    report = {
        "schema": "agx.dagger-policy-dataset.v1",
        "data_version": args.data_version,
        "base_dir": display_path(args.base_dir),
        "base_files_sha256": {
            split: sha256_file(args.base_dir / f"{split}.jsonl")
            for split in ("train", "validation", "test")
        },
        "labels": display_path(args.labels),
        "labels_sha256": sha256_file(args.labels),
        "replaced_train_labels": len(matched),
        "validation_labels_replaced": 0,
        "test_labels_replaced": 0,
        "teacher_family_transitions": dict(sorted(disagreements.items())),
        "split_decisions": dict(split_counts),
        "action_counts": {action: action_counts[action] for action in ACTIONS},
        "files": {
            name: {"path": display_path(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for name, path in output_paths.items()
        },
    }
    write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
