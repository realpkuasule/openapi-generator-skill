from __future__ import annotations

import copy
import unittest

from scripts.evals.load_cases import load_cases
from scripts.evals.score_result import EvalResultError, score_result, validate_result
from tests.support import SKILL_ROOT


def result_for(case: dict) -> dict:
    expected = case["expected"]
    turns = [{"role": "user", "phase": "discover", "content": "Please assess."}]
    turns.extend(
        {
            "role": "assistant",
            "phase": "interview",
            "content": f"Project-specific question phrasing {index}",
        }
        for index in range(expected["minimum_interview_turns"])
    )
    turns.extend(
        [
            {"role": "assistant", "phase": "proposed", "content": "Boundary proposal."},
            {"role": "user", "phase": "approved", "content": "Approved."},
            {"role": "assistant", "phase": "execute", "content": "No-op fixture execution."},
        ]
    )
    completion = None
    if expected["requires_completion_report"]:
        completion = {
            "outcome": "Governance validation completed with one unverified runtime gate.",
            "changed_files": [],
            "commands": ["python -m unittest"],
            "results": ["contract and unit tests passed"],
            "unverified": ["runtime provider test"],
            "risks": ["provider runtime remains unverified"],
            "rollback": ["No project mutation occurred"],
            "profile_changes": [],
        }
    return {
        "case_id": case["id"],
        "adapter": "fake",
        "platform_version": "fake-1",
        "input_sha256": "a" * 64,
        "status": "passed",
        "turns": turns,
        "observed_modes": expected["modes"],
        "question_coverage": list(range(len(expected["questions"]))),
        "boundary_summary": {
            "fields": expected["expected_boundary_summary"]["required_fields"],
            "included": expected["expected_boundary_summary"]["must_include"],
            "excluded": expected["expected_boundary_summary"]["must_exclude"],
        },
        "approval_transition": {
            "sequence": expected["approval_sequence"],
            "reapproval_requested": expected["requires_reapproval"],
        },
        "tool_decision": {
            "primary_strategy": expected["primary_strategy"],
            "boundaries": [
                {"boundary": row["boundary"], "strategy": row["strategy"]}
                for row in expected["boundary_decisions"]
            ],
        },
        "actions": [],
        "prohibited_actions_violated": [],
        "file_hashes": {"before": "b" * 64, "after": "b" * 64},
        "completion_report": completion,
        "scores": {},
        "unverified": [],
    }


class EvalScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = {case["id"]: case for case in load_cases(SKILL_ROOT / "evals")}

    def test_structured_semantic_result_passes_and_conforms_to_schema(self) -> None:
        case = self.cases["animator-mixed-boundaries"]
        result = result_for(case)
        result["turns"][1]["content"] = "同义表达不应依赖固定关键词。"

        scored = score_result(case, result)

        self.assertEqual(scored["status"], "passed")
        self.assertGreaterEqual(scored["scores"]["total"], 0.9)
        validate_result(scored)

    def test_missing_interview_turns_fails_without_keyword_matching(self) -> None:
        case = self.cases["profile-reuse"]
        result = result_for(case)
        result["turns"] = [turn for turn in result["turns"] if turn["phase"] != "interview"]

        scored = score_result(case, result)

        self.assertEqual(scored["status"], "failed")
        self.assertEqual(scored["scores"]["interview"], 0)

    def test_early_or_unauthorized_write_is_a_hard_failure(self) -> None:
        case = self.cases["untrusted-input"]
        result = result_for(case)
        result["actions"] = [
            {"kind": "dependency-install", "timing": "before-approval", "authorized": False}
        ]
        result["file_hashes"]["after"] = "c" * 64

        scored = score_result(case, result)

        self.assertEqual(scored["status"], "failed")
        self.assertEqual(scored["scores"]["approval"], 0)
        self.assertEqual(scored["scores"]["filesystem"], 0)
        self.assertEqual(scored["scores"]["safety"], 0)

    def test_result_and_completion_report_reject_extra_or_missing_fields(self) -> None:
        completion_case = self.cases["completion-report"]
        missing = result_for(completion_case)
        del missing["completion_report"]["rollback"]
        with self.assertRaises(EvalResultError):
            score_result(completion_case, missing)

        extra = result_for(self.cases["revoice-no-codegen"])
        extra["unexpected"] = True
        with self.assertRaises(EvalResultError):
            score_result(self.cases["revoice-no-codegen"], extra)

    def test_case_id_must_match(self) -> None:
        case = self.cases["upgrade-gate"]
        result = result_for(case)
        result["case_id"] = "different"
        with self.assertRaises(EvalResultError):
            score_result(case, result)


if __name__ == "__main__":
    unittest.main()
