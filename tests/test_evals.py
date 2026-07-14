from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

import yaml

from tests.support import REPO_ROOT, SKILL_ROOT


EVAL_ROOT = SKILL_ROOT / "evals"
SCHEMA_PATH = REPO_ROOT / "contracts" / "schemas" / "eval-case.schema.json"
EXPECTED_CASES = {"animator.yaml", "revoice.yaml", "scope-expansion.yaml"}


def require_fields(value: dict[str, Any], required: list[str], context: str) -> None:
    missing = set(required) - set(value)
    if missing:
        raise AssertionError(f"{context} missing fields: {sorted(missing)}")


class EvalCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.cases: dict[str, dict[str, Any]] = {}
        if EVAL_ROOT.is_dir():
            for path in sorted(EVAL_ROOT.glob("*.yaml")):
                cls.cases[path.name] = yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_expected_eval_cases_exist(self) -> None:
        self.assertEqual(set(self.cases), EXPECTED_CASES)

    def test_cases_follow_contract_shape(self) -> None:
        required_top = self.schema["required"]
        required_expected = self.schema["properties"]["expected"]["required"]
        valid_modes = set(self.schema["$defs"]["mode"]["enum"])
        valid_strategies = set(self.schema["$defs"]["strategy"]["enum"])
        for name, case in self.cases.items():
            with self.subTest(case=name):
                require_fields(case, required_top, name)
                self.assertEqual(case["case_version"], 1)
                require_fields(case["input"], ["prompt", "project_facts"], f"{name}.input")
                require_fields(case["expected"], required_expected, f"{name}.expected")
                expected = case["expected"]
                self.assertTrue(expected["read_only_evidence"])
                self.assertTrue(expected["questions"])
                self.assertTrue(expected["prohibited_actions"])
                self.assertTrue(expected["wait_points"])
                self.assertTrue(set(expected["modes"]) <= valid_modes)
                self.assertIn(expected["primary_strategy"], valid_strategies)
                for decision in expected["boundary_decisions"]:
                    require_fields(
                        decision,
                        ["boundary", "strategy", "condition"],
                        f"{name}.boundary_decisions",
                    )
                    self.assertIn(decision["strategy"], valid_strategies)

    def test_animator_requires_a_mixed_strategy(self) -> None:
        decisions = self.cases["animator.yaml"]["expected"]["boundary_decisions"]
        strategies = {item["strategy"] for item in decisions}
        self.assertTrue(
            {"openapi-generator", "official-sdk", "governance-only"}.issubset(strategies)
        )
        prohibited = " ".join(
            self.cases["animator.yaml"]["expected"]["prohibited_actions"]
        ).lower()
        self.assertIn("all", prohibited)
        self.assertIn("openapi generator", prohibited)

    def test_revoice_prefers_no_codegen_or_official_sdk(self) -> None:
        expected = self.cases["revoice.yaml"]["expected"]
        self.assertIn(expected["primary_strategy"], {"no-codegen", "official-sdk"})
        strategies = {item["strategy"] for item in expected["boundary_decisions"]}
        self.assertTrue(strategies <= {"no-codegen", "official-sdk", "governance-only"})
        prohibited = " ".join(expected["prohibited_actions"]).lower()
        self.assertIn("create an openapi", prohibited)

    def test_scope_expansion_stops_for_reapproval(self) -> None:
        expected = self.cases["scope-expansion.yaml"]["expected"]
        self.assertTrue(expected["requires_reapproval"])
        self.assertTrue(expected.get("scope_expansion_triggers"))
        wait_points = " ".join(expected["wait_points"]).lower()
        self.assertIn("second approval", wait_points)
        prohibited = " ".join(expected["prohibited_actions"]).lower()
        self.assertIn("upgrade", prohibited)


if __name__ == "__main__":
    unittest.main()
