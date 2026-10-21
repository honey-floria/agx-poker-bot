#!/usr/bin/env python3
"""Structural checks for the NG-4C diagnostic configuration."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
config = json.loads((
    ROOT / "poker-distill/teachers/noregrets/config/ng4c-diagnostic-v1.json"
).read_text(encoding="utf-8"))

assert config["schema"] == "agx.noregrets-ng4c-diagnostic-config.v1"
assert config["hands_per_match"] == 240
assert config["matches_per_pair"] >= 2
assert set(config["policies"]) == {"calling_station", "tag", "mixed", "current_submission"}
assert config["hybrids"] == {
    "noregrets_preflop": ["preflop"],
    "noregrets_postflop": ["flop", "turn", "river"],
}
assert set(config["hybrid_opponents"]) == {"tag", "current_submission"}
assert config["eligible_for_student_queries"] is False

print("noregrets NG-4C diagnostic tests: ok")
