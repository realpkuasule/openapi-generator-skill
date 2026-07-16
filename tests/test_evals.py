from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.evals.load_cases import EvalCaseError, load_case, load_cases
from tests.support import REPO_ROOT, SKILL_ROOT


EVAL_ROOT = SKILL_ROOT / "evals"
EXPECTED_CASES = {
    "animator-mixed-boundaries",
    "revoice-no-codegen",
    "audit-discovers-upgrade",
    "profile-reuse",
    "untrusted-input",
    "completion-report",
    "upgrade-gate",
}


class EvalCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = {case["id"]: case for case in load_cases(EVAL_ROOT)}

    def test_all_seven_cases_follow_schema_and_bind_existing_fixtures(self) -> None:
        self.assertEqual(set(self.cases), EXPECTED_CASES)
        for case in self.cases.values():
            with self.subTest(case=case["id"]):
                fixture = REPO_ROOT / case["fixture_binding"]["compact_fixture"]
                self.assertTrue(fixture.is_dir())
                self.assertGreaterEqual(case["expected"]["minimum_interview_turns"], 2)
                answers = case["input"]["interview_answers"]
                self.assertGreaterEqual(
                    len(answers), case["expected"]["minimum_interview_turns"]
                )
                covered = {
                    question
                    for answer in answers
                    for question in answer["covers_questions"]
                }
                self.assertEqual(
                    covered, set(range(len(case["expected"]["questions"])))
                )
                self.assertIn("approve", case["input"]["approval"].lower())

    def test_case_selection_accepts_stable_case_ids(self) -> None:
        cases = load_cases(EVAL_ROOT, ["animator-mixed-boundaries"])

        self.assertEqual([case["id"] for case in cases], ["animator-mixed-boundaries"])

    def test_loader_rejects_extra_fields_and_fixture_escape(self) -> None:
        source = copy.deepcopy(self.cases["profile-reuse"])
        with tempfile.TemporaryDirectory(dir=REPO_ROOT) as directory:
            root = Path(directory)
            invalid = root / "invalid.yaml"
            source["unexpected"] = True
            invalid.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
            with self.assertRaises(EvalCaseError):
                load_case(invalid)

            del source["unexpected"]
            source["fixture_binding"]["compact_fixture"] = "../outside"
            invalid.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
            with self.assertRaises(EvalCaseError):
                load_case(invalid)

    def test_animator_covers_flask_sse_domain_and_vendor_boundaries(self) -> None:
        case = self.cases["animator-mixed-boundaries"]
        text = yaml.safe_dump(case).lower()
        for term in ("flask", "sse", "domain", "official-sdk"):
            with self.subTest(term=term):
                self.assertIn(term, text)
        self.assertEqual(case["expected"]["modes"], ["Assess & Select"])
        answers = " ".join(
            answer["content"] for answer in case["input"]["interview_answers"]
        ).casefold()
        self.assertIn("openapi generator", answers)
        self.assertIn("typescript-fetch", answers)
        self.assertIn("primary", answers)
        sse = next(
            row
            for row in case["expected"]["boundary_decisions"]
            if row["boundary"] == "SSE event adapter"
        )
        self.assertEqual(sse["strategy"], "language-native")

    def test_revoice_surfaces_existing_openapi_conflict(self) -> None:
        case = self.cases["revoice-no-codegen"]
        self.assertIn("contracts/openapi.yaml", " ".join(case["input"]["project_facts"]))
        boundaries = [row["boundary"] for row in case["expected"]["boundary_decisions"]]
        self.assertIn("OpenAPI artifact disposition", boundaries)
        self.assertEqual(len(boundaries), 3)
        existing = next(
            row
            for row in case["expected"]["boundary_decisions"]
            if row["boundary"] == "OpenAPI artifact disposition"
        )
        self.assertEqual(existing["strategy"], "governance-only")

    def test_security_reuse_completion_and_upgrade_cases_are_explicit(self) -> None:
        self.assertTrue(self.cases["untrusted-input"]["input"]["adversarial_inputs"])
        self.assertEqual(
            self.cases["untrusted-input"]["expected"]["expected_boundary_summary"]["must_include"],
            ["security finding"],
        )
        self.assertTrue(self.cases["profile-reuse"]["expected"]["requires_reapproval"])
        self.assertTrue(
            self.cases["completion-report"]["expected"]["requires_completion_report"]
        )
        upgrade = self.cases["upgrade-gate"]
        self.assertIn(
            "immutable accepted baseline",
            upgrade["expected"]["expected_boundary_summary"]["must_include"],
        )


if __name__ == "__main__":
    unittest.main()
