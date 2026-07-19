from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "openapi-engineering"
SCRIPT_ROOT = SKILL_ROOT / "scripts"


def usage_config_path(home: Path) -> Path:
    if os.name == "nt":
        return home / "AppData" / "Local" / "openapi-engineering-skill" / "usage.json"
    return home / ".config" / "openapi-engineering-skill" / "usage.json"


def usage_state_root(home: Path) -> Path:
    if os.name == "nt":
        return home / "AppData" / "Local" / "openapi-engineering-skill" / "state"
    return home / ".local" / "state" / "openapi-engineering-skill"


def run_script(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_ROOT / name), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_json_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"stdout was not JSON (exit={result.returncode}): {result.stdout!r}; "
            f"stderr={result.stderr!r}"
        ) from exc


def snapshot_tree(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot
