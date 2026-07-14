#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def artifact_row(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "path": display_path(path),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def refresh_manifest(manifest_path: Path, evidence_root: Path) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    evidence_root = evidence_root.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Evidence manifest must be a schema_version 1 JSON object.")
    if not evidence_root.is_dir():
        raise ValueError("Evidence root must be a directory.")

    artifacts = [
        artifact_row(path)
        for path in sorted(evidence_root.rglob("*"))
        if path.is_file()
        and path.resolve() != manifest_path
        and not path.name.endswith(".tmp")
    ]
    manifest["artifacts"] = artifacts
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh a deterministic SHA-256 inventory of TDD evidence."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = refresh_manifest(args.manifest, args.evidence_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"status": "ok", "artifacts": len(manifest["artifacts"])}, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
