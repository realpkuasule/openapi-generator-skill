from __future__ import annotations

import hashlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_NAMES = (
    "completion-report.schema.json",
    "eval-case.schema.json",
    "eval-result.schema.json",
    "forward-eval-report.schema.json",
    "forward-observation.schema.json",
)


def harness_files() -> list[Path]:
    files = [
        REPO_ROOT / "contracts" / "openapi-engineering.openapi.yaml",
        REPO_ROOT / "scripts" / "run_skill_evals.py",
        REPO_ROOT / "scripts" / "aggregate_forward_evals.py",
    ]
    files.extend(sorted((REPO_ROOT / "scripts" / "evals").rglob("*.py")))
    files.extend(
        REPO_ROOT / "contracts" / "schemas" / name for name in SCHEMA_NAMES
    )
    return sorted(set(files))


def harness_digest() -> str:
    hasher = hashlib.sha256()
    for path in harness_files():
        if not path.is_file():
            raise FileNotFoundError(f"Evaluation harness file is missing: {path}")
        hasher.update(path.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()
