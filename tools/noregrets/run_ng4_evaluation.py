#!/usr/bin/env python3
"""Run resumable NG-4A evaluation for completed NoRegrets blueprints."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EVAL_RE = re.compile(
    r"winrate:\s*([+-]?[0-9.]+)\s+mbb/hand\s+\(95% CI ±([0-9.]+)\)\s+"
    r"over\s+(\d+)\s+hands in\s+([0-9.]+)s"
)
CROSSPLAY_RE = re.compile(
    r"focal winrate:\s*([+-]?[0-9.]+)\s+mbb/hand\s+"
    r"\(95% CI ±([0-9.]+)\)\s+over\s+(\d+)\s+hands"
)


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


def final_json_line(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        if line.lstrip().startswith("{"):
            value = json.loads(line)
            if isinstance(value, dict):
                return value
    raise ValueError("no JSON object found in command output")


def parse_eval(text: str) -> dict[str, Any]:
    match = EVAL_RE.search(text)
    if not match:
        raise ValueError("could not parse duplicate evaluation output")
    return {
        "mbb_per_hand": float(match.group(1)),
        "ci95": float(match.group(2)),
        "hands": int(match.group(3)),
        "command_wall_seconds": float(match.group(4)),
    }


def parse_crossplay(text: str) -> dict[str, Any]:
    match = CROSSPLAY_RE.search(text)
    if not match:
        raise ValueError("could not parse crossplay output")
    return {
        "mbb_per_hand": float(match.group(1)),
        "ci95": float(match.group(2)),
        "hands": int(match.group(3)),
    }


class Ng4Evaluation:
    def __init__(self, source: Path, config: Path, formal_root: Path, output: Path):
        self.source = source.resolve()
        self.config_path = config.resolve()
        self.formal_root = formal_root.resolve()
        self.output = output.resolve()
        self.binary = self.source / "target" / "release" / "pluribus"
        self.cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.progress_path = self.output / "progress.json"
        self.report_path = self.output / "report.json"
        self.progress: dict[str, Any] = {}
        self.blueprints: dict[int, Path] = {}

    def preflight(self) -> None:
        if not os.environ.get("SLURM_JOB_ID"):
            raise RuntimeError("NG-4 evaluation requires a Slurm allocation")
        if socket.gethostname().startswith("gpu2gate"):
            raise RuntimeError("refusing to evaluate on a login/gateway host")
        if self.cfg.get("schema") != "agx.noregrets-ng4-eval-config.v1":
            raise RuntimeError("unsupported NG-4 evaluation config")
        if self.cfg.get("eligible_for_student_queries") is not False:
            raise RuntimeError("phase A must not authorize student queries")
        if not self.binary.is_file() or sha256(self.binary) != self.cfg["binary_sha256"]:
            raise RuntimeError("release binary is missing or has the wrong SHA-256")
        seeds = [int(seed) for seed in self.cfg["seeds"]]
        if len(seeds) != 3 or len(set(seeds)) != 3:
            raise RuntimeError("NG-4 evaluation requires three distinct seeds")
        hands = int(self.cfg["duplicate_hands_per_baseline"])
        if hands <= 0 or hands % int(self.cfg["players"]):
            raise RuntimeError("duplicate hand count must be positive and divisible by players")
        status = json.loads((self.formal_root / "status.json").read_text(encoding="utf-8"))
        if status.get("gate") != "trained_pending_ng4_evaluation":
            raise RuntimeError("formal training has not reached the NG-4 evaluation gate")
        if status.get("config_sha256") != self.cfg["formal_training_config_sha256"]:
            raise RuntimeError("formal training status has the wrong config SHA-256")

        self.output.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, Any] = {}
        for seed in seeds:
            directory = self.formal_root / f"seed-{seed}"
            progress = json.loads((directory / "progress.json").read_text(encoding="utf-8"))
            if progress.get("gate") != "trained_pending_ng4_evaluation":
                raise RuntimeError(f"seed {seed} is not ready for NG-4 evaluation")
            final = progress.get("final_blueprint") or {}
            blueprint = directory / str(final.get("path", ""))
            if not blueprint.is_file() or blueprint.stat().st_size != int(final.get("bytes", -1)):
                raise RuntimeError(f"seed {seed} final blueprint is missing or has the wrong size")
            actual_hash = sha256(blueprint)
            if actual_hash != final.get("sha256"):
                raise RuntimeError(f"seed {seed} final blueprint SHA-256 mismatch")
            self.blueprints[seed] = blueprint
            artifacts[str(seed)] = {
                "path": str(blueprint),
                "sha256": actual_hash,
                "bytes": blueprint.stat().st_size,
                "training_curve": [
                    {
                        "iterations": item["iterations"],
                        "evaluations": item["evaluations"],
                        "validation": item["validation"],
                    }
                    for item in progress["checkpoints"]
                ],
            }

        if self.progress_path.exists():
            self.progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
            if self.progress.get("config_sha256") != sha256(self.config_path):
                raise RuntimeError("existing NG-4 progress belongs to another config")
        else:
            self.progress = {
                "schema": "agx.noregrets-ng4-progress.v1",
                "config": str(self.config_path),
                "config_sha256": sha256(self.config_path),
                "formal_root": str(self.formal_root),
                "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
                "hostname": socket.gethostname(),
                "gate": "running",
                "artifacts": artifacts,
                "validation": {},
                "duplicate_baselines": {},
                "crossplay": {},
                "steps": {},
                "error": None,
            }
            atomic_json(self.progress_path, self.progress)

    def run_step(self, name: str, command: list[str]) -> str:
        logs = self.output / "logs"
        logs.mkdir(exist_ok=True)
        stdout_path = logs / f"{name}.stdout.log"
        stderr_path = logs / f"{name}.stderr.log"
        begun = time.monotonic()
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            result = subprocess.run(
                command, cwd=self.source, stdout=stdout, stderr=stderr, check=False
            )
        record = {
            "command": shlex.join(command),
            "exit_code": result.returncode,
            "wall_seconds": time.monotonic() - begun,
            "stdout": str(stdout_path.relative_to(self.output)),
            "stderr": str(stderr_path.relative_to(self.output)),
        }
        self.progress["steps"][name] = record
        atomic_json(self.progress_path, self.progress)
        if result.returncode:
            raise RuntimeError(f"{name} failed with exit code {result.returncode}")
        return stdout_path.read_text(encoding="utf-8", errors="replace")

    def validate(self) -> None:
        for seed, blueprint in self.blueprints.items():
            key = str(seed)
            if key in self.progress["validation"]:
                continue
            output = self.run_step(
                f"validate-{seed}",
                [str(self.binary), "validate-blueprint", "--blueprint", str(blueprint),
                 "--hands", str(self.cfg["validation_hands_per_blueprint"]),
                 "--seed", str(self.cfg["evaluation_seed"])],
            )
            self.progress["validation"][key] = final_json_line(output)
            atomic_json(self.progress_path, self.progress)

    def duplicate_baselines(self) -> None:
        for seed, blueprint in self.blueprints.items():
            results = self.progress["duplicate_baselines"].setdefault(str(seed), {})
            for baseline in self.cfg["baselines"]:
                if baseline in results:
                    continue
                output = self.run_step(
                    f"duplicate-{baseline}-{seed}",
                    [str(self.binary), "eval", "--blueprint", str(blueprint),
                     "--hands", str(self.cfg["duplicate_hands_per_baseline"]),
                     "--baseline", baseline, "--players", str(self.cfg["players"]),
                     "--seed", str(self.cfg["evaluation_seed"]), "--duplicate"],
                )
                results[baseline] = parse_eval(output)
                atomic_json(self.progress_path, self.progress)

    def crossplay(self) -> None:
        for focal, focal_path in self.blueprints.items():
            for field, field_path in self.blueprints.items():
                if focal == field:
                    continue
                key = f"{focal}-vs-{field}"
                if key in self.progress["crossplay"]:
                    continue
                output = self.run_step(
                    f"crossplay-{key}",
                    [str(self.binary), "crossplay", "--focal", str(focal_path),
                     "--field", str(field_path),
                     "--hands", str(self.cfg["crossplay_hands_per_direction"]),
                     "--seed", str(self.cfg["evaluation_seed"])],
                )
                self.progress["crossplay"][key] = parse_crossplay(output)
                atomic_json(self.progress_path, self.progress)

    def finalize(self) -> None:
        blockers: list[str] = []
        minimum_share = float(self.cfg["minimum_action_probability_share"])
        maximum_illegal = float(self.cfg["maximum_illegal_action_probability_mass"])
        minimum_lower = float(self.cfg["minimum_baseline_ci95_lower_bound_mbb_per_hand"])
        for seed in self.cfg["seeds"]:
            key = str(seed)
            validation = self.progress["validation"][key]
            if validation.get("gate") != "passed":
                blockers.append(f"seed {seed} validation gate did not pass")
            if int(validation.get("deterministic_mismatches", -1)) != 0:
                blockers.append(f"seed {seed} has deterministic mismatches")
            if int(validation.get("invalid_probability_vectors", -1)) != 0:
                blockers.append(f"seed {seed} has invalid probability vectors")
            if float(validation.get("illegal_action_probability_mass", 1.0)) > maximum_illegal:
                blockers.append(f"seed {seed} has illegal action probability mass")
            shares = validation.get("action_probability_share", {})
            if any(float(shares.get(action, 0.0)) < minimum_share
                   for action in ("fold", "check_call", "raise", "all_in")):
                blockers.append(f"seed {seed} has a degenerate action-family share")
            for baseline in self.cfg["baselines"]:
                result = self.progress["duplicate_baselines"][key][baseline]
                lower = float(result["mbb_per_hand"]) - float(result["ci95"])
                result["ci95_lower_bound"] = lower
                if lower <= minimum_lower:
                    blockers.append(f"seed {seed} does not significantly beat {baseline}")

        gate = "phase_a_passed_pending_project_baselines" if not blockers else "failed"
        self.progress["gate"] = gate
        self.progress["blockers"] = blockers
        self.progress["error"] = None
        self.progress["completed_at_epoch"] = time.time()
        self.progress["full_ng4_approved"] = False
        self.progress["remaining_required_evaluation"] = [
            "AGX TAG baseline", "AGX Calling Station baseline", "AGX Mixed baseline",
            "current official JavaScript policy", "paired seat-rotation comparison",
        ]
        atomic_json(self.progress_path, self.progress)
        atomic_json(self.report_path, self.progress)

    def execute(self) -> None:
        self.preflight()
        self.validate()
        self.duplicate_baselines()
        self.crossplay()
        self.finalize()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--formal-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluation = Ng4Evaluation(args.source, args.config, args.formal_root, args.output)
    try:
        evaluation.execute()
    except Exception as exc:
        if evaluation.output.exists() and evaluation.progress:
            evaluation.progress["gate"] = "failed"
            evaluation.progress["error"] = str(exc)
            atomic_json(evaluation.progress_path, evaluation.progress)
        print(json.dumps({"gate": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(evaluation.report_path.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
