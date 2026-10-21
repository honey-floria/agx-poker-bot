#!/usr/bin/env python3
"""Fast structural tests for the NoRegrets NG-4A evaluation runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "noregrets" / "run_ng4_evaluation.py"
SPEC = importlib.util.spec_from_file_location("noregrets_ng4", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

config_path = ROOT / "poker-distill" / "teachers" / "noregrets" / "config" / "ng4-eval-v1.json"
config = json.loads(config_path.read_text(encoding="utf-8"))
assert config["schema"] == "agx.noregrets-ng4-eval-config.v1"
assert len(set(config["seeds"])) == 3
assert config["duplicate_hands_per_baseline"] % config["players"] == 0
assert config["crossplay_is_diagnostic_only"] is True
assert config["eligible_for_student_queries"] is False

evaluated = MODULE.parse_eval(
    "winrate: +123.4 mbb/hand (95% CI ±56.7) over 120000 hands in 8.9s"
)
assert evaluated == {
    "mbb_per_hand": 123.4,
    "ci95": 56.7,
    "hands": 120000,
    "command_wall_seconds": 8.9,
}

crossplay = MODULE.parse_crossplay(
    "focal winrate: -12.3 mbb/hand (95% CI ±45.6) over 100000 hands"
)
assert crossplay == {"mbb_per_hand": -12.3, "ci95": 45.6, "hands": 100000}

payload = MODULE.final_json_line("loading\n{\"gate\":\"passed\"}\n")
assert payload["gate"] == "passed"

print("noregrets NG-4A evaluation tests: ok")
