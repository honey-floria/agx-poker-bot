#!/usr/bin/env python3

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "experiment_registry.py"


def run(root: Path, *arguments: str, succeeds: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["python3", str(SCRIPT), "--root", str(root), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if succeeds and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    if not succeeds and result.returncode == 0:
        raise AssertionError("command unexpectedly succeeded")
    return result


with tempfile.TemporaryDirectory(prefix="agx-experiments-") as temporary:
    temporary_path = Path(temporary)
    registry_root = temporary_path / "poker-distill"
    config = temporary_path / "config.json"
    model = temporary_path / "model.bin"
    config.write_text('{"epochs":3,"seed":7607}\n', encoding="utf-8")
    model.write_bytes(b"deterministic-model-payload")

    create_args = (
        "create",
        "--id", "E03_solver_mix_v2",
        "--config", str(config),
        "--training-data", "solver-mix",
        "--data-version", "dataset-2026-10-20",
        "--seed", "7607",
        "--teacher-version", "teacher-v2",
        "--model-structure", "32x64x32x4",
        "--loss-weights", "ce=1,value=0.25,regret=0.5",
        "--quantization", "float16",
        "--notes", "registry lifecycle test",
    )
    run(registry_root, *create_args)
    duplicate = run(registry_root, *create_args, succeeds=False)
    assert "已登记" in duplicate.stderr
    invalid = run(
        registry_root,
        "create", "--id", "bad-id", "--config", str(config),
        "--training-data", "x", "--data-version", "x", "--seed", "1",
        "--teacher-version", "x", "--model-structure", "x",
        "--loss-weights", "x", "--quantization", "x",
        succeeds=False,
    )
    assert "编号必须匹配" in invalid.stderr
    run(registry_root, "check")

    run(
        registry_root,
        "complete",
        "--id", "E03_solver_mix_v2",
        "--model", str(model),
        "--offline-results", '{"mbb_per_hand":12.5,"first_place_rate":0.24}',
    )
    run(
        registry_root,
        "set-online",
        "--id", "E03_solver_mix_v2",
        "--online-version", "agx-v17",
    )
    checked = run(registry_root, "check")
    assert "1 records" in checked.stdout

    csv_path = registry_root / "experiments" / "experiments.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "completed"
    assert row["git_commit"]
    assert row["random_seed"] == "7607"
    assert row["online_version"] == "agx-v17"
    assert row["model_sha256"] == hashlib.sha256(model.read_bytes()).hexdigest()
    assert json.loads(row["offline_results"])["mbb_per_hand"] == 12.5

    experiment_dir = registry_root / "experiments" / "E03_solver_mix_v2"
    assert (experiment_dir / "config.json").read_bytes() == config.read_bytes()
    manifest = json.loads((experiment_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == row

print("experiment registry test: ok")
