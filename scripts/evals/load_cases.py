#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import yaml
from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "eval-case.schema.json"
DEFAULT_EVAL_ROOT = REPO_ROOT / "skills" / "openapi-engineering" / "evals"


class EvalCaseError(ValueError):
    pass


def schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def fixture_path(case: dict[str, Any]) -> Path:
    relative = Path(case["fixture_binding"]["compact_fixture"])
    if relative.is_absolute():
        raise EvalCaseError("compact_fixture must be repository-relative.")
    resolved = (REPO_ROOT / relative).resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise EvalCaseError("compact_fixture escapes the repository.") from exc
    if not resolved.is_dir():
        raise EvalCaseError(f"compact_fixture does not exist: {relative.as_posix()}")
    return resolved


def load_case(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EvalCaseError(f"Unable to load eval case {path.name}.") from exc
    if not isinstance(value, dict):
        raise EvalCaseError(f"Eval case {path.name} must be an object.")
    errors = sorted(schema_validator().iter_errors(value), key=lambda item: list(item.path))
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].path)
        raise EvalCaseError(
            f"Eval case {path.name} violates its schema at {location or '/'}: "
            f"{errors[0].message}"
        )
    fixture_path(value)
    return value


def load_cases(root: Path, names: Iterable[str] = ()) -> list[dict[str, Any]]:
    selected = set(names)
    paths = sorted(root.glob("*.yaml"))
    loaded = [(path, load_case(path)) for path in paths]
    if selected:
        missing = [
            name
            for name in selected
            if not any(
                name in {path.stem, path.name, case["id"]}
                for path, case in loaded
            )
        ]
        if missing:
            raise EvalCaseError(f"Unknown eval cases: {', '.join(sorted(missing))}")
        loaded = [
            (path, case)
            for path, case in loaded
            if selected & {path.stem, path.name, case["id"]}
        ]
    cases = [case for _path, case in loaded]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise EvalCaseError("Eval case ids must be unique.")
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Load and validate skill evaluation cases.")
    parser.add_argument("--root", type=Path, default=DEFAULT_EVAL_ROOT)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    try:
        cases = load_cases(args.root.expanduser().resolve(), args.case)
    except EvalCaseError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"status": "ok", "count": len(cases), "case_ids": [case["id"] for case in cases]},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
