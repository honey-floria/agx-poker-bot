#!/usr/bin/env python3
"""Train a legality-masked hierarchical behavior clone from verified replays."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random
import sys
import time

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from replay_data_v2 import (
    FAMILY_ACTIONS,
    FAMILY_OUTPUT_SIZE,
    INPUT_SIZE_V2,
    SIZE_ACTIONS,
    SIZE_OUTPUT_SIZE,
    decision_features_v2,
    hierarchical_target,
    legal_family_mask,
)


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from competition_rules import load_and_check_rules  # noqa: E402
from environment_gate import load_status  # noqa: E402


class HierarchicalBehaviorMLP(nn.Module):
    def __init__(self, hidden1: int, hidden2: int):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(INPUT_SIZE_V2, hidden1), nn.ReLU(),
            nn.Linear(hidden1, hidden2), nn.ReLU(),
        )
        self.family_head = nn.Linear(hidden2, FAMILY_OUTPUT_SIZE)
        self.size_head = nn.Linear(hidden2, SIZE_OUTPUT_SIZE)

    def forward(self, inputs):
        hidden = self.trunk(inputs)
        return self.family_head(hidden), self.size_head(hidden)


def detected_data_version(path: Path) -> str:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                version = json.loads(line).get("data_version")
                if not isinstance(version, str) or not version:
                    raise RuntimeError(f"missing data_version: {path}")
                return version
    raise RuntimeError(f"empty dataset: {path}")


def dataset(path: Path, expected_data_version: str) -> tuple[TensorDataset, Counter[int], Counter[int]]:
    with path.open("r", encoding="utf-8") as handle:
        count = sum(1 for line in handle if line.strip())
    if count == 0:
        raise RuntimeError(f"empty dataset: {path}")
    features = torch.empty((count, INPUT_SIZE_V2), dtype=torch.float32)
    families = torch.empty(count, dtype=torch.long)
    sizes = torch.empty(count, dtype=torch.long)
    legal = torch.empty((count, FAMILY_OUTPUT_SIZE), dtype=torch.bool)
    family_counts: Counter[int] = Counter()
    size_counts: Counter[int] = Counter()
    offset = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("data_version") != expected_data_version:
                raise RuntimeError(
                    f"data_version mismatch in {path}:{line_number}: "
                    f"expected {expected_data_version!r}, got {row.get('data_version')!r}"
                )
            family, size = hierarchical_target(row)
            mask = legal_family_mask(row)
            if not mask[family]:
                raise RuntimeError(f"target is illegal in {path}:{line_number}: {FAMILY_ACTIONS[family]}")
            features[offset] = torch.tensor(decision_features_v2(row), dtype=torch.float32)
            families[offset] = family
            sizes[offset] = size
            legal[offset] = torch.tensor(mask, dtype=torch.bool)
            family_counts[family] += 1
            if size >= 0:
                size_counts[size] += 1
            offset += 1
    return TensorDataset(features, families, sizes, legal), family_counts, size_counts


def class_weights(counts: Counter[int], classes: int, mode: str, maximum: float) -> torch.Tensor:
    if mode == "none":
        return torch.ones(classes, dtype=torch.float32)
    total = sum(counts.values())
    values = [math.sqrt(total / (classes * max(1, counts[index]))) for index in range(classes)]
    return torch.tensor([min(maximum, value) for value in values], dtype=torch.float32)


def _summary(confusion: list[list[int]]) -> dict:
    classes = len(confusion)
    actual = [sum(row) for row in confusion]
    predicted = [sum(confusion[row][column] for row in range(classes)) for column in range(classes)]
    precision = [confusion[i][i] / predicted[i] if predicted[i] else 0.0 for i in range(classes)]
    recall = [confusion[i][i] / actual[i] if actual[i] else 0.0 for i in range(classes)]
    f1 = [
        2 * precision[i] * recall[i] / (precision[i] + recall[i]) if precision[i] + recall[i] else 0.0
        for i in range(classes)
    ]
    present = [index for index, support in enumerate(actual) if support]
    return {
        "accuracy": sum(confusion[i][i] for i in range(classes)) / max(1, sum(actual)),
        "balanced_accuracy": sum(recall[i] for i in present) / max(1, len(present)),
        "macro_f1": sum(f1[i] for i in present) / max(1, len(present)),
        "support": actual,
        "predicted": predicted,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def masked_family_logits(logits, legal):
    return logits.masked_fill(~legal, torch.finfo(logits.dtype).min)


class MaskedCrossEntropy(nn.Module):
    """Cross entropy whose label smoothing distributes mass over legal actions only."""

    def __init__(self, weights: torch.Tensor, label_smoothing: float):
        super().__init__()
        self.register_buffer("weights", weights)
        self.label_smoothing = label_smoothing

    def forward(self, logits, targets, legal):
        masked = masked_family_logits(logits, legal)
        log_probabilities = torch.log_softmax(masked, dim=1)
        nll = -log_probabilities.gather(1, targets[:, None]).squeeze(1)
        legal_log_probabilities = log_probabilities.masked_fill(~legal, 0.0)
        smooth = -legal_log_probabilities.sum(dim=1) / legal.sum(dim=1).clamp_min(1)
        losses = (1.0 - self.label_smoothing) * nll + self.label_smoothing * smooth
        sample_weights = self.weights[targets]
        return (losses * sample_weights).sum() / sample_weights.sum().clamp_min(1e-12)


def evaluate(model, loader, device, family_criterion, size_criterion, size_loss_weight: float) -> dict:
    model.eval()
    family_loss_sum = size_loss_sum = 0.0
    family_count = size_count = top3 = combined_correct = 0
    family_confusion = [[0] * FAMILY_OUTPUT_SIZE for _ in range(FAMILY_OUTPUT_SIZE)]
    size_confusion = [[0] * SIZE_OUTPUT_SIZE for _ in range(SIZE_OUTPUT_SIZE)]
    action_confusion = [[0] * 10 for _ in range(10)]
    with torch.inference_mode():
        for inputs, families, sizes, legal in loader:
            inputs = inputs.to(device)
            families = families.to(device)
            sizes = sizes.to(device)
            legal = legal.to(device)
            family_logits, size_logits = model(inputs)
            batch_count = families.numel()
            family_loss_sum += family_criterion(family_logits, families, legal).item() * batch_count
            family_count += batch_count
            family_logits = masked_family_logits(family_logits, legal)
            family_guess = family_logits.argmax(1)
            size_guess = size_logits.argmax(1)
            top3 += (family_logits.topk(3, dim=1).indices == families[:, None]).any(dim=1).sum().item()
            raise_rows = sizes >= 0
            if raise_rows.any():
                selected_sizes = sizes[raise_rows]
                size_loss_sum += size_criterion(size_logits[raise_rows], selected_sizes).item() * selected_sizes.numel()
                size_count += selected_sizes.numel()
            for actual_family, guessed_family, actual_size, guessed_size in zip(
                families.cpu().tolist(), family_guess.cpu().tolist(), sizes.cpu().tolist(), size_guess.cpu().tolist()
            ):
                family_confusion[actual_family][guessed_family] += 1
                if actual_size >= 0:
                    size_confusion[actual_size][guessed_size] += 1
                actual_action = actual_family if actual_family <= 2 else (3 + actual_size if actual_family == 3 else 9)
                guessed_action = guessed_family if guessed_family <= 2 else (3 + guessed_size if guessed_family == 3 else 9)
                action_confusion[actual_action][guessed_action] += 1
                combined_correct += int(actual_action == guessed_action)
    family_metrics = _summary(family_confusion)
    size_metrics = _summary(size_confusion)
    action_metrics = _summary(action_confusion)
    selection_score = (
        0.50 * family_metrics["macro_f1"]
        + 0.30 * family_metrics["accuracy"]
        + 0.20 * size_metrics["accuracy"]
    )
    return {
        "loss": family_loss_sum / family_count + size_loss_weight * size_loss_sum / max(1, size_count),
        "family_loss": family_loss_sum / family_count,
        "size_loss": size_loss_sum / max(1, size_count),
        "family_top3": top3 / family_count,
        "combined_accuracy": combined_correct / family_count,
        "selection_score": selection_score,
        "family": family_metrics,
        "size": size_metrics,
        "action": action_metrics,
        "family_confusion": family_confusion,
        "size_confusion": size_confusion,
        "action_confusion": action_confusion,
    }


def export_model(model: HierarchicalBehaviorMLP, args, path: Path) -> None:
    trunk_layers = [layer for layer in model.trunk if isinstance(layer, nn.Linear)]
    value = {
        "format": "agx-poker-bc-v2",
        "data_version": args.data_version,
        "feature_version": "public-replay-features-v2",
        "input_size": INPUT_SIZE_V2,
        "hidden1_size": args.hidden1,
        "hidden2_size": args.hidden2,
        "family_actions": list(FAMILY_ACTIONS),
        "size_actions": list(SIZE_ACTIONS),
        "trunk_w1": trunk_layers[0].weight.detach().cpu().tolist(),
        "trunk_b1": trunk_layers[0].bias.detach().cpu().tolist(),
        "trunk_w2": trunk_layers[1].weight.detach().cpu().tolist(),
        "trunk_b2": trunk_layers[1].bias.detach().cpu().tolist(),
        "family_w": model.family_head.weight.detach().cpu().tolist(),
        "family_b": model.family_head.bias.detach().cpu().tolist(),
        "size_w": model.size_head.weight.detach().cpu().tolist(),
        "size_b": model.size_head.bias.detach().cpu().tolist(),
    }
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def compact_metrics(value: dict) -> dict:
    return {
        "loss": value["loss"],
        "selection_score": value["selection_score"],
        "family_accuracy": value["family"]["accuracy"],
        "family_macro_f1": value["family"]["macro_f1"],
        "family_balanced_accuracy": value["family"]["balanced_accuracy"],
        "family_top3": value["family_top3"],
        "raise_size_accuracy": value["size"]["accuracy"],
        "combined_10_action_accuracy": value["combined_accuracy"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="训练合法动作掩码与分层动作头的公开回放行为克隆 v2")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "poker-distill" / "data" / "parsed-decisions")
    parser.add_argument("--data-version", help="预期的数据版本；默认从训练集首行读取并校验全部划分")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "neural" / "artifacts" / "behavior-v2")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--hidden1", type=int, default=192)
    parser.add_argument("--hidden2", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--label-smoothing", type=float, default=0.03)
    parser.add_argument("--size-loss-weight", type=float, default=0.5)
    parser.add_argument("--class-weighting", choices=("none", "sqrt"), default="sqrt")
    parser.add_argument("--max-class-weight", type=float, default=3.0)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--loader-workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=7607)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--skip-test", action="store_true")
    args = parser.parse_args()
    args.data_version = args.data_version or detected_data_version(args.data_dir / "train.jsonl")

    load_and_check_rules()
    status = load_status()
    if not status["ready_for_large_scale_distillation"]:
        raise RuntimeError("100-match replay validation gate is not ready")
    if args.epochs < 1 or args.batch_size < 1 or args.patience < 1 or args.size_loss_weight < 0:
        raise RuntimeError("training parameters must be positive")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    chosen = "cuda" if args.device == "auto" and torch.cuda.is_available() else ("cpu" if args.device == "auto" else args.device)
    device = torch.device(chosen)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    train_set, train_family_counts, train_size_counts = dataset(args.data_dir / "train.jsonl", args.data_version)
    validation_set, validation_family_counts, validation_size_counts = dataset(args.data_dir / "validation.jsonl", args.data_version)
    options = {"batch_size": args.batch_size, "num_workers": args.loader_workers, "pin_memory": device.type == "cuda"}
    train_loader = DataLoader(train_set, shuffle=True, **options)
    validation_loader = DataLoader(validation_set, shuffle=False, **options)
    family_weights = class_weights(train_family_counts, FAMILY_OUTPUT_SIZE, args.class_weighting, args.max_class_weight).to(device)
    size_weights = class_weights(train_size_counts, SIZE_OUTPUT_SIZE, args.class_weighting, args.max_class_weight).to(device)
    family_criterion = MaskedCrossEntropy(family_weights, args.label_smoothing)
    size_criterion = nn.CrossEntropyLoss(weight=size_weights, label_smoothing=args.label_smoothing)
    model = HierarchicalBehaviorMLP(args.hidden1, args.hidden2).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)

    started = time.perf_counter()
    best_score = -1.0
    best_state = None
    best_epoch = 0
    stale = 0
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        for inputs, families, sizes, legal in train_loader:
            inputs = inputs.to(device)
            families = families.to(device)
            sizes = sizes.to(device)
            legal = legal.to(device)
            optimizer.zero_grad(set_to_none=True)
            family_logits, size_logits = model(inputs)
            loss = family_criterion(family_logits, families, legal)
            raise_rows = sizes >= 0
            if raise_rows.any():
                loss = loss + args.size_loss_weight * size_criterion(size_logits[raise_rows], sizes[raise_rows])
            loss.backward()
            optimizer.step()
        metrics = evaluate(model, validation_loader, device, family_criterion, size_criterion, args.size_loss_weight)
        compact = {"epoch": epoch, **compact_metrics(metrics)}
        history.append(compact)
        print(
            f"epoch {epoch:03d} score={metrics['selection_score']:.4f} "
            f"family_acc={metrics['family']['accuracy']:.2%} family_f1={metrics['family']['macro_f1']:.2%} "
            f"size_acc={metrics['size']['accuracy']:.2%} combined={metrics['combined_accuracy']:.2%}",
            flush=True,
        )
        if metrics["selection_score"] > best_score + 1e-5:
            best_score = metrics["selection_score"]
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            best_epoch = epoch
            stale = 0
        else:
            stale += 1
            if stale >= args.patience:
                break
    if best_state is None:
        raise RuntimeError("training produced no checkpoint")
    model.load_state_dict(best_state)
    model.to(device)
    validation_metrics = evaluate(model, validation_loader, device, family_criterion, size_criterion, args.size_loss_weight)
    test_metrics = None
    test_counts = None
    if not args.skip_test:
        test_set, test_family_counts, test_size_counts = dataset(args.data_dir / "test.jsonl", args.data_version)
        test_loader = DataLoader(test_set, shuffle=False, **options)
        test_metrics = evaluate(model, test_loader, device, family_criterion, size_criterion, args.size_loss_weight)
        test_counts = {
            "examples": len(test_set),
            "family": {FAMILY_ACTIONS[i]: test_family_counts[i] for i in range(FAMILY_OUTPUT_SIZE)},
            "raise_size": {SIZE_ACTIONS[i]: test_size_counts[i] for i in range(SIZE_OUTPUT_SIZE)},
        }

    checkpoint = {
        "format": "agx-poker-bc-v2",
        "data_version": args.data_version,
        "feature_version": "public-replay-features-v2",
        "model_state": model.state_dict(),
        "input_size": INPUT_SIZE_V2,
        "hidden1_size": args.hidden1,
        "hidden2_size": args.hidden2,
        "family_actions": FAMILY_ACTIONS,
        "size_actions": SIZE_ACTIONS,
        "seed": args.seed,
    }
    torch.save(checkpoint, args.output_dir / "model.pt")
    export_model(model, args, args.output_dir / "model.json")
    report = {
        "format": "agx-poker-bc-training-v2",
        "data_version": args.data_version,
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "seed": args.seed,
        "best_epoch": best_epoch,
        "train_examples": len(train_set),
        "validation_examples": len(validation_set),
        "train_family_counts": {FAMILY_ACTIONS[i]: train_family_counts[i] for i in range(FAMILY_OUTPUT_SIZE)},
        "train_raise_size_counts": {SIZE_ACTIONS[i]: train_size_counts[i] for i in range(SIZE_OUTPUT_SIZE)},
        "validation_family_counts": {FAMILY_ACTIONS[i]: validation_family_counts[i] for i in range(FAMILY_OUTPUT_SIZE)},
        "validation_raise_size_counts": {SIZE_ACTIONS[i]: validation_size_counts[i] for i in range(SIZE_OUTPUT_SIZE)},
        "family_class_weights": family_weights.detach().cpu().tolist(),
        "raise_size_class_weights": size_weights.detach().cpu().tolist(),
        "validation": {**compact_metrics(validation_metrics), "family": validation_metrics["family"], "size": validation_metrics["size"], "action": validation_metrics["action"], "family_confusion": validation_metrics["family_confusion"], "size_confusion": validation_metrics["size_confusion"], "action_confusion": validation_metrics["action_confusion"]},
        "test_counts": test_counts,
        "test": None if test_metrics is None else {**compact_metrics(test_metrics), "family": test_metrics["family"], "size": test_metrics["size"], "action": test_metrics["action"], "family_confusion": test_metrics["family_confusion"], "size_confusion": test_metrics["size_confusion"], "action_confusion": test_metrics["action_confusion"]},
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "history": history,
    }
    (args.output_dir / "training_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"best_epoch": best_epoch, "validation": compact_metrics(validation_metrics), "test": None if test_metrics is None else compact_metrics(test_metrics), "output": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
