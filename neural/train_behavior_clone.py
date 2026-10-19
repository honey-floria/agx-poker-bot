#!/usr/bin/env python3
"""Train a 10-action behavior clone from verified public replay decisions."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import random
from pathlib import Path
import sys
import time

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from replay_data import ACTIONS, INPUT_SIZE, OUTPUT_SIZE, decision_features, load_jsonl


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from competition_rules import load_and_check_rules  # noqa: E402
from environment_gate import load_status  # noqa: E402


class BehaviorMLP(nn.Module):
    def __init__(self, hidden1: int, hidden2: int):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(INPUT_SIZE, hidden1), nn.ReLU(),
            nn.Linear(hidden1, hidden2), nn.ReLU(),
            nn.Linear(hidden2, OUTPUT_SIZE),
        )

    def forward(self, inputs):
        return self.layers(inputs)


def dataset(path: Path) -> tuple[TensorDataset, Counter[int]]:
    rows = load_jsonl(path)
    if not rows:
        raise RuntimeError(f"empty dataset: {path}")
    features = [decision_features(row) for row in rows]
    labels = [int(row["action_index"]) for row in rows]
    if any(not 0 <= label < OUTPUT_SIZE for label in labels):
        raise RuntimeError(f"invalid action index in {path}")
    return TensorDataset(torch.tensor(features, dtype=torch.float32), torch.tensor(labels, dtype=torch.long)), Counter(labels)


def evaluate(model, loader, device, criterion) -> tuple[float, float, float, list[list[int]]]:
    model.eval()
    loss_sum = correct = top3 = count = 0
    confusion = [[0] * OUTPUT_SIZE for _ in range(OUTPUT_SIZE)]
    with torch.inference_mode():
        for inputs, labels in loader:
            inputs, labels = inputs.to(device), labels.to(device)
            logits = model(inputs)
            loss_sum += criterion(logits, labels).item() * labels.numel()
            predicted = logits.argmax(1)
            correct += (predicted == labels).sum().item()
            top3 += (logits.topk(3, dim=1).indices == labels[:, None]).any(dim=1).sum().item()
            count += labels.numel()
            for actual, guess in zip(labels.cpu().tolist(), predicted.cpu().tolist()):
                confusion[actual][guess] += 1
    return loss_sum / count, correct / count, top3 / count, confusion


def export_model(model: BehaviorMLP, args, path: Path) -> None:
    layers = [layer for layer in model.layers if isinstance(layer, nn.Linear)]
    value = {
        "format": "agx-poker-bc-v1",
        "data_version": "public-replay-bc-v1",
        "input_size": INPUT_SIZE,
        "hidden1_size": args.hidden1,
        "hidden2_size": args.hidden2,
        "output_size": OUTPUT_SIZE,
        "actions": list(ACTIONS),
    }
    for index, layer in enumerate(layers, start=1):
        value[f"w{index}"] = layer.weight.detach().cpu().tolist()
        value[f"b{index}"] = layer.bias.detach().cpu().tolist()
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="训练公开回放10动作行为克隆模型")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "poker-distill" / "data" / "parsed-decisions")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "neural" / "artifacts" / "behavior-v1")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--hidden1", type=int, default=192)
    parser.add_argument("--hidden2", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--label-smoothing", type=float, default=0.05)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--loader-workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7607)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    args = parser.parse_args()

    load_and_check_rules()
    status = load_status()
    if not status["ready_for_large_scale_distillation"]:
        raise RuntimeError("100-match replay validation gate is not ready")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    chosen = "cuda" if args.device == "auto" and torch.cuda.is_available() else ("cpu" if args.device == "auto" else args.device)
    device = torch.device(chosen)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    train_set, train_counts = dataset(args.data_dir / "train.jsonl")
    validation_set, validation_counts = dataset(args.data_dir / "validation.jsonl")
    options = {"batch_size": args.batch_size, "num_workers": args.loader_workers, "pin_memory": device.type == "cuda"}
    train_loader = DataLoader(train_set, shuffle=True, **options)
    validation_loader = DataLoader(validation_set, shuffle=False, **options)
    counts = torch.tensor([max(1, train_counts[index]) for index in range(OUTPUT_SIZE)], dtype=torch.float32)
    weights = (counts.sum() / (OUTPUT_SIZE * counts)).clamp(max=10.0).to(device)
    criterion = nn.CrossEntropyLoss(weight=weights, label_smoothing=args.label_smoothing)
    model = BehaviorMLP(args.hidden1, args.hidden2).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)

    started = time.perf_counter()
    best_loss = float("inf")
    best_state = None
    stale = 0
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        for inputs, labels in train_loader:
            inputs, labels = inputs.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(inputs), labels)
            loss.backward()
            optimizer.step()
        loss, accuracy, top3, _ = evaluate(model, validation_loader, device, criterion)
        history.append({"epoch": epoch, "validation_loss": loss, "validation_accuracy": accuracy, "validation_top3": top3})
        print(f"epoch {epoch:03d} val_loss={loss:.5f} top1={accuracy:.2%} top3={top3:.2%}", flush=True)
        if loss < best_loss - 1e-5:
            best_loss = loss
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= args.patience:
                break
    if best_state is None:
        raise RuntimeError("training produced no checkpoint")
    model.load_state_dict(best_state)
    model.to(device)
    loss, accuracy, top3, confusion = evaluate(model, validation_loader, device, criterion)
    torch.save({
        "format": "agx-poker-bc-v1", "model_state": model.state_dict(),
        "input_size": INPUT_SIZE, "hidden1_size": args.hidden1,
        "hidden2_size": args.hidden2, "output_size": OUTPUT_SIZE,
        "actions": ACTIONS, "seed": args.seed,
    }, args.output_dir / "model.pt")
    export_model(model, args, args.output_dir / "model.json")
    report = {
        "format": "agx-poker-bc-training-v1",
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "train_examples": len(train_set), "validation_examples": len(validation_set),
        "train_action_counts": {ACTIONS[i]: train_counts[i] for i in range(OUTPUT_SIZE)},
        "validation_action_counts": {ACTIONS[i]: validation_counts[i] for i in range(OUTPUT_SIZE)},
        "best_validation_loss": loss, "best_validation_accuracy": accuracy,
        "best_validation_top3": top3, "confusion_matrix": confusion,
        "elapsed_seconds": round(time.perf_counter() - started, 3), "history": history,
    }
    (args.output_dir / "training_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"validation_accuracy": accuracy, "validation_top3": top3, "output": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
