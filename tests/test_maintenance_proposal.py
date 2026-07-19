from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.support import REPO_ROOT


SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "build_proposal.py"
SCHEMA = json.loads(
    (REPO_ROOT / "contracts" / "schemas" / "maintenance-proposal.schema.json").read_text(
        encoding="utf-8"
    )
)


def analysis() -> dict:
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
    return {
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
        "clusters": [{"key": "resource-regression", "finding_ids": ["finding-0123456789abcdef"]}],
        "confidence": 0.9,
        "candidate_causes": ["A deterministic candidate cause."],
        "unverified": [],
    }


def candidate() -> dict:
    return {
        "candidate_id": "candidate-0123456789abcdef",
        "contract_impact": "compatible",
        "target_files": ["existing.txt", "tests/test_resource_regression.py"],
        "artifacts": [
            {
                "kind": "traceability-candidate",
                "path": "existing.txt",
                "media_type": "application/json",
                "content": '{"candidate":true}\n',
            },
            {
                "kind": "failing-test",
                "path": "tests/test_resource_regression.py",
                "media_type": "text/x-python",
                "content": "def test_candidate_remains_red():\n    assert False\n",
            },
        ],
        "open_questions": [],
        "failing_tests": ["tests/test_resource_regression.py"],
        "verification": ["Run the new failing test before implementation."],
        "rollback": ["Remove only digest-matched candidate files."],
    }


def run_builder(root: Path, analysis_path: Path, candidate_path: Path, output: Path):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--analysis",
            str(analysis_path),
            "--candidate",
            str(candidate_path),
            "--target-root",
            str(root),
            "--skill-root",
            str(REPO_ROOT / "skills" / "openapi-engineering"),
            "--skill-version",
            "0.1.0-rc.2",
            "--config-sha256",
            "b" * 64,
            "--output",
            str(output),
            "--now",
            "2026-07-19T12:00:00Z",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class MaintenanceProposalTests(unittest.TestCase):
    def test_proposal_binds_inputs_targets_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing.txt").write_text("accepted baseline\n", encoding="utf-8")
            analysis_path = root / "analysis.json"
            candidate_path = root / "candidate.json"
            first_path = root / "proposal-one.json"
            second_path = root / "proposal-two.json"
            analysis_path.write_text(json.dumps(analysis()), encoding="utf-8")
            candidate_path.write_text(json.dumps(candidate()), encoding="utf-8")

            first = run_builder(root, analysis_path, candidate_path, first_path)
            second = run_builder(root, analysis_path, candidate_path, second_path)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            proposal = json.loads(first.stdout)
            self.assertEqual(proposal, json.loads(second.stdout))
            errors = list(
                Draft202012Validator(SCHEMA, format_checker=FormatChecker()).iter_errors(proposal)
            )
            self.assertEqual(errors, [], [error.message for error in errors])
            targets = {row["path"]: row["expected_sha256"] for row in proposal["target_files"]}
            self.assertEqual(
                targets["existing.txt"],
                hashlib.sha256((root / "existing.txt").read_bytes()).hexdigest(),
            )
            self.assertIsNone(targets["tests/test_resource_regression.py"])
            self.assertRegex(proposal["approval_sha256"], r"^[a-f0-9]{64}$")

    def test_any_candidate_change_changes_approval_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "existing.txt").write_text("accepted baseline\n", encoding="utf-8")
            analysis_path = root / "analysis.json"
            candidate_path = root / "candidate.json"
            analysis_path.write_text(json.dumps(analysis()), encoding="utf-8")
            candidate_path.write_text(json.dumps(candidate()), encoding="utf-8")
            first = run_builder(root, analysis_path, candidate_path, root / "one.json")
            changed = copy.deepcopy(candidate())
            changed["verification"].append("Run the deterministic suite.")
            candidate_path.write_text(json.dumps(changed), encoding="utf-8")
            second = run_builder(root, analysis_path, candidate_path, root / "two.json")

            self.assertNotEqual(
                json.loads(first.stdout)["approval_sha256"],
                json.loads(second.stdout)["approval_sha256"],
            )

    def test_traversal_and_symlink_targets_are_blocked_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            analysis_path = root / "analysis.json"
            candidate_path = root / "candidate.json"
            output = root / "proposal.json"
            analysis_path.write_text(json.dumps(analysis()), encoding="utf-8")
            unsafe = candidate()
            unsafe["target_files"] = ["../outside.txt"]
            candidate_path.write_text(json.dumps(unsafe), encoding="utf-8")

            result = run_builder(root, analysis_path, candidate_path, output)

            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())
            self.assertEqual(json.loads(result.stdout)["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
