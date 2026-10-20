#!/usr/bin/env python3
"""Build an identity-free behavior dataset using only selected Top-K actions."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "poker-distill" / "replay-parser"))
sys.path.insert(0, str(ROOT / "neural"))
sys.path.insert(0, str(ROOT / "tools"))
from parse_replay import normalize_public_replay, parse_match  # noqa: E402
from replay_data import ACTIONS, action_bucket  # noqa: E402
from build_replay_dataset import assign_splits, display_path, sha256_file, write_json_atomic  # noqa: E402


def anonymous_for_identity(normalized: dict) -> dict[str, str]:
    identities: list[str] = []
    for hand in normalized.get("hands", []):
        for player in hand.get("players", []):
            identity = str(player.get("player", ""))
            if identity and identity not in identities:
                identities.append(identity)
    return {identity: f"anon_{index + 1}" for index, identity in enumerate(identities)}


def main() -> None:
    parser = argparse.ArgumentParser(description="构建仅以排行榜 Top-K 玩家动作为标签的数据集")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=ROOT / "poker-distill" / "reports" / "top20_replay_validation_300.json")
    parser.add_argument("--dataset-manifest", type=Path, default=ROOT / "poker-distill" / "reports" / "top20_dataset_manifest.json")
    parser.add_argument("--required", type=int, default=300)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7607)
    args = parser.parse_args()

    source_manifest_path = args.raw_dir / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("failures"):
        raise SystemExit("download manifest contains failures")
    selection = source_manifest.get("selection", {})
    if int(selection.get("top_k", 0)) != args.top_k:
        raise SystemExit("download selection Top-K differs from requested Top-K")
    selected_ids = list(selection.get("job_ids", []))
    if len(selected_ids) < args.required or len(set(selected_ids[:args.required])) != args.required:
        raise SystemExit(f"download manifest does not contain {args.required} unique jobs")
    selected_ids = selected_ids[:args.required]
    rows_by_id = {row.get("job_id"): row for row in source_manifest.get("completed", [])}
    split_for = assign_splits(selected_ids, args.seed, 0.8, 0.1)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = {name: args.output_dir / f".{name}.jsonl.tmp" for name in ("all", "train", "validation", "test")}
    handles = {name: path.open("w", encoding="utf-8") for name, path in temporary.items()}
    started = time.perf_counter()
    match_reports = []
    failures = []
    action_counts: Counter[str] = Counter()
    rank_counts: Counter[int] = Counter()
    split_decisions: Counter[str] = Counter()
    projection_error_sum = 0.0
    projected_raises = 0
    try:
        for index, job_id in enumerate(selected_ids, start=1):
            metadata = rows_by_id.get(job_id)
            try:
                if not metadata:
                    raise ValueError("missing download manifest row")
                source = args.raw_dir / str(metadata.get("file", f"replay-{job_id}.json"))
                actual_sha = sha256_file(source)
                if actual_sha != metadata.get("sha256"):
                    raise ValueError("file SHA-256 differs from download manifest")
                rank_by_team = {
                    str(item.get("team")): int(item["leaderboard_rank"])
                    for item in metadata.get("participants", [])
                    if item.get("leaderboard_rank") is not None and int(item["leaderboard_rank"]) <= args.top_k
                }
                if not rank_by_team:
                    raise ValueError("match has no selected Top-K participant")
                document = json.loads(source.read_text(encoding="utf-8"))
                normalized = normalize_public_replay(document)
                anon_for = anonymous_for_identity(normalized)
                rank_by_anon = {anon_for[team]: rank for team, rank in rank_by_team.items() if team in anon_for}
                if not rank_by_anon:
                    raise ValueError("replay participant mapping does not match job metadata")
                decisions, parsed = parse_match(document)
                split = split_for[job_id]
                selected_count = 0
                for decision in decisions:
                    rank = rank_by_anon.get(decision["player"])
                    if rank is None:
                        continue
                    label, projection = action_bucket(decision)
                    row = dict(decision)
                    row.update({
                        "split": split,
                        "teacher_rank": rank,
                        "teacher_tier": "top5" if rank <= 5 else "top10" if rank <= 10 else "top20",
                        "action_index": label,
                        "action_bucket": ACTIONS[label],
                        "action_projection": projection,
                        "data_version": "public-replay-top20-v1",
                    })
                    line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                    handles["all"].write(line)
                    handles[split].write(line)
                    action_counts[ACTIONS[label]] += 1
                    rank_counts[rank] += 1
                    split_decisions[split] += 1
                    selected_count += 1
                    if projection.get("fraction") is not None:
                        projection_error_sum += float(projection["error"])
                        projected_raises += 1
                if selected_count == 0:
                    raise ValueError("Top-K participants produced no decisions")
                match_reports.append({
                    "match_id": job_id,
                    "hands": parsed["hands"],
                    "all_decisions": parsed["decisions"],
                    "teacher_decisions": selected_count,
                    "teacher_ranks": sorted(set(rank_by_anon.values())),
                    "split": split,
                    "source_file": source.name,
                    "source_sha256": actual_sha,
                })
                print(f"[{index}/{args.required}] verified {job_id}: {selected_count} Top-{args.top_k} decisions", flush=True)
            except Exception as exc:
                failures.append({"job_id": job_id, "error": f"{type(exc).__name__}: {exc}"})
                print(f"[{index}/{args.required}] FAILED {job_id}: {exc}", flush=True)
    finally:
        for handle in handles.values():
            handle.close()

    report = {
        "schema": "agx.top-teacher-replay-validation.v1",
        "competition_id": selection.get("competition_id"),
        "leaderboard_selected_at_unix": selection.get("selected_at_unix"),
        "top_k": args.top_k,
        "required_matches": args.required,
        "verified_matches": len(match_reports),
        "failed_matches": len(failures),
        "hands": sum(item["hands"] for item in match_reports),
        "teacher_decisions": sum(item["teacher_decisions"] for item in match_reports),
        "failures": failures,
        "matches": match_reports,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json_atomic(args.report, report)
    success = len(match_reports) == args.required and not failures
    if success:
        final = {name: args.output_dir / f"{name}.jsonl" for name in temporary}
        for name, path in temporary.items():
            path.replace(final[name])
        split_ids = {
            split: sorted(job_id for job_id, assigned in split_for.items() if assigned == split)
            for split in ("train", "validation", "test")
        }
        manifest = {
            "schema": "agx.top-teacher-behavior-dataset.v1",
            "data_version": "public-replay-top20-v1",
            "competition_id": selection.get("competition_id"),
            "leaderboard_selected_at_unix": selection.get("selected_at_unix"),
            "top_k": args.top_k,
            "seed": args.seed,
            "source_download_manifest_sha256": sha256_file(source_manifest_path),
            "matches": args.required,
            "hands": report["hands"],
            "decisions": report["teacher_decisions"],
            "split_match_ids": split_ids,
            "split_matches": {name: len(ids) for name, ids in split_ids.items()},
            "split_decisions": dict(split_decisions),
            "action_counts": {action: action_counts[action] for action in ACTIONS},
            "teacher_rank_decisions": {str(rank): rank_counts[rank] for rank in range(1, args.top_k + 1)},
            "mean_raise_projection_error": round(projection_error_sum / max(1, projected_raises), 6),
            "files": {
                name: {"path": display_path(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                for name, path in final.items()
            },
        }
        write_json_atomic(args.dataset_manifest, manifest)
    else:
        for path in temporary.values():
            path.unlink(missing_ok=True)
    print(json.dumps({
        "success": success,
        "verified": len(match_reports),
        "failed": len(failures),
        "teacher_decisions": report["teacher_decisions"],
    }, ensure_ascii=False))
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
