from __future__ import annotations

import re
import subprocess
import sys
import unittest

import yaml

from tests.support import REPO_ROOT


MAINTAINER_ROOT = REPO_ROOT / "skills" / "openapi-engineering-maintainer"
VALIDATOR = REPO_ROOT / "scripts" / "quick_validate.py"


class MaintainerSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_path = MAINTAINER_ROOT / "SKILL.md"
        cls.skill_text = cls.skill_path.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", cls.skill_text, flags=re.DOTALL)
        if not match:
            raise AssertionError("SKILL.md must start with YAML frontmatter")
        cls.frontmatter = yaml.safe_load(match.group(1))
        cls.body = cls.skill_text[match.end() :]

    def test_validator_is_repository_local_and_portable(self) -> None:
        self.assertEqual(VALIDATOR, REPO_ROOT / "scripts" / "quick_validate.py")

    def test_official_structure_validates_and_contains_no_placeholders(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(MAINTAINER_ROOT)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("TODO", self.skill_text)
        self.assertLess(len(self.skill_text.splitlines()), 500)
        self.assertFalse(
            {"README.md", "CHANGELOG.md", "INSTALLATION_GUIDE.md"}
            & {path.name for path in MAINTAINER_ROOT.rglob("*")}
        )

    def test_frontmatter_is_minimal_and_trigger_boundary_is_complete(self) -> None:
        self.assertEqual(set(self.frontmatter), {"name", "description"})
        self.assertEqual(self.frontmatter["name"], "openapi-engineering-maintainer")
        description = self.frontmatter["description"].lower()
        for phrase in ("usage summary", "trigger", "private", "proposal", "promotion"):
            self.assertIn(phrase, description)
        self.assertIn("not for ordinary openapi", description)

    def test_workflow_stops_before_public_or_unapproved_writes(self) -> None:
        body = self.body.lower()
        for phrase in (
            "sanitized finding bundle",
            "deterministic trigger",
            "codex",
            "claude",
            "approval sha-256",
            "public source",
            "stop",
        ):
            self.assertIn(phrase, body)
        self.assertIn("never run analyzers concurrently", body)
        self.assertIn("at most 50", body)
        self.assertIn("standing authorization", body)
        self.assertIn("max 2", body)
        self.assertIn("fixed notification", body)

    def test_references_are_one_hop_and_cover_analysis_privacy_and_promotion(self) -> None:
        expected = {
            "analysis-workflow.md",
            "privacy-boundary.md",
            "promotion-policy.md",
            "unattended-cycle.md",
        }
        observed = {path.name for path in (MAINTAINER_ROOT / "references").glob("*.md")}
        self.assertEqual(observed, expected)
        for name in expected:
            with self.subTest(reference=name):
                self.assertIn(f"references/{name}", self.body)
                reference = (MAINTAINER_ROOT / "references" / name).read_text(
                    encoding="utf-8"
                )
                self.assertNotIn("TODO", reference)
                self.assertNotRegex(reference, r"\]\([^)]*references/")

    def test_openai_metadata_uses_explicit_skill_prompt(self) -> None:
        metadata = yaml.safe_load(
            (MAINTAINER_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        self.assertIn("$openapi-engineering-maintainer", metadata["interface"]["default_prompt"])


if __name__ == "__main__":
    unittest.main()
