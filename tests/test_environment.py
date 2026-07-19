from __future__ import annotations

import importlib.metadata
import unittest
from pathlib import Path

from tests.support import REPO_ROOT


class EnvironmentTests(unittest.TestCase):
    def test_locked_validation_dependencies_are_available(self) -> None:
        for distribution in ("jsonschema", "openapi-spec-validator", "PyYAML"):
            with self.subTest(distribution=distribution):
                self.assertTrue(importlib.metadata.version(distribution))

    def test_project_and_lock_files_exist(self) -> None:
        self.assertTrue((REPO_ROOT / "pyproject.toml").is_file())
        self.assertTrue((REPO_ROOT / "uv.lock").is_file())
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('requires-python = ">=3.11"', text)
        self.assertIn("openapi-spec-validator", text)

    def test_ci_has_a_repository_local_skill_validator(self) -> None:
        validator = REPO_ROOT / "scripts" / "quick_validate.py"
        self.assertTrue(validator.is_file())

    def test_git_checkout_normalizes_text_to_lf_on_every_platform(self) -> None:
        attributes = REPO_ROOT / ".gitattributes"

        self.assertTrue(attributes.is_file())
        self.assertIn("* text=auto eol=lf", attributes.read_text(encoding="utf-8").splitlines())


if __name__ == "__main__":
    unittest.main()
