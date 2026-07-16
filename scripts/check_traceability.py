#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "contracts" / "schemas"
TRACEABILITY_SCHEMA = SCHEMA_ROOT / "acceptance-traceability.schema.json"
EXPECTED_IDS = tuple(f"AC-{index:02d}" for index in range(1, 13))
TEST_SELECTOR = re.compile(r"^(?P<path>.+\.py)::(?P<name>test_[A-Za-z0-9_]+)$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _inside_repo(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("artifact path escapes the repository") from exc
    return resolved


def _repo_path(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return _inside_repo(candidate)


def _schemas() -> dict[str, dict[str, Any]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in SCHEMA_ROOT.glob("*.json")
    }


def _validator(schema_name: str) -> Draft202012Validator:
    schemas = _schemas()
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return Draft202012Validator(
        schemas[schema_name], registry=registry, format_checker=FormatChecker()
    )


def _validate(instance: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(instance),
        key=lambda item: list(item.path),
    )
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].path)
        raise ValueError(f"{label} violates its schema at {location}: {errors[0].message}")


def validate_report(report: dict[str, Any]) -> None:
    errors = sorted(
        _validator(TRACEABILITY_SCHEMA.name).iter_errors(report),
        key=lambda item: list(item.path),
    )
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].path)
        raise ValueError(
            f"traceability report violates its schema at {location}: {errors[0].message}"
        )


def load_manifest(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.expanduser().resolve().read_bytes()
        manifest = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load traceability manifest: {exc}") from exc
    schema = json.loads(TRACEABILITY_SCHEMA.read_text(encoding="utf-8"))
    manifest_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/manifest",
    }
    _validate(manifest, manifest_schema, "traceability manifest")
    ids = tuple(item["id"] for item in manifest["requirements"])
    if ids != EXPECTED_IDS:
        raise ValueError("traceability manifest must contain AC-01 through AC-12 in order")
    return manifest, sha256_bytes(raw)


def _load_structured(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def _json_pointer(payload: Any, pointer: str) -> Any:
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
    result = {
        "path": selector,
        "sha256": None,
        "status": "failed",
        "reason": None,
    }
    try:
        path = _repo_path(path_value)
        if not path.is_file():
            raise ValueError("contract file is missing")
        result["sha256"] = sha256_file(path)
        if separator:
            selected = _json_pointer(_load_structured(path), fragment)
            if selected is None:
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


def check_test(selector: str) -> dict[str, Any]:
    result = {
        "path": selector,
        "sha256": None,
        "status": "failed",
        "reason": None,
    }
    try:
        match = TEST_SELECTOR.fullmatch(selector)
        if not match:
            raise ValueError("test selector must be path.py::test_name")
        path = _repo_path(match.group("path"))
        if not path.is_file():
            raise ValueError("test file is missing")
        result["sha256"] = sha256_file(path)
        definition = re.compile(rf"^\s*def\s+{re.escape(match.group('name'))}\s*\(", re.MULTILINE)
        if not definition.search(path.read_text(encoding="utf-8")):
            raise ValueError("test function is missing")
        result["status"] = "passed"
    except (OSError, ValueError) as exc:
        result["reason"] = str(exc)
    return result


def _platforms(payload: dict[str, Any]) -> list[str]:
    if isinstance(payload.get("platforms"), list):
        values = []
        for item in payload["platforms"]:
            if isinstance(item, dict) and item.get("adapter") in {"codex", "claude"}:
                values.append(item["adapter"])
        return sorted(set(values))
    if payload.get("adapter") in {"codex", "claude"}:
        return [payload["adapter"]]
    return []


def check_evidence(requirement: dict[str, Any]) -> dict[str, Any]:
    value = requirement["path"]
    kind = requirement["kind"]
    result = {
        "path": value,
        "kind": kind,
        "sha256": None,
        "source_status": None,
        "platforms": [],
        "status": "failed",
        "reason": None,
    }
    try:
        path = _repo_path(value)
        if not path.is_file():
            raise ValueError("evidence file is missing")
        result["sha256"] = sha256_file(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("evidence must be a JSON object")
        result["source_status"] = payload.get("status")
        result["platforms"] = _platforms(payload)
        if result["source_status"] != requirement["required_status"]:
            raise ValueError("evidence source status is not passed")
        missing_platforms = sorted(
            set(requirement["required_platforms"]) - set(result["platforms"])
        )
        if missing_platforms:
            raise ValueError(
                "evidence misses required platforms: " + ", ".join(missing_platforms)
            )
        if requirement["require_unverified_empty"] and payload.get("unverified") != []:
            raise ValueError("evidence has non-empty or missing unverified findings")
        if kind == "empirical":
            integrity = (
                payload.get("workspace", {}).get("reclaimed") is True
                and payload.get("project", {}).get("unchanged") is True
                and payload.get("baseline", {}).get("unchanged") is True
            )
            if not integrity:
                raise ValueError("empirical evidence does not prove workspace integrity")
        if kind == "deterministic":
            gates = payload.get("gates")
            if not isinstance(gates, list) or not gates or any(
                gate.get("status") != "passed" for gate in gates if isinstance(gate, dict)
            ):
                raise ValueError("deterministic evidence does not prove all gates passed")
        result["status"] = "passed"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result["reason"] = str(exc)
    return result


def evaluate_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    contracts = [check_contract(item) for item in requirement["contracts"]]
    tests = [check_test(item) for item in requirement["tests"]]
    evidence = [check_evidence(item) for item in requirement["evidence"]]
    reasons = []
    if requirement["status"] != "passed":
        reasons.append(f"declared status is {requirement['status']}, not passed")
    for group in (contracts, tests, evidence):
        reasons.extend(item["reason"] for item in group if item["reason"])
    return {
        "id": requirement["id"],
        "declared_status": requirement["status"],
        "computed_status": "passed" if not reasons else "failed",
        "contracts": contracts,
        "tests": tests,
        "evidence": evidence,
        "reasons": reasons,
    }


def build_report(manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
    requirements = [evaluate_requirement(item) for item in manifest["requirements"]]
    failed = [item["id"] for item in requirements if item["computed_status"] != "passed"]
    status = "passed" if not failed else "failed"
    completion = {
        "outcome": (
            "All 12 acceptance requirements have machine-verifiable evidence."
            if status == "passed"
            else "Acceptance traceability failed for: " + ", ".join(failed)
        ),
        "changed_files": [],
        "commands": [
            "python scripts/check_traceability.py --manifest contracts/acceptance-traceability.yaml"
        ],
        "results": [
            f"{item['id']}: {item['computed_status']}" for item in requirements
        ],
        "unverified": [] if status == "passed" else failed,
        "risks": [] if status == "passed" else ["Acceptance evidence is incomplete."],
        "rollback": ["Delete the generated traceability report; source evidence is read-only."],
        "profile_changes": [],
    }
    return {
        "report_version": 1,
        "status": status,
        "manifest_sha256": manifest_sha256,
        "generated_at": utc_now(),
        "requirements": requirements,
        "completion_report": completion,
    }


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AC-01 through AC-12 evidence")
    parser.add_argument("--manifest", type=Path, required=True)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--report", type=Path)
    output.add_argument("--check-report", type=Path)
    args = parser.parse_args()
    try:
        manifest, digest = load_manifest(args.manifest)
        report = build_report(manifest, digest)
        validate_report(report)
        if args.check_report:
            stored = json.loads(
                args.check_report.expanduser().resolve().read_text(encoding="utf-8")
            )
            validate_report(stored)
            report["generated_at"] = stored["generated_at"]
            if report != stored:
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
                return 1
        else:
            atomic_write(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["status"] == "passed" else 1
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
