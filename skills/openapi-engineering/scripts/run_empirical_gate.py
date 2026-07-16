#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO


SCHEMA_NAME = "empirical-gate.schema.json"
ADOPTION_GATE_ORDER = (
    "validate",
    "generate",
    "inventory",
    "diff",
    "compile",
    "fixture",
)
UPGRADE_GATE_ORDER = (
    "validate",
    "generate-previous",
    "baseline-match",
    "generate",
    "inventory-previous",
    "inventory",
    "diff",
    "compile-previous",
    "compile",
    "fixture-previous",
    "fixture",
)
COMMAND_GATES = {
    "validate",
    "generate-previous",
    "generate",
    "compile-previous",
    "compile",
    "fixture-previous",
    "fixture",
}
SKIP_DIRECTORIES = {".git", ".pytest_cache", "__pycache__", "node_modules"}
SKIP_FILES = {".DS_Store"}
PLACEHOLDER = re.compile(r"\{[a-z_]+\}")
ALLOWED_PLACEHOLDERS = {
    "{artifact}",
    "{contract}",
    "{fixture}",
    "{output}",
    "{previous_artifact}",
    "{previous_output}",
}
SENSITIVE_VALUE = re.compile(
    r"(?i)(?:\bbearer\s+[a-z0-9._~+/=-]{8,}|"
    r"\bsk-(?:proj-)?[a-z0-9_-]{20,}|"
    r"\bsk-ant-[a-z0-9_-]{20,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"[?&](?:api_?key|access_?token|token|secret|password)=[^&\s]+)"
)
SAFE_ENVIRONMENT = {
    "JAVA_HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TMPDIR",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def collect_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name for name in directories if name not in SKIP_DIRECTORIES
        )
        current_path = Path(current)
        for filename in sorted(filenames):
            if filename in SKIP_FILES:
                continue
            path = current_path / filename
            if path.is_file() and not path.is_symlink():
                files[path.relative_to(root).as_posix()] = sha256_file(path)
    return files


def tree_sha256(root: Path) -> str:
    hasher = hashlib.sha256()
    for relative, digest in collect_files(root).items():
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(bytes.fromhex(digest))
        hasher.update(b"\0")
    return hasher.hexdigest()


def inventory(root: Path) -> dict[str, Any]:
    files = collect_files(root)
    return {
        "file_count": len(files),
        "tree_sha256": tree_sha256(root),
        "files": sorted(files),
    }


def compare_trees(
    baseline: Path,
    candidate: Path,
    *,
    accepted_changes: list[dict[str, str]] | None = None,
    allow_initial_generation: bool = False,
) -> dict[str, Any]:
    before = collect_files(baseline)
    after = collect_files(candidate)
    summary = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    changes: set[tuple[str, str]] = set()
    for path in sorted(set(before) | set(after)):
        if path not in before:
            state = "added"
        elif path not in after:
            state = "removed"
        elif before[path] != after[path]:
            state = "changed"
        else:
            state = "unchanged"
        summary[state] += 1
        if state != "unchanged":
            changes.add((path, state))
    accepted = {
        (change["path"], change["state"]) for change in (accepted_changes or [])
    }
    if allow_initial_generation:
        unexplained: list[str] = []
    else:
        unexplained = [
            f"{path}:{state}" for path, state in sorted(changes - accepted)
        ]
        unexplained.extend(
            f"missing:{path}:{state}" for path, state in sorted(accepted - changes)
        )
    return {"summary": summary, "unexplained": unexplained}


def gate_order(manifest: dict[str, Any]) -> tuple[str, ...]:
    return UPGRADE_GATE_ORDER if manifest["mode"] == "upgrade" else ADOPTION_GATE_ORDER


def find_schema() -> Path:
    override = os.environ.get("OPENAPI_ENGINEERING_EMPIRICAL_SCHEMA")
    if override:
        path = Path(override).expanduser().resolve()
        if path.is_file():
            return path
        raise RuntimeError("Configured empirical gate schema does not exist.")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / "schemas" / SCHEMA_NAME
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "The authoritative empirical gate schema was not found; set "
        "OPENAPI_ENGINEERING_EMPIRICAL_SCHEMA to its path."
    )


def load_schema() -> dict[str, Any]:
    value = json.loads(find_schema().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("The authoritative empirical gate schema must be an object.")
    return value


def validate_value(value: Any, schema: dict[str, Any]) -> list[Any]:
    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return sorted(validator.iter_errors(value), key=lambda item: list(item.path))


def load_manifest(path: Path, schema: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Manifest is not readable JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError("Manifest must be a JSON object.")
    manifest_schema = {
        "$schema": schema["$schema"],
        "$ref": "#/$defs/manifest",
        "$defs": schema["$defs"],
    }
    if validate_value(value, manifest_schema):
        raise ValueError("Manifest does not satisfy the authoritative schema.")
    return value


def contains_sensitive_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(SENSITIVE_VALUE.search(value))
    if isinstance(value, list):
        return any(contains_sensitive_value(item) for item in value)
    if isinstance(value, dict):
        return any(contains_sensitive_value(item) for item in value.values())
    return False


def validate_manifest_semantics(manifest: dict[str, Any]) -> None:
    expected_order = gate_order(manifest)
    if manifest["required_gates"] != list(expected_order):
        raise ValueError("Required gates must use the canonical complete order.")
    commands = manifest["commands"]
    command_names = [command["gate"] for command in commands]
    expected_commands = COMMAND_GATES.intersection(expected_order)
    if (
        len(set(command_names)) != len(command_names)
        or set(command_names) != expected_commands
    ):
        raise ValueError("Commands must define each executable gate exactly once.")
    for command in commands:
        for argument in command["argv"]:
            placeholders = set(PLACEHOLDER.findall(argument))
            if not placeholders.issubset(ALLOWED_PLACEHOLDERS):
                raise ValueError("A command uses an unsupported placeholder.")
    if contains_sensitive_value(manifest):
        raise ValueError("Manifest contains a value that is unsafe to persist or execute.")
    if manifest["mode"] == "upgrade":
        previous = manifest["previous_generator"]
        current = manifest["generator"]
        if previous["name"] != current["name"] or previous["target"] != current["target"]:
            raise ValueError("Upgrade generators must use the same tool and target.")
        if previous["version"] == current["version"]:
            raise ValueError("Upgrade generators must use different exact versions.")


def error_payload(code: str, message: str) -> dict[str, Any]:
    return {"status": "error", "error": {"code": code, "message": message}}


def emit(payload: dict[str, Any], pretty: bool) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        )
    )


def persist_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def unverified_gate(
    name: str,
    command: list[str],
    *,
    network: bool = False,
    dependency_install: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "unverified",
        "command": command,
        "network": network,
        "dependency_install": dependency_install,
        "exit_code": None,
        "duration_ms": 0,
        "stdout_sha256": None,
        "stderr_sha256": None,
        "summary": "Planned only.",
        "risk": "Execution requires exact approval.",
        "rollback": "Discard the temporary output." if name == "generate" else None,
    }


def input_records(manifest: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    project = Path(manifest["project_root"]).expanduser().resolve()
    contract = Path(manifest["contract"]["path"]).expanduser().resolve()
    fixture = Path(manifest["fixture"]["path"]).expanduser().resolve()
    baseline = Path(manifest["baseline"]["path"]).expanduser().resolve()
    artifact = Path(manifest["generator"]["artifact"]["path"]).expanduser().resolve()
    previous_artifact = None
    if manifest["mode"] == "upgrade":
        previous_artifact = Path(
            manifest["previous_generator"]["artifact"]["path"]
        ).expanduser().resolve()
    if not project.is_dir() or not baseline.is_dir():
        raise ValueError("Project root and baseline must be existing directories.")
    if not contract.is_file() or not fixture.is_file() or not artifact.is_file():
        raise ValueError("Contract, fixture, and generator artifact must be existing files.")
    if previous_artifact is not None and not previous_artifact.is_file():
        raise ValueError("Previous generator artifact must be an existing file.")
    if not contract.is_relative_to(project) or not fixture.is_relative_to(project):
        raise ValueError("Contract and fixture must be within the project root.")
    if not baseline.is_relative_to(project):
        raise ValueError("Baseline must be within the project root.")

    contract_observed = sha256_file(contract)
    fixture_observed = sha256_file(fixture)
    artifact_observed = sha256_file(artifact)
    previous_artifact_observed = (
        sha256_file(previous_artifact) if previous_artifact is not None else None
    )
    baseline_observed = tree_sha256(baseline)
    project_observed = tree_sha256(project)
    contract_record = {
        "path": str(contract),
        "expected_sha256": manifest["contract"]["sha256"],
        "observed_sha256": contract_observed,
        "verified": contract_observed == manifest["contract"]["sha256"],
    }
    fixture_record = {
        "path": str(fixture),
        "expected_sha256": manifest["fixture"]["sha256"],
        "observed_sha256": fixture_observed,
        "verified": fixture_observed == manifest["fixture"]["sha256"],
    }
    baseline_record = {
        "path": str(baseline),
        "before_sha256": baseline_observed,
        "after_sha256": baseline_observed,
        "unchanged": baseline_observed == manifest["baseline"]["tree_sha256"],
    }
    project_record = {
        "path": str(project),
        "before_sha256": project_observed,
        "after_sha256": project_observed,
        "unchanged": True,
    }
    generator_record = {
        "name": manifest["generator"]["name"],
        "version": manifest["generator"]["version"],
        "target": manifest["generator"]["target"],
        "maturity": manifest["generator"]["maturity"],
        "artifact_sha256": artifact_observed,
    }
    previous_generator_record = None
    if manifest["mode"] == "upgrade":
        previous_generator_record = {
            "name": manifest["previous_generator"]["name"],
            "version": manifest["previous_generator"]["version"],
            "target": manifest["previous_generator"]["target"],
            "maturity": manifest["previous_generator"]["maturity"],
            "artifact_sha256": previous_artifact_observed,
        }
    verified = (
        contract_record["verified"]
        and fixture_record["verified"]
        and baseline_record["unchanged"]
        and artifact_observed == manifest["generator"]["artifact"]["sha256"]
        and (
            manifest["mode"] != "upgrade"
            or previous_artifact_observed
            == manifest["previous_generator"]["artifact"]["sha256"]
        )
    )
    paths = {
        "project": project,
        "contract": contract,
        "fixture": fixture,
        "baseline": baseline,
        "artifact": artifact,
    }
    if previous_artifact is not None:
        paths["previous_artifact"] = previous_artifact
    records = (
        contract_record,
        fixture_record,
        generator_record,
        baseline_record,
        project_record,
        {
            "verified": verified,
            "paths": paths,
            "previous_generator": previous_generator_record,
        },
    )
    return records


def planned_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    commands = {command["gate"]: command for command in manifest["commands"]}
    planned: list[dict[str, Any]] = []
    for name in gate_order(manifest):
        definition = commands.get(name)
        planned.append(
            unverified_gate(
                name,
                list(definition["argv"]) if definition else [],
                network=bool(definition and definition["network"]),
                dependency_install=bool(
                    definition and definition["dependency_install"]
                ),
            )
        )
    return planned


def build_base_report(
    manifest: dict[str, Any],
    manifest_sha256: str,
    started_at: str,
    records: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    contract, fixture, generator, baseline, project, _ = records
    return {
        "report_version": 1,
        "status": "proposed",
        "mode": manifest["mode"],
        "manifest_sha256": manifest_sha256,
        "approval_digest": manifest_sha256,
        "started_at": started_at,
        "finished_at": utc_now(),
        "workspace": {"created": False, "temporary": True, "reclaimed": True},
        "contract": contract,
        "fixture": fixture,
        "generator": generator,
        "previous_generator": records[-1]["previous_generator"],
        "baseline": baseline,
        "project": project,
        "gates": planned_gates(manifest),
        "inventory": None,
        "previous_inventory": None,
        "diff": None,
        "decision": "proposed",
        "unverified": list(gate_order(manifest)),
        "risks": ["Commands have not run; no generator claim is verified."],
        "rollback": manifest["rollback"],
    }


def blocked_report(report: dict[str, Any], message: str) -> dict[str, Any]:
    report["status"] = "blocked"
    report["decision"] = "blocked"
    report["risks"] = [message]
    report["finished_at"] = utc_now()
    return report


def terminate_process_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        process.terminate()
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    else:
        process.kill()
    process.wait(timeout=2)


def stream_digest(stream: BinaryIO) -> str:
    stream.seek(0)
    hasher = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        hasher.update(chunk)
    return hasher.hexdigest()


def stream_summary(stream: BinaryIO) -> str:
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(max(0, size - 4096))
    text = stream.read(4096).decode("utf-8", errors="replace").strip()
    if not text:
        return "Command produced no output."
    if SENSITIVE_VALUE.search(text):
        return "Command output contained a redacted sensitive-value pattern."
    return text[-512:]


def safe_environment(home: Path, *, allow_network: bool) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key in SAFE_ENVIRONMENT}
    environment["HOME"] = str(home)
    environment["TMPDIR"] = str(home.parent / "tmp")
    if not allow_network:
        environment.update(
            {
                "GOPROXY": "off",
                "GOSUMDB": "off",
                "PIP_NO_INDEX": "1",
                "npm_config_offline": "true",
            }
        )
    return environment


def expand_command(command: dict[str, Any], paths: dict[str, Path]) -> list[str]:
    replacements = {
        "{artifact}": str(paths["artifact"]),
        "{contract}": str(paths["contract_copy"]),
        "{fixture}": str(paths["fixture_copy"]),
        "{output}": str(paths["output"]),
    }
    if "previous_artifact" in paths:
        replacements["{previous_artifact}"] = str(paths["previous_artifact"])
    if "previous_output" in paths:
        replacements["{previous_output}"] = str(paths["previous_output"])
    expanded: list[str] = []
    for argument in command["argv"]:
        value = argument
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        expanded.append(value)
    return expanded


def run_command(
    name: str,
    command: list[str],
    timeout_seconds: int,
    workspace: Path,
    *,
    network: bool,
    dependency_install: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        kwargs: dict[str, Any] = {
            "cwd": workspace,
            "env": safe_environment(workspace / "home", allow_network=network),
            "stdin": subprocess.DEVNULL,
            "stdout": stdout,
            "stderr": stderr,
            "shell": False,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
        timed_out = False
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_group(process)
        except BaseException:
            terminate_process_group(process)
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        status = "failed" if timed_out or process.returncode != 0 else "passed"
        summary = (
            "Command timed out and its process group was terminated."
            if timed_out
            else stream_summary(stderr if process.returncode else stdout)
        )
        return {
            "name": name,
            "status": status,
            "command": command,
            "network": network,
            "dependency_install": dependency_install,
            "exit_code": None if timed_out else process.returncode,
            "duration_ms": duration_ms,
            "stdout_sha256": stream_digest(stdout),
            "stderr_sha256": stream_digest(stderr),
            "summary": summary,
            "risk": "A required empirical command did not pass." if status == "failed" else None,
            "rollback": "Discard the temporary output." if name == "generate" else None,
        }


def internal_gate(name: str, passed: bool, summary: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "command": [],
        "network": False,
        "dependency_install": False,
        "exit_code": 0 if passed else 1,
        "duration_ms": 0,
        "stdout_sha256": None,
        "stderr_sha256": None,
        "summary": summary,
        "risk": None if passed else "Generated output did not satisfy an internal gate.",
        "rollback": None,
    }


def check_integrity(
    result: dict[str, Any],
    records: tuple[dict[str, Any], ...],
) -> bool:
    contract, fixture, generator, baseline, project, preflight = records
    paths = preflight["paths"]
    baseline_after = tree_sha256(paths["baseline"])
    project_after = tree_sha256(paths["project"])
    artifact_after = sha256_file(paths["artifact"])
    baseline["after_sha256"] = baseline_after
    baseline["unchanged"] = baseline_after == baseline["before_sha256"]
    project["after_sha256"] = project_after
    project["unchanged"] = project_after == project["before_sha256"]
    immutable_files = (
        sha256_file(paths["contract"]) == contract["observed_sha256"]
        and sha256_file(paths["fixture"]) == fixture["observed_sha256"]
        and artifact_after == generator["artifact_sha256"]
        and (
            "previous_artifact" not in paths
            or sha256_file(paths["previous_artifact"])
            == preflight["previous_generator"]["artifact_sha256"]
        )
    )
    passed = baseline["unchanged"] and project["unchanged"] and immutable_files
    if not passed:
        result["status"] = "failed"
        result["exit_code"] = 1
        result["summary"] = "Integrity check failed after this gate."
        result["risk"] = "A protected project, baseline, input, or tool artifact changed."
    return passed


def reclaim_workspace(workspace: Path) -> bool:
    def make_writable_and_retry(function: Any, path: str, _error: Any) -> None:
        target = Path(path)
        try:
            target.parent.chmod(0o700)
            target.chmod(0o700)
            function(path)
        except OSError:
            return

    try:
        for current, directories, filenames in os.walk(workspace, followlinks=False):
            current_path = Path(current)
            current_path.chmod(0o700)
            for name in directories:
                path = current_path / name
                if not path.is_symlink():
                    path.chmod(0o700)
            for name in filenames:
                path = current_path / name
                if not path.is_symlink():
                    path.chmod(0o600)
        shutil.rmtree(workspace, onerror=make_writable_and_retry)
    except OSError:
        return False
    return not workspace.exists()


def execute(
    manifest: dict[str, Any],
    report: dict[str, Any],
    records: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    preflight = records[-1]
    source_paths = preflight["paths"]
    workspace = Path(tempfile.mkdtemp(prefix="openapi-empirical-"))
    report["workspace"] = {"created": True, "temporary": True, "reclaimed": False}
    results: dict[str, dict[str, Any]] = {}
    output_inventory: dict[str, Any] | None = None
    diff_result: dict[str, Any] | None = None
    previous_inventory: dict[str, Any] | None = None
    stopped = False
    try:
        (workspace / "home").mkdir()
        (workspace / "tmp").mkdir()
        contract_copy = workspace / "inputs" / source_paths["contract"].name
        fixture_copy = workspace / "inputs" / source_paths["fixture"].name
        contract_copy.parent.mkdir()
        shutil.copy2(source_paths["contract"], contract_copy)
        shutil.copy2(source_paths["fixture"], fixture_copy)
        baseline_copy = workspace / "baseline"
        shutil.copytree(source_paths["baseline"], baseline_copy)
        output = workspace / "candidate"
        output.mkdir()
        previous_output = workspace / "previous"
        if manifest["mode"] == "upgrade":
            previous_output.mkdir()
        execution_paths = {
            **source_paths,
            "contract_copy": contract_copy,
            "fixture_copy": fixture_copy,
            "baseline_copy": baseline_copy,
            "output": output,
        }
        if manifest["mode"] == "upgrade":
            execution_paths["previous_output"] = previous_output
        commands = {command["gate"]: command for command in manifest["commands"]}
        for name in gate_order(manifest):
            if stopped:
                continue
            if name in COMMAND_GATES:
                definition = commands[name]
                result = run_command(
                    name,
                    expand_command(definition, execution_paths),
                    definition["timeout_seconds"],
                    workspace,
                    network=definition["network"],
                    dependency_install=definition["dependency_install"],
                )
            elif name == "inventory-previous":
                previous_inventory = inventory(previous_output)
                result = internal_gate(
                    name,
                    previous_inventory["file_count"] > 0,
                    f"Inventoried {previous_inventory['file_count']} previous files.",
                )
            elif name == "inventory":
                output_inventory = inventory(output)
                result = internal_gate(
                    name,
                    output_inventory["file_count"] > 0,
                    f"Inventoried {output_inventory['file_count']} generated files.",
                )
            elif name == "baseline-match":
                baseline_diff = compare_trees(baseline_copy, previous_output)
                result = internal_gate(
                    name,
                    not baseline_diff["unexplained"],
                    "Previous clean generation matches the accepted baseline."
                    if not baseline_diff["unexplained"]
                    else "Previous clean generation differs from the accepted baseline.",
                )
            else:
                comparison_base = (
                    previous_output if manifest["mode"] == "upgrade" else baseline_copy
                )
                diff_result = compare_trees(
                    comparison_base,
                    output,
                    accepted_changes=manifest["diff_policy"]["accepted_changes"],
                    allow_initial_generation=manifest["diff_policy"][
                        "allow_initial_generation"
                    ],
                )
                result = internal_gate(
                    name,
                    not diff_result["unexplained"],
                    "Generated diff is fully explained."
                    if not diff_result["unexplained"]
                    else "Generated diff contains unexplained changes.",
                )
            integrity_passed = check_integrity(result, records)
            results[name] = result
            if result["status"] != "passed" or not integrity_passed:
                stopped = True
    finally:
        try:
            reclaimed = reclaim_workspace(workspace)
        except OSError:
            reclaimed = False
        report["workspace"]["reclaimed"] = reclaimed

    planned = {gate["name"]: gate for gate in planned_gates(manifest)}
    report["gates"] = [
        results.get(name, planned[name]) for name in gate_order(manifest)
    ]
    report["inventory"] = output_inventory
    report["previous_inventory"] = previous_inventory
    report["diff"] = diff_result
    report["unverified"] = [
        gate["name"] for gate in report["gates"] if gate["status"] == "unverified"
    ]
    passed = all(gate["status"] == "passed" for gate in report["gates"])
    passed = passed and report["workspace"]["reclaimed"]
    report["status"] = "passed" if passed else "failed"
    report["decision"] = (
        "adopt-upgrade" if passed and manifest["mode"] == "upgrade"
        else "adopt" if passed
        else "reject"
    )
    report["risks"] = [] if passed else [
        "At least one empirical, integrity, or workspace cleanup gate did not pass."
    ]
    report["finished_at"] = utc_now()
    return report


def validate_report(report: dict[str, Any], schema: dict[str, Any]) -> None:
    errors = validate_value(report, schema)
    if errors:
        raise RuntimeError("Empirical report does not satisfy its authoritative schema.")


def check_existing_report(
    manifest: dict[str, Any],
    report_path: Path,
    records: tuple[dict[str, Any], ...],
    schema: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    try:
        report = json.loads(report_path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return error_payload("invalid-report", "Empirical report is missing or invalid."), 2
    try:
        validate_report(report, schema)
    except RuntimeError:
        return error_payload("invalid-report", "Empirical report violates its contract."), 2

    contract, fixture, generator, baseline, project, preflight = records
    digest = sha256_bytes(canonical_bytes(manifest))
    expected_decision = "adopt-upgrade" if manifest["mode"] == "upgrade" else "adopt"
    current_inputs_verified = bool(preflight["verified"])
    identity_matches = (
        report["manifest_sha256"] == digest
        and report["approval_digest"] == digest
        and report["mode"] == manifest["mode"]
        and report["contract"] == contract
        and report["fixture"] == fixture
        and report["generator"] == generator
        and report["previous_generator"] == preflight["previous_generator"]
        and report["baseline"]["path"] == baseline["path"]
        and report["baseline"]["before_sha256"] == baseline["before_sha256"]
        and report["baseline"]["after_sha256"] == baseline["before_sha256"]
        and report["project"]["path"] == project["path"]
        and report["project"]["before_sha256"] == project["before_sha256"]
        and report["project"]["after_sha256"] == project["before_sha256"]
        and report["rollback"] == manifest["rollback"]
    )
    evidence_passed = (
        report["status"] == "passed"
        and report["decision"] == expected_decision
        and report["unverified"] == []
        and report["risks"] == []
        and report["workspace"]["created"] is True
        and report["workspace"]["temporary"] is True
        and report["workspace"]["reclaimed"] is True
        and report["baseline"]["unchanged"] is True
        and report["project"]["unchanged"] is True
        and report["inventory"] is not None
        and report["diff"] is not None
        and report["diff"]["unexplained"] == []
        and [gate["name"] for gate in report["gates"]] == list(gate_order(manifest))
        and all(gate["status"] == "passed" for gate in report["gates"])
        and (
            manifest["mode"] != "upgrade"
            or report["previous_inventory"] is not None
        )
    )
    if not current_inputs_verified:
        return error_payload(
            "stale-input", "Pinned empirical inputs no longer match the manifest."
        ), 2
    if not identity_matches or not evidence_passed:
        return error_payload(
            "stale-report", "Empirical report does not match current approved evidence."
        ), 1
    return report, 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or run an approval-bound empirical generator gate."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approve")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-report", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if args.check_report and (args.execute or args.approve or args.report):
        parser.error("--check-report cannot be combined with execution or report output")

    try:
        schema = load_schema()
        manifest = load_manifest(args.manifest.expanduser().resolve(), schema)
        validate_manifest_semantics(manifest)
        records = input_records(manifest)
    except (OSError, RuntimeError, ValueError) as exc:
        emit(error_payload("invalid-manifest", str(exc)), args.pretty)
        return 2

    if args.check_report:
        report, exit_code = check_existing_report(
            manifest, args.check_report, records, schema
        )
        emit(report, args.pretty)
        return exit_code

    started_at = utc_now()
    manifest_sha256 = sha256_bytes(canonical_bytes(manifest))
    report = build_base_report(manifest, manifest_sha256, started_at, records)
    preflight = records[-1]
    if not preflight["verified"]:
        blocked_report(report, "One or more pinned input digests do not match.")
        exit_code = 2
    elif not args.execute:
        exit_code = 0
    elif args.approve != manifest_sha256:
        blocked_report(report, "Execution approval does not match the exact manifest digest.")
        exit_code = 2
    else:
        if args.report and args.report.expanduser().resolve().is_relative_to(
            preflight["paths"]["project"]
        ):
            blocked_report(report, "The empirical report must be outside the protected project.")
            exit_code = 2
        else:
            report = execute(manifest, report, records)
            exit_code = 0 if report["status"] == "passed" else 1

    try:
        validate_report(report, schema)
        if args.report:
            persist_report(args.report.expanduser().resolve(), report)
    except (OSError, RuntimeError) as exc:
        emit(error_payload("report-error", str(exc)), args.pretty)
        return 2
    emit(report, args.pretty)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
