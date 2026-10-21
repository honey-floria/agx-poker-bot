#!/usr/bin/env python3
"""Structural and statistical checks for DAgger round-1 screening."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "run_dagger1_screening.py"
SPEC = importlib.util.spec_from_file_location("dagger1_screening", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

config = json.loads((
    ROOT / "poker-distill" / "experiments" / "behavior_dagger1_screening.json"
).read_text(encoding="utf-8"))
assert config["schema"] == "agx.dagger1-screening-config.v1"
assert config["matches_per_pair"] >= 200
assert config["hands_per_match"] == 240
assert config["bootstrap_samples"] >= 1000
assert len(config["candidates"]) == 9
assert set(config["opponents"]) == {"current_submission", "tag"}
assert all("seed" in name for name in config["candidates"])

sample = [float(value) for value in range(1, 21)]
first = MODULE.bootstrap_mean_interval(sample, samples=1000, seed=7607)
second = MODULE.bootstrap_mean_interval(sample, samples=1000, seed=7607)
assert first == second
assert first[0] < sum(sample) / len(sample) < first[1]
assert MODULE.mbb_per_hand(240.0) == 10.0

print("DAgger round-1 screening tests: ok")
