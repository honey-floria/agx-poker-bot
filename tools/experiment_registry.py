#!/usr/bin/env python3
"""Create and maintain reproducible poker-distillation experiment records."""

from __future__ import annotations

import argparse
import csv
import hashlib
import out
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "poker-distill"
EXPERIMENT_ID = re.compile(r"^E\d{2,}_[a-z0-9][a-z0-9_-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
FIELDS = [
    "experiment_id",
    "created_at_utc",
    "completed_at_utc",
    "status",
    "git_commit",
    "git_dirty",
    "config_path",
    "config_sha256",
    "training_data",
    "data_version",
    "teacher_version",
    "model_structure",
    "loss_weights",
    "quantization",
    "random_seed",
    "model_path",
    "model_sha256",
    "offline_results",
    "online_version",
    "notes",
]
CREATE_REQUIRED = [
    "git_commit",
    "config_path",
    "config_sha256",
    "training_data",
    "data_version",
    "teacher_version",
    "model_structure",
    "loss_weights",
    "quantization",
    "random_seed",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def git_state() -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    return commit, "true" if status.strip() else "false"


class Registry:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.experiments_dir = self.root / "experiments"
        self.csv_path = self.experiments_dir / "experiments.csv"

    def ensure(self) -> None:
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            self._write_rows([])

    def read_rows(self) -> list[dict[str, str]]:
        self.ensure()
        with self.csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != FIELDS:
                raise RuntimeError("experiments.csv 字段与登记规范不一致")
            return [dict(row) for row in reader]

    def _write_rows(self, rows: list[dict[str, str]]) -> None:
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix="experiments.", suffix=".csv.tmp", dir=self.experiments_dir
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="raise")
                writer.writeheader()
                writer.writerows(rows)
            os.replace(temporary, self.csv_path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _manifest_path(self, experiment_id: str) -> Path:
        return self.experiments_dir / experiment_id / "manifest.out"

    def _write_manifest(self, row: dict[str, str]) -> None:
        path = self._manifest_path(row["experiment_id"])
        path.write_text(
            out.dumps(row, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    def _find(self, rows: list[dict[str, str]], experiment_id: str) -> dict[str, str]:
        matches = [row for row in rows if row["experiment_id"] == experiment_id]
        if not matches:
            raise RuntimeError(f"实验不存在：{experiment_id}")
        if len(matches) != 1:
            raise RuntimeError(f"实验编号重复：{experiment_id}")
        return matches[0]

    def create(self, args: argparse.Namespace) -> None:
        if not EXPERIMENT_ID.fullmatch(args.experiment_id):
            raise RuntimeError("实验编号必须匹配 E<至少两位数字>_<小写名称>")
        config = args.config.resolve()
        if not config.is_file():
            raise RuntimeError(f"配置文件不存在：{config}")
        rows = self.read_rows()
        if any(row["experiment_id"] == args.experiment_id for row in rows):
            raise RuntimeError(f"实验编号已登记：{args.experiment_id}")
        experiment_dir = self.experiments_dir / args.experiment_id
        if experiment_dir.exists():
            raise RuntimeError(f"实验目录已存在：{experiment_dir}")

        experiment_dir.mkdir(parents=False)
        suffix = config.suffix.lower() or ".txt"
        snapshot = experiment_dir / f"config{suffix}"
        try:
            shutil.copy2(config, snapshot)
            commit, dirty = git_state()
            row = {field: "" for field in FIELDS}
            row.update(
                {
                    "experiment_id": args.experiment_id,
                    "created_at_utc": utc_now(),
                    "status": "running",
                    "git_commit": commit,
                    "git_dirty": dirty,
                    "config_path": display_path(snapshot),
                    "config_sha256": sha256_file(snapshot),
                    "training_data": args.training_data,
                    "data_version": args.data_version,
                    "teacher_version": args.teacher_version,
                    "model_structure": args.model_structure,
                    "loss_weights": args.loss_weights,
                    "quantization": args.quantization,
                    "random_seed": str(args.seed),
                    "notes": args.notes,
                }
            )
            self._write_manifest(row)
            self._write_rows(rows + [row])
        except Exception:
            shutil.rmtree(experiment_dir, ignore_errors=True)
            raise
        print(f"experiment created: {args.experiment_id}")
        print(f"manifest: {self._manifest_path(args.experiment_id)}")

    def complete(self, experiment_id: str, model: Path, offline_results: str) -> None:
        model = model.resolve()
        if not model.is_file():
            raise RuntimeError(f"模型文件不存在：{model}")
        try:
            parsed_results = out.loads(offline_results)
        except out.JSONDecodeError as error:
            raise RuntimeError(f"offline-results 必须是合法 JSON：{error}") from error
        if not isinstance(parsed_results, dict) or not parsed_results:
            raise RuntimeError("offline-results 必须是非空 JSON 对象")

        rows = self.read_rows()
        row = self._find(rows, experiment_id)
        if row["status"] == "completed":
            raise RuntimeError(f"实验已经完成：{experiment_id}")
        row.update(
            {
                "completed_at_utc": utc_now(),
                "status": "completed",
                "model_path": display_path(model),
                "model_sha256": sha256_file(model),
                "offline_results": out.dumps(parsed_results, ensure_ascii=False, separators=(",", ":")),
            }
        )
        self._write_manifest(row)
        self._write_rows(rows)
        print(f"experiment completed: {experiment_id}")
        print(f"model sha256: {row['model_sha256']}")

    def set_online(self, experiment_id: str, online_version: str) -> None:
        rows = self.read_rows()
        row = self._find(rows, experiment_id)
        if row["status"] != "completed":
            raise RuntimeError("只有已完成实验可以登记线上版本")
        row["online_version"] = online_version
        self._write_manifest(row)
        self._write_rows(rows)
        print(f"online version recorded: {experiment_id} -> {online_version}")

    def check(self) -> None:
        rows = self.read_rows()
        errors = []
        seen = set()
        for line_number, row in enumerate(rows, start=2):
            experiment_id = row.get("experiment_id", "")
            prefix = f"第{line_number}行 {experiment_id or '<空编号>'}"
            if not EXPERIMENT_ID.fullmatch(experiment_id):
                errors.append(f"{prefix}：编号格式错误")
            if experiment_id in seen:
                errors.append(f"{prefix}：编号重复")
            seen.add(experiment_id)
            for field in CREATE_REQUIRED:
                if not row.get(field):
                    errors.append(f"{prefix}：缺少 {field}")
            if row.get("git_commit") and not GIT_COMMIT.fullmatch(row["git_commit"]):
                errors.append(f"{prefix}：git_commit 格式错误")
            if row.get("git_dirty") not in ("true", "false"):
                errors.append(f"{prefix}：git_dirty 必须为 true 或 false")
            for field in ("config_sha256", "model_sha256"):
                if row.get(field) and not SHA256.fullmatch(row[field]):
                    errors.append(f"{prefix}：{field} 不是 SHA-256")
            if row.get("status") not in ("running", "completed"):
                errors.append(f"{prefix}：未知状态 {row.get('status')!r}")
            if row.get("status") == "completed":
                for field in ("completed_at_utc", "model_path", "model_sha256", "offline_results"):
                    if not row.get(field):
                        errors.append(f"{prefix}：已完成实验缺少 {field}")
                try:
                    result = out.loads(row.get("offline_results", ""))
                    if not isinstance(result, dict) or not result:
                        raise ValueError
                except (out.JSONDecodeError, ValueError):
                    errors.append(f"{prefix}：offline_results 不是非空 JSON 对象")

            config_path = Path(row.get("config_path", ""))
            if not config_path.is_absolute():
                config_path = REPO_ROOT / config_path
            if not config_path.is_file():
                errors.append(f"{prefix}：配置快照不存在")
            elif sha256_file(config_path) != row.get("config_sha256"):
                errors.append(f"{prefix}：配置快照哈希不一致")

            manifest = self._manifest_path(experiment_id)
            if not manifest.is_file():
                errors.append(f"{prefix}：缺少 manifest.out")
            else:
                try:
                    manifest_row = out.loads(manifest.read_text(encoding="utf-8"))
                    if manifest_row != row:
                        errors.append(f"{prefix}：manifest.out 与 CSV 不一致")
                except out.JSONDecodeError:
                    errors.append(f"{prefix}：manifest.out 无法解析")

        if errors:
            raise RuntimeError("实验登记检查失败：\n- " + "\n- ".join(errors))
        print(f"experiment registry: ok ({len(rows)} records)")

    def list_rows(self) -> None:
        rows = self.read_rows()
        if not rows:
            print("no experiments")
            return
        print("experiment_id\tstatus\tdata_version\tmodel_sha256\tonline_version")
        for row in rows:
            print("\t".join(row[field] for field in (
                "experiment_id", "status", "data_version", "model_sha256", "online_version"
            )))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="管理可复现的扑克蒸馏实验记录")
    result.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="poker-distill 根目录")
    commands = result.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="创建唯一实验编号并保存配置快照")
    create.add_argument("--id", dest="experiment_id", required=True)
    create.add_argument("--config", type=Path, required=True)
    create.add_argument("--training-data", required=True)
    create.add_argument("--data-version", required=True)
    create.add_argument("--seed", type=int, required=True)
    create.add_argument("--teacher-version", required=True)
    create.add_argument("--model-structure", required=True)
    create.add_argument("--loss-weights", required=True)
    create.add_argument("--quantization", required=True)
    create.add_argument("--notes", default="")

    complete = commands.add_parser("complete", help="登记模型哈希与离线结果")
    complete.add_argument("--id", dest="experiment_id", required=True)
    complete.add_argument("--model", type=Path, required=True)
    complete.add_argument("--offline-results", required=True)

    online = commands.add_parser("set-online", help="登记正式线上版本号")
    online.add_argument("--id", dest="experiment_id", required=True)
    online.add_argument("--online-version", required=True)

    commands.add_parser("check", help="校验编号、必填字段、哈希和 manifest 一致性")
    commands.add_parser("list", help="列出实验摘要")
    return result


def main() -> None:
    args = parser().parse_args()
    registry = Registry(args.root)
    try:
        if args.command == "create":
            registry.create(args)
        elif args.command == "complete":
            registry.complete(args.experiment_id, args.model, args.offline_results)
        elif args.command == "set-online":
            registry.set_online(args.experiment_id, args.online_version)
        elif args.command == "check":
            registry.check()
        elif args.command == "list":
            registry.list_rows()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"error: {error}") from error


if __name__ == "__main__":
    main()
