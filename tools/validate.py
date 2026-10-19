#!/usr/bin/env python3
import argparse
from pathlib import Path
import re

from competition_rules import load_and_check_rules

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="校验 AGX 单文件提交")
parser.add_argument("submission", nargs="?", type=Path, default=ROOT / "submission.js")
args = parser.parse_args()
submission = args.submission if args.submission.is_absolute() else Path.cwd() / args.submission
source = submission.read_text(encoding="utf-8")
errors = []
rules = load_and_check_rules()

if len(source.encode()) > rules["limits"]["sourceBytes"]:
    errors.append(f"submission exceeds {rules['limits']['sourceBytes']} bytes")
if not re.search(r"function\s+act\s*\(\s*view\s*\)", source):
    errors.append("missing function act(view)")
if rules["rulesVersion"] not in source:
    errors.append(f"submission does not pin rules version {rules['rulesVersion']}")
for pattern, label in [
    (r"\brequire\s*\(", "require"),
    (r"\bimport\s+", "import"),
    (r"\bfetch\s*\(", "network fetch"),
    (r"\bXMLHttpRequest\b", "XMLHttpRequest"),
    (r"\bWebSocket\b", "WebSocket"),
    (r"\bEventSource\b", "EventSource"),
    (r"\bimportScripts\s*\(", "importScripts"),
    (r"\bDate\s*\(", "host clock"),
    (r"\basync\s+function", "async function"),
    (r"\bconsole\.", "console"),
]:
    if re.search(pattern, source):
        errors.append(f"runtime-forbidden construct: {label}")

actions = set(re.findall(r'type:\s*"([a-z_]+)"', source))
unknown = actions - {"fold", "check", "call", "bet", "raise", "allin", "all_in"}
if unknown:
    errors.append(f"unknown literal actions: {sorted(unknown)}")

if errors:
    print("validation: FAILED")
    for error in errors:
        print("-", error)
    raise SystemExit(1)

print("validation: ok")
print(f"file: {submission}")
print(f"source bytes: {len(source.encode())}")
print("entry point: function act(view)")
print("literal actions:", ", ".join(sorted(actions)))
