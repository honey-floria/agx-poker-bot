#!/usr/bin/env python3
"""Run resumable paired screening for DAgger round-1 policy candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HANDS_PER_MATCH = 240


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


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot take a percentile of an empty sample")
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def bootstrap_mean_interval(
    values: list[float], *, samples: int, seed: int, confidence: float = 0.95,
) -> list[float]:
    if len(values) < 2 or samples < 100:
        raise ValueError("bootstrap requires at least two observations and 100 samples")
    generator = random.Random(seed)
    count = len(values)
    means = []
    for _ in range(samples):
        means.append(sum(values[generator.randrange(count)] for _ in range(count)) / count)
    tail = (1.0 - confidence) / 2.0
    return [percentile(means, tail), percentile(means, 1.0 - tail)]


def mbb_per_hand(match_net: float) -> float:
    return 10.0 * match_net / HANDS_PER_MATCH


class Screening:
    def __init__(self, project: Path, config: Path, output: Path, node: Path):
        self.project = project.resolve()
        self.config_path = config.resolve()
        self.output = output.resolve()
        self.node = node.resolve()
        self.cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.simulator = self.project / "simulator" / "simulate_submission.js"
        self.progress_path = self.output / "progress.json"
        self.report_path = self.output / "report.json"
        self.progress: dict[str, Any] = {}
        self.candidates: dict[str, Path] = {}
        self.opponents: dict[str, Path] = {}

    def preflight(self) -> None:
        if not os.environ.get("SLURM_JOB_ID"):
            raise RuntimeError("DAgger screening requires a Slurm allocation")
        if socket.gethostname().startswith("gpu2gate"):
            raise RuntimeError("refusing to evaluate on a login/gateway host")
        if self.cfg.get("schema") != "agx.dagger1-screening-config.v1":
            raise RuntimeError("unsupported DAgger screening configuration")
        if int(self.cfg.get("hands_per_match", 0)) != HANDS_PER_MATCH:
            raise RuntimeError("screening requires complete 240-hand matches")
        if int(self.cfg.get("matches_per_pair", 0)) < 200:
            raise RuntimeError("quick screening requires at least 200 matches per candidate")
        if int(self.cfg.get("bootstrap_samples", 0)) < 1000:
            raise RuntimeError("screening requires at least 1,000 bootstrap samples")
        if not self.node.is_file() or not os.access(self.node, os.X_OK):
            raise RuntimeError(f"Node executable is unavailable: {self.node}")
        if not self.simulator.is_file():
            raise RuntimeError("paired simulator is missing")

        artifacts: dict[str, Any] = {
            "simulator": {"path": str(self.simulator), "sha256": sha256(self.simulator)},
            "candidates": {},
            "opponents": {},
        }
        for name, relative in self.cfg["candidates"].items():
            candidate = self.project / relative
            if not candidate.is_file():
                raise RuntimeError(f"candidate is missing: {candidate}")
            self.candidates[name] = candidate
            artifacts["candidates"][name] = {
                "path": str(candidate), "sha256": sha256(candidate), "bytes": candidate.stat().st_size,
            }
        for name, relative in self.cfg["opponents"].items():
            opponent = self.project / relative
            if not opponent.is_file():
                raise RuntimeError(f"opponent is missing: {opponent}")
            self.opponents[name] = opponent
            artifacts["opponents"][name] = {
                "path": str(opponent), "sha256": sha256(opponent), "bytes": opponent.stat().st_size,
            }

        self.output.mkdir(parents=True, exist_ok=True)
        config_hash = sha256(self.config_path)
        if self.progress_path.exists():
            self.progress = json.loads(self.progress_path.read_text(encoding="utf-8"))
            if self.progress.get("config_sha256") != config_hash:
                raise RuntimeError("existing progress belongs to another configuration")
            if self.progress.get("artifacts") != artifacts:
                raise RuntimeError("candidate, opponent, or simulator artifacts changed during screening")
        else:
            self.progress = {
                "schema": "agx.dagger1-screening-progress.v1",
                "gate": "running",
                "config": str(self.config_path),
                "config_sha256": config_hash,
                "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
                "hostname": socket.gethostname(),
                "artifacts": artifacts,
                "results": {},
                "steps": {},
                "error": None,
            }
            atomic_json(self.progress_path, self.progress)

    def run_pair(self, key: str, candidate: Path, opponent: Path) -> None:
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
            "--candidate", str(candidate),
            "--opponent", str(opponent),
            "--json-out", str(result_path),
        ]
        stdout_path = logs / f"{key}.stdout.log"
        stderr_path = logs / f"{key}.stderr.log"
        begun = time.monotonic()
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            completed = subprocess.run(command, cwd=self.project, stdout=stdout, stderr=stderr, check=False)
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
        expected_hands = int(self.cfg["matches_per_pair"]) * HANDS_PER_MATCH
        if result.get("schema") != "agx.paired-policy-evaluation.v1":
            raise RuntimeError(f"{key} returned the wrong report schema")
        if int(result.get("hands", -1)) != expected_hands:
            raise RuntimeError(f"{key} returned incomplete evaluation data")
        if result.get("external_noregrets") is not False:
            raise RuntimeError(f"{key} unexpectedly used an external NoRegrets policy")
        match_nets = [float(value) for value in result.get("match_nets", [])]
        if len(match_nets) != int(self.cfg["matches_per_pair"]):
            raise RuntimeError(f"{key} returned the wrong number of match results")
        interval = bootstrap_mean_interval(
            match_nets,
            samples=int(self.cfg["bootstrap_samples"]),
            seed=int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big"),
        )
        result["bootstrap_95_mean_match_net"] = interval
        result["bootstrap_95_mbb_per_hand"] = [mbb_per_hand(value) for value in interval]
        self.progress["results"][key] = result
        atomic_json(self.progress_path, self.progress)

    def add_tag_deltas(self) -> None:
        baseline = self.progress["results"]["reference__current_submission__vs__tag"]
        baseline_nets = [float(value) for value in baseline["match_nets"]]
        for name in self.candidates:
            key = f"{name}__vs__tag"
            result = self.progress["results"][key]
            candidate_nets = [float(value) for value in result["match_nets"]]
            deltas = [candidate - reference for candidate, reference in zip(candidate_nets, baseline_nets)]
            interval = bootstrap_mean_interval(
                deltas,
                samples=int(self.cfg["bootstrap_samples"]),
                seed=int.from_bytes(hashlib.sha256((key + "-delta").encode("utf-8")).digest()[:8], "big"),
            )
            result["paired_delta_vs_current_tag_reference"] = {
                "mean_match_net": sum(deltas) / len(deltas),
                "mbb_per_hand": mbb_per_hand(sum(deltas) / len(deltas)),
                "bootstrap_95_mean_match_net": interval,
                "bootstrap_95_mbb_per_hand": [mbb_per_hand(value) for value in interval],
            }

    def finalize(self) -> None:
        self.add_tag_deltas()
        decisions: dict[str, Any] = {}
        eligible: list[str] = []
        maximum_invalid = int(self.cfg["maximum_invalid_actions"])
        maximum_timeouts = int(self.cfg["maximum_timeouts"])
        for name in self.candidates:
            blockers: list[str] = []
            for opponent_name in self.opponents:
                result = self.progress["results"][f"{name}__vs__{opponent_name}"]
                if int(result["invalid_actions"]) > maximum_invalid:
                    blockers.append(f"invalid actions against {opponent_name}")
                if int(result["timeouts"]) > maximum_timeouts:
                    blockers.append(f"timeouts against {opponent_name}")
            current = self.progress["results"][f"{name}__vs__current_submission"]
            if float(current["bootstrap_95_mbb_per_hand"][0]) <= 0.0:
                blockers.append("95% lower bound versus current submission is not positive")
            passed = not blockers
            decisions[name] = {"passed": passed, "blockers": blockers}
            if passed:
                eligible.append(name)
        self.progress["decisions"] = decisions
        self.progress["eligible_candidates"] = eligible
        self.progress["gate"] = "passed" if eligible else "failed"
        self.progress["error"] = None
        self.progress["completed_at_epoch"] = time.time()
        atomic_json(self.progress_path, self.progress)
        atomic_json(self.report_path, self.progress)

    def execute(self) -> None:
        self.preflight()
        self.run_pair(
            "reference__current_submission__vs__tag",
            self.opponents["current_submission"], self.opponents["tag"],
        )
        for name, candidate in self.candidates.items():
            for opponent_name, opponent in self.opponents.items():
                self.run_pair(f"{name}__vs__{opponent_name}", candidate, opponent)
        self.finalize()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    args = parser.parse_args()
    screening = Screening(args.project, args.config, args.output, args.node)
    try:
        screening.execute()
    except Exception as exc:
        if screening.output.exists() and screening.progress:
            screening.progress["gate"] = "failed"
            screening.progress["error"] = str(exc)
            atomic_json(screening.progress_path, screening.progress)
        print(json.dumps({"gate": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({
        "gate": screening.progress["gate"],
        "eligible_candidates": screening.progress["eligible_candidates"],
        "report": str(screening.report_path),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
