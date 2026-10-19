#!/usr/bin/env python3
"""Download complete public AGX poker replay aggregates with verification."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "https://agx.cool/api/v1"


def request_bytes(url: str, api_key: str, attempts: int = 6) -> bytes:
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": "agx-replay-archiver/1"}
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers=headers), timeout=120, context=ssl.create_default_context()) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504) or attempt + 1 == attempts:
                raise
        except (URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise
        time.sleep(min(60, 2 ** attempt))
    raise AssertionError("unreachable")


def list_jobs(api_key: str, limit: int, offset: int) -> tuple[list[dict], int]:
    query = urlencode({
        "game_id": "poker",
        "status": "succeeded",
        "public_only": "true",
        "limit": limit,
        "offset": offset,
        "include_total": "true",
    })
    payload = json.loads(request_bytes(f"{API}/jobs?{query}", api_key))
    jobs = [item for item in payload.get("items", []) if item.get("replay_availability") == "available"]
    if len(jobs) != limit:
        raise RuntimeError(f"requested {limit} available jobs, received {len(jobs)}")
    return jobs, int(payload.get("total", len(jobs)))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_replay(path: Path, job_id: str) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        replay = json.load(handle)
    descriptor = replay.get("descriptor", {})
    if replay.get("schema") != "agx.public-replay.v1":
        raise ValueError("unexpected replay schema")
    if replay.get("complete") is not True or descriptor.get("complete") is not True:
        raise ValueError("replay is incomplete")
    if descriptor.get("job_id") != job_id:
        raise ValueError("replay job ID mismatch")
    result = descriptor.get("result", {})
    return {
        "job_id": job_id,
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "hands": result.get("hands"),
        "decisions": result.get("decisions"),
        "rules_version": descriptor.get("rules_version"),
        "simulation_version": descriptor.get("simulation_version"),
        "verified": True,
    }


def download_one(output_dir: Path, job_id: str, api_key: str) -> dict:
    target = output_dir / f"replay-{job_id}.json"
    if target.exists():
        try:
            result = validate_replay(target, job_id)
            result["status"] = "existing"
            return result
        except (OSError, ValueError, json.JSONDecodeError):
            target.rename(target.with_suffix(f".invalid-{int(time.time())}"))

    temporary = target.with_suffix(".json.part")
    payload = request_bytes(f"{API}/jobs/{job_id}/replay.json", api_key)
    temporary.write_bytes(payload)
    result = validate_replay(temporary, job_id)
    temporary.replace(target)
    result["file"] = target.name
    result["status"] = "downloaded"
    return result


def write_json_atomic(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100 or not 1 <= args.workers <= 8:
        raise SystemExit("limit must be 1..100 and workers must be 1..8")
    api_key = os.environ.get("AGX_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("AGX_API_KEY is not set")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(args.output_dir).free
    if free < 5 * 1024 ** 3:
        raise SystemExit(f"less than 5 GiB free: {free} bytes")

    jobs, total = list_jobs(api_key, args.limit, args.offset)
    selection = {
        "selected_at_unix": int(time.time()),
        "available_total": total,
        "limit": args.limit,
        "offset": args.offset,
        "job_ids": [item["id"] for item in jobs],
    }
    write_json_atomic(args.output_dir / "selection.json", selection)

    completed: list[dict] = []
    failures: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download_one, args.output_dir, item["id"], api_key): item["id"] for item in jobs}
        for future in as_completed(futures):
            job_id = futures[future]
            try:
                row = future.result()
                completed.append(row)
                print(f"[{len(completed)}/{args.limit}] {row['status']} {job_id} {row['bytes']} bytes", flush=True)
            except Exception as exc:  # keep other downloads running and persist failures
                failures.append({"job_id": job_id, "error": f"{type(exc).__name__}: {exc}"})
                print(f"FAILED {job_id}: {exc}", flush=True)
            write_json_atomic(args.output_dir / "manifest.json", {
                "selection": selection,
                "completed": sorted(completed, key=lambda item: item["job_id"]),
                "failures": failures,
            })
    if failures or len(completed) != args.limit:
        raise SystemExit(f"download incomplete: {len(completed)} completed, {len(failures)} failed")
    print(f"complete: {len(completed)} verified replays, {sum(item['bytes'] for item in completed)} bytes")


if __name__ == "__main__":
    main()
