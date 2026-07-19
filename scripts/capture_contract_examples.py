#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = REPO_ROOT / "skills" / "openapi-engineering" / "scripts"
EXAMPLE_ROOT = REPO_ROOT / "contracts" / "examples"
CLI = REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"
MAINTENANCE_SCRIPTS = REPO_ROOT / "scripts" / "maintenance"
EXAMPLE_NAMES = (
    "error-response.json",
    "empirical-gate-response.json",
    "generation-comparison-response.json",
    "inspect-response.json",
    "profile-state-response.json",
    "profile-validation-response.json",
    "usage-status-response.json",
    "usage-record-response.json",
    "usage-summary-response.json",
    "usage-due-response.json",
    "usage-trend-response.json",
    "maintenance-finding-response.json",
    "maintenance-proposal-response.json",
    "maintenance-promotion-response.json",
)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def run_json(script: str, *arguments: str, expected_exit: int = 0) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(SKILL_SCRIPTS / script), *arguments],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != expected_exit:
        raise RuntimeError(
            f"{script} exited {result.returncode}, expected {expected_exit}: "
            f"{result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{script} did not emit JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{script} did not emit a JSON object.")
    return payload


def run_command_json(command: list[str], expected_exit: int = 0) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != expected_exit:
        raise RuntimeError(
            f"{command[0]} exited {result.returncode}, expected {expected_exit}: "
            f"{result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{command[0]} did not emit JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{command[0]} did not emit a JSON object.")
    return payload


def run_usage(home: Path, *arguments: str) -> dict[str, Any]:
    return run_command_json(
        ["node", str(CLI), "usage", *arguments, "--home", str(home), "--json"]
    )


def make_inspection_fixture(root: Path) -> Path:
    project = root / "project"
    write_text(project / "AGENTS.md", "Use contract-first API engineering.\n")
    write_text(
        project / "package.json",
        json.dumps(
            {
                "devDependencies": {
                    "@openapitools/openapi-generator-cli": "2.15.3"
                }
            }
        ),
    )
    write_text(project / "pyproject.toml", "[project]\nname = \"fixture\"\n")
    write_text(project / "tsconfig.json", "{}\n")
    write_text(
        project / "contracts" / "openapi.yaml",
        "openapi: 3.1.0\ninfo:\n  title: Fixture\n  version: 1.0.0\npaths: {}\n",
    )
    write_text(
        project / "contracts" / "domain.schema.json",
        '{"$schema":"https://json-schema.org/draft/2020-12/schema"}\n',
    )
    write_text(project / ".github" / "workflows" / "ci.yml", "name: CI\n")
    write_text(project / ".openapi-engineering" / "profile.yaml", "profile_version: 1\n")
    write_text(project / "generated" / "client.ts", "export const generated = true;\n")
    write_text(project / ".worktrees" / "stale" / "openapi.yaml", "openapi: 3.1.0\n")
    return project


def capture_inspection(root: Path) -> dict[str, Any]:
    project = make_inspection_fixture(root)
    payload = run_json("inspect_project.py", "--root", str(project), "--pretty")
    payload["root"] = "/workspace/project"
    return payload


def capture_comparison(root: Path) -> dict[str, Any]:
    baseline = root / "baseline"
    candidate = root / "candidate"
    write_text(baseline / "removed.txt", "removed\n")
    write_text(baseline / "changed.txt", "before\n")
    write_text(baseline / "same.txt", "same\n")
    write_text(candidate / "added.txt", "added\n")
    write_text(candidate / "changed.txt", "after\n")
    write_text(candidate / "same.txt", "same\n")
    payload = run_json("compare_generation.py", str(baseline), str(candidate), "--pretty")
    payload["baseline"] = "/tmp/baseline"
    payload["candidate"] = "/tmp/candidate"
    return payload


def capture_profile_state(root: Path) -> dict[str, Any]:
    import yaml

    profile = yaml.safe_load(
        (EXAMPLE_ROOT / "governance-profile.valid.yaml").read_text(encoding="utf-8")
    )
    profile["contract"]["sources_of_truth"] = ["contracts/legacy.yaml"]
    profile_path = root / "profile.yaml"
    write_text(profile_path, yaml.safe_dump(profile, allow_unicode=True, sort_keys=False))
    inspection = {
        "status": "ok",
        "root": "/workspace/project",
        "contract_files": ["contracts/openapi.yaml"],
        "schema_files": [],
        "truncated": False,
        "evidence": [{"kind": "contract", "path": "contracts/openapi.yaml"}],
    }
    inspection_path = root / "inspection.json"
    write_text(inspection_path, json.dumps(inspection, sort_keys=True))
    return run_json(
        "profile_state.py",
        "check",
        "--profile",
        str(profile_path),
        "--inspection",
        str(inspection_path),
        "--pretty",
    )


def capture_empirical(root: Path) -> dict[str, Any]:
    project = root / "project"
    baseline = project / "accepted"
    baseline.mkdir(parents=True)
    contract = project / "openapi.yaml"
    fixture = project / "fixtures" / "generated_client.py"
    artifact = root / "openapi-generator-cli-7.23.0.jar"
    write_text(
        contract,
        "openapi: 3.0.3\ninfo:\n  title: Fixture\n  version: 1.0.0\npaths: {}\n",
    )
    write_text(fixture, "# deterministic fixture placeholder\n")
    write_text(artifact, "deterministic generator artifact placeholder\n")
    request = json.loads(
        (EXAMPLE_ROOT / "empirical-gate-request.json").read_text(encoding="utf-8")
    )
    request["project_root"] = str(project)
    request["contract"] = {
        "path": str(contract),
        "sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
    }
    request["fixture"] = {
        "path": str(fixture),
        "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
    }
    request["baseline"] = {
        "path": str(baseline),
        "tree_sha256": hashlib.sha256().hexdigest(),
    }
    request["generator"]["artifact"] = {
        "path": str(artifact),
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    manifest = root / "manifest.json"
    write_text(manifest, json.dumps(request, sort_keys=True))
    payload = run_json("run_empirical_gate.py", "--manifest", str(manifest), "--pretty")
    payload["started_at"] = "2026-07-15T12:00:00Z"
    payload["finished_at"] = "2026-07-15T12:00:00Z"
    payload["manifest_sha256"] = "d" * 64
    payload["approval_digest"] = "d" * 64
    payload["contract"].update(
        path="/workspace/project/openapi.yaml",
        expected_sha256="a" * 64,
        observed_sha256="a" * 64,
    )
    payload["fixture"].update(
        path="/workspace/project/fixtures/generated_client.py",
        expected_sha256="f" * 64,
        observed_sha256="f" * 64,
    )
    payload["baseline"].update(
        path="/workspace/project/accepted",
        before_sha256="b" * 64,
        after_sha256="b" * 64,
    )
    payload["project"].update(
        path="/workspace/project",
        before_sha256="e" * 64,
        after_sha256="e" * 64,
    )
    payload["generator"]["artifact_sha256"] = "c" * 64
    return payload


def fixture_usage_event(index: int, *, peak_rss_mb: int | None = None) -> dict[str, Any]:
    peak = (
        {"availability": "available", "source": "launcher", "value": peak_rss_mb}
        if peak_rss_mb is not None
        else {"availability": "unavailable", "source": "best-effort"}
    )
    return {
        "schema_version": 1,
        "event_id": f"evt-{index:016x}",
        "session_id": f"ses-{index:016x}",
        "recorded_at": f"2026-07-{14 + index:02d}T12:00:00Z",
        "device_alias": "m4",
        "skill_version": "0.1.0-rc.2",
        "skill_sha256": "a" * 64,
        "platform": "codex",
        "platform_version": None,
        "capture_mode": "best-effort",
        "anonymous_project_id": "b" * 64,
        "project_alias": "openapi-generator-skill",
        "lifecycle_modes": ["governance-hardening"],
        "tool_strategy": "governance-only",
        "outcome": "passed",
        "interview_turns": 4,
        "boundary_revisions": 0,
        "tool_overridden": False,
        "gates": {"passed": 1, "failed": 0, "unverified": 0},
        "duration_ms": {"availability": "unavailable", "source": "best-effort"},
        "peak_rss_mb": peak,
        "exit_code": {"availability": "unavailable", "source": "best-effort"},
        "termination_reason": "not-reported",
        "feedback_status": "unknown",
        "safety_violation": False,
        "resource_anomaly": peak_rss_mb is not None and peak_rss_mb > 512,
        "platform_drift": False,
        "incident_ids": [],
    }


def capture_usage(root: Path) -> dict[str, dict[str, Any]]:
    record_home = root / "record-home"
    status = run_usage(record_home, "status")
    run_usage(record_home, "enable", "--device", "m4", "--apply")
    completion = root / "completion-report.json"
    write_text(
        completion,
        json.dumps(
            {
                "outcome": "passed",
                "changed_files": [],
                "commands": [],
                "results": ["contract gate passed"],
                "unverified": [],
                "risks": [],
                "rollback": [],
                "profile_changes": [],
            },
            sort_keys=True,
        ),
    )
    record = run_usage(
        record_home,
        "record",
        "--completion-report",
        str(completion),
        "--capture-mode",
        "best-effort",
        "--platform",
        "codex",
        "--project-alias",
        "openapi-generator-skill",
        "--session",
        "ses-0123456789abcdef",
        "--lifecycle",
        "governance-hardening",
        "--tool-strategy",
        "governance-only",
        "--interview-turns",
        "4",
        "--boundary-revisions",
        "0",
        "--now",
        "2026-07-19T12:00:00Z",
    )
    # The local salt is intentionally random; replace only its derived pseudonym so the
    # checked-in example remains reproducible while retaining the actual CLI structure.
    record["event"]["anonymous_project_id"] = "b" * 64

    summary_home = root / "summary-home"
    summary_state = root / "summary-state"
    run_usage(
        summary_home,
        "enable",
        "--device",
        "m4",
        "--coordinator",
        "--state-root",
        str(summary_state),
        "--apply",
    )
    event_log = (
        summary_state
        / "local"
        / "events"
        / "m4"
        / "2026-07.jsonl"
    )
    write_text(
        event_log,
        "".join(
            json.dumps(
                fixture_usage_event(index, peak_rss_mb=640 if index == 5 else None),
                sort_keys=True,
            )
            + "\n"
            for index in range(1, 6)
        ),
    )
    summary = run_usage(
        summary_home,
        "summarize",
        "--period",
        "iso-week",
        "--now",
        "2026-07-19T18:00:00Z",
    )
    due = run_usage(summary_home, "due", "--now", "2026-07-19T18:00:00Z")
    trends = run_usage(
        summary_home,
        "trends",
        "--now",
        "2026-07-19T18:00:00Z",
        "--fix-at",
        "2026-06-19T18:00:00Z",
    )
    return {
        "usage-status-response.json": status,
        "usage-record-response.json": record,
        "usage-summary-response.json": summary,
        "usage-due-response.json": due,
        "usage-trend-response.json": trends,
        "maintenance-finding-response.json": due["findings"][0],
    }


def capture_maintenance_proposal(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    target = root / "target"
    target.mkdir(parents=True)
    resources = {
        "measurement_status": "not-run",
        "peak_rss_bytes": None,
        "warning_limit_bytes": 512 * 1024 * 1024,
        "hard_limit_bytes": 1024 * 1024 * 1024,
        "warning_exceeded": False,
        "termination_reason": "not-run",
        "duration_ms": 0,
        "process_group_reclaimed": False,
    }
    analysis = {
        "schema_version": 1,
        "analysis_id": "analysis-0123456789abcdef",
        "generated_at": "2026-07-19T12:00:00Z",
        "input_sha256": "a" * 64,
        "finding_ids": ["finding-0123456789abcdef"],
        "primary": {
            "platform": "fake",
            "session_id": "analysis-session-0123456789abcdef",
            "cli_version": "test",
            "model": "fake",
            "status": "passed",
            "resources": resources,
        },
        "analyzer_sequence": [
            {
                "platform": "fake",
                "session_id": "analysis-session-0123456789abcdef",
                "cli_version": "test",
                "model": "fake",
                "status": "passed",
                "resources": resources,
            }
        ],
        "secondary_review": {
            "required": False,
            "trigger_reasons": [],
            "status": "not-required",
            "analyzer": None,
            "independent": False,
            "result": None,
            "agreements": [],
            "disagreements": [],
        },
        "clusters": [
            {
                "key": "resource-regression",
                "finding_ids": ["finding-0123456789abcdef"],
            }
        ],
        "confidence": 0.9,
        "candidate_causes": ["A deterministic candidate cause."],
        "unverified": [],
    }
    candidate = {
        "candidate_id": "candidate-0123456789abcdef",
        "contract_impact": "compatible",
        "target_files": ["tests/test_maintenance_candidate_usage_resource.py"],
        "artifacts": [
            {
                "kind": "failing-test",
                "path": "tests/test_maintenance_candidate_usage_resource.py",
                "media_type": "text/x-python",
                "content": "def test_approved_candidate_remains_red():\n    assert False\n",
            }
        ],
        "open_questions": [],
        "failing_tests": ["tests/test_maintenance_candidate_usage_resource.py"],
        "verification": ["Run the new failing test before implementation."],
        "rollback": ["Remove only the approved candidate fixture if its digest still matches."],
    }
    analysis_path = root / "analysis.json"
    candidate_path = root / "candidate.json"
    output_path = root / "proposal.json"
    write_text(analysis_path, json.dumps(analysis, sort_keys=True))
    write_text(candidate_path, json.dumps(candidate, sort_keys=True))
    proposal = run_command_json(
        [
            sys.executable,
            str(MAINTENANCE_SCRIPTS / "build_proposal.py"),
            "--analysis",
            str(analysis_path),
            "--candidate",
            str(candidate_path),
            "--target-root",
            str(target),
            "--skill-root",
            str(REPO_ROOT / "skills" / "openapi-engineering"),
            "--skill-version",
            "0.1.0-rc.3",
            "--config-sha256",
            "b" * 64,
            "--output",
            str(output_path),
            "--now",
            "2026-07-19T12:00:00Z",
        ]
    )
    promotion = run_command_json(
        [
            sys.executable,
            str(MAINTENANCE_SCRIPTS / "promote_candidate.py"),
            "--proposal",
            str(output_path),
            "--target-root",
            str(target),
            "--approve",
            proposal["approval_sha256"],
        ]
    )
    return proposal, promotion


def capture_examples(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        usage_examples = capture_usage(root / "usage")
        proposal, promotion = capture_maintenance_proposal(root / "maintenance-proposal")
        examples = {
            "inspect-response.json": capture_inspection(root / "inspection"),
            "generation-comparison-response.json": capture_comparison(root / "comparison"),
            "empirical-gate-response.json": capture_empirical(root / "empirical"),
            "profile-state-response.json": capture_profile_state(root / "profile-state"),
            "profile-validation-response.json": run_json(
                "validate_profile.py",
                str(EXAMPLE_ROOT / "governance-profile.invalid-secret.yaml"),
                "--pretty",
                expected_exit=1,
            ),
            "error-response.json": run_json(
                "inspect_project.py",
                "--root",
                str(root / "does-not-exist"),
                "--pretty",
                expected_exit=2,
            ),
            **usage_examples,
            "maintenance-proposal-response.json": proposal,
            "maintenance-promotion-response.json": promotion,
        }
    for name, payload in examples.items():
        (output / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def check_examples() -> int:
    with tempfile.TemporaryDirectory() as directory:
        generated = Path(directory)
        capture_examples(generated)
        mismatches = [
            name
            for name in EXAMPLE_NAMES
            if not (EXAMPLE_ROOT / name).is_file()
            or (EXAMPLE_ROOT / name).read_bytes() != (generated / name).read_bytes()
        ]
    if mismatches:
        print(
            json.dumps(
                {"status": "failed", "mismatched_examples": mismatches},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps({"status": "ok", "checked": list(EXAMPLE_NAMES)}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture deterministic OpenAPI engineering contract examples."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output-dir", type=Path, help="Write examples to this directory.")
    mode.add_argument("--write", action="store_true", help="Update checked-in examples.")
    mode.add_argument("--check", action="store_true", help="Check examples for drift.")
    args = parser.parse_args()

    if args.check:
        return check_examples()
    output = EXAMPLE_ROOT if args.write else args.output_dir.expanduser().resolve()
    capture_examples(output)
    print(json.dumps({"status": "ok", "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
