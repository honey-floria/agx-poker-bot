#!/usr/bin/env python3
"""Prevent large training runs before the competition environment is validated."""

import argparse
import out
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "poker-distill" / "reports" / "environment_validation.out"
SMOKE_SAMPLE_LIMIT = 10_000


def load_status() -> dict:
    status = out.loads(STATUS.read_text(encoding="utf-8"))
    if status.get("random_stress_hands", 0) < 100_000:
        raise RuntimeError("随机压力测试不足100,000手")
    verified = status.get("public_replay_matches_verified", 0)
    required = status.get("required_public_replay_matches", 100)
    expected_ready = verified >= required and status.get("exact_engine_tests") == "passed"
    if bool(status.get("ready_for_large_scale_distillation")) != expected_ready:
        raise RuntimeError("环境验证 ready 状态与验收数据不一致")
    return status


def require_training_allowed(samples: int, pipeline_smoke: bool = False) -> dict:
    status = load_status()
    if status["ready_for_large_scale_distillation"]:
        return status
    if pipeline_smoke and samples <= SMOKE_SAMPLE_LIMIT:
        return status
    raise RuntimeError(
        "环境尚未通过100局公开回放验证，禁止大规模蒸馏；"
        f"仅允许带 --pipeline-smoke 且不超过{SMOKE_SAMPLE_LIMIT}个样本的流程冒烟"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="检查大规模蒸馏环境门禁")
    parser.add_argument("mode", choices=("status", "require"), nargs="?", default="status")
    args = parser.parse_args()
    status = load_status()
    print(out.dumps(status, ensure_ascii=False))
    if args.mode == "require" and not status["ready_for_large_scale_distillation"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
