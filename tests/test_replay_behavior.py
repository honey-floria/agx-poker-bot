#!/usr/bin/env python3

import hashlib
import json
from copy import deepcopy
from pathlib import Path
import shutil
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
from download_agx_top_teacher_replays import balanced_selection


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

# Python training features and the exported QuickJS runtime must stay exactly
# aligned; a zero-weight fixture also exercises legality-masked runtime action.
with tempfile.TemporaryDirectory(prefix="agx-bc-v2-runtime-") as temporary:
    folder = Path(temporary)
    model_path, output_path, hybrid_path = folder / "model.json", folder / "submission.js", folder / "hybrid.js"
    model = {
        "format": "agx-poker-bc-v2", "data_version": "public-replay-bc-v1",
        "feature_version": "public-replay-features-v2", "input_size": INPUT_SIZE_V2,
        "hidden1_size": 2, "hidden2_size": 2,
        "family_actions": list(FAMILY_ACTIONS), "size_actions": list(SIZE_ACTIONS),
        "trunk_w1": [[0.0] * INPUT_SIZE_V2 for _ in range(2)], "trunk_b1": [0.0, 0.0],
        "trunk_w2": [[0.0, 0.0], [0.0, 0.0]], "trunk_b2": [0.0, 0.0],
        "family_w": [[0.0, 0.0] for _ in FAMILY_ACTIONS], "family_b": [0.0, 1.0, 0.0, 0.0, 0.0],
        "size_w": [[0.0, 0.0] for _ in SIZE_ACTIONS], "size_b": [0.0] * len(SIZE_ACTIONS),
    }
    model_path.write_text(json.dumps(model), encoding="utf-8")
    exported = subprocess.run([
        sys.executable, str(ROOT / "neural" / "export_behavior_v2.py"),
        "--model", str(model_path), "--output", str(output_path),
    ], cwd=ROOT, text=True, capture_output=True)
    assert exported.returncode == 0, exported.stderr + exported.stdout
    validated = subprocess.run([
        sys.executable, str(ROOT / "tools" / "validate.py"), str(output_path),
    ], cwd=ROOT, text=True, capture_output=True)
    assert validated.returncode == 0, validated.stderr + validated.stdout
    hybrid = subprocess.run([
        sys.executable, str(ROOT / "neural" / "export_behavior_hybrid.py"),
        "--neural", str(output_path), "--output", str(hybrid_path),
        "--min-confidence", "0.99",
    ], cwd=ROOT, text=True, capture_output=True)
    assert hybrid.returncode == 0, hybrid.stderr + hybrid.stdout
    hybrid_validated = subprocess.run([
        sys.executable, str(ROOT / "tools" / "validate.py"), str(hybrid_path),
    ], cwd=ROOT, text=True, capture_output=True)
    assert hybrid_validated.returncode == 0, hybrid_validated.stderr + hybrid_validated.stdout
    runtime_view = {
        "rules": "rsi-poker-4.0", "street": BASE["street"], "board": BASE["board"],
        "pot": BASE["pot"], "toCall": BASE["to_call"], "minRaiseTo": BASE["min_raise_to"],
        "maxRaiseTo": BASE["max_raise_to"], "canRaise": BASE["can_raise"], "legal": BASE["legal"],
        "me": {"seat": BASE["seat"], "cards": BASE["hole"], "position": BASE["position"],
               "stack": BASE["stack"], "bet": BASE["me_bet"], "invested": BASE["invested"]},
        "players": BASE["players"], "actions": BASE["history"],
    }
    if shutil.which("node"):
        script = (
            f"const policy=require({json.dumps(str(output_path))});"
            f"const view={json.dumps(runtime_view)};"
            "console.log(JSON.stringify({features:policy.features(view),action:policy.act(view)}));"
        )
        runtime = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True)
        assert runtime.returncode == 0, runtime.stderr
        runtime_result = json.loads(runtime.stdout)
        assert max(abs(left - right) for left, right in zip(runtime_result["features"], features_v2)) < 1e-12
        assert runtime_result["action"] == {"type": "check"}

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

# Targeted replay selection should prefer the least represented teacher while
# remaining deterministic when several candidates are equally useful.
teacher_ranks = {"top-1": 1, "top-2": 2}
candidate_jobs = [
    {"id": "j1", "participants": [{"team": 0, "display_name": "top-1"}]},
    {"id": "j2", "participants": [{"team": 1, "display_name": "top-1"}]},
    {"id": "j3", "participants": [{"team": 2, "display_name": "top-2"}]},
    {"id": "j4", "participants": [{"team": 3, "display_name": "top-2"}]},
]
selected_jobs, teacher_appearances = balanced_selection(candidate_jobs, teacher_ranks, 3)
assert [job["id"] for job in selected_jobs] == ["j1", "j3", "j2"]
assert teacher_appearances == {"top-1": 2, "top-2": 1}


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

with tempfile.TemporaryDirectory(prefix="agx-top-teacher-dataset-") as temporary:
    folder = Path(temporary)
    raw, output, reports = folder / "raw", folder / "parsed", folder / "reports"
    raw.mkdir()
    source = raw / "replay-fixture-public.json"
    source.write_text(json.dumps(public), encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    download_manifest = {
        "selection": {
            "competition_id": "fixture-competition", "selected_at_unix": 1,
            "top_k": 20, "job_ids": ["fixture-public"],
        },
        "failures": [],
        "completed": [{
            "job_id": "fixture-public", "file": source.name, "sha256": digest,
            "participants": [
                {"team": team, "display_name": f"player-{team}",
                 "leaderboard_rank": 1 if team == 0 else None}
                for team in range(6)
            ],
        }],
    }
    (raw / "manifest.json").write_text(json.dumps(download_manifest), encoding="utf-8")
    result = subprocess.run([
        sys.executable, str(ROOT / "tools" / "build_top_teacher_dataset.py"),
        "--raw-dir", str(raw), "--output-dir", str(output), "--required", "1",
        "--report", str(reports / "validation.json"),
        "--dataset-manifest", str(reports / "dataset.json"),
    ], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr + result.stdout
    rows = [json.loads(line) for line in (output / "all.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["player"] == "anon_1" and rows[0]["teacher_rank"] == 1
    assert rows[0]["teacher_tier"] == "top5"
    assert "display_name" not in rows[0]
    manifest = json.loads((reports / "dataset.json").read_text())
    assert manifest["matches"] == 1 and manifest["decisions"] == 1
    assert manifest["teacher_rank_decisions"]["1"] == 1

print("replay behavior dataset tests: ok")
