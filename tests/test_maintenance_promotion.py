from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.support import REPO_ROOT, SKILL_ROOT, snapshot_tree
from tests.test_maintenance_proposal import analysis, run_builder


SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "promote_candidate.py"
SCHEMA = json.loads(
    (REPO_ROOT / "contracts" / "schemas" / "maintenance-promotion.schema.json").read_text(
        encoding="utf-8"
    )
)
MAINTENANCE_SCRIPTS = REPO_ROOT / "scripts" / "maintenance"
if str(MAINTENANCE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE_SCRIPTS))


def artifact(path: str, content: str) -> dict:
    return {
        "kind": "failing-test",
        "path": path,
        "media_type": "text/x-python",
        "content": content,
    }


def candidate(*artifacts: dict, open_questions: list[str] | None = None) -> dict:
    paths = [item["path"] for item in artifacts]
    return {
        "candidate_id": "candidate-0123456789abcdef",
        "contract_impact": "compatible",
        "target_files": paths,
        "artifacts": list(artifacts),
        "open_questions": open_questions or [],
        "failing_tests": paths,
        "verification": ["Observe the promoted candidate test RED before implementation."],
        "rollback": ["Restore only exact promotion snapshots."],
    }


def build(root: Path, value: dict) -> tuple[Path, dict]:
    analysis_path = root / "analysis.json"
    candidate_path = root / "candidate.json"
    proposal_path = root / "proposal.json"
    analysis_path.write_text(json.dumps(analysis()), encoding="utf-8")
    candidate_path.write_text(json.dumps(value), encoding="utf-8")
    result = run_builder(root, analysis_path, candidate_path, proposal_path)
    if result.returncode != 0:
        raise AssertionError(result.stdout or result.stderr)
    return proposal_path, json.loads(result.stdout)


def run_promotion(
    root: Path, proposal: Path, approval: str, *, apply: bool = False
) -> tuple[subprocess.CompletedProcess[str], dict]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--proposal",
        str(proposal),
        "--target-root",
        str(root),
        "--approve",
        approval,
    ]
    if apply:
        command.append("--apply")
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, json.loads(result.stdout) if result.stdout else {}


class MaintenancePromotionTests(unittest.TestCase):
    def test_dry_run_is_zero_write_and_exact_approval_atomically_promotes_red_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = "tests/test_maintenance_candidate_resource.py"
            content = "def test_candidate_stays_red():\n    assert False, 'candidate remains RED'\n"
            proposal_path, proposal = build(root, candidate(artifact(path, content)))
            before = snapshot_tree(root)

            planned_result, plan = run_promotion(
                root, proposal_path, proposal["approval_sha256"]
            )

            self.assertEqual(planned_result.returncode, 0, planned_result.stderr)
            self.assertEqual(snapshot_tree(root), before)
            self.assertEqual(plan["action"], "would-promote")
            self.assertFalse(plan["applied"])
            self.assertEqual(
                list(
                    Draft202012Validator(
                        SCHEMA, format_checker=FormatChecker()
                    ).iter_errors(plan)
                ),
                [],
            )

            applied_result, applied = run_promotion(
                root, proposal_path, proposal["approval_sha256"], apply=True
            )

            self.assertEqual(applied_result.returncode, 0, applied_result.stderr)
            self.assertEqual(applied["action"], "promoted")
            self.assertTrue(applied["applied"])
            self.assertEqual((root / path).read_text(encoding="utf-8"), content)
            self.assertIn("assert False", content)

    def test_wrong_digest_open_questions_secret_or_unapproved_path_leave_tree_unchanged(self) -> None:
        cases = [
            (
                candidate(
                    artifact(
                        "tests/test_maintenance_candidate_open.py",
                        "def test_red():\n    assert False\n",
                    ),
                    open_questions=["Which contract owns this behavior?"],
                ),
                None,
            ),
            (
                candidate(
                    artifact(
                        "tests/test_maintenance_candidate_secret.py",
                        "OPENAI_API_KEY = 'sk-forbidden-secret-value'\n",
                    )
                ),
                None,
            ),
            (
                candidate(
                    artifact("README.md", "def test_red():\n    assert False\n")
                ),
                None,
            ),
        ]
        for value, _ in cases:
            with self.subTest(path=value["target_files"][0]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                proposal_path, proposal = build(root, value)
                before = snapshot_tree(root)
                result, payload = run_promotion(
                    root, proposal_path, proposal["approval_sha256"], apply=True
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(payload["status"], "blocked")
                self.assertEqual(snapshot_tree(root), before)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proposal_path, _proposal = build(
                root,
                candidate(
                    artifact(
                        "tests/test_maintenance_candidate_digest.py",
                        "def test_red():\n    assert False\n",
                    )
                ),
            )
            before = snapshot_tree(root)
            result, _payload = run_promotion(root, proposal_path, "0" * 64, apply=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(snapshot_tree(root), before)

    def test_stale_hash_and_symlink_are_rejected_without_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(directory)
            outside = Path(outside_dir)
            path = "tests/test_maintenance_candidate_stale.py"
            proposal_path, proposal = build(
                root, candidate(artifact(path, "def test_red():\n    assert False\n"))
            )
            (root / "tests").mkdir()
            (root / path).write_text("user change\n", encoding="utf-8")
            before = snapshot_tree(root)
            result, _payload = run_promotion(
                root, proposal_path, proposal["approval_sha256"], apply=True
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(snapshot_tree(root), before)

            (root / "tests").unlink() if (root / "tests").is_symlink() else None
            for child in (root / "tests").iterdir():
                child.unlink()
            (root / "tests").rmdir()
            (root / "tests").symlink_to(outside, target_is_directory=True)
            outside_before = snapshot_tree(outside)
            result, _payload = run_promotion(
                root, proposal_path, proposal["approval_sha256"], apply=True
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(snapshot_tree(outside), outside_before)

    def test_partial_replace_failure_restores_all_target_snapshots(self) -> None:
        from promote_candidate import PromotionBlocked, promote

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = "tests/test_maintenance_candidate_one.py"
            second = "tests/test_maintenance_candidate_two.py"
            (root / "tests").mkdir()
            (root / first).write_text("first original\n", encoding="utf-8")
            (root / second).write_text("second original\n", encoding="utf-8")
            proposal_path, proposal = build(
                root,
                candidate(
                    artifact(first, "def test_one():\n    assert False\n"),
                    artifact(second, "def test_two():\n    assert False\n"),
                ),
            )
            before = snapshot_tree(root)
            calls = 0

            def fail_second(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected second replace failure")
                os.replace(source, target)

            with self.assertRaises(PromotionBlocked):
                promote(
                    proposal_path=proposal_path,
                    target_root=root,
                    approval_sha256=proposal["approval_sha256"],
                    apply=True,
                    replace_artifact=fail_second,
                )

            self.assertEqual(snapshot_tree(root), before)


if __name__ == "__main__":
    unittest.main()
