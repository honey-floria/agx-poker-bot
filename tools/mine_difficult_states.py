#!/usr/bin/env python3
"""Mine high-loss and low-confidence replay states for teacher relabeling."""

from __future__ import annotations

import argparse
from collections import Counter
import heapq
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "neural"))
sys.path.insert(0, str(ROOT / "tools"))
from replay_data_v2 import FAMILY_ACTIONS, decision_features_v2, hierarchical_target, legal_family_mask  # noqa: E402
from build_replay_dataset import display_path, sha256_file, write_json_atomic  # noqa: E402


def difficulty_score(correct: bool, confidence: float, margin: float, pot: int) -> float:
    """Prioritize mistakes, ambiguity, and consequential pots without outcome leakage."""
    pot_weight = min(1.0, math.log1p(max(0, pot)) / math.log1p(20_000))
    return 1.5 * (not correct) + (1.0 - confidence) + 0.5 * (1.0 - margin) + 0.35 * pot_weight


def main() -> None:
    parser = argparse.ArgumentParser(description="从行为模型错误、低置信和大底池状态中挖掘困难样本")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-states", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--postflop-only", action="store_true")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    args = parser.parse_args()
    if args.max_states < 1 or args.batch_size < 1:
        raise SystemExit("max-states and batch-size must be positive")

    try:
        import torch
    except ImportError as exc:
        raise SystemExit("PyTorch is required for difficult-state mining") from exc

    chosen = "cuda" if args.device == "auto" and torch.cuda.is_available() else ("cpu" if args.device == "auto" else args.device)
    if chosen == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA requested but unavailable")
    device = torch.device(chosen)
    model = json.loads(args.model.read_text(encoding="utf-8"))
    if model.get("format") != "agx-poker-bc-v2" or model.get("feature_version") != "public-replay-features-v2":
        raise SystemExit("unsupported behavior model")
    tensor = lambda key: torch.tensor(model[key], dtype=torch.float32, device=device)
    w1, b1 = tensor("trunk_w1"), tensor("trunk_b1")
    w2, b2 = tensor("trunk_w2"), tensor("trunk_b2")
    wf, bf = tensor("family_w"), tensor("family_b")

    heap: list[tuple[float, int, dict]] = []
    scanned = eligible = incorrect = 0
    selected_families: Counter[str] = Counter()
    sequence = 0

    def process(rows: list[dict]) -> None:
        nonlocal incorrect, sequence
        features = torch.tensor([decision_features_v2(row) for row in rows], dtype=torch.float32, device=device)
        legal = torch.tensor([legal_family_mask(row) for row in rows], dtype=torch.bool, device=device)
        hidden = torch.relu(features @ w1.T + b1)
        hidden = torch.relu(hidden @ w2.T + b2)
        logits = hidden @ wf.T + bf
        logits = logits.masked_fill(~legal, torch.finfo(logits.dtype).min)
        probabilities = torch.softmax(logits, dim=1)
        values, indices = probabilities.topk(2, dim=1)
        for row, top_values, top_indices in zip(rows, values.tolist(), indices.tolist()):
            target, _ = hierarchical_target(row)
            guess = top_indices[0]
            correct = guess == target
            incorrect += int(not correct)
            confidence = top_values[0]
            margin = top_values[0] - top_values[1]
            score = difficulty_score(correct, confidence, margin, int(row.get("pot", 0)))
            enriched = dict(row)
            enriched["mining"] = {
                "version": "behavior-v3-difficulty-v1",
                "score": round(score, 8),
                "model_family": FAMILY_ACTIONS[guess],
                "observed_family": FAMILY_ACTIONS[target],
                "confidence": round(confidence, 8),
                "margin": round(margin, 8),
                "incorrect": not correct,
            }
            item = (score, sequence, enriched)
            sequence += 1
            if len(heap) < args.max_states:
                heapq.heappush(heap, item)
            elif score > heap[0][0]:
                heapq.heapreplace(heap, item)

    batch: list[dict] = []
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            row = json.loads(line)
            if row.get("data_version") != model.get("data_version"):
                raise RuntimeError(
                    f"data_version mismatch at line {scanned}: "
                    f"expected {model.get('data_version')!r}, got {row.get('data_version')!r}"
                )
            if args.postflop_only and row.get("street") == "preflop":
                continue
            eligible += 1
            batch.append(row)
            if len(batch) >= args.batch_size:
                process(batch)
                batch = []
        if batch:
            process(batch)

    selected = [item[2] for item in sorted(heap, key=lambda item: (-item[0], item[1]))]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in selected:
            selected_families[row["mining"]["observed_family"]] += 1
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(args.output)
    report = {
        "schema": "agx.difficult-state-mining.v1",
        "input": display_path(args.input),
        "input_sha256": sha256_file(args.input),
        "model": display_path(args.model),
        "model_sha256": sha256_file(args.model),
        "postflop_only": args.postflop_only,
        "device": chosen,
        "scanned": scanned,
        "eligible": eligible,
        "model_incorrect": incorrect,
        "selected": len(selected),
        "selected_observed_families": dict(selected_families),
        "score_min": selected[-1]["mining"]["score"] if selected else None,
        "score_max": selected[0]["mining"]["score"] if selected else None,
        "output": display_path(args.output),
        "output_sha256": sha256_file(args.output),
    }
    write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
