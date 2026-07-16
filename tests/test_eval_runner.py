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
from scripts.run_skill_evals import (
    load_resume_results,
    retry_nonpassing_results,
    run_evaluation,
    run_many,
)
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
        self.assertTrue(adapter.requests[0].interview_answers)
        self.assertTrue(adapter.requests[0].approval)
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
        self.assertRegex(passed_report["skill_sha256"], r"^[a-f0-9]{64}$")
        self.assertRegex(passed_report["harness_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(passed_report["timeout_seconds"], 5)
        self.assertEqual(passed_report["report_version"], 2)
        self.assertEqual(passed_report["case_ids"], ["profile-reuse"])
        self.assertEqual(passed_report["requested_results"], 1)
        self.assertEqual(passed_report["completed_results"], 1)
        self.assertEqual(passed_exit, 0)

        blocked_report, blocked_exit = run_many(
            [self.case],
            RecordingAdapter(result_for(self.case), available=False),
            timeout_seconds=5,
        )
        self.assertEqual(blocked_report["status"], "blocked")
        self.assertEqual(blocked_exit, 2)

    def test_run_many_checkpoints_each_result_and_resumes_the_exact_prefix(self) -> None:
        checkpoints: list[dict] = []
        adapter = RecordingAdapter(result_for(self.case))

        report, exit_code = run_many(
            [self.case],
            adapter,
            timeout_seconds=5,
            samples=2,
            checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual([row["completed_results"] for row in checkpoints], [1, 2])
        self.assertEqual([row["requested_results"] for row in checkpoints], [2, 2])
        self.assertEqual(checkpoints[0]["status"], "blocked")
        self.assertEqual(checkpoints[1], report)

        resumed_checkpoints: list[dict] = []
        resumed_adapter = RecordingAdapter(result_for(self.case))
        resumed, resumed_exit = run_many(
            [self.case],
            resumed_adapter,
            timeout_seconds=5,
            samples=2,
            initial_results=checkpoints[0]["results"],
            checkpoint=lambda value: resumed_checkpoints.append(copy.deepcopy(value)),
        )

        self.assertEqual(resumed_exit, 0)
        self.assertEqual(len(resumed_adapter.requests), 1)
        self.assertEqual(resumed, report)
        self.assertEqual(len(resumed_checkpoints), 1)

    def test_resume_loader_rejects_a_stale_harness_digest(self) -> None:
        checkpoints: list[dict] = []
        adapter = RecordingAdapter(result_for(self.case))
        run_many(
            [self.case],
            adapter,
            timeout_seconds=5,
            samples=2,
            checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)),
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            path.write_text(json.dumps(checkpoints[0]), encoding="utf-8")
            resumed = load_resume_results(
                path,
                [self.case],
                RecordingAdapter(result_for(self.case)),
                timeout_seconds=5,
                samples=2,
            )
            self.assertEqual(resumed, checkpoints[0]["results"])

            stale = copy.deepcopy(checkpoints[0])
            stale["harness_sha256"] = "0" * 64
            path.write_text(json.dumps(stale), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "harness_sha256"):
                load_resume_results(
                    path,
                    [self.case],
                    RecordingAdapter(result_for(self.case)),
                    timeout_seconds=5,
                    samples=2,
                )

            wrong_plan = copy.deepcopy(checkpoints[0])
            wrong_plan["case_ids"] = ["untrusted-input"]
            path.write_text(json.dumps(wrong_plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "case_ids"):
                load_resume_results(
                    path,
                    [self.case],
                    RecordingAdapter(result_for(self.case)),
                    timeout_seconds=5,
                    samples=2,
                )

    def test_retry_nonpassing_replaces_only_failed_or_blocked_slots(self) -> None:
        passed, _exit_code = run_many(
            [self.case],
            RecordingAdapter(result_for(self.case)),
            timeout_seconds=5,
            samples=2,
        )
        existing = copy.deepcopy(passed["results"])
        existing[0]["status"] = "failed"
        retry_adapter = RecordingAdapter(result_for(self.case))
        checkpoints: list[dict] = []

        retried, retry_exit = retry_nonpassing_results(
            [self.case],
            retry_adapter,
            timeout_seconds=5,
            samples=2,
            existing_results=existing,
            checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)),
        )

        self.assertEqual(retry_exit, 0)
        self.assertEqual(retried["status"], "passed")
        self.assertEqual(len(retry_adapter.requests), 1)
        self.assertEqual(retried["results"][1], existing[1])
        self.assertEqual(checkpoints, [retried])

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
