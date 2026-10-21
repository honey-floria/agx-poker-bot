#!/usr/bin/env python3
"""Structural tests for NoRegrets project-domain NG-4 evaluation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "noregrets" / "run_ng4_project_evaluation.py"
SPEC = importlib.util.spec_from_file_location("noregrets_ng4_project", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

config = json.loads((
    ROOT / "poker-distill" / "teachers" / "noregrets" / "config" / "ng4-project-eval-v1.json"
).read_text(encoding="utf-8"))
assert config["schema"] == "agx.noregrets-ng4-project-eval-config.v1"
assert config["hands_per_match"] == 240
assert config["matches_per_pair"] >= 2
assert len(config["seeds"]) == 3
assert set(config["required_positive_ci95_lower_bound"]) == set(config["opponents"])
assert config["eligible_for_student_queries_before_pass"] is False

sample = {"ci95_match_net": 2400.0}
assert MODULE.ci95_mbb(sample) == 100.0

print("noregrets project NG-4 evaluation tests: ok")
