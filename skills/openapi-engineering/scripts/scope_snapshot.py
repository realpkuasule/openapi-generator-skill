#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "scope-snapshot.schema.json"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _validate(report: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(report),
        key=lambda item: list(item.path),
    )
    if errors:
        raise ValueError("Scope snapshot report violates its contract.")


def _normalize_paths(paths: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    for value in paths:
        path = Path(value)
        if path.is_absolute() or not path.parts or any(
            part in {"", ".", ".."} for part in path.parts
        ):
            raise ValueError("Selected paths must be non-traversing relative paths.")
        normalized.append(path.as_posix())
    if not normalized or len(normalized) != len(set(normalized)):
        raise ValueError("Selected paths must be non-empty and unique.")
    ordered = sorted(normalized)
    for index, left in enumerate(ordered):
        if any(right.startswith(left + "/") for right in ordered[index + 1 :]):
            raise ValueError("Selected paths must not overlap.")
    return ordered


def _validate_roots(root: Path, snapshot_dir: Path) -> tuple[Path, Path]:
    root = root.expanduser().resolve()
    snapshot_dir = snapshot_dir.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Project root must be an existing directory.")
    if (
        snapshot_dir == root
        or snapshot_dir.is_relative_to(root)
        or root.is_relative_to(snapshot_dir)
    ):
        raise ValueError("Snapshot directory must be external to the project root.")
    return root, snapshot_dir


def _reject_symlinks(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("Scope snapshots do not follow symlinks.")
    if path.is_dir() and any(item.is_symlink() for item in path.rglob("*")):
        raise ValueError("Scope snapshots do not follow symlinks.")


def _scope_state(
    root: Path, selected: Sequence[str]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    targets: list[dict[str, str]] = []
    inventory: list[dict[str, str]] = []
    for value in selected:
        target = root / value
        _reject_symlinks(target)
        if target.is_file():
            state = "file"
            inventory.append({"path": value, "sha256": sha256_file(target)})
        elif target.is_dir():
            state = "directory"
            for path in sorted(item for item in target.rglob("*") if item.is_file()):
                inventory.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "sha256": sha256_file(path),
                    }
                )
        elif target.exists():
            raise ValueError("Selected paths must be regular files or directories.")
        else:
            state = "missing"
        targets.append({"path": value, "state": state})
    return targets, inventory


def _scope_digest(
    targets: list[dict[str, str]], inventory: list[dict[str, str]]
) -> str:
    return sha256_bytes(canonical_bytes({"targets": targets, "inventory": inventory}))


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def create_snapshot(
    root: Path, snapshot_dir: Path, selected_paths: Sequence[str]
) -> dict[str, Any]:
    root, snapshot_dir = _validate_roots(root, snapshot_dir)
    selected = _normalize_paths(selected_paths)
    if snapshot_dir.exists() and any(snapshot_dir.iterdir()):
        raise ValueError("Snapshot directory must not already contain files.")
    created = not snapshot_dir.exists()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    data = snapshot_dir / "data"
    try:
        targets, inventory = _scope_state(root, selected)
        data.mkdir()
        for target in targets:
            if target["state"] == "missing":
                continue
            source = root / target["path"]
            destination = data / target["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            if target["state"] == "file":
                shutil.copy2(source, destination)
            else:
                shutil.copytree(source, destination)
        copied_targets, copied_inventory = _scope_state(data, selected)
        if copied_targets != targets or copied_inventory != inventory:
            raise ValueError("External snapshot copy failed its digest check.")
        core = {
            "report_version": 1,
            "status": "proposed",
            "operation": "snapshot",
            "root": str(root),
            "snapshot_dir": str(snapshot_dir),
            "selected_paths": selected,
            "targets": targets,
            "inventory": inventory,
            "scope_tree_sha256": _scope_digest(targets, inventory),
            "unchanged": True,
        }
        report = {
            **core,
            "approval_digest": sha256_bytes(canonical_bytes(core)),
        }
        _validate(report)
        _atomic_json(snapshot_dir / "manifest.json", report)
        return report
    except Exception:
        if created and snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)
        raise


def _remove_target(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("Restore refuses symlink targets.")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def restore_snapshot(
    root: Path,
    snapshot_dir: Path,
    manifest_path: Path,
    approval_digest: str,
) -> tuple[dict[str, Any], int]:
    try:
        root, snapshot_dir = _validate_roots(root, snapshot_dir)
        manifest = json.loads(
            manifest_path.expanduser().resolve().read_text(encoding="utf-8")
        )
        _validate(manifest)
        if manifest["status"] != "proposed" or manifest["operation"] != "snapshot":
            raise ValueError("Snapshot manifest is not a restorable proposal.")
        core = {key: value for key, value in manifest.items() if key != "approval_digest"}
        expected_approval = sha256_bytes(canonical_bytes(core))
        if (
            approval_digest != manifest["approval_digest"]
            or approval_digest != expected_approval
        ):
            return {"status": "blocked", "error": "Approval digest mismatch."}, 1
        if manifest["root"] != str(root) or manifest["snapshot_dir"] != str(snapshot_dir):
            raise ValueError("Snapshot manifest is bound to different paths.")
        selected = _normalize_paths(manifest["selected_paths"])
        data = snapshot_dir / "data"
        copied_targets, copied_inventory = _scope_state(data, selected)
        if (
            copied_targets != manifest["targets"]
            or copied_inventory != manifest["inventory"]
            or _scope_digest(copied_targets, copied_inventory)
            != manifest["scope_tree_sha256"]
        ):
            raise ValueError("Snapshot data no longer matches its manifest.")
        for target in manifest["targets"]:
            destination = root / target["path"]
            _remove_target(destination)
            if target["state"] == "missing":
                continue
            source = data / target["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            if target["state"] == "file":
                shutil.copy2(source, destination)
            else:
                shutil.copytree(source, destination)
        restored_targets, restored_inventory = _scope_state(root, selected)
        unchanged = (
            restored_targets == manifest["targets"]
            and restored_inventory == manifest["inventory"]
        )
        report = {
            **manifest,
            "status": "restored" if unchanged else "blocked",
            "operation": "restore",
            "unchanged": unchanged,
        }
        _validate(report)
        return report, 0 if unchanged else 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "blocked", "error": str(exc)}, 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or restore an external scope snapshot"
    )
    parser.add_argument("operation", choices=("snapshot", "restore"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--snapshot-dir", required=True, type=Path)
    parser.add_argument("--path", action="append", dest="paths")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--approve")
    args = parser.parse_args()
    try:
        if args.operation == "snapshot":
            if not args.paths or args.manifest or args.approve:
                raise ValueError("snapshot requires --path and does not accept restore arguments")
            payload = create_snapshot(args.root, args.snapshot_dir, args.paths)
            exit_code = 0
        else:
            if args.paths or not args.manifest or not args.approve:
                raise ValueError("restore requires --manifest and --approve")
            payload, exit_code = restore_snapshot(
                args.root, args.snapshot_dir, args.manifest, args.approve
            )
    except (OSError, ValueError) as exc:
        payload, exit_code = {"status": "blocked", "error": str(exc)}, 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
