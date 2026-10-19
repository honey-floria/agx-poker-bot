#!/usr/bin/env python3
"""Generate oracle-labelled poker states and train a compact CUDA MLP."""

import argparse
import json
import os
import random
import time
from collections import Counter
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset, random_split

from data import INPUT_SIZE, LABELS, OUTPUT_SIZE, generate_dataset, load_dataset, save_dataset


class PokerMLP(nn.Module):
    def __init__(self, hidden1, hidden2):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(INPUT_SIZE, hidden1),
            nn.ReLU(),
            nn.Linear(hidden1, hidden2),
            nn.ReLU(),
            nn.Linear(hidden2, OUTPUT_SIZE),
        )

    def forward(self, inputs):
        return self.layers(inputs)


def parse_args():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="训练可导出到 QuickJS 的德州扑克 MLP")
    parser.add_argument("--samples", type=int, default=100_000, help="合成训练状态数量")
    parser.add_argument("--mc-samples", type=int, default=32, help="每个状态的蒙特卡洛试验数")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--hidden1", type=int, default=64)
    parser.add_argument("--hidden2", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--validation-ratio", type=float, default=0.15)
    parser.add_argument("--patience", type=int, default=8)
    parser.add_argument("--workers", type=int, default=max(1, min(24, (os.cpu_count() or 2) - 1)))
    parser.add_argument("--loader-workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7607)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--reuse-data", action="store_true", help="若数据集存在则直接复用")
    parser.add_argument("--output-dir", type=Path, default=root / "artifacts")
    return parser.parse_args()


def choose_device(requested):
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise SystemExit("指定了 CUDA，但 torch.cuda.is_available() 为 False")
        return torch.device("cuda")
    if requested == "cpu":
        return torch.device("cpu")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def accuracy_and_confusion(model, loader, device, criterion):
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    confusion = [[0 for _ in range(OUTPUT_SIZE)] for _ in range(OUTPUT_SIZE)]
    with torch.inference_mode():
        for inputs, labels in loader:
            inputs = inputs.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)
            logits = model(inputs)
            total_loss += criterion(logits, labels).item() * labels.numel()
            predictions = logits.argmax(dim=1)
            correct += (predictions == labels).sum().item()
            total += labels.numel()
            for actual, predicted in zip(labels.cpu().tolist(), predictions.cpu().tolist()):
                confusion[actual][predicted] += 1
    return total_loss / max(1, total), correct / max(1, total), confusion


def export_json(model, args, output):
    linears = [layer for layer in model.layers if isinstance(layer, nn.Linear)]
    payload = {
        "format": "agx-poker-mlp-v2",
        "input_size": INPUT_SIZE,
        "hidden1_size": args.hidden1,
        "hidden2_size": args.hidden2,
        "output_size": OUTPUT_SIZE,
        "w1": linears[0].weight.detach().cpu().tolist(),
        "b1": linears[0].bias.detach().cpu().tolist(),
        "w2": linears[1].weight.detach().cpu().tolist(),
        "b2": linears[1].bias.detach().cpu().tolist(),
        "w3": linears[2].weight.detach().cpu().tolist(),
        "b3": linears[2].bias.detach().cpu().tolist(),
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    args = parse_args()
    if args.samples < 100 or args.mc_samples < 1:
        raise SystemExit("samples 至少为100，mc-samples 至少为1")
    if not 0.01 <= args.validation_ratio <= 0.5:
        raise SystemExit("validation-ratio 必须位于0.01到0.5之间")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    device = choose_device(args.device)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = args.output_dir / "dataset.jsonl"

    print(f"PyTorch：{torch.__version__}")
    print(f"训练设备：{device}")
    if device.type == "cuda":
        print(f"GPU：{torch.cuda.get_device_name(0)}")

    started = time.perf_counter()
    if args.reuse_data and dataset_path.exists():
        print(f"复用数据集：{dataset_path}")
        examples = load_dataset(dataset_path)
    else:
        print(f"生成 {args.samples} 个状态，每状态 {args.mc_samples} 次蒙特卡洛，进程数 {args.workers}")
        examples = generate_dataset(args.samples, args.seed, args.mc_samples, args.workers)
        save_dataset(dataset_path, examples)
        print(f"数据集已保存：{dataset_path}")

    label_counts = Counter(label for _, label in examples)
    print("标签分布：" + "，".join(f"{LABELS[index]}={label_counts[index]}" for index in range(OUTPUT_SIZE)))
    inputs = torch.tensor([features for features, _ in examples], dtype=torch.float32)
    labels = torch.tensor([label for _, label in examples], dtype=torch.long)
    full_dataset = TensorDataset(inputs, labels)
    validation_size = max(1, round(len(full_dataset) * args.validation_ratio))
    train_size = len(full_dataset) - validation_size
    generator = torch.Generator().manual_seed(args.seed)
    train_set, validation_set = random_split(full_dataset, [train_size, validation_size], generator=generator)

    loader_options = {
        "batch_size": args.batch_size,
        "num_workers": args.loader_workers,
        "pin_memory": device.type == "cuda",
        "persistent_workers": args.loader_workers > 0,
    }
    train_loader = DataLoader(train_set, shuffle=True, **loader_options)
    validation_loader = DataLoader(validation_set, shuffle=False, **loader_options)

    counts = torch.tensor([max(1, label_counts[index]) for index in range(OUTPUT_SIZE)], dtype=torch.float32)
    class_weights = counts.sum() / (OUTPUT_SIZE * counts)
    criterion = nn.CrossEntropyLoss(weight=class_weights.to(device))
    model = PokerMLP(args.hidden1, args.hidden2).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=device.type == "cuda")

    best_loss = float("inf")
    best_state = None
    stale_epochs = 0
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0
        for batch_inputs, batch_labels in train_loader:
            batch_inputs = batch_inputs.to(device, non_blocking=True)
            batch_labels = batch_labels.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=device.type == "cuda"):
                logits = model(batch_inputs)
                loss = criterion(logits, batch_labels)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            train_loss += loss.item() * batch_labels.numel()
            train_correct += (logits.argmax(dim=1) == batch_labels).sum().item()
            train_total += batch_labels.numel()

        train_loss /= max(1, train_total)
        train_accuracy = train_correct / max(1, train_total)
        validation_loss, validation_accuracy, confusion = accuracy_and_confusion(
            model, validation_loader, device, criterion
        )
        record = {
            "epoch": epoch,
            "train_loss": train_loss,
            "train_accuracy": train_accuracy,
            "validation_loss": validation_loss,
            "validation_accuracy": validation_accuracy,
        }
        history.append(record)
        print(
            f"epoch {epoch:03d} | train loss {train_loss:.5f} acc {train_accuracy:.2%} "
            f"| val loss {validation_loss:.5f} acc {validation_accuracy:.2%}",
            flush=True,
        )
        if validation_loss < best_loss - 1e-5:
            best_loss = validation_loss
            best_state = {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= args.patience:
                print(f"验证损失连续 {args.patience} 轮未改善，提前停止")
                break

    if best_state is None:
        raise RuntimeError("训练没有产生可保存模型")
    model.load_state_dict(best_state)
    model.to(device)
    final_loss, final_accuracy, confusion = accuracy_and_confusion(model, validation_loader, device, criterion)
    checkpoint = {
        "format": "agx-poker-mlp-v2",
        "model_state": model.state_dict(),
        "input_size": INPUT_SIZE,
        "hidden1_size": args.hidden1,
        "hidden2_size": args.hidden2,
        "output_size": OUTPUT_SIZE,
        "seed": args.seed,
    }
    torch.save(checkpoint, args.output_dir / "model.pt")
    export_json(model, args, args.output_dir / "model.json")
    report = {
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "samples": len(examples),
        "mc_samples": args.mc_samples,
        "label_counts": {LABELS[index]: label_counts[index] for index in range(OUTPUT_SIZE)},
        "best_validation_loss": final_loss,
        "best_validation_accuracy": final_accuracy,
        "confusion_matrix_rows_actual_columns_predicted": confusion,
        "elapsed_seconds": time.perf_counter() - started,
        "history": history,
    }
    (args.output_dir / "training_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"最佳验证准确率：{final_accuracy:.2%}")
    print(f"混淆矩阵（行=真实，列=预测）：{confusion}")
    print(f"模型已保存：{args.output_dir / 'model.pt'}")
    print(f"导出权重：{args.output_dir / 'model.json'}")


if __name__ == "__main__":
    main()
