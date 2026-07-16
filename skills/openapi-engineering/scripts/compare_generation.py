#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SKIP_DIRECTORIES = {".git", ".pytest_cache", "__pycache__", "node_modules"}
SKIP_FILES = {".DS_Store"}


def emit(payload: dict[str, Any], pretty: bool) -> None:
    kwargs: dict[str, Any] = {"ensure_ascii": False, "sort_keys": True}
    if pretty:
        kwargs["indent"] = 2
    else:
        kwargs["separators"] = (",", ":")
    print(json.dumps(payload, **kwargs))


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def collect(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(
            directory for directory in directories if directory not in SKIP_DIRECTORIES
        )
        current_path = Path(current)
        for filename in sorted(filenames):
            if filename in SKIP_FILES:
                continue
            path = current_path / filename
            if path.is_symlink() or not path.is_file():
                continue
            files[path.relative_to(root).as_posix()] = digest(path)
    return files


def tree_digest(files: dict[str, str]) -> str:
    hasher = hashlib.sha256()
    for path, file_digest in files.items():
        hasher.update(path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(bytes.fromhex(file_digest))
        hasher.update(b"\0")
    return hasher.hexdigest()


def compare(baseline: Path, candidate: Path) -> dict[str, Any]:
    baseline_files = collect(baseline)
    candidate_files = collect(candidate)
    rows: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}

    for path in sorted(set(baseline_files) | set(candidate_files)):
        baseline_hash = baseline_files.get(path)
        candidate_hash = candidate_files.get(path)
        if baseline_hash is None:
            state = "added"
        elif candidate_hash is None:
            state = "removed"
        elif baseline_hash != candidate_hash:
            state = "changed"
        else:
            state = "unchanged"
        counts[state] += 1
        rows.append(
            {
                "path": path,
                "state": state,
                "baseline_sha256": baseline_hash,
                "candidate_sha256": candidate_hash,
            }
        )

    return {
        "status": "ok",
        "baseline": str(baseline),
        "candidate": str(candidate),
        "baseline_tree_sha256": tree_digest(baseline_files),
        "candidate_tree_sha256": tree_digest(candidate_files),
        "summary": counts,
        "files": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two generated output directories.")
    parser.add_argument("baseline", help="Baseline generated directory.")
    parser.add_argument("candidate", help="Candidate generated directory.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()
    baseline = Path(args.baseline).expanduser().resolve()
    candidate = Path(args.candidate).expanduser().resolve()

    if not baseline.is_dir() or not candidate.is_dir():
        emit(
            {
                "status": "error",
                "error": {
                    "code": "invalid-directory",
                    "message": "Baseline and candidate must both be directories.",
                },
            },
            args.pretty,
        )
        return 2

    emit(compare(baseline, candidate), args.pretty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
