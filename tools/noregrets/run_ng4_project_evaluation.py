#!/usr/bin/env python3
"""Run resumable project-domain paired evaluation for NoRegrets blueprints."""

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


def ci95_mbb(result: dict[str, Any]) -> float:
    return 10.0 * float(result["ci95_match_net"]) / 240.0


class ProjectEvaluation:
    def __init__(
        self, project: Path, source: Path, config: Path, formal_root: Path, output: Path,
        node: Path,
    ):
        self.project = project.resolve()
        self.source = source.resolve()
        self.config_path = config.resolve()
        self.formal_root = formal_root.resolve()
        self.output = output.resolve()
        self.node = node.resolve()
        self.query_binary = self.source / "target" / "release" / "pluribus-agx-query"
        self.simulator = self.project / "simulator" / "simulate_submission.js"
        self.cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.progress_path = self.output / "progress.json"
        self.report_path = self.output / "report.json"
        self.progress: dict[str, Any] = {}
        self.blueprints: dict[int, Path] = {}
        self.opponents: dict[str, Path] = {}

    def preflight(self) -> None:
        if not os.environ.get("SLURM_JOB_ID"):
            raise RuntimeError("project NG-4 evaluation requires a Slurm allocation")
        if socket.gethostname().startswith("gpu2gate"):
            raise RuntimeError("refusing to evaluate on a login/gateway host")
        if self.cfg.get("schema") != "agx.noregrets-ng4-project-eval-config.v1":
            raise RuntimeError("unsupported project NG-4 configuration")
        if self.cfg.get("eligible_for_student_queries_before_pass") is not False:
            raise RuntimeError("configuration must not authorize queries before the gate passes")
        if not self.node.is_file() or not os.access(self.node, os.X_OK):
            raise RuntimeError(f"Node executable is unavailable: {self.node}")
        if not self.query_binary.is_file() or sha256(self.query_binary) != self.cfg["query_binary_sha256"]:
            raise RuntimeError("query binary is missing or has the wrong SHA-256")
        if not self.simulator.is_file():
            raise RuntimeError("paired simulator is missing")
        if int(self.cfg["matches_per_pair"]) < 2 or int(self.cfg["hands_per_match"]) != 240:
            raise RuntimeError("evaluation needs at least two complete 240-hand matches")
        status = json.loads((self.formal_root / "status.json").read_text(encoding="utf-8"))
        if status.get("gate") != "trained_pending_ng4_evaluation":
            raise RuntimeError("formal blueprints are not ready for NG-4")
        if status.get("config_sha256") != self.cfg["formal_training_config_sha256"]:
            raise RuntimeError("formal training config SHA-256 mismatch")

        artifacts: dict[str, Any] = {
            "query_binary": {"path": str(self.query_binary), "sha256": sha256(self.query_binary)},
            "simulator": {"path": str(self.simulator), "sha256": sha256(self.simulator)},
            "blueprints": {},
            "opponents": {},
        }
        for seed in map(int, self.cfg["seeds"]):
            progress = json.loads(
                (self.formal_root / f"seed-{seed}" / "progress.json").read_text(encoding="utf-8")
            )
            final = progress.get("final_blueprint") or {}
            blueprint = self.formal_root / f"seed-{seed}" / str(final.get("path", ""))
            if progress.get("gate") != "trained_pending_ng4_evaluation" or not blueprint.is_file():
                raise RuntimeError(f"seed {seed} blueprint is not ready")
            actual_hash = sha256(blueprint)
            if actual_hash != final.get("sha256"):
                raise RuntimeError(f"seed {seed} blueprint SHA-256 mismatch")
            self.blueprints[seed] = blueprint
            artifacts["blueprints"][str(seed)] = {
                "path": str(blueprint), "sha256": actual_hash, "bytes": blueprint.stat().st_size,
            }
        for name, relative in self.cfg["opponents"].items():
            opponent = self.project / relative
            if not opponent.is_file():
                raise RuntimeError(f"opponent is missing: {opponent}")
            self.opponents[name] = opponent
            artifacts["opponents"][name] = {"path": str(opponent), "sha256": sha256(opponent)}

        self.output.mkdir(parents=True, exist_ok=True)
        if self.progress_path.exists():
            self.progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
            if self.progress.get("config_sha256") != sha256(self.config_path):
                raise RuntimeError("existing progress belongs to a different config")
        else:
            self.progress = {
                "schema": "agx.noregrets-ng4-project-progress.v1",
                "gate": "running",
                "full_ng4_approved": False,
                "config": str(self.config_path),
                "config_sha256": sha256(self.config_path),
                "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
                "hostname": socket.gethostname(),
                "artifacts": artifacts,
                "results": {},
                "steps": {},
                "error": None,
            }
            atomic_json(self.progress_path, self.progress)

    def run_pair(self, seed: int, opponent_name: str, opponent: Path) -> None:
        key = f"{seed}-vs-{opponent_name}"
        if key in self.progress["results"]:
            return
        logs = self.output / "logs"
        raw = self.output / "raw"
        logs.mkdir(exist_ok=True)
        raw.mkdir(exist_ok=True)
        result_path = raw / f"{key}.json"
        command = [
            str(self.node), str(self.simulator),
            "--matches", str(self.cfg["matches_per_pair"]),
            "--seed", str(self.cfg["evaluation_seed"]),
            "--noregrets-bin", str(self.query_binary),
            "--noregrets-blueprint", str(self.blueprints[seed]),
            "--opponent", str(opponent),
            "--json-out", str(result_path),
        ]
        stdout_path = logs / f"{key}.stdout.log"
        stderr_path = logs / f"{key}.stderr.log"
        begun = time.monotonic()
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            completed = subprocess.run(
                command, cwd=self.project, stdout=stdout, stderr=stderr, check=False
            )
        self.progress["steps"][key] = {
            "command": shlex.join(command),
            "exit_code": completed.returncode,
            "wall_seconds": time.monotonic() - begun,
            "stdout": str(stdout_path.relative_to(self.output)),
            "stderr": str(stderr_path.relative_to(self.output)),
        }
        atomic_json(self.progress_path, self.progress)
        if completed.returncode:
            detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"{key} failed with exit code {completed.returncode}: {detail}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("schema") != "agx.paired-policy-evaluation.v1":
            raise RuntimeError(f"{key} returned the wrong report schema")
        expected_hands = int(self.cfg["matches_per_pair"]) * int(self.cfg["hands_per_match"])
        if result.get("hands") != expected_hands or result.get("external_noregrets") is not True:
            raise RuntimeError(f"{key} returned incomplete evaluation data")
        result["ci95_mbb_per_hand"] = ci95_mbb(result)
        result["ci95_lower_bound_mbb_per_hand"] = (
            float(result["mbb_per_hand"]) - result["ci95_mbb_per_hand"]
        )
        result["opponent_name"] = opponent_name
        self.progress["results"][key] = result
        atomic_json(self.progress_path, self.progress)

    def finalize(self) -> None:
        blockers: list[str] = []
        required = set(self.cfg["required_positive_ci95_lower_bound"])
        for seed in map(int, self.cfg["seeds"]):
            for opponent in self.opponents:
                key = f"{seed}-vs-{opponent}"
                result = self.progress["results"][key]
                if int(result["invalid_actions"]) > int(self.cfg["maximum_invalid_actions"]):
                    blockers.append(f"{key} has invalid actions")
                if int(result["timeouts"]) > int(self.cfg["maximum_timeouts"]):
                    blockers.append(f"{key} has query timeouts")
                if opponent in required and float(result["ci95_lower_bound_mbb_per_hand"]) <= 0.0:
                    blockers.append(f"{key} does not have a positive 95% lower bound")
        passed = not blockers
        self.progress["gate"] = "passed" if passed else "failed"
        self.progress["full_ng4_approved"] = passed
        self.progress["eligible_for_student_queries"] = passed
        self.progress["blockers"] = blockers
        self.progress["error"] = None
        self.progress["completed_at_epoch"] = time.time()
        atomic_json(self.progress_path, self.progress)
        atomic_json(self.report_path, self.progress)

    def execute(self) -> None:
        self.preflight()
        for seed in map(int, self.cfg["seeds"]):
            for name, opponent in self.opponents.items():
                self.run_pair(seed, name, opponent)
        self.finalize()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    args = parser.parse_args()
    evaluation = ProjectEvaluation(
        args.project, args.source, args.config, args.formal_root, args.output, args.node
    )
    try:
        evaluation.execute()
    except Exception as exc:
        if evaluation.output.exists() and evaluation.progress:
            evaluation.progress["gate"] = "failed"
            evaluation.progress["full_ng4_approved"] = False
            evaluation.progress["error"] = str(exc)
            atomic_json(evaluation.progress_path, evaluation.progress)
        print(json.dumps({"gate": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(evaluation.report_path.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
