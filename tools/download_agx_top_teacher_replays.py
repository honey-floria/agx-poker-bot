#!/usr/bin/env python3
"""Select balanced Top-K leaderboard matches and download their complete replays."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import time
from urllib.parse import urlencode

from download_agx_full_replays import (
    API,
    DEFAULT_COMPETITION_ID,
    download_one,
    request_bytes,
    write_json_atomic,
)


def request_json(url: str, api_key: str) -> dict:
    return json.loads(request_bytes(url, api_key))


def leaderboard(api_key: str, competition_id: str, top_k: int) -> list[dict]:
    payload = request_json(f"{API}/competitions/{competition_id}/leaderboard", api_key)
    rows = sorted(payload.get("items", []), key=lambda item: int(item.get("rank", 10**9)))
    selected = rows[:top_k]
    if len(selected) != top_k or [int(item["rank"]) for item in selected] != list(range(1, top_k + 1)):
        raise RuntimeError(f"leaderboard does not contain contiguous Top-{top_k}")
    if len({item["display_name"] for item in selected}) != top_k:
        raise RuntimeError("Top-K leaderboard display names are not unique")
    return selected


def scan_jobs(api_key: str, competition_id: str, scan_limit: int) -> tuple[list[dict], int]:
    jobs: list[dict] = []
    total = 0
    for offset in range(0, scan_limit, 100):
        limit = min(100, scan_limit - offset)
        query = urlencode({
            "game_id": "poker",
            "competition_id": competition_id,
            "status": "succeeded",
            "public_only": "true",
            "limit": limit,
            "offset": offset,
            "include_total": "true",
        })
        payload = request_json(f"{API}/jobs?{query}", api_key)
        page = payload.get("items", [])
        total = int(payload.get("total", len(page)))
        jobs.extend(
            item for item in page
            if item.get("competition_id") == competition_id
            and item.get("status") == "succeeded"
            and item.get("replay_availability") == "available"
        )
        if len(page) < limit or offset + limit >= total:
            break
    return jobs, total


def top_participants(job: dict, rank_for: dict[str, int]) -> list[dict]:
    selected = []
    for participant in job.get("participants", []):
        name = participant.get("display_name")
        if name in rank_for:
            selected.append({
                "team": participant.get("team"),
                "display_name": name,
                "leaderboard_rank": rank_for[name],
            })
    return sorted(selected, key=lambda item: (item["leaderboard_rank"], item["team"]))


def balanced_selection(jobs: list[dict], rank_for: dict[str, int], count: int) -> tuple[list[dict], Counter[str]]:
    candidates = []
    seen = set()
    for index, job in enumerate(jobs):
        if job.get("id") in seen:
            continue
        seen.add(job.get("id"))
        teachers = top_participants(job, rank_for)
        if teachers:
            candidates.append((index, job, teachers))
    if len(candidates) < count:
        raise RuntimeError(f"only {len(candidates)} Top-K matches found; need {count}")
    appearances: Counter[str] = Counter()
    selected = []
    unused = list(candidates)
    while len(selected) < count:
        best_index = min(
            range(len(unused)),
            key=lambda index: (
                min(appearances[item["display_name"]] for item in unused[index][2]),
                sum(appearances[item["display_name"]] for item in unused[index][2]),
                unused[index][0],
            ),
        )
        _, job, teachers = unused.pop(best_index)
        row = dict(job)
        row["top_teachers"] = teachers
        selected.append(row)
        for teacher in teachers:
            appearances[teacher["display_name"]] += 1
    return selected, appearances


def main() -> None:
    parser = argparse.ArgumentParser(description="下载包含排行榜 Top-K 玩家的完整公开比赛回放")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--competition-id", default=DEFAULT_COMPETITION_ID)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--matches", type=int, default=300)
    parser.add_argument("--scan-jobs", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.top_k <= 100 or args.matches < 1 or args.scan_jobs < args.matches:
        raise SystemExit("invalid Top-K, match count, or scan limit")
    if not 1 <= args.workers <= 8:
        raise SystemExit("workers must be 1..8")
    api_key = os.environ.get("AGX_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("AGX_API_KEY is not set")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    minimum_free = max(5 * 1024**3, args.matches * 8 * 1024**2)
    free = shutil.disk_usage(args.output_dir).free
    if free < minimum_free:
        raise SystemExit(f"insufficient free space: {free} bytes; require {minimum_free}")

    board = leaderboard(api_key, args.competition_id, args.top_k)
    rank_for = {item["display_name"]: int(item["rank"]) for item in board}
    jobs, available_total = scan_jobs(api_key, args.competition_id, args.scan_jobs)
    selected, appearances = balanced_selection(jobs, rank_for, args.matches)
    snapshot = {
        "schema": "agx.top-teacher-selection.v1",
        "selected_at_unix": int(time.time()),
        "competition_id": args.competition_id,
        "top_k": args.top_k,
        "matches": args.matches,
        "scanned_jobs": len(jobs),
        "available_total": available_total,
        "leaderboard": board,
        "teacher_match_appearances": {
            item["display_name"]: appearances[item["display_name"]] for item in board
        },
        "job_ids": [item["id"] for item in selected],
    }
    write_json_atomic(args.output_dir / "selection.json", snapshot)

    completed: list[dict] = []
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download_one, args.output_dir, item["id"], api_key): item for item in selected}
        for future in as_completed(futures):
            item = futures[future]
            job_id = item["id"]
            try:
                row = future.result()
                row.update({
                    "competition_id": item.get("competition_id"),
                    "created_at": item.get("created_at"),
                    "participants": [
                        {
                            "team": participant.get("team"),
                            "display_name": participant.get("display_name"),
                            "leaderboard_rank": rank_for.get(participant.get("display_name")),
                        }
                        for participant in item.get("participants", [])
                    ],
                    "top_teachers": item["top_teachers"],
                })
                completed.append(row)
                print(f"[{len(completed)}/{args.matches}] {row['status']} {job_id} {row['bytes']} bytes", flush=True)
            except Exception as exc:
                failures.append({"job_id": job_id, "error": f"{type(exc).__name__}: {exc}"})
                print(f"FAILED {job_id}: {exc}", flush=True)
            write_json_atomic(args.output_dir / "manifest.json", {
                "selection": snapshot,
                "completed": sorted(completed, key=lambda value: value["job_id"]),
                "failures": failures,
            })
    if failures or len(completed) != args.matches:
        raise SystemExit(f"download incomplete: {len(completed)} completed, {len(failures)} failed")
    print(json.dumps({
        "complete": len(completed),
        "bytes": sum(item["bytes"] for item in completed),
        "teacher_match_appearances": snapshot["teacher_match_appearances"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
