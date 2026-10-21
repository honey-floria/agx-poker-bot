#!/usr/bin/env python3
"""Run resumable, multi-seed NoRegrets formal blueprint training under Slurm."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
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


def parse_time(text: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    patterns = {
        "user_seconds": (r"User time \(seconds\):\s*([0-9.]+)", float),
        "system_seconds": (r"System time \(seconds\):\s*([0-9.]+)", float),
        "cpu_percent": (r"Percent of CPU this job got:\s*(\S+)", str),
        "peak_rss_kib": (r"Maximum resident set size \(kbytes\):\s*(\d+)", int),
        "exit_code": (r"Exit status:\s*(\d+)", int),
    }
    for key, (pattern, conversion) in patterns.items():
        match = re.search(pattern, text)
        if match:
            values[key] = conversion(match.group(1))
    return values


def build_train_command(
    binary: Path,
    cfg: dict[str, Any],
    seed: int,
    iterations: int,
    blueprint: Path,
    checkpoint: Path,
    resume: Path | None,
) -> list[str]:
    command = [
        str(binary), "train", "--iters", str(iterations),
        "--out", str(blueprint), "--checkpoint", str(checkpoint),
        "--players", str(cfg["players"]), "--stack", str(cfg["stack"]),
        "--buckets", str(cfg["buckets"]), "--menu", str(cfg["menu"]),
        "--rollouts", str(cfg["rollouts"]), "--runouts", str(cfg["runouts"]),
        "--kmeans-samples", str(cfg["kmeans_samples"]),
        "--train-seed", str(seed), "--threads", str(cfg["threads"]),
    ]
    if resume is not None:
        command.extend(["--resume", str(resume)])
    return command


class FormalTraining:
    def __init__(self, source: Path, config: Path, output: Path):
        self.source = source.resolve()
        self.config_path = config.resolve()
        self.output = output.resolve()
        self.binary = self.source / "target" / "release" / "pluribus"
        self.cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.root_status = self.output / "status.json"

    def preflight(self) -> None:
        if not os.environ.get("SLURM_JOB_ID"):
            raise RuntimeError("formal training requires a Slurm allocation")
        if socket.gethostname().startswith("gpu2gate"):
            raise RuntimeError("refusing to train on a login/gateway host")
        if self.cfg.get("schema") != "agx.noregrets-formal-training-config.v1":
            raise RuntimeError("unsupported formal training config")
        if not self.binary.is_file() or sha256(self.binary) != self.cfg["binary_sha256"]:
            raise RuntimeError("release binary is missing or has the wrong SHA-256")
        if shutil.which("zstd") is None:
            raise RuntimeError("zstd is required for checkpoint retention")
        total = int(self.cfg["iterations_per_seed"])
        interval = int(self.cfg["checkpoint_interval"])
        if total <= 0 or interval <= 0 or total % interval:
            raise RuntimeError("iterations_per_seed must be divisible by checkpoint_interval")
        if len(set(self.cfg["seeds"])) != 3:
            raise RuntimeError("formal training requires exactly three distinct seeds")
        self.output.mkdir(parents=True, exist_ok=True)

    def disk_guard(self) -> None:
        free = shutil.disk_usage(self.output).free
        minimum = int(self.cfg["minimum_free_gib"]) * 1024**3
        if free < minimum:
            raise RuntimeError(f"free disk {free / 1024**3:.1f} GiB is below safety floor")

    def run_step(self, directory: Path, name: str, command: list[str]) -> dict[str, Any]:
        logs = directory / "logs"
        logs.mkdir(exist_ok=True)
        stdout_path = logs / f"{name}.stdout.log"
        stderr_path = logs / f"{name}.stderr.log"
        resource_path = logs / f"{name}.time.log"
        wrapped = ["/usr/bin/time", "-v", "-o", str(resource_path), *command]
        begun = time.monotonic()
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            result = subprocess.run(wrapped, cwd=self.source, stdout=stdout, stderr=stderr, check=False)
        record = {
            "name": name,
            "command": shlex.join(command),
            "exit_code": result.returncode,
            "wall_seconds": time.monotonic() - begun,
            "stdout": str(stdout_path.relative_to(directory)),
            "stderr": str(stderr_path.relative_to(directory)),
            "resource_log": str(resource_path.relative_to(directory)),
            "resources": parse_time(resource_path.read_text(encoding="utf-8", errors="replace")),
        }
        if result.returncode:
            raise RuntimeError(f"{name} failed with exit code {result.returncode}")
        return record

    def seed_progress(self, seed: int) -> tuple[Path, dict[str, Any]]:
        directory = self.output / f"seed-{seed}"
        directory.mkdir(exist_ok=True)
        (directory / "checkpoints").mkdir(exist_ok=True)
        path = directory / "progress.json"
        if path.exists():
            progress = json.loads(path.read_text(encoding="utf-8"))
            current_hash = sha256(self.config_path)
            previous_hash = progress.get("config_sha256")
            if previous_hash != current_hash:
                compatible = self.cfg.get("resume_compatible_config_sha256", [])
                if previous_hash not in compatible:
                    raise RuntimeError(f"seed {seed} progress belongs to a different config")
                progress.setdefault("config_migrations", []).append({
                    "from": previous_hash,
                    "to": current_hash,
                    "reason": "resource-constrained iteration cap and rolling checkpoint retention",
                })
                progress["config_sha256"] = current_hash
                atomic_json(path, progress)
        else:
            progress = {
                "schema": "agx.noregrets-formal-seed-progress.v1",
                "seed": seed,
                "config_sha256": sha256(self.config_path),
                "binary_sha256": sha256(self.binary),
                "completed_iterations": 0,
                "checkpoints": [],
                "gate": "running",
            }
            atomic_json(path, progress)
        return directory, progress

    def prune_archives(self, directory: Path, progress: dict[str, Any]) -> None:
        keep_count = int(self.cfg["retained_checkpoints_per_seed"])
        checkpoints = sorted(progress["checkpoints"], key=lambda item: int(item["iterations"]))
        retained_iterations = {int(item["iterations"]) for item in checkpoints[-keep_count:]}
        for item in checkpoints:
            archive = directory / item["checkpoint_archive"]
            retained = int(item["iterations"]) in retained_iterations
            if not retained and archive.exists():
                archive.unlink()
            item["archive_retained"] = retained and archive.exists()

    def restore_current(self, directory: Path, progress: dict[str, Any], current: Path) -> None:
        if current.exists() or not progress["checkpoints"]:
            return
        latest = max(progress["checkpoints"], key=lambda item: int(item["iterations"]))
        archive = directory / latest["checkpoint_archive"]
        if not archive.is_file():
            raise RuntimeError(f"latest retained checkpoint archive is missing: {archive}")
        label = f"{int(latest['iterations']):012d}"
        self.run_step(
            directory, f"restore-{label}",
            ["zstd", "-d", "-f", str(archive), "-o", str(current)],
        )
        if sha256(current) != latest["checkpoint_sha256"]:
            raise RuntimeError("restored checkpoint SHA-256 mismatch")

    def finalize_existing_seed(
        self, seed: int, directory: Path, progress: dict[str, Any], current: Path
    ) -> None:
        total = int(self.cfg["iterations_per_seed"])
        if int(progress["completed_iterations"]) != total or progress.get("final_blueprint"):
            return
        self.restore_current(directory, progress, current)
        label = f"{total:012d}"
        stage_blueprint = directory / f"blueprint-{label}.finalizing.bin"
        unused_checkpoint = directory / "checkpoint-export-unused.bin"
        exported = self.run_step(
            directory, f"export-final-{label}",
            build_train_command(
                self.binary, self.cfg, seed, 0, stage_blueprint, unused_checkpoint, current
            ),
        )
        inspected = self.run_step(
            directory, f"inspect-final-{label}",
            [str(self.binary), "inspect", "--blueprint", str(stage_blueprint)],
        )
        inspect_text = (directory / inspected["stdout"]).read_text(encoding="utf-8", errors="replace")
        match = INSPECT_RE.search(inspect_text)
        if not match or int(match.group(1)) != total:
            raise RuntimeError(f"final blueprint iteration mismatch for seed {seed}")
        validated = self.run_step(
            directory, f"validate-final-{label}",
            [str(self.binary), "validate-blueprint", "--blueprint", str(stage_blueprint),
             "--hands", str(self.cfg["validation_hands"]), "--seed", str(self.cfg["eval_seed"])],
        )
        validation = final_json_line(
            (directory / validated["stdout"]).read_text(encoding="utf-8", errors="replace")
        )
        if validation.get("gate") != "passed":
            raise RuntimeError(f"final blueprint validation failed for seed {seed}")
        final_blueprint = directory / "blueprint-final.bin"
        stage_blueprint.replace(final_blueprint)
        progress["gate"] = "trained_pending_ng4_evaluation"
        progress["final_blueprint"] = {
            "path": "blueprint-final.bin", "sha256": sha256(final_blueprint),
            "bytes": final_blueprint.stat().st_size,
        }
        progress["finalization_steps"] = [exported, inspected, validated]
        self.prune_archives(directory, progress)
        atomic_json(directory / "progress.json", progress)
        current.unlink(missing_ok=True)

    def train_seed(self, seed: int) -> dict[str, Any]:
        directory, progress = self.seed_progress(seed)
        progress_path = directory / "progress.json"
        total = int(self.cfg["iterations_per_seed"])
        interval = int(self.cfg["checkpoint_interval"])
        current = directory / "checkpoint-current.bin"
        if int(progress["completed_iterations"]) > total:
            raise RuntimeError(f"seed {seed} already exceeds the configured iteration cap")
        self.finalize_existing_seed(seed, directory, progress, current)
        if progress.get("final_blueprint"):
            return progress
        self.restore_current(directory, progress, current)
        while int(progress["completed_iterations"]) < total:
            self.disk_guard()
            before = int(progress["completed_iterations"])
            after = min(before + interval, total)
            increment = after - before
            label = f"{after:012d}"
            stage_blueprint = directory / f"blueprint-{label}.stage.bin"
            stage_checkpoint = directory / f"checkpoint-{label}.stage.bin"
            resume = current if before else None
            record = self.run_step(
                directory,
                f"train-{label}",
                build_train_command(
                    self.binary, self.cfg, seed, increment,
                    stage_blueprint, stage_checkpoint, resume,
                ),
            )
            train_stdout = (directory / record["stdout"]).read_text(encoding="utf-8", errors="replace")
            train_match = TRAIN_RE.search(train_stdout)
            if not train_match:
                raise RuntimeError(f"could not parse training output at seed {seed}, {after}")

            inspect = self.run_step(
                directory, f"inspect-{label}",
                [str(self.binary), "inspect", "--blueprint", str(stage_blueprint)],
            )
            inspect_text = (directory / inspect["stdout"]).read_text(encoding="utf-8", errors="replace")
            inspected = INSPECT_RE.search(inspect_text)
            if not inspected or int(inspected.group(1)) != after:
                raise RuntimeError(f"blueprint iteration mismatch at seed {seed}, {after}")

            validation = self.run_step(
                directory, f"validate-{label}",
                [str(self.binary), "validate-blueprint", "--blueprint", str(stage_blueprint),
                 "--hands", str(self.cfg["validation_hands"]), "--seed", str(self.cfg["eval_seed"])],
            )
            validation_payload = final_json_line(
                (directory / validation["stdout"]).read_text(encoding="utf-8", errors="replace")
            )
            if validation_payload.get("gate") != "passed":
                raise RuntimeError(f"blueprint validation failed at seed {seed}, {after}")

            evaluations: dict[str, Any] = {}
            eval_records = []
            for baseline in ("random", "caller"):
                evaluated = self.run_step(
                    directory, f"eval-{baseline}-{label}",
                    [str(self.binary), "eval", "--blueprint", str(stage_blueprint),
                     "--hands", str(self.cfg["eval_hands_per_baseline"]),
                     "--baseline", baseline, "--players", str(self.cfg["players"]),
                     "--seed", str(self.cfg["eval_seed"])],
                )
                eval_records.append(evaluated)
                eval_text = (directory / evaluated["stdout"]).read_text(encoding="utf-8", errors="replace")
                match = EVAL_RE.search(eval_text)
                if not match:
                    raise RuntimeError(f"could not parse {baseline} eval at seed {seed}, {after}")
                evaluations[baseline] = {
                    "mbb_per_hand": float(match.group(1)), "ci95": float(match.group(2)),
                    "hands": int(match.group(3)), "wall_seconds": float(match.group(4)),
                }

            checkpoint_hash = sha256(stage_checkpoint)
            archive = directory / "checkpoints" / f"checkpoint-{label}.bin.zst"
            compression = self.run_step(
                directory, f"compress-{label}",
                ["zstd", f"-{self.cfg['checkpoint_compression']['level']}",
                 f"-T{self.cfg['checkpoint_compression']['threads']}", "-f",
                 str(stage_checkpoint), "-o", str(archive)],
            )
            stage_checkpoint.replace(current)
            blueprint_hash = sha256(stage_blueprint)
            if after == total:
                final_blueprint = directory / "blueprint-final.bin"
                stage_blueprint.replace(final_blueprint)
            else:
                stage_blueprint.unlink()

            checkpoint_record = {
                "iterations": after,
                "increment": increment,
                "checkpoint_sha256": checkpoint_hash,
                "checkpoint_archive": str(archive.relative_to(directory)),
                "checkpoint_archive_sha256": sha256(archive),
                "checkpoint_archive_bytes": archive.stat().st_size,
                "blueprint_sha256": blueprint_hash,
                "training": {
                    "seconds": float(train_match.group("seconds")),
                    "iterations_per_second": float(train_match.group("rate")),
                    "infosets": int(train_match.group("infosets")),
                },
                "validation": validation_payload,
                "evaluations": evaluations,
                "steps": [record, inspect, validation, *eval_records, compression],
            }
            progress["completed_iterations"] = after
            progress["checkpoints"].append(checkpoint_record)
            self.prune_archives(directory, progress)
            if after == total:
                progress["gate"] = "trained_pending_ng4_evaluation"
                progress["final_blueprint"] = {
                    "path": "blueprint-final.bin", "sha256": blueprint_hash,
                    "bytes": (directory / "blueprint-final.bin").stat().st_size,
                }
            atomic_json(progress_path, progress)
            if after == total:
                current.unlink(missing_ok=True)
            self.write_root_status()
        return progress

    def write_root_status(self, error: str | None = None) -> None:
        seeds: dict[str, Any] = {}
        for seed in self.cfg["seeds"]:
            path = self.output / f"seed-{seed}" / "progress.json"
            if path.exists():
                progress = json.loads(path.read_text(encoding="utf-8"))
                seeds[str(seed)] = {
                    "completed_iterations": progress["completed_iterations"],
                    "gate": progress["gate"],
                    "checkpoints": len(progress["checkpoints"]),
                }
        payload = {
            "schema": "agx.noregrets-formal-training-status.v1",
            "updated_at_epoch": time.time(),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "hostname": socket.gethostname(),
            "config": str(self.config_path),
            "config_sha256": sha256(self.config_path),
            "seeds": seeds,
            "error": error,
            "gate": "failed" if error else (
                "trained_pending_ng4_evaluation"
                if len(seeds) == 3 and all(x["completed_iterations"] == self.cfg["iterations_per_seed"] for x in seeds.values())
                else "running"
            ),
        }
        atomic_json(self.root_status, payload)

    def execute(self) -> None:
        self.preflight()
        self.write_root_status()
        for seed in self.cfg["seeds"]:
            self.train_seed(int(seed))
        self.write_root_status()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    training = FormalTraining(args.source, args.config, args.output)
    try:
        training.execute()
    except Exception as exc:
        if training.output.exists():
            training.write_root_status(str(exc))
        print(json.dumps({"gate": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(training.root_status.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
