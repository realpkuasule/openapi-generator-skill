#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "contracts" / "schemas"
TRACEABILITY_SCHEMA = SCHEMA_ROOT / "self-improvement-traceability.schema.json"
EXPECTED_IDS = tuple(f"SI-AC-{index:02d}" for index in range(1, 25))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def repo_path(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    resolved = candidate.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("artifact path escapes the repository") from exc
    return resolved


def schemas() -> dict[str, dict[str, Any]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in SCHEMA_ROOT.glob("*.json")
    }


def validator(schema_name: str) -> Draft202012Validator:
    values = schemas()
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in values.values()
    )
    return Draft202012Validator(
        values[schema_name], registry=registry, format_checker=FormatChecker()
    )


def validate_with(instance: Any, value_schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(value_schema).iter_errors(instance),
        key=lambda item: list(item.path),
    )
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].path)
        raise ValueError(f"{label} violates its schema at {location}: {errors[0].message}")


def validate_report(report: dict[str, Any]) -> None:
    errors = sorted(
        validator(TRACEABILITY_SCHEMA.name).iter_errors(report),
        key=lambda item: list(item.path),
    )
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].path)
        raise ValueError(
            f"self-improvement traceability report violates its schema at {location}: "
            f"{errors[0].message}"
        )


def load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.expanduser().resolve().read_bytes()
        manifest = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load self-improvement traceability manifest: {exc}") from exc
    schema = json.loads(TRACEABILITY_SCHEMA.read_text(encoding="utf-8"))
    manifest_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/manifest",
    }
    validate_with(manifest, manifest_schema, "self-improvement traceability manifest")
    ids = tuple(item["id"] for item in manifest["requirements"])
    if ids != EXPECTED_IDS:
        raise ValueError("manifest must contain SI-AC-01 through SI-AC-24 in order")
    return manifest, sha256_bytes(raw)


def load_structured(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)


def json_pointer(payload: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ValueError("contract fragment must be a JSON pointer")
    current = payload
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise ValueError("contract JSON pointer cannot be resolved")
    return current


def check_contract(selector: str) -> dict[str, Any]:
    path_value, separator, fragment = selector.partition("#")
    result = {"path": selector, "sha256": None, "status": "failed", "reason": None}
    try:
        path = repo_path(path_value)
        if not path.is_file():
            raise ValueError("contract file is missing")
        result["sha256"] = sha256_file(path)
        if separator and json_pointer(load_structured(path), fragment) is None:
            raise ValueError("contract selector resolved to null")
        result["status"] = "passed"
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        json.JSONDecodeError,
        yaml.YAMLError,
    ) as exc:
        result["reason"] = str(exc)
    return result


def selector_path(selector: str) -> tuple[Path, list[str]]:
    parts = selector.split(".")
    if len(parts) < 4 or parts[0] != "tests" or not parts[-1].startswith("test_"):
        raise ValueError("test selector is not a unittest test method")
    path = repo_path(f"tests/{parts[1]}.py")
    return path, parts[2:]


def selector_exists(selector: str) -> tuple[Path, str]:
    path, object_parts = selector_path(selector)
    if not path.is_file():
        raise ValueError("test file is missing")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes: list[ast.AST] = list(tree.body)
    for name in object_parts:
        matched = next(
            (
                node
                for node in nodes
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name
            ),
            None,
        )
        if matched is None:
            raise ValueError("test method is missing")
        nodes = list(getattr(matched, "body", []))
    return path, sha256_file(path)


def run_test_group(selectors: list[str]) -> dict[str, dict[str, Any]]:
    static: dict[str, dict[str, Any]] = {}
    valid: list[str] = []
    for selector in selectors:
        try:
            _path, digest = selector_exists(selector)
            static[selector] = {
                "selector": selector,
                "sha256": digest,
                "exit_code": None,
                "status": "blocked",
                "duration_ms": 0,
                "reason": None,
            }
            valid.append(selector)
        except (OSError, SyntaxError, ValueError) as exc:
            static[selector] = {
                "selector": selector,
                "sha256": None,
                "exit_code": None,
                "status": "failed",
                "duration_ms": 0,
                "reason": str(exc),
            }
    if not valid:
        return static

    started = time.monotonic()
    try:
        grouped = subprocess.run(
            [sys.executable, "-m", "unittest", *valid, "-q"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        for selector in valid:
            static[selector]["status"] = "blocked"
            static[selector]["reason"] = str(exc)
        return static
    duration = int((time.monotonic() - started) * 1000)
    if grouped.returncode == 0:
        for selector in valid:
            static[selector].update(
                exit_code=0, status="passed", duration_ms=duration, reason=None
            )
        return static

    # A failing grouped run is rerun serially so one failing gate does not obscure the others.
    for selector in valid:
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-m", "unittest", selector, "-q"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        reason = None
        if result.returncode:
            reason = (result.stdout + result.stderr).strip()[-1000:] or "test failed"
        static[selector].update(
            exit_code=result.returncode,
            status="passed" if result.returncode == 0 else "failed",
            duration_ms=int((time.monotonic() - started) * 1000),
            reason=reason,
        )
    return static


def check_evidence(
    evidence: dict[str, str], tests: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    result = {
        "kind": evidence["kind"],
        "path": evidence["path"],
        "status": "failed",
        "reason": None,
    }
    try:
        if evidence["kind"] == "automated-test":
            if evidence["path"] not in tests:
                raise ValueError("automated evidence is not an enforced test")
            test = tests[evidence["path"]]
            if test["status"] != "passed":
                raise ValueError("automated evidence test did not pass")
        else:
            path = repo_path(evidence["path"])
            if not path.is_file():
                raise ValueError("static or deferred evidence file is missing")
        result["status"] = "passed"
    except (OSError, ValueError) as exc:
        result["reason"] = str(exc)
    return result


def evaluate_requirement(
    requirement: dict[str, Any], test_results: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    contracts = [check_contract(item) for item in requirement["contracts"]]
    tests = [test_results[item] for item in requirement["tests"]]
    evidence = [check_evidence(item, test_results) for item in requirement["evidence"]]
    reasons = [item["reason"] for item in [*contracts, *tests, *evidence] if item["reason"]]
    loaded = all(item["status"] == "passed" for item in contracts)
    enforced = all(item["sha256"] is not None for item in tests)
    passing = all(item["status"] == "passed" for item in tests)
    declared = requirement["status"]
    if declared == "blocked":
        computed = "blocked"
        reasons.append("declared status is blocked")
    elif reasons:
        computed = "failed"
    else:
        computed = declared
    return {
        "id": requirement["id"],
        "phase": requirement["phase"],
        "declared_status": declared,
        "computed_status": computed,
        "configured": True,
        "loaded": loaded,
        "enforced": enforced,
        "passing": passing,
        "contracts": contracts,
        "tests": tests,
        "evidence": evidence,
        "reasons": reasons,
    }


def build_report(manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
    selectors = sorted(
        {selector for requirement in manifest["requirements"] for selector in requirement["tests"]}
    )
    test_results = run_test_group(selectors)
    requirements = [
        evaluate_requirement(requirement, test_results)
        for requirement in manifest["requirements"]
    ]
    failed = [
        row["id"]
        for row in requirements
        if row["computed_status"] in {"failed", "blocked"}
    ]
    incomplete = [row["id"] for row in requirements if row["computed_status"] != "passed"]
    status = "failed" if failed else "passed"
    return {
        "report_version": 1,
        "status": status,
        "acceptance_complete": not incomplete,
        "manifest_sha256": manifest_sha256,
        "generated_at": utc_now(),
        "requirements": requirements,
        "completion_report": {
            "outcome": (
                "All 24 self-improvement acceptance requirements are complete."
                if not incomplete
                else "Traceability is valid; incomplete requirements: " + ", ".join(incomplete)
            ),
            "changed_files": [],
            "commands": [
                "python scripts/check_self_improvement_traceability.py "
                "--manifest contracts/self-improvement-acceptance-traceability.yaml"
            ],
            "results": [
                f"{row['id']}: {row['computed_status']}" for row in requirements
            ],
            "unverified": incomplete,
            "risks": (
                []
                if not incomplete
                else ["P1/P2 acceptance remains incomplete until static-only items pass."]
            ),
            "rollback": ["Delete the generated report; contracts and tests are read-only."],
            "profile_changes": [],
        },
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("report path is a symbolic link")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def normalize_volatile(actual: dict[str, Any], stored: dict[str, Any]) -> None:
    actual["generated_at"] = stored.get("generated_at")
    stored_rows = {row.get("id"): row for row in stored.get("requirements", [])}
    for row in actual["requirements"]:
        stored_row = stored_rows.get(row["id"], {})
        stored_tests = {
            item.get("selector"): item for item in stored_row.get("tests", [])
        }
        for result in row["tests"]:
            previous = stored_tests.get(result["selector"])
            if previous is not None:
                result["duration_ms"] = previous.get("duration_ms")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify SI-AC-01 through SI-AC-24 contracts and fresh automated tests."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--report", type=Path)
    output.add_argument("--check-report", type=Path)
    output.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        manifest, digest = load_manifest(args.manifest)
        report = build_report(manifest, digest)
        validate_report(report)
        if args.check_report:
            stored = json.loads(args.check_report.expanduser().resolve().read_text(encoding="utf-8"))
            validate_report(stored)
            normalize_volatile(report, stored)
            if report != stored:
                print(json.dumps(report, ensure_ascii=False, sort_keys=True))
                return 1
        elif args.report:
            atomic_write(args.report, report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
