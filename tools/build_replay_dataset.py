#!/usr/bin/env python3
"""Verify complete replay aggregates and build leak-free behavior data splits."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "poker-distill" / "replay-parser"))
sys.path.insert(0, str(ROOT / "neural"))
from parse_replay import parse_match  # noqa: E402
from replay_data import ACTIONS, action_bucket  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def assign_splits(job_ids: list[str], seed: int, train_ratio: float, validation_ratio: float) -> dict[str, str]:
    ordered = sorted(job_ids, key=lambda job_id: hashlib.sha256(f"{seed}:{job_id}".encode()).hexdigest())
    train_end = round(len(ordered) * train_ratio)
    validation_end = train_end + round(len(ordered) * validation_ratio)
    return {
        job_id: ("train" if index < train_end else "validation" if index < validation_end else "test")
        for index, job_id in enumerate(ordered)
    }


def update_gate(status_path: Path, report_path: Path, manifest_path: Path, success: bool, verified: int, required: int) -> None:
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update({
        "public_replay_matches_verified": verified,
        "required_public_replay_matches": required,
        "ready_for_large_scale_distillation": bool(success and verified >= required),
        "replay_validation_report": str(report_path.relative_to(ROOT)),
        "replay_validation_report_sha256": sha256_file(report_path),
        "replay_dataset_manifest": str(manifest_path.relative_to(ROOT)) if manifest_path.exists() else None,
        "replay_dataset_manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else None,
        "block_reason": None if success and verified >= required else f"{max(0, required - verified)} more verified replay matches required",
    })
    status.pop("verified_replays", None)
    write_json_atomic(status_path, status)


def main() -> None:
    parser = argparse.ArgumentParser(description="验证完整公开回放并构建按对局隔离的数据集")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=ROOT / "poker-distill" / "reports" / "replay_validation_100.json")
    parser.add_argument("--dataset-manifest", type=Path, default=ROOT / "poker-distill" / "reports" / "replay_dataset_manifest.json")
    parser.add_argument("--status", type=Path, default=ROOT / "poker-distill" / "reports" / "environment_validation.json")
    parser.add_argument("--required", type=int, default=100)
    parser.add_argument("--seed", type=int, default=7607)
    parser.add_argument("--train-ratio", type=float, default=0.80)
    parser.add_argument("--validation-ratio", type=float, default=0.10)
    parser.add_argument("--update-gate", action="store_true")
    args = parser.parse_args()
    if args.required < 1 or args.train_ratio <= 0 or args.validation_ratio <= 0:
        raise SystemExit("required and split ratios must be positive")
    if args.train_ratio + args.validation_ratio >= 1:
        raise SystemExit("train-ratio + validation-ratio must be below 1")

    source_manifest_path = args.raw_dir / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("failures"):
        raise SystemExit("download manifest contains failures")
    completed = source_manifest.get("completed", [])
    by_id = {row.get("job_id"): row for row in completed}
    selected_ids = source_manifest.get("selection", {}).get("job_ids", [])
    if len(selected_ids) < args.required or len(set(selected_ids[:args.required])) != args.required:
        raise SystemExit(f"download manifest does not contain {args.required} unique selected jobs")
    selected_ids = selected_ids[:args.required]
    split_for = assign_splits(selected_ids, args.seed, args.train_ratio, args.validation_ratio)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    temporary_paths = {name: args.output_dir / f".{name}.jsonl.tmp" for name in ("all", "train", "validation", "test")}
    handles = {name: path.open("w", encoding="utf-8") for name, path in temporary_paths.items()}
    started = time.perf_counter()
    match_reports = []
    failures = []
    action_counts: Counter[str] = Counter()
    split_matches: Counter[str] = Counter()
    split_decisions: Counter[str] = Counter()
    projection_error_sum = 0.0
    projected_raises = 0
    try:
        for index, job_id in enumerate(selected_ids, start=1):
            metadata = by_id.get(job_id)
            if not metadata:
                failures.append({"job_id": job_id, "error": "missing download manifest row"})
                continue
            source = args.raw_dir / str(metadata.get("file", f"replay-{job_id}.json"))
            try:
                actual_sha = sha256_file(source)
                if actual_sha != metadata.get("sha256"):
                    raise ValueError("file SHA-256 differs from download manifest")
                document = json.loads(source.read_text(encoding="utf-8"))
                decisions, report = parse_match(document)
                if report["match_id"] != job_id:
                    raise ValueError("parsed match ID differs from manifest")
                split = split_for[job_id]
                for decision in decisions:
                    label, projection = action_bucket(decision)
                    row = dict(decision)
                    row.update({
                        "split": split,
                        "action_index": label,
                        "action_bucket": ACTIONS[label],
                        "action_projection": projection,
                        "data_version": "public-replay-bc-v1",
                    })
                    line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                    handles["all"].write(line)
                    handles[split].write(line)
                    action_counts[ACTIONS[label]] += 1
                    if projection.get("fraction") is not None:
                        projection_error_sum += float(projection["error"])
                        projected_raises += 1
                split_matches[split] += 1
                split_decisions[split] += len(decisions)
                match_reports.append({
                    **report,
                    "split": split,
                    "source_file": source.name,
                    "source_sha256": actual_sha,
                })
                print(f"[{index}/{args.required}] verified {job_id}: {report['hands']} hands, {len(decisions)} decisions", flush=True)
            except Exception as exc:
                failures.append({"job_id": job_id, "error": f"{type(exc).__name__}: {exc}"})
                print(f"[{index}/{args.required}] FAILED {job_id}: {exc}", flush=True)
    finally:
        for handle in handles.values():
            handle.close()

    report = {
        "schema": "agx.replay-validation.v1",
        "rules": "rsi-poker-4.1",
        "simulation": "rsi-poker-4.0",
        "required_matches": args.required,
        "verified_matches": len(match_reports),
        "failed_matches": len(failures),
        "hands": sum(row["hands"] for row in match_reports),
        "decisions": sum(row["decisions"] for row in match_reports),
        "zero_sum_verified": not failures,
        "failures": failures,
        "matches": match_reports,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json_atomic(args.report, report)
    success = len(match_reports) == args.required and not failures
    if success:
        final_paths = {name: args.output_dir / f"{name}.jsonl" for name in temporary_paths}
        for name, temporary in temporary_paths.items():
            temporary.replace(final_paths[name])
        split_ids = {
            split: sorted(job_id for job_id, assigned in split_for.items() if assigned == split)
            for split in ("train", "validation", "test")
        }
        dataset_manifest = {
            "schema": "agx.behavior-dataset.v1",
            "data_version": "public-replay-bc-v1",
            "seed": args.seed,
            "source_download_manifest_sha256": sha256_file(source_manifest_path),
            "matches": args.required,
            "hands": report["hands"],
            "decisions": report["decisions"],
            "split_match_ids": split_ids,
            "split_matches": dict(split_matches),
            "split_decisions": dict(split_decisions),
            "action_counts": {action: action_counts[action] for action in ACTIONS},
            "mean_raise_projection_error": round(projection_error_sum / max(1, projected_raises), 6),
            "files": {
                name: {"path": display_path(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                for name, path in final_paths.items()
            },
        }
        write_json_atomic(args.dataset_manifest, dataset_manifest)
    else:
        for temporary in temporary_paths.values():
            temporary.unlink(missing_ok=True)
    if args.update_gate:
        update_gate(args.status, args.report, args.dataset_manifest, success, len(match_reports), args.required)
    print(json.dumps({"success": success, "verified": len(match_reports), "failed": len(failures), "decisions": report["decisions"]}, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
