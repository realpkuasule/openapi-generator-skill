from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, SCRIPT_ROOT


class SchemaAuthorityTests(unittest.TestCase):
    def test_profile_validator_loads_the_authoritative_schema(self) -> None:
        path = SCRIPT_ROOT / "validate_profile.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        string_values = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("governance-profile.schema.json", string_values)

    def test_profile_validator_does_not_duplicate_structural_constants(self) -> None:
        text = (SCRIPT_ROOT / "validate_profile.py").read_text(encoding="utf-8")
        for forbidden in (
            "TOP_LEVEL_FIELDS",
            "SECTION_FIELDS",
            "PROJECT_KINDS",
            "PROJECT_STAGES",
            "CONTRACT_APPROACHES",
            "STRATEGIES",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_authoritative_schema_location_is_stable(self) -> None:
        self.assertTrue(
            (
                REPO_ROOT
                / "contracts"
                / "schemas"
                / "governance-profile.schema.json"
            ).is_file()
        )


if __name__ == "__main__":
    unittest.main()
