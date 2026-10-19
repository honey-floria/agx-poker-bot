#!/usr/bin/env python3
"""Prevent large training runs before the competition environment is validated."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "poker-distill" / "reports" / "environment_validation.json"
SMOKE_SAMPLE_LIMIT = 10_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if ROOT.resolve() not in path.parents:
        raise RuntimeError("环境验收证据路径越出项目目录")
    return path


def validate_ready_evidence(status: dict) -> None:
    report_path = evidence_path(status.get("replay_validation_report", ""))
    manifest_path = evidence_path(status.get("replay_dataset_manifest", ""))
    if not report_path.is_file() or not manifest_path.is_file():
        raise RuntimeError("环境已标记 ready，但回放验证证据不存在")
    if sha256_file(report_path) != status.get("replay_validation_report_sha256"):
        raise RuntimeError("回放验证报告哈希不一致")
    if sha256_file(manifest_path) != status.get("replay_dataset_manifest_sha256"):
        raise RuntimeError("回放数据清单哈希不一致")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verified = int(status["public_replay_matches_verified"])
    if report.get("schema") != "agx.replay-validation.v1":
        raise RuntimeError("回放验证报告 schema 不受支持")
    if report.get("verified_matches") != verified or report.get("failed_matches") != 0:
        raise RuntimeError("回放验证报告与 ready 状态不一致")
    if manifest.get("schema") != "agx.behavior-dataset.v1" or manifest.get("matches") != verified:
        raise RuntimeError("行为数据清单与已验证对局数不一致")
    split_ids = manifest.get("split_match_ids", {})
    sets = [set(split_ids.get(name, [])) for name in ("train", "validation", "test")]
    if any(sets[i] & sets[j] for i in range(3) for j in range(i + 1, 3)):
        raise RuntimeError("数据切分存在 match 泄漏")
    if len(set().union(*sets)) != verified:
        raise RuntimeError("数据切分没有覆盖全部已验证对局")


def load_status() -> dict:
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    if status.get("random_stress_hands", 0) < 100_000:
        raise RuntimeError("随机压力测试不足100,000手")
    verified = status.get("public_replay_matches_verified", 0)
    required = status.get("required_public_replay_matches", 100)
    expected_ready = verified >= required and status.get("exact_engine_tests") == "passed"
    if bool(status.get("ready_for_large_scale_distillation")) != expected_ready:
        raise RuntimeError("环境验证 ready 状态与验收数据不一致")
    if expected_ready:
        validate_ready_evidence(status)
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
    print(json.dumps(status, ensure_ascii=False))
    if args.mode == "require" and not status["ready_for_large_scale_distillation"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
