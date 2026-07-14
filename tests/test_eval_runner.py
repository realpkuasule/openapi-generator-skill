from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.evals.adapters.base import AdapterCapability, EvalRequest
from scripts.evals.load_cases import load_cases
from scripts.evals.sandbox import tree_digest
from scripts.run_skill_evals import run_evaluation, run_many
from tests.support import REPO_ROOT, SKILL_ROOT
from tests.test_eval_scorer import result_for


class RecordingAdapter:
    name = "fake"

    def __init__(self, result: dict, *, available: bool = True) -> None:
        self.result = result
        self.available = available
        self.requests: list[EvalRequest] = []
        self.project_was_available: list[bool] = []

    def probe(self) -> AdapterCapability:
        return AdapterCapability(self.available, "fake-1", None if self.available else "off")

    def invoke(self, request: EvalRequest, timeout_seconds: int) -> dict:
        self.requests.append(request)
        self.project_was_available.append(request.project_root.is_dir())
        return copy.deepcopy(self.result)


class TimeoutAdapter(RecordingAdapter):
    def invoke(self, request: EvalRequest, timeout_seconds: int) -> dict:
        self.requests.append(request)
        raise TimeoutError("fixture timeout")


class WritingAdapter(RecordingAdapter):
    def invoke(self, request: EvalRequest, timeout_seconds: int) -> dict:
        self.requests.append(request)
        (request.project_root / "early-write.txt").write_text("changed\n", encoding="utf-8")
        return copy.deepcopy(self.result)


class EvalRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = next(
            case
            for case in load_cases(SKILL_ROOT / "evals")
            if case["id"] == "profile-reuse"
        )

    def test_pass_result_is_scored_in_sandbox_without_expected_leakage(self) -> None:
        adapter = RecordingAdapter(result_for(self.case))
        fixture = Path(self.case["fixture_binding"]["compact_fixture"])
        source = Path(__file__).resolve().parents[1] / fixture
        before = tree_digest(source)

        first = run_evaluation(self.case, adapter, timeout_seconds=5)
        second = run_evaluation(self.case, adapter, timeout_seconds=5)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "passed")
        self.assertEqual(tree_digest(source), before)
        self.assertEqual(len(adapter.requests), 2)
        self.assertFalse(hasattr(adapter.requests[0], "expected"))
        self.assertEqual(adapter.project_was_available, [True, True])

    def test_early_write_is_detected_by_hash_gate(self) -> None:
        adapter = WritingAdapter(result_for(self.case))

        result = run_evaluation(self.case, adapter, timeout_seconds=5)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["scores"]["filesystem"], 0)
        self.assertNotEqual(result["file_hashes"]["before"], result["file_hashes"]["after"])

    def test_timeout_is_failed_and_unavailable_adapter_is_blocked(self) -> None:
        timed_out = run_evaluation(
            self.case, TimeoutAdapter(result_for(self.case)), timeout_seconds=1
        )
        self.assertEqual(timed_out["status"], "failed")
        self.assertIn("adapter timeout", timed_out["unverified"])

        unavailable = run_evaluation(
            self.case,
            RecordingAdapter(result_for(self.case), available=False),
            timeout_seconds=1,
        )
        self.assertEqual(unavailable["status"], "blocked")

    def test_run_many_exit_semantics_do_not_convert_blocked_to_passed(self) -> None:
        passed_report, passed_exit = run_many(
            [self.case], RecordingAdapter(result_for(self.case)), timeout_seconds=5
        )
        self.assertEqual(passed_report["status"], "passed")
        self.assertEqual(passed_exit, 0)

        blocked_report, blocked_exit = run_many(
            [self.case],
            RecordingAdapter(result_for(self.case), available=False),
            timeout_seconds=5,
        )
        self.assertEqual(blocked_report["status"], "blocked")
        self.assertEqual(blocked_exit, 2)

    def test_dry_run_cli_writes_an_explicitly_blocked_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "dry-run.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "run_skill_evals.py"),
                    "--dry-run",
                    "--case",
                    "profile-reuse",
                    "--report",
                    str(report),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
