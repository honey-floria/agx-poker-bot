#!/usr/bin/env python3
"""Run and audit the CPU-only NoRegrets blueprint smoke pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


TRAIN_RE = re.compile(
    r"trained\s+(?P<iters>\d+)\s+iterations in\s+(?P<seconds>[0-9.]+)s\s+"
    r"\((?P<rate>[0-9.]+)\s+iters/s\),\s+(?P<infosets>\d+)\s+infosets"
)
INSPECT_RE = re.compile(r"trained iterations:\s*(\d+)")
EVAL_RE = re.compile(
    r"winrate:\s*([+-]?[0-9.]+)\s+mbb/hand\s+\(95% CI ±([0-9.]+)\)\s+"
    r"over\s+(\d+)\s+hands in\s+([0-9.]+)s"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time_verbose(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    patterns = {
        "elapsed": r"Elapsed \(wall clock\) time.*\):\s*(\S+)",
        "user_seconds": r"User time \(seconds\):\s*([0-9.]+)",
        "system_seconds": r"System time \(seconds\):\s*([0-9.]+)",
        "cpu_percent": r"Percent of CPU this job got:\s*(\S+)",
        "peak_rss_kb": r"Maximum resident set size \(kbytes\):\s*(\d+)",
        "exit_code": r"Exit status:\s*(\d+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            value: Any = match.group(1)
            if key in {"user_seconds", "system_seconds"}:
                value = float(value)
            elif key in {"peak_rss_kb", "exit_code"}:
                value = int(value)
            fields[key] = value
    return fields


def final_json_line(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            value = json.loads(line)
            if isinstance(value, dict):
                return value
    raise ValueError("command output has no JSON object line")


def build_train_command(
    binary: Path,
    cfg: dict[str, Any],
    iterations: int,
    output: Path,
    checkpoint: Path,
    resume: Path | None = None,
) -> list[str]:
    command = [
        str(binary), "train",
        "--iters", str(iterations),
        "--out", str(output),
        "--checkpoint", str(checkpoint),
        "--players", str(cfg["players"]),
        "--stack", str(cfg["stack"]),
        "--buckets", str(cfg["buckets"]),
        "--menu", str(cfg["menu"]),
        "--rollouts", str(cfg["rollouts"]),
        "--runouts", str(cfg["runouts"]),
        "--kmeans-samples", str(cfg["kmeans_samples"]),
        "--train-seed", str(cfg["train_seed"]),
        "--threads", str(cfg["threads"]),
    ]
    if resume is not None:
        command.extend(["--resume", str(resume)])
    return command


class SmokeRun:
    def __init__(self, source: Path, config: Path, output: Path, allow_non_slurm: bool):
        self.source = source.resolve()
        self.config_path = config.resolve()
        self.output = output.resolve()
        self.binary = self.source / "target" / "release" / "pluribus"
        self.cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.allow_non_slurm = allow_non_slurm
        self.steps: list[dict[str, Any]] = []
        self.started = time.time()

    def preflight(self) -> None:
        if not self.allow_non_slurm and not os.environ.get("SLURM_JOB_ID"):
            raise RuntimeError("refusing to train outside a Slurm compute allocation")
        if socket.gethostname().startswith("gpu2gate"):
            raise RuntimeError("refusing to train on a login/gateway host")
        if not self.binary.is_file():
            raise RuntimeError(f"missing release binary: {self.binary}")
        if self.output.exists():
            raise RuntimeError(f"output directory already exists: {self.output}")
        if self.cfg.get("purpose") != "pipeline-smoke-only":
            raise RuntimeError("configuration is not marked pipeline-smoke-only")
        if self.cfg.get("eligible_for_student_training") is not False:
            raise RuntimeError("smoke output must be ineligible for student training")
        self.output.mkdir(parents=True)

    def write_report(self, gate: str = "running", blockers: list[str] | None = None) -> None:
        payload = {
            "schema": "agx.noregrets-smoke-report.v1",
            "gate": gate,
            "blockers": blockers or [],
            "started_at_epoch": self.started,
            "updated_at_epoch": time.time(),
            "host": {
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "cpu_count": os.cpu_count(),
                "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
                "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
            },
            "source": str(self.source),
            "binary_sha256": sha256(self.binary),
            "config": str(self.config_path),
            "config_sha256": sha256(self.config_path),
            "steps": self.steps,
        }
        temporary = self.output / "report.json.tmp"
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.output / "report.json")

    def run_step(self, name: str, command: list[str]) -> dict[str, Any]:
        stdout_path = self.output / f"{name}.stdout.log"
        stderr_path = self.output / f"{name}.stderr.log"
        time_path = self.output / f"{name}.time.log"
        wrapped = ["/usr/bin/time", "-v", "-o", str(time_path), *command]
        step: dict[str, Any] = {
            "name": name,
            "command": shlex.join(command),
            "stdout": stdout_path.name,
            "stderr": stderr_path.name,
            "resource_log": time_path.name,
        }
        begun = time.monotonic()
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            result = subprocess.run(wrapped, cwd=self.source, stdout=stdout, stderr=stderr, check=False)
        step["exit_code"] = result.returncode
        step["wall_seconds"] = time.monotonic() - begun
        step["resources"] = parse_time_verbose(time_path.read_text(encoding="utf-8", errors="replace"))
        self.steps.append(step)
        self.write_report()
        if result.returncode != 0:
            raise RuntimeError(f"step {name} failed with exit code {result.returncode}")
        return step

    def execute(self) -> dict[str, Any]:
        self.preflight()
        self.write_report()
        initial = self.output / "blueprint-initial.bin"
        checkpoint = self.output / "checkpoint-initial.bin"
        resumed = self.output / "blueprint-resumed.bin"
        resumed_checkpoint = self.output / "checkpoint-resumed.bin"

        train = self.run_step(
            "train-initial",
            build_train_command(
                self.binary, self.cfg, int(self.cfg["iterations"]), initial, checkpoint
            ),
        )
        self.run_step("inspect-initial", [str(self.binary), "inspect", "--blueprint", str(initial)])
        self.run_step(
            "train-resume",
            build_train_command(
                self.binary,
                self.cfg,
                int(self.cfg["resume_iterations"]),
                resumed,
                resumed_checkpoint,
                checkpoint,
            ),
        )
        self.run_step("inspect-resumed", [str(self.binary), "inspect", "--blueprint", str(resumed)])
        for suffix in ("a", "b"):
            self.run_step(
                f"validate-{suffix}",
                [
                    str(self.binary), "validate-blueprint",
                    "--blueprint", str(resumed),
                    "--hands", str(self.cfg["validation_hands"]),
                    "--seed", str(self.cfg["query_seed"]),
                ],
            )
        for baseline in ("random", "caller"):
            self.run_step(
                f"eval-{baseline}",
                [
                    str(self.binary), "eval",
                    "--blueprint", str(resumed),
                    "--hands", str(self.cfg["eval_hands"]),
                    "--baseline", baseline,
                    "--players", str(self.cfg["players"]),
                    "--seed", str(self.cfg["eval_seed"]),
                ],
            )

        blockers: list[str] = []
        stdout = {
            step["name"]: (self.output / step["stdout"]).read_text(encoding="utf-8", errors="replace")
            for step in self.steps
        }
        initial_iterations = int(INSPECT_RE.search(stdout["inspect-initial"]).group(1))
        resumed_iterations = int(INSPECT_RE.search(stdout["inspect-resumed"]).group(1))
        expected_resumed = int(self.cfg["iterations"]) + int(self.cfg["resume_iterations"])
        if initial_iterations != int(self.cfg["iterations"]):
            blockers.append("initial blueprint iteration count mismatch")
        if resumed_iterations != expected_resumed:
            blockers.append("resumed blueprint iteration count mismatch")
        validation_a = final_json_line(stdout["validate-a"])
        validation_b = final_json_line(stdout["validate-b"])
        if validation_a != validation_b:
            blockers.append("cross-process blueprint queries are not deterministic")
        if validation_a.get("gate") != "passed":
            blockers.append("blueprint probability validation failed")

        evaluations: dict[str, Any] = {}
        for baseline in ("random", "caller"):
            match = EVAL_RE.search(stdout[f"eval-{baseline}"])
            if not match:
                blockers.append(f"could not parse {baseline} evaluation")
                continue
            evaluations[baseline] = {
                "mbb_per_hand": float(match.group(1)),
                "ci95": float(match.group(2)),
                "hands": int(match.group(3)),
                "wall_seconds": float(match.group(4)),
            }

        train_match = TRAIN_RE.search(stdout["train-initial"])
        estimates: dict[str, Any] = {}
        if train_match:
            rate = float(train_match.group("rate"))
            target = int(self.cfg["formal_training_iterations"])
            wall_hours = target / rate / 3600.0
            estimates = {
                "basis_iterations_per_second": rate,
                "formal_training_iterations": target,
                "estimated_wall_hours": wall_hours,
                "estimated_cpu_hours": wall_hours * int(self.cfg["threads"]),
                "peak_rss_gib_observed": max(
                    (step.get("resources", {}).get("peak_rss_kb", 0) for step in self.steps),
                    default=0,
                ) / 1024.0 / 1024.0,
                "artifact_bytes_observed": sum(
                    path.stat().st_size for path in (initial, checkpoint, resumed, resumed_checkpoint)
                ),
                "planning_note": "Linear extrapolation from a smoke run; rerun a longer pilot before reserving a formal job.",
            }
        else:
            blockers.append("could not parse initial training throughput")

        summary = {
            "checkpoint_reload": {
                "initial_iterations": initial_iterations,
                "resumed_iterations": resumed_iterations,
                "passed": resumed_iterations == expected_resumed,
            },
            "validation": validation_a,
            "evaluations": evaluations,
            "resource_estimate": estimates,
            "artifacts": {
                path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                for path in (initial, checkpoint, resumed, resumed_checkpoint)
            },
        }
        summary_path = self.output / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        gate = "passed" if not blockers else "failed"
        self.write_report(gate, blockers)
        return {"gate": gate, "blockers": blockers, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-non-slurm", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    run = SmokeRun(args.source, args.config, args.output, args.allow_non_slurm)
    try:
        result = run.execute()
    except Exception as exc:
        if run.output.exists():
            run.write_report("failed", [str(exc)])
        print(json.dumps({"gate": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["gate"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
