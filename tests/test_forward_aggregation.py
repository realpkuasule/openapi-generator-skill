from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.aggregate_forward_evals import (
    aggregate_reports,
    check_aggregate_report,
    validate_aggregate_report,
)


CASES = (
    "animator-mixed-boundaries",
    "revoice-no-codegen",
    "audit-discovers-upgrade",
    "profile-reuse",
    "untrusted-input",
)
STRATEGIES = {
    "animator-mixed-boundaries": "governance-only",
    "revoice-no-codegen": "no-codegen",
    "audit-discovers-upgrade": "governance-only",
    "profile-reuse": "governance-only",
    "untrusted-input": "governance-only",
}


def evaluation_result(adapter: str, case_id: str, strategy: str) -> dict:
    return {
        "case_id": case_id,
        "adapter": adapter,
        "platform_version": "fixture-1.0",
        "input_sha256": hashlib.sha256(case_id.encode()).hexdigest(),
        "status": "passed",
        "turns": [
            {"role": "assistant", "phase": "discover", "content": "inspected"},
            {"role": "user", "phase": "interview", "content": "bounded"},
            {"role": "assistant", "phase": "proposed", "content": "proposed"},
        ],
        "observed_modes": ["Assess & Select"],
        "question_coverage": [0],
        "boundary_summary": {
            "fields": ["goal"],
            "included": ["read-only assessment"],
            "excluded": ["writes"],
        },
        "approval_transition": {
            "sequence": ["discover", "interview", "proposed"],
            "reapproval_requested": False,
        },
        "tool_decision": {
            "primary_strategy": strategy,
            "boundaries": [{"boundary": "application", "strategy": strategy}],
        },
        "actions": [],
        "prohibited_actions_violated": [],
        "file_hashes": {"before": "a" * 64, "after": "a" * 64},
        "completion_report": None,
        "scores": {
            "interview": 1,
            "boundary": 1,
            "strategy": 1,
            "approval": 1,
            "filesystem": 1,
            "safety": 1,
            "completion": 1,
            "total": 1,
        },
        "unverified": [],
    }


class ForwardAggregationTests(unittest.TestCase):
    def write_platform_report(
        self,
        root: Path,
        adapter: str,
        *,
        digest: str = "b" * 64,
        harness_digest: str = "d" * 64,
        samples: int = 2,
        timeout_seconds: int = 300,
    ) -> Path:
        results = [
            evaluation_result(adapter, case_id, STRATEGIES[case_id])
            for _sample in range(samples)
            for case_id in CASES
        ]
        report = {
            "report_version": 2,
            "adapter": adapter,
            "skill_sha256": digest,
            "harness_sha256": harness_digest,
            "samples": samples,
            "timeout_seconds": timeout_seconds,
            "case_ids": list(CASES),
            "requested_results": len(results),
            "completed_results": len(results),
            "status": "passed",
            "results": results,
        }
        path = root / f"{adapter}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_two_fresh_equivalent_platform_reports_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["equivalence"]["same_skill_digest"])
        self.assertTrue(report["equivalence"]["same_harness_digest"])
        self.assertTrue(report["equivalence"]["hard_gates_passed"])
        self.assertTrue(
            all(case["same_input_digest"] for case in report["equivalence"]["cases"])
        )
        self.assertTrue(
            all(case["same_fixture_digest"] for case in report["equivalence"]["cases"])
        )
        self.assertEqual(
            {platform["timeout_seconds"] for platform in report["platforms"]},
            {300},
        )
        self.assertEqual(
            {platform["completed_results"] for platform in report["platforms"]},
            {10},
        )
        self.assertEqual(
            {tuple(platform["case_ids"]) for platform in report["platforms"]},
            {CASES},
        )
        self.assertEqual(report["equivalence"]["reasons"], [])
        validate_aggregate_report(report)

    def test_minimum_threshold_cannot_be_lowered_below_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")

            with self.assertRaisesRegex(ValueError, "at least two"):
                aggregate_reports(codex, claude, minimum_samples=1)

    def test_different_skill_digests_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex", digest="b" * 64)
            claude = self.write_platform_report(root, "claude", digest="c" * 64)

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertIsNone(report["skill_sha256"])
        self.assertFalse(report["equivalence"]["same_skill_digest"])

    def test_different_harness_digests_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(
                root, "codex", harness_digest="d" * 64
            )
            claude = self.write_platform_report(
                root, "claude", harness_digest="e" * 64
            )

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertIsNone(report["harness_sha256"])
        self.assertFalse(report["equivalence"]["same_harness_digest"])

    def test_missing_required_samples_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex", samples=1)
            claude = self.write_platform_report(root, "claude")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("codex declares 1 samples; 2 required", report["equivalence"]["reasons"])

    def test_incomplete_checkpoint_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            payload = json.loads(codex.read_text(encoding="utf-8"))
            payload["results"].pop()
            payload["completed_results"] -= 1
            payload["status"] = "blocked"
            codex.write_text(json.dumps(payload), encoding="utf-8")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertIn(
            "codex source checkpoint is incomplete",
            report["equivalence"]["reasons"],
        )

    def test_source_results_must_follow_the_declared_ordered_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            payload = json.loads(codex.read_text(encoding="utf-8"))
            payload["results"][0], payload["results"][1] = (
                payload["results"][1],
                payload["results"][0],
            )
            codex.write_text(json.dumps(payload), encoding="utf-8")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertIn(
            "codex: source report results are not its ordered plan prefix",
            report["equivalence"]["reasons"],
        )

    def test_different_input_or_fixture_digests_fail_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            payload = json.loads(claude.read_text(encoding="utf-8"))
            payload["results"][0]["input_sha256"] = "f" * 64
            payload["results"][1]["file_hashes"] = {
                "before": "e" * 64,
                "after": "e" * 64,
            }
            claude.write_text(json.dumps(payload), encoding="utf-8")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["status"], "failed")
        animator = next(
            case
            for case in report["equivalence"]["cases"]
            if case["case_id"] == "animator-mixed-boundaries"
        )
        revoice = next(
            case
            for case in report["equivalence"]["cases"]
            if case["case_id"] == "revoice-no-codegen"
        )
        self.assertFalse(animator["same_input_digest"])
        self.assertFalse(revoice["same_fixture_digest"])

    def test_failed_sample_fails_hard_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            payload = json.loads(claude.read_text(encoding="utf-8"))
            payload["status"] = "failed"
            payload["results"][0]["status"] = "failed"
            claude.write_text(json.dumps(payload), encoding="utf-8")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["equivalence"]["hard_gates_passed"])

    def test_primary_strategy_mismatch_fails_semantic_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            payload = json.loads(claude.read_text(encoding="utf-8"))
            for result in payload["results"]:
                if result["case_id"] == "profile-reuse":
                    result["tool_decision"]["primary_strategy"] = "no-codegen"
            claude.write_text(json.dumps(payload), encoding="utf-8")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["status"], "failed")
        case = next(
            item
            for item in report["equivalence"]["cases"]
            if item["case_id"] == "profile-reuse"
        )
        self.assertFalse(case["equivalent"])

    def test_primary_ranking_difference_is_equivalent_when_boundary_matrix_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            for path in (codex, claude):
                payload = json.loads(path.read_text(encoding="utf-8"))
                for result in payload["results"]:
                    if result["case_id"] == "revoice-no-codegen":
                        result["tool_decision"]["boundaries"] = [
                            {"boundary": "Revoice CLI", "strategy": "no-codegen"},
                            {"boundary": "Vendor APIs", "strategy": "official-sdk"},
                            {"boundary": "OpenAPI artifact", "strategy": "governance-only"},
                        ]
                        if path == codex:
                            result["tool_decision"]["primary_strategy"] = "governance-only"
                path.write_text(json.dumps(payload), encoding="utf-8")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 0)
        case = next(
            item
            for item in report["equivalence"]["cases"]
            if item["case_id"] == "revoice-no-codegen"
        )
        self.assertTrue(case["equivalent"])
        self.assertEqual(
            case["codex_boundary_strategies"],
            ["governance-only", "no-codegen", "official-sdk"],
        )

    def test_language_native_adapter_may_refine_shared_no_codegen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            payload = json.loads(claude.read_text(encoding="utf-8"))
            for result in payload["results"]:
                if result["case_id"] == "revoice-no-codegen":
                    result["tool_decision"]["boundaries"].append(
                        {"boundary": "typed Python adapter", "strategy": "language-native"}
                    )
            claude.write_text(json.dumps(payload), encoding="utf-8")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 0)
        case = next(
            item
            for item in report["equivalence"]["cases"]
            if item["case_id"] == "revoice-no-codegen"
        )
        self.assertTrue(case["equivalent"])
        self.assertEqual(
            case["strategy_refinements"],
            ["language-native refines shared no-codegen maintenance"],
        )

    def test_unrelated_boundary_strategy_addition_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            payload = json.loads(claude.read_text(encoding="utf-8"))
            for result in payload["results"]:
                if result["case_id"] == "profile-reuse":
                    result["tool_decision"]["boundaries"].append(
                        {"boundary": "unexpected generator", "strategy": "openapi-generator"}
                    )
            claude.write_text(json.dumps(payload), encoding="utf-8")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["status"], "failed")

    def test_transparent_unverified_findings_do_not_fail_a_passing_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            for path in (codex, claude):
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["results"][0]["unverified"] = [
                    "current upstream release was not checked without network approval"
                ]
                path.write_text(json.dumps(payload), encoding="utf-8")

            report, exit_code = aggregate_reports(codex, claude)

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "passed")

    def test_check_accepts_passed_report_for_current_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            report, _ = aggregate_reports(codex, claude)
            combined = root / "combined.json"
            combined.write_text(json.dumps(report), encoding="utf-8")

            message, exit_code = check_aggregate_report(
                combined,
                expected_skill_sha256="b" * 64,
                expected_harness_sha256="d" * 64,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("passed", message)

    def test_check_blocks_stale_skill_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            report, _ = aggregate_reports(codex, claude)
            combined = root / "combined.json"
            combined.write_text(json.dumps(report), encoding="utf-8")

            message, exit_code = check_aggregate_report(
                combined,
                expected_skill_sha256="c" * 64,
                expected_harness_sha256="d" * 64,
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("stale", message)

    def test_check_rejects_a_tampered_combined_conclusion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.write_platform_report(root, "codex")
            claude = self.write_platform_report(root, "claude")
            report, _ = aggregate_reports(codex, claude)
            report["equivalence"]["hard_gates_passed"] = False
            combined = root / "combined.json"
            combined.write_text(json.dumps(report), encoding="utf-8")

            message, exit_code = check_aggregate_report(
                combined,
                expected_skill_sha256="b" * 64,
                expected_harness_sha256="d" * 64,
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("recomputed", message)


if __name__ == "__main__":
    unittest.main()
