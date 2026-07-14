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


if __name__ == "__main__":
    unittest.main()
