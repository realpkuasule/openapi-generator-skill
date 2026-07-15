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
EXAMPLE_NAMES = (
    "error-response.json",
    "empirical-gate-response.json",
    "generation-comparison-response.json",
    "inspect-response.json",
    "profile-state-response.json",
    "profile-validation-response.json",
)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def capture_examples(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
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
