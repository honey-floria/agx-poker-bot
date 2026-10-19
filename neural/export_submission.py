#!/usr/bin/env python3
"""Embed a trained neural model into a standalone QuickJS submission."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from competition_rules import load_and_check_rules


def main():
    root = ROOT
    rules = load_and_check_rules()
    parser = argparse.ArgumentParser(description="导出单文件神经网络扑克 AI")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path(__file__).resolve().parent / "artifacts" / "model.json",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=Path(__file__).resolve().parent / "submission_nn.template.js",
    )
    parser.add_argument("--output", type=Path, default=root / "submission_nn.js")
    args = parser.parse_args()

    model = json.loads(args.model.read_text(encoding="utf-8"))
    required = {
        "format", "input_size", "hidden1_size", "hidden2_size", "output_size",
        "w1", "b1", "w2", "b2", "w3", "b3",
    }
    missing = required - set(model)
    if missing:
        raise SystemExit(f"模型缺少字段：{sorted(missing)}")
    if model["format"] != "agx-poker-mlp-v2":
        raise SystemExit("模型格式不是 agx-poker-mlp-v2")
    if model["input_size"] != 32 or model["output_size"] != 4:
        raise SystemExit("模型维度与提交模板不兼容")
    if len(model["w1"]) != model["hidden1_size"] or any(len(row) != 32 for row in model["w1"]):
        raise SystemExit("w1 维度错误")
    if len(model["b1"]) != model["hidden1_size"]:
        raise SystemExit("b1 维度错误")
    if len(model["w2"]) != model["hidden2_size"] or any(
        len(row) != model["hidden1_size"] for row in model["w2"]
    ):
        raise SystemExit("w2 维度错误")
    if len(model["b2"]) != model["hidden2_size"]:
        raise SystemExit("b2 维度错误")
    if len(model["w3"]) != 4 or any(len(row) != model["hidden2_size"] for row in model["w3"]):
        raise SystemExit("w3 维度错误")
    if len(model["b3"]) != 4:
        raise SystemExit("b3 维度错误")

    runtime_model = {
        "input_size": model["input_size"],
        "hidden1_size": model["hidden1_size"],
        "hidden2_size": model["hidden2_size"],
        "output_size": model["output_size"],
        "w1": model["w1"],
        "b1": model["b1"],
        "w2": model["w2"],
        "b2": model["b2"],
        "w3": model["w3"],
        "b3": model["b3"],
    }
    template = args.template.read_text(encoding="utf-8")
    placeholder = "__MODEL_JSON__"
    if template.count(placeholder) != 1:
        raise SystemExit("模板中的模型占位符数量不等于1")
    source = template.replace(
        placeholder,
        json.dumps(runtime_model, ensure_ascii=False, separators=(",", ":")),
    )
    if len(source.encode("utf-8")) > rules["limits"]["sourceBytes"]:
        raise SystemExit(f"导出的提交文件超过{rules['limits']['sourceBytes']}字节")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding="utf-8")
    print(f"已导出：{args.output}")
    print(f"文件大小：{len(source.encode('utf-8'))} bytes")


if __name__ == "__main__":
    main()
