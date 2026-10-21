#!/usr/bin/env python3

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "noregrets" / "check_environment.py"


status = subprocess.run(
    ["python3", str(SCRIPT), "status"],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=True,
)
payload = json.loads(status.stdout)
assert payload["manifest_valid"] is True
assert payload["source_checked"] is False
assert payload["training_allowed"] is False
assert payload["blockers"] == ["source checkout was not checked"]

required = subprocess.run(
    ["python3", str(SCRIPT), "require"],
    cwd=ROOT,
    text=True,
    capture_output=True,
)
assert required.returncode != 0

manifest = json.loads(
    (ROOT / "poker-distill" / "teachers" / "noregrets" / "manifest.json").read_text(encoding="utf-8")
)
assert manifest["upstream"]["commit"] == "757f7692738069522195d2b486eec60a8b010c0c"
assert manifest["upstream"]["commercial_artifacts_allowed"] is False
assert manifest["competition_authorization"]["status"] == "confirmed"

print("noregrets environment audit test: ok")
