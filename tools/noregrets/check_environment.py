#!/usr/bin/env python3
"""Verify a pinned NoRegrets checkout without starting training.

The checker is intentionally read-only.  ``status`` verifies the checked-in
audit manifest and, when ``--source`` is supplied, the third-party checkout.
``require`` additionally enforces the competition-authorization and build
gates before a caller may start training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "poker-distill" / "teachers" / "noregrets" / "manifest.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class AuditError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*args: str, cwd: Path) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    except OSError as exc:
        raise AuditError(f"cannot execute {args[0]}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise AuditError(f"command failed ({' '.join(args)}): {detail}")
    return result.stdout.strip()


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read manifest {path}: {exc}") from exc
    if manifest.get("schema") != "agx.noregrets-teacher.v1":
        raise AuditError("unsupported NoRegrets manifest schema")
    upstream = manifest.get("upstream", {})
    if upstream.get("url") != "https://github.com/conorarmstrong/noregrets.git":
        raise AuditError("unexpected upstream URL")
    if not HEX40.fullmatch(str(upstream.get("commit", ""))):
        raise AuditError("upstream commit must be a full 40-character SHA")
    if upstream.get("license", {}).get("spdx") != "MIT":
        raise AuditError("only the audited MIT upstream is accepted")
    for filename in ("LICENSE", "README.md", "Cargo.toml", "Cargo.lock"):
        value = upstream.get("files", {}).get(filename, {}).get("sha256", "")
        if not HEX64.fullmatch(str(value)):
            raise AuditError(f"missing SHA-256 for {filename}")
    if upstream.get("has_git_submodules") is not False:
        raise AuditError("manifest must explicitly deny Git submodules")
    if upstream.get("pretrained_artifacts_in_public_repo") is not False:
        raise AuditError("manifest must explicitly deny public pretrained artifacts")
    license_copy = ROOT / upstream["license"]["local_copy"]
    if not license_copy.is_file():
        raise AuditError("audited LICENSE copy is missing")
    if sha256_file(license_copy) != upstream["files"]["LICENSE"]["sha256"]:
        raise AuditError("audited LICENSE copy hash does not match upstream")
    artifacts = manifest.get("artifacts", {})
    config_path = ROOT / str(artifacts.get("training_config", ""))
    config_hash = str(artifacts.get("training_config_sha256", ""))
    if not config_path.is_file() or not HEX64.fullmatch(config_hash):
        raise AuditError("pinned training configuration or its SHA-256 is missing")
    if sha256_file(config_path) != config_hash:
        raise AuditError("pinned training configuration hash mismatch")
    formal_config_value = artifacts.get("formal_training_config")
    if formal_config_value:
        formal_config_path = ROOT / str(formal_config_value)
        formal_config_hash = str(artifacts.get("formal_training_config_sha256", ""))
        if not formal_config_path.is_file() or not HEX64.fullmatch(formal_config_hash):
            raise AuditError("formal training configuration or its SHA-256 is missing")
        if sha256_file(formal_config_path) != formal_config_hash:
            raise AuditError("formal training configuration hash mismatch")
    for name in ("ng4_evaluation", "ng4_project_evaluation"):
        value = artifacts.get(f"{name}_config")
        if not value:
            continue
        path = ROOT / str(value)
        expected = str(artifacts.get(f"{name}_config_sha256", ""))
        if not path.is_file() or not HEX64.fullmatch(expected):
            raise AuditError(f"{name} configuration or its SHA-256 is missing")
        if sha256_file(path) != expected:
            raise AuditError(f"{name} configuration hash mismatch")
    for patch in manifest.get("integration", {}).get("upstream_modifications", []):
        patch_path = ROOT / str(patch.get("patch", ""))
        patch_hash = str(patch.get("sha256", ""))
        if not patch_path.is_file() or not HEX64.fullmatch(patch_hash):
            raise AuditError("recorded upstream patch or its SHA-256 is missing")
        if sha256_file(patch_path) != patch_hash:
            raise AuditError(f"upstream patch hash mismatch: {patch_path}")
    smoke_path_value = artifacts.get("smoke_report")
    if smoke_path_value:
        smoke_path = ROOT / str(smoke_path_value)
        smoke_hash = str(artifacts.get("smoke_report_sha256", ""))
        if not smoke_path.is_file() or not HEX64.fullmatch(smoke_hash):
            raise AuditError("recorded smoke report or its SHA-256 is missing")
        if sha256_file(smoke_path) != smoke_hash:
            raise AuditError("smoke report hash mismatch")
        try:
            smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuditError(f"cannot read smoke report: {exc}") from exc
        if smoke.get("schema") != "agx.noregrets-smoke-summary.v1" or smoke.get("gate") != "passed":
            raise AuditError("NG-3 smoke report has not passed")
        if smoke.get("eligible_for_student_training") is not False:
            raise AuditError("smoke artifacts must be ineligible for student training")
        if smoke.get("binary_sha256") != manifest.get("build", {}).get("binary_sha256"):
            raise AuditError("smoke report binary does not match the audited build")
        if smoke.get("config_sha256") != config_hash:
            raise AuditError("smoke report configuration does not match the pinned configuration")
        if smoke.get("artifacts", {}).get("checkpoint_resumed", {}).get("sha256") != artifacts.get("checkpoint_sha256"):
            raise AuditError("smoke checkpoint hash does not match the teacher manifest")
    return manifest


def normalize_remote(value: str) -> str:
    return value.removesuffix("/").removesuffix(".git")


def check_source(source: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if not (source / ".git").exists():
        raise AuditError(f"not a Git checkout: {source}")
    upstream = manifest["upstream"]
    actual_commit = run("git", "rev-parse", "HEAD", cwd=source)
    if actual_commit != upstream["commit"]:
        raise AuditError(f"checkout commit {actual_commit} is not pinned commit {upstream['commit']}")
    remote = run("git", "remote", "get-url", "origin", cwd=source)
    if normalize_remote(remote) != normalize_remote(upstream["url"]):
        raise AuditError(f"unexpected origin remote: {remote}")
    dirty = run("git", "status", "--porcelain", cwd=source)
    expected_dirty = manifest.get("integration", {}).get("expected_git_status", "")
    if dirty != expected_dirty:
        raise AuditError(f"unexpected upstream worktree state: {dirty!r}")
    diff = run("git", "diff", "--no-ext-diff", "--binary", cwd=source)
    # run() strips only the outer newline; git diff hashes are recorded with
    # the canonical trailing newline restored.
    diff_hash = hashlib.sha256((diff + ("\n" if diff else "")).encode()).hexdigest()
    if diff_hash != manifest.get("integration", {}).get("applied_diff_sha256"):
        raise AuditError("applied upstream diff hash does not match the audited patch stack")
    gitmodules = source / ".gitmodules"
    if gitmodules.exists() and gitmodules.read_text(encoding="utf-8").strip():
        raise AuditError("upstream checkout unexpectedly contains submodules")
    for filename, record in upstream["files"].items():
        path = source / filename
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise AuditError(f"upstream file hash mismatch: {filename}")
    toolchain = manifest["toolchain"]
    versions = {}
    for command in ("rustc", "cargo"):
        actual = run(command, "--version", cwd=source)
        expected = toolchain[command]
        if actual != expected:
            raise AuditError(f"{command} version mismatch: {actual!r} != {expected!r}")
        versions[command] = actual
    build = manifest["build"]
    if build.get("status") == "passed":
        binary = source / str(build.get("binary", ""))
        expected_binary_hash = str(build.get("binary_sha256", ""))
        if not binary.is_file() or not HEX64.fullmatch(expected_binary_hash):
            raise AuditError("passed build is missing its release binary or SHA-256")
        if sha256_file(binary) != expected_binary_hash:
            raise AuditError("release binary hash does not match the audited build")
        query_value = build.get("agx_query_binary")
        if query_value:
            query = source / str(query_value)
            expected_query_hash = str(build.get("agx_query_binary_sha256", ""))
            if not query.is_file() or not HEX64.fullmatch(expected_query_hash):
                raise AuditError("AGX query binary or its SHA-256 is missing")
            if sha256_file(query) != expected_query_hash:
                raise AuditError("AGX query binary hash does not match the audited build")
    return {"path": str(source.resolve()), "commit": actual_commit, "toolchain": versions}


def gate_errors(manifest: dict[str, Any]) -> list[str]:
    errors = []
    authorization = manifest["competition_authorization"]
    if authorization.get("status") != "confirmed":
        errors.append("competition authorization for an offline public-source teacher is not confirmed")
    build = manifest["build"]
    if build.get("status") != "passed" or not HEX64.fullmatch(str(build.get("binary_sha256", ""))):
        errors.append("pinned release build has not passed with a recorded binary SHA-256")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the pinned NoRegrets environment")
    parser.add_argument("mode", choices=("status", "require"), nargs="?", default="status")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source", type=Path, help="path to the independent upstream checkout")
    args = parser.parse_args()

    try:
        manifest = load_manifest(args.manifest.resolve())
        source_status = check_source(args.source.resolve(), manifest) if args.source else None
        blockers = gate_errors(manifest)
        result = {
            "schema": "agx.noregrets-environment-check.v1",
            "manifest": str(args.manifest.resolve()),
            "manifest_valid": True,
            "source_checked": source_status is not None,
            "source": source_status,
            "training_allowed": not blockers and source_status is not None,
            "blockers": blockers + ([] if source_status is not None else ["source checkout was not checked"]),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if args.mode == "require" and not result["training_allowed"]:
            raise SystemExit(1)
    except AuditError as exc:
        print(json.dumps({"schema": "agx.noregrets-environment-check.v1", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
