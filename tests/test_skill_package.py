from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from tests.support import SKILL_ROOT


EXPECTED_REFERENCES = {
    "boundary-interview.md",
    "lifecycle-modes.md",
    "decision-framework.md",
    "generator-evaluation.md",
    "governance-gates.md",
    "platform-compatibility.md",
}


class SkillPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_path = SKILL_ROOT / "SKILL.md"
        cls.skill_text = cls.skill_path.read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", cls.skill_text, flags=re.DOTALL)
        if not match:
            raise AssertionError("SKILL.md must start with YAML frontmatter")
        cls.frontmatter = yaml.safe_load(match.group(1))
        cls.body = cls.skill_text[match.end() :]

    def test_frontmatter_is_portable_and_trigger_complete(self) -> None:
        self.assertEqual(set(self.frontmatter), {"name", "description"})
        self.assertEqual(self.frontmatter["name"], "openapi-engineering")
        description = self.frontmatter["description"].lower()
        for phrase in (
            "openapi",
            "code generation",
            "audit",
            "upgrade",
            "troubleshoot",
            "no code generation",
            "codex",
            "claude code",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, description)

    def test_core_workflow_enforces_approval_boundary(self) -> None:
        for phrase in (
            "Read-only discovery",
            "Adaptive interview",
            "Work-boundary summary",
            "Explicit approval",
            "Execute and validate",
            "Persist decisions",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.body)
        self.assertIn("Return to proposed", self.body)
        self.assertNotIn("TODO", self.skill_text)

    def test_all_references_exist_and_are_one_hop_from_skill(self) -> None:
        reference_root = SKILL_ROOT / "references"
        observed = {path.name for path in reference_root.glob("*.md")}
        self.assertEqual(observed, EXPECTED_REFERENCES)
        for name in EXPECTED_REFERENCES:
            with self.subTest(reference=name):
                self.assertIn(f"references/{name}", self.body)
                text = (reference_root / name).read_text(encoding="utf-8")
                self.assertNotRegex(text, r"\]\([^)]*references/")

    def test_decision_reference_supports_every_strategy(self) -> None:
        text = (SKILL_ROOT / "references" / "decision-framework.md").read_text(
            encoding="utf-8"
        )
        for strategy in (
            "openapi-generator",
            "language-native",
            "official-sdk",
            "governance-only",
            "mcp",
            "no-codegen",
        ):
            with self.subTest(strategy=strategy):
                self.assertIn(strategy, text)

    def test_generator_evaluation_has_seven_step_empirical_gate(self) -> None:
        text = (SKILL_ROOT / "references" / "generator-evaluation.md").read_text(
            encoding="utf-8"
        )
        for step in range(1, 8):
            self.assertRegex(text, rf"(?m)^{step}\. ")
        for phrase in ("temporary directory", "compile/import", "fixture", "reject"):
            self.assertIn(phrase, text.lower())

    def test_lifecycle_reference_defines_all_modes(self) -> None:
        text = (SKILL_ROOT / "references" / "lifecycle-modes.md").read_text(
            encoding="utf-8"
        )
        for mode in (
            "Assess & Select",
            "Initial Design",
            "First Integration",
            "Daily Evolution",
            "Audit & Drift",
            "Upgrade & Migration",
            "Troubleshoot",
            "Governance Hardening",
            "Reselect & Decommission",
        ):
            with self.subTest(mode=mode):
                self.assertIn(mode, text)

    def test_platform_metadata_and_package_are_minimal(self) -> None:
        metadata = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("$openapi-engineering", metadata)
        self.assertLess(len(self.skill_text.splitlines()), 500)
        forbidden = {"README.md", "INSTALLATION_GUIDE.md", "QUICK_REFERENCE.md", "CHANGELOG.md"}
        self.assertFalse(forbidden & {path.name for path in SKILL_ROOT.rglob("*")})


if __name__ == "__main__":
    unittest.main()
