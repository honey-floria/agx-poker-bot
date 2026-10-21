#!/usr/bin/env python3
"""Fast structural tests for the formal NoRegrets training runner."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "noregrets" / "run_formal_training.py"
SPEC = importlib.util.spec_from_file_location("noregrets_formal", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

config_path = ROOT / "poker-distill" / "teachers" / "noregrets" / "config" / "blueprint-formal-v1.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
assert config["iterations_per_seed"] == 100_000_000
assert config["checkpoint_interval"] == 20_000_000
assert len(set(config["seeds"])) == 3
assert config["eligible_for_student_queries_before_ng4"] is False
assert config["retained_checkpoints_per_seed"] == 3

with tempfile.TemporaryDirectory(prefix="noregrets-formal-test-") as temporary:
    root = Path(temporary)
    command = MODULE.build_train_command(
        root / "pluribus", config, 7607, 20_000_000,
        root / "blueprint.bin", root / "checkpoint.bin", root / "resume.bin",
    )
assert command[command.index("--iters") + 1] == "20000000"
assert command[command.index("--train-seed") + 1] == "7607"
assert command[command.index("--resume") + 1].endswith("resume.bin")
assert "--snapshot-avg" not in command

payload = MODULE.final_json_line("loaded\n{\"gate\":\"passed\"}\n")
assert payload["gate"] == "passed"

print("noregrets formal training tests: ok")
