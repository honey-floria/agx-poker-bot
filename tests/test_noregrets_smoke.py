#!/usr/bin/env python3
"""Fast tests for the NoRegrets CPU smoke orchestrator."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "noregrets" / "run_smoke.py"
SPEC = importlib.util.spec_from_file_location("noregrets_run_smoke", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


resource_text = """
Command being timed: "pluribus train"
User time (seconds): 12.50
System time (seconds): 0.75
Percent of CPU this job got: 800%
Elapsed (wall clock) time (h:mm:ss or m:ss): 0:01.75
Maximum resident set size (kbytes): 123456
Exit status: 0
"""
parsed = MODULE.parse_time_verbose(resource_text)
assert parsed["user_seconds"] == 12.5
assert parsed["peak_rss_kb"] == 123456
assert parsed["exit_code"] == 0

payload = MODULE.final_json_line("loaded blueprint\n{\"gate\":\"passed\",\"decisions\":7}\n")
assert payload == {"gate": "passed", "decisions": 7}

cfg = {
    "players": 6,
    "stack": 10000,
    "buckets": 12,
    "menu": "pluribus",
    "rollouts": 200,
    "runouts": 24,
    "kmeans_samples": 30000,
    "train_seed": 7607,
    "threads": 16,
}
with tempfile.TemporaryDirectory(prefix="noregrets-smoke-test-") as temporary:
    root = Path(temporary)
    command = MODULE.build_train_command(
        root / "pluribus",
        cfg,
        100_000,
        root / "blueprint.bin",
        root / "checkpoint.bin",
        root / "old-checkpoint.bin",
    )
assert command[:3] == [str(root / "pluribus"), "train", "--iters"]
assert command[command.index("--resume") + 1].endswith("old-checkpoint.bin")
assert command[command.index("--threads") + 1] == "16"

print("noregrets smoke tests: ok")
