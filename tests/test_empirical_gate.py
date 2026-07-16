from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.support import REPO_ROOT, snapshot_tree


SCRIPT = (
    REPO_ROOT
    / "skills"
    / "openapi-engineering"
    / "scripts"
    / "run_empirical_gate.py"
)
SCHEMA = REPO_ROOT / "contracts" / "schemas" / "empirical-gate.schema.json"


def load_empirical_module():
    spec = importlib.util.spec_from_file_location("run_empirical_gate", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load empirical gate module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        hasher.update(path.relative_to(root).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(bytes.fromhex(sha256_file(path)))
        hasher.update(b"\0")
    return hasher.hexdigest()


def write_fixture_tool(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

action = sys.argv[1]
if action == "validate":
    assert "openapi:" in pathlib.Path(sys.argv[2]).read_text()
elif action in {"generate", "generate-previous"}:
    output = pathlib.Path(sys.argv[3])
    output.mkdir(parents=True, exist_ok=True)
    value = 6 if action == "generate-previous" else 7
    (output / "client.py").write_text(f"VALUE = {value}\\n")
elif action == "fixture-previous":
    namespace = {}
    exec((pathlib.Path(sys.argv[2]) / "client.py").read_text(), namespace)
    assert namespace["VALUE"] == 6
elif action == "fail":
    raise SystemExit(9)
elif action == "escape":
    pathlib.Path(sys.argv[3]).write_text("outside temporary output\\n")
else:
    raise SystemExit(8)
""",
        encoding="utf-8",
    )


def build_manifest(root: Path) -> tuple[Path, dict[str, object]]:
    project = root / "project"
    baseline = project / "accepted"
    baseline.mkdir(parents=True)
    contract = project / "openapi.yaml"
    contract.write_text(
        "openapi: 3.0.3\ninfo:\n  title: Fixture\n  version: 1.0.0\npaths: {}\n",
        encoding="utf-8",
    )
    fixture_tool = root / "fixture_tool.py"
    write_fixture_tool(fixture_tool)
    fixture = project / "fixture.py"
    fixture.write_text(
        """import pathlib
import sys

namespace = {}
exec((pathlib.Path(sys.argv[1]) / "client.py").read_text(), namespace)
assert namespace["VALUE"] == 7
""",
        encoding="utf-8",
    )
    manifest: dict[str, object] = {
        "manifest_version": 1,
        "mode": "adoption",
        "project_root": str(project),
        "contract": {"path": str(contract), "sha256": sha256_file(contract)},
        "fixture": {"path": str(fixture), "sha256": sha256_file(fixture)},
        "baseline": {"path": str(baseline), "tree_sha256": tree_sha256(baseline)},
        "generator": {
            "name": "fixture-generator",
            "version": "1.2.3",
            "distribution": "fixture",
            "target": "python",
            "maturity": "stable",
            "artifact": {
                "path": str(fixture_tool),
                "sha256": sha256_file(fixture_tool),
            },
            "feature_gaps": [
                {
                    "feature": "streaming",
                    "status": "unsupported",
                    "evidence": "The compact fixture intentionally excludes streaming.",
                }
            ],
            "official_sources": ["https://example.invalid/fixture-generator"],
        },
        "commands": [
            {
                "gate": "validate",
                "argv": [sys.executable, "{artifact}", "validate", "{contract}"],
                "timeout_seconds": 5,
                "network": False,
                "dependency_install": False,
            },
            {
                "gate": "generate",
                "argv": [
                    sys.executable,
                    "{artifact}",
                    "generate",
                    "{contract}",
                    "{output}",
                ],
                "timeout_seconds": 5,
                "network": False,
                "dependency_install": False,
            },
            {
                "gate": "compile",
                "argv": [sys.executable, "-m", "compileall", "-q", "{output}"],
                "timeout_seconds": 5,
                "network": False,
                "dependency_install": False,
            },
            {
                "gate": "fixture",
                "argv": [sys.executable, "{fixture}", "{output}"],
                "timeout_seconds": 5,
                "network": False,
                "dependency_install": False,
            },
        ],
        "required_gates": [
            "validate",
            "generate",
            "inventory",
            "diff",
            "compile",
            "fixture",
        ],
        "diff_policy": {"allow_initial_generation": True, "accepted_changes": []},
        "rollback": ["Discard the temporary candidate directory."],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, manifest


def build_upgrade_manifest(root: Path) -> tuple[Path, dict[str, object]]:
    manifest_path, manifest = build_manifest(root)
    baseline = Path(manifest["baseline"]["path"])
    (baseline / "client.py").write_text("VALUE = 6\n", encoding="utf-8")
    manifest["baseline"]["tree_sha256"] = tree_sha256(baseline)
    previous_generator = json.loads(json.dumps(manifest["generator"]))
    previous_generator["version"] = "1.2.2"
    manifest["mode"] = "upgrade"
    manifest["previous_generator"] = previous_generator
    manifest["commands"] = [
        manifest["commands"][0],
        {
            "gate": "generate-previous",
            "argv": [
                sys.executable,
                "{previous_artifact}",
                "generate-previous",
                "{contract}",
                "{previous_output}",
            ],
            "timeout_seconds": 5,
            "network": False,
            "dependency_install": False,
        },
        manifest["commands"][1],
        {
            "gate": "compile-previous",
            "argv": [
                sys.executable,
                "-m",
                "compileall",
                "-q",
                "{previous_output}",
            ],
            "timeout_seconds": 5,
            "network": False,
            "dependency_install": False,
        },
        manifest["commands"][2],
        {
            "gate": "fixture-previous",
            "argv": [
                sys.executable,
                "{previous_artifact}",
                "fixture-previous",
                "{previous_output}",
            ],
            "timeout_seconds": 5,
            "network": False,
            "dependency_install": False,
        },
        manifest["commands"][3],
    ]
    manifest["required_gates"] = [
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
    ]
    manifest["diff_policy"] = {
        "allow_initial_generation": False,
        "accepted_changes": [
            {
                "path": "client.py",
                "state": "changed",
                "reason": "The fixture models an explicitly reviewed generator upgrade.",
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, manifest


def run_gate(
    manifest: Path,
    *arguments: str,
    temp_root: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if temp_root is not None:
        env["TMPDIR"] = str(temp_root)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(manifest), *arguments],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class EmpiricalGateTests(unittest.TestCase):
    def test_upgrade_generates_both_versions_and_accepts_only_explained_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, _ = build_upgrade_manifest(root)
            proposal_result = run_gate(manifest_path)
            self.assertEqual(proposal_result.returncode, 0, proposal_result.stderr)
            proposal = json.loads(proposal_result.stdout)

            result = run_gate(
                manifest_path,
                "--execute",
                "--approve",
                proposal["approval_digest"],
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["decision"], "adopt-upgrade")
            self.assertEqual(len(payload["gates"]), 11)
            self.assertEqual(
                {gate["name"]: gate["status"] for gate in payload["gates"]}[
                    "baseline-match"
                ],
                "passed",
            )
            self.assertEqual(payload["diff"]["summary"]["changed"], 1)
            self.assertEqual(payload["diff"]["unexplained"], [])
            self.assertEqual(payload["previous_generator"]["version"], "1.2.2")
            self.assertEqual(payload["generator"]["version"], "1.2.3")

    def test_upgrade_rejects_an_unexplained_generated_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, manifest = build_upgrade_manifest(root)
            manifest["diff_policy"]["accepted_changes"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            approval = json.loads(run_gate(manifest_path).stdout)["approval_digest"]

            result = run_gate(manifest_path, "--execute", "--approve", approval)

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            diff = next(gate for gate in payload["gates"] if gate["name"] == "diff")
            self.assertEqual(diff["status"], "failed")
            self.assertEqual(payload["diff"]["unexplained"], ["client.py:changed"])
            self.assertEqual(
                next(
                    gate for gate in payload["gates"] if gate["name"] == "compile"
                )["status"],
                "unverified",
            )

    def test_network_false_enforces_offline_tool_environment(self) -> None:
        module = load_empirical_module()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            environment = module.safe_environment(home, allow_network=False)

        self.assertEqual(environment["GOPROXY"], "off")
        self.assertEqual(environment["GOSUMDB"], "off")
        self.assertEqual(environment["PIP_NO_INDEX"], "1")
        self.assertEqual(environment["npm_config_offline"], "true")

    def test_workspace_cleanup_handles_read_only_tool_caches(self) -> None:
        module = load_empirical_module()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            locked = workspace / "home" / "go" / "pkg" / "mod" / "locked"
            locked.mkdir(parents=True)
            (locked / "cache.txt").write_text("cache", encoding="utf-8")
            locked.chmod(0o500)
            try:
                reclaimed = module.reclaim_workspace(workspace)
                self.assertTrue(reclaimed)
                self.assertFalse(workspace.exists())
            finally:
                if workspace.exists():
                    locked.chmod(0o700)
                    shutil.rmtree(workspace)

    def test_dry_run_is_read_only_and_emits_schema_valid_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, manifest = build_manifest(root)
            before = snapshot_tree(root)

            result = run_gate(manifest_path)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "proposed")
            self.assertEqual(payload["decision"], "proposed")
            self.assertEqual(
                payload["unverified"], manifest["required_gates"]
            )
            self.assertFalse(payload["workspace"]["created"])
            self.assertEqual(snapshot_tree(root), before)
            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            errors = list(
                Draft202012Validator(
                    schema, format_checker=FormatChecker()
                ).iter_errors(payload)
            )
            self.assertEqual(errors, [], [error.message for error in errors])

    def test_execute_requires_the_exact_manifest_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, _ = build_manifest(root)
            before = snapshot_tree(root)

            result = run_gate(
                manifest_path,
                "--execute",
                "--approve",
                "0" * 64,
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["status"], "blocked")
            self.assertEqual(snapshot_tree(root), before)

    def test_fake_generator_passes_all_gates_without_touching_project_or_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            temp_root = root / "tmp"
            temp_root.mkdir()
            manifest_path, _ = build_manifest(root)
            proposal = json.loads(run_gate(manifest_path).stdout)
            project = root / "project"
            before_project = snapshot_tree(project)
            report_path = root / "report.json"

            result = run_gate(
                manifest_path,
                "--execute",
                "--approve",
                proposal["approval_digest"],
                "--report",
                str(report_path),
                temp_root=temp_root,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["decision"], "adopt")
            self.assertEqual(
                [gate["status"] for gate in payload["gates"]], ["passed"] * 6
            )
            self.assertEqual(payload["inventory"]["file_count"], 1)
            self.assertEqual(payload["diff"]["unexplained"], [])
            self.assertTrue(payload["workspace"]["reclaimed"])
            self.assertEqual(snapshot_tree(project), before_project)
            self.assertEqual(json.loads(report_path.read_text()), payload)
            self.assertEqual(list(temp_root.glob("openapi-empirical-*")), [])

    def test_check_report_accepts_fresh_evidence_and_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, _ = build_manifest(root)
            report_path = root / "report.json"
            approval = json.loads(run_gate(manifest_path).stdout)["approval_digest"]
            executed = run_gate(
                manifest_path,
                "--execute",
                "--approve",
                approval,
                "--report",
                str(report_path),
            )
            self.assertEqual(executed.returncode, 0, executed.stderr)

            checked = run_gate(manifest_path, "--check-report", str(report_path))
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            payload["generator"]["version"] = "9.9.9"
            report_path.write_text(json.dumps(payload), encoding="utf-8")
            tampered = run_gate(manifest_path, "--check-report", str(report_path))
            self.assertEqual(tampered.returncode, 1)

    def test_failed_generation_leaves_later_gates_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, manifest = build_manifest(root)
            manifest["commands"][1]["argv"] = [
                sys.executable,
                "{artifact}",
                "fail",
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            approval = json.loads(run_gate(manifest_path).stdout)["approval_digest"]

            result = run_gate(manifest_path, "--execute", "--approve", approval)

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            statuses = {gate["name"]: gate["status"] for gate in payload["gates"]}
            self.assertEqual(statuses["generate"], "failed")
            self.assertEqual(statuses["compile"], "unverified")
            self.assertEqual(statuses["fixture"], "unverified")
            self.assertIn("compile", payload["unverified"])

    def test_out_of_scope_project_write_fails_integrity_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, manifest = build_manifest(root)
            escaped = root / "project" / "escaped.txt"
            manifest["commands"][1]["argv"] = [
                sys.executable,
                "{artifact}",
                "escape",
                "{output}",
                str(escaped),
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            approval = json.loads(run_gate(manifest_path).stdout)["approval_digest"]

            result = run_gate(manifest_path, "--execute", "--approve", approval)

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            generate = next(gate for gate in payload["gates"] if gate["name"] == "generate")
            self.assertEqual(generate["status"], "failed")
            self.assertIn("integrity", generate["summary"].lower())
            self.assertFalse(payload["project"]["unchanged"])


if __name__ == "__main__":
    unittest.main()
