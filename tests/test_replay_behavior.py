#!/usr/bin/env python3

import hashlib
import json
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "neural"))
sys.path.insert(0, str(ROOT / "tools"))
from replay_data import ACTIONS, INPUT_SIZE, action_bucket, decision_features
from replay_data_v2 import (
    FAMILY_ACTIONS, INPUT_SIZE_V2, SIZE_ACTIONS,
    decision_features_v2, hierarchical_target, legal_family_mask,
)
from build_replay_dataset import assign_splits


BASE = {
    "match_id": "m1", "hand": 1, "rotation": 0, "rotation_hand": 1,
    "seat": 2, "button": 5, "player": "anon_3", "position": "UTG",
    "hole": ["As", "Kh"], "board": ["Qd", "Jc", "2s"], "street": "flop",
    "pot": 900, "stack": 9000, "me_bet": 0, "invested": 300,
    "to_call": 0, "legal": ["check", "raise", "allin"],
    "min_raise_to": 100, "max_raise_to": 9000, "can_raise": True,
    "history": [{"seat": 0, "player": "anon_1", "street": "preflop", "type": "raise", "amount": 300, "to": 300}],
    "players": [{"seat": i, "player": f"anon_{i+1}", "stack": 9000, "bet": 0, "invested": 300, "state": "in", "position": "BTN"} for i in range(6)],
    "action": {"type": "raise", "to": 450}, "final_net": 100, "match_net": 500, "final_rank": 1,
}

features = decision_features(BASE)
assert len(features) == INPUT_SIZE and all(0 <= value <= 1 for value in features)
no_outcome = dict(BASE, final_net=-9999, match_net=-9999, final_rank=6)
assert decision_features(no_outcome) == features
suit_swapped = dict(BASE, hole=["Ah", "Ks"], board=["Qc", "Jd", "2h"])
assert decision_features(suit_swapped) == features

features_v2 = decision_features_v2(BASE)
assert len(features_v2) == INPUT_SIZE_V2 and all(0 <= value <= 1 for value in features_v2)
assert decision_features_v2(no_outcome) == features_v2
assert decision_features_v2(suit_swapped) == features_v2
family, size = hierarchical_target(BASE)
assert FAMILY_ACTIONS[family] == "raise" and SIZE_ACTIONS[size] == "0.50"
assert legal_family_mask(BASE) == [False, True, False, True, True]

# Rotating every physical seat while keeping relative position unchanged must
# not change v2 input. Account display names are deliberately changed too.
rotated = deepcopy(BASE)
rotated["seat"] = (BASE["seat"] + 1) % 6
rotated["button"] = (BASE["button"] + 1) % 6
rotated["player"] = "different-account"
for item in rotated["players"]:
    item["seat"] = (item["seat"] + 1) % 6
    item["player"] = f"changed-{item['player']}"
for item in rotated["history"]:
    item["seat"] = (item["seat"] + 1) % 6
    item["player"] = "changed-history-account"
assert decision_features_v2(rotated) == features_v2

label, projection = action_bucket(BASE)
assert ACTIONS[label] == "raise_0.50" and projection["error"] == 0
assert ACTIONS[action_bucket(dict(BASE, action={"type": "fold"}))[0]] == "fold"
assert ACTIONS[action_bucket(dict(BASE, action={"type": "raise", "to": 9000}))[0]] == "allin"
assert ACTIONS[action_bucket(dict(BASE, action={"type": "call"}, stack=100, to_call=100))[0]] == "allin"

ids = [f"job-{index}" for index in range(100)]
splits = assign_splits(ids, 7607, 0.8, 0.1)
assert splits == assign_splits(list(reversed(ids)), 7607, 0.8, 0.1)
assert list(splits.values()).count("train") == 80
assert list(splits.values()).count("validation") == 10
assert list(splits.values()).count("test") == 10


holes = [["As", "Ah"], ["Ks", "Kh"], ["Qs", "Qh"], ["Js", "Jh"], ["Ts", "Th"], ["9s", "9h"]]
public = {
    "schema": "agx.public-replay.v1", "complete": True,
    "descriptor": {
        "complete": True, "job_id": "fixture-public", "rules_version": "rsi-poker-4.1",
        "simulation_version": "rsi-poker-4.0", "result": {"hands": 1},
    },
    "streams": {"public_events": [
        {"event": "hand_start", "hand": 1, "rotation": 0, "rotation_hand": 1, "A": list(range(6)),
         "button": 5, "start_stacks": [10000] * 6, "holes": holes},
        {"event": "blind", "seat": 0, "amount": 50}, {"event": "blind", "seat": 1, "amount": 100},
        {"event": "deal", "street": "preflop", "cards": []},
        {"event": "act", "seat": 2, "action": "raise", "to": 300},
        *({"event": "act", "seat": seat, "action": "fold", "to": 0} for seat in (3, 4, 5, 0, 1)),
        {"event": "uncalled", "seat": 2, "amount": 200}, {"event": "award", "awards": [0, 0, 250, 0, 0, 0]},
        {"event": "hand_end", "end_stacks": [9950, 9900, 10150, 10000, 10000, 10000]},
        {"event": "match_end"}, {"event": "final"},
    ]},
}
with tempfile.TemporaryDirectory(prefix="agx-dataset-") as temporary:
    folder = Path(temporary)
    raw, output, reports = folder / "raw", folder / "parsed", folder / "reports"
    raw.mkdir()
    source = raw / "replay-fixture-public.json"
    source.write_text(json.dumps(public), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    download_manifest = {
        "selection": {"job_ids": ["fixture-public"]}, "failures": [],
        "completed": [{"job_id": "fixture-public", "file": source.name, "sha256": digest}],
    }
    (raw / "manifest.json").write_text(json.dumps(download_manifest), encoding="utf-8")
    result = subprocess.run([
        sys.executable, str(ROOT / "tools" / "build_replay_dataset.py"),
        "--raw-dir", str(raw), "--output-dir", str(output), "--required", "1",
        "--report", str(reports / "validation.json"),
        "--dataset-manifest", str(reports / "dataset.json"),
    ], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr + result.stdout
    rows = [json.loads(line) for line in (output / "all.jsonl").read_text().splitlines()]
    assert len(rows) == 6 and all(row["match_id"] == "fixture-public" for row in rows)
    assert all("action_bucket" in row and "players" in row for row in rows)
    manifest = json.loads((reports / "dataset.json").read_text())
    assert manifest["matches"] == 1 and manifest["decisions"] == 6

print("replay behavior dataset tests: ok")
