#!/usr/bin/env python3
"""Run resumable NG-4C baseline-matrix and street-hybrid diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


class Diagnostic:
    def __init__(self, project: Path, source: Path, config: Path, formal_root: Path, output: Path, node: Path):
        self.project = project.resolve()
        self.source = source.resolve()
        self.config_path = config.resolve()
        self.formal_root = formal_root.resolve()
        self.output = output.resolve()
        self.node = node.resolve()
        self.cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.query_binary = self.source / "target/release/pluribus-agx-query"
        self.simulator = self.project / "simulator/simulate_submission.js"
        self.progress_path = self.output / "progress.json"
        self.report_path = self.output / "report.json"
        self.progress: dict[str, Any] = {}
        self.policies: dict[str, Path] = {}
        self.blueprints: dict[int, Path] = {}

    def preflight(self) -> None:
        if not os.environ.get("SLURM_JOB_ID") or socket.gethostname().startswith("gpu2gate"):
            raise RuntimeError("NG-4C requires a Slurm compute-node allocation")
        if self.cfg.get("schema") != "agx.noregrets-ng4c-diagnostic-config.v1":
            raise RuntimeError("unsupported NG-4C config")
        if self.cfg.get("eligible_for_student_queries") is not False:
            raise RuntimeError("diagnostics must not authorize student queries")
        if self.cfg.get("hands_per_match") != 240 or self.cfg.get("matches_per_pair", 0) < 2:
            raise RuntimeError("invalid paired-evaluation sample size")
        if sha256(self.query_binary) != self.cfg["query_binary_sha256"]:
            raise RuntimeError("query binary SHA-256 mismatch")
        if not self.node.is_file() or not self.simulator.is_file():
            raise RuntimeError("Node or simulator is missing")
        status = json.loads((self.formal_root / "status.json").read_text(encoding="utf-8"))
        if status.get("config_sha256") != self.cfg["formal_training_config_sha256"]:
            raise RuntimeError("formal training config SHA-256 mismatch")
        for name, relative in self.cfg["policies"].items():
            path = self.project / relative
            if not path.is_file():
                raise RuntimeError(f"missing policy {name}: {path}")
            self.policies[name] = path
        for seed in map(int, self.cfg["seeds"]):
            progress = json.loads((self.formal_root / f"seed-{seed}/progress.json").read_text(encoding="utf-8"))
            final = progress.get("final_blueprint") or {}
            path = self.formal_root / f"seed-{seed}" / str(final.get("path", ""))
            if not path.is_file() or sha256(path) != final.get("sha256"):
                raise RuntimeError(f"blueprint {seed} is missing or corrupt")
            self.blueprints[seed] = path
        self.output.mkdir(parents=True, exist_ok=True)
        config_hash = sha256(self.config_path)
        if self.progress_path.exists():
            self.progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
            if self.progress.get("config_sha256") != config_hash:
                raise RuntimeError("existing progress belongs to another config")
        else:
            self.progress = {
                "schema": "agx.noregrets-ng4c-diagnostic.v1",
                "status": "running",
                "eligible_for_student_queries": False,
                "config": str(self.config_path),
                "config_sha256": config_hash,
                "slurm_job_id": os.environ["SLURM_JOB_ID"],
                "hostname": socket.gethostname(),
                "results": {},
                "steps": {},
                "error": None,
            }
            atomic_json(self.progress_path, self.progress)

    def run(self, key: str, candidate: Path, opponent: Path, blueprint: Path | None = None, streets: list[str] | None = None) -> None:
        if key in self.progress["results"]:
            return
        raw = self.output / "raw"
        logs = self.output / "logs"
        raw.mkdir(exist_ok=True)
        logs.mkdir(exist_ok=True)
        result_path = raw / f"{key}.json"
        command = [
            str(self.node), str(self.simulator), "--matches", str(self.cfg["matches_per_pair"]),
            "--seed", str(self.cfg["evaluation_seed"]), "--candidate", str(candidate),
            "--opponent", str(opponent), "--json-out", str(result_path),
        ]
        if blueprint is not None:
            command += [
                "--noregrets-bin", str(self.query_binary), "--noregrets-blueprint", str(blueprint),
                "--noregrets-streets", ",".join(streets or []),
            ]
        stdout_path = logs / f"{key}.stdout.log"
        stderr_path = logs / f"{key}.stderr.log"
        begun = time.monotonic()
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            completed = subprocess.run(command, cwd=self.project, stdout=stdout, stderr=stderr, check=False)
        self.progress["steps"][key] = {
            "command": shlex.join(command), "exit_code": completed.returncode,
            "wall_seconds": time.monotonic() - begun,
        }
        atomic_json(self.progress_path, self.progress)
        if completed.returncode:
            raise RuntimeError(f"{key} failed: {stderr_path.read_text(errors='replace')[-2000:]}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        expected = int(self.cfg["matches_per_pair"]) * int(self.cfg["hands_per_match"])
        if result.get("hands") != expected:
            raise RuntimeError(f"{key} returned incomplete results")
        result["ci95_mbb_per_hand"] = 10.0 * float(result["ci95_match_net"]) / 240.0
        result["ci95_lower_bound_mbb_per_hand"] = float(result["mbb_per_hand"]) - result["ci95_mbb_per_hand"]
        self.progress["results"][key] = result
        atomic_json(self.progress_path, self.progress)

    def execute(self) -> None:
        self.preflight()
        names = list(self.policies)
        for candidate_name in names:
            for opponent_name in names:
                if candidate_name != opponent_name:
                    self.run(
                        f"baseline__{candidate_name}__vs__{opponent_name}",
                        self.policies[candidate_name], self.policies[opponent_name],
                    )
        current = self.policies["current_submission"]
        for seed, blueprint in self.blueprints.items():
            for hybrid_name, streets in self.cfg["hybrids"].items():
                for opponent_name in self.cfg["hybrid_opponents"]:
                    self.run(
                        f"hybrid__{seed}__{hybrid_name}__vs__{opponent_name}",
                        current, self.policies[opponent_name], blueprint, streets,
                    )
        self.progress["status"] = "completed"
        self.progress["completed_at_epoch"] = time.time()
        self.progress["error"] = None
        atomic_json(self.progress_path, self.progress)
        atomic_json(self.report_path, self.progress)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    args = parser.parse_args()
    diagnostic = Diagnostic(args.project, args.source, args.config, args.formal_root, args.output, args.node)
    try:
        diagnostic.execute()
    except Exception as exc:
        if diagnostic.progress:
            diagnostic.progress["status"] = "failed"
            diagnostic.progress["error"] = str(exc)
            atomic_json(diagnostic.progress_path, diagnostic.progress)
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(diagnostic.report_path.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
