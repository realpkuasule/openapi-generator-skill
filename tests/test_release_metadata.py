from __future__ import annotations

import tomllib
import unittest

from tests.support import REPO_ROOT


RELEASE_TAG = "v0.1.0-rc.1"
PEP440_VERSION = "0.1.0rc1"
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
RELEASE_PLAN = REPO_ROOT / "docs" / "plans" / "release-v0.1.0-rc.1.md"


class ReleaseMetadataTests(unittest.TestCase):
    def test_project_and_lock_versions_match_release_candidate(self) -> None:
        project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
        locked_project = next(
            package
            for package in lock["package"]
            if package["name"] == "openapi-engineering-skill"
        )

        self.assertEqual(project["project"]["version"], PEP440_VERSION)
        self.assertEqual(locked_project["version"], PEP440_VERSION)

    def test_readme_documents_pinned_dual_platform_install_and_rollback(self) -> None:
        content = README.read_text(encoding="utf-8")

        for required in (
            RELEASE_TAG,
            "--platform codex",
            "--platform claude",
            "--apply",
            "--uninstall",
            "scripts/verify.py --tier deterministic",
            "multi-turn boundary interview",
            "no-codegen",
        ):
            self.assertIn(required, content)

        self.assertNotIn("scripts/run_deterministic_suite.py", content)

    def test_changelog_contains_dated_release_candidate(self) -> None:
        content = CHANGELOG.read_text(encoding="utf-8")

        self.assertIn("## [0.1.0-rc.1] - 2026-07-16", content)
        self.assertIn("Contract-First", content)
        self.assertIn("Codex", content)
        self.assertIn("Claude Code", content)

    def test_release_plan_records_contract_impact_gates_and_rollback(self) -> None:
        content = RELEASE_PLAN.read_text(encoding="utf-8")

        for required in (
            RELEASE_TAG,
            "Contract-First",
            "OpenAPI 1.1.0",
            "no schema change",
            "147/147",
            "rollback",
            "Codex",
            "Claude Code",
        ):
            self.assertIn(required, content)


if __name__ == "__main__":
    unittest.main()
