from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.install_skill import install_skill, tree_digest
from tests.support import REPO_ROOT, SKILL_ROOT, snapshot_tree


class InstallSkillTests(unittest.TestCase):
    def test_default_dry_run_plans_both_platforms_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            before = snapshot_tree(home)

            report, exit_code = install_skill(SKILL_ROOT, home, ("codex", "claude"))

            self.assertEqual(exit_code, 0)
            self.assertFalse(report["applied"])
            self.assertEqual(snapshot_tree(home), before)
            expected_action = "would-copy" if os.name == "nt" else "would-link"
            self.assertEqual(
                {row["action"] for row in report["installations"]},
                {expected_action},
            )

    def test_apply_links_both_platforms_to_one_core_tree_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            sentinel = home / ".claude" / "settings.json"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_text('{"keep":true}\n', encoding="utf-8")

            report, exit_code = install_skill(
                SKILL_ROOT, home, ("codex", "claude"), apply=True
            )
            repeated, repeated_exit = install_skill(
                SKILL_ROOT, home, ("codex", "claude"), apply=True
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(repeated_exit, 0)
            self.assertTrue(report["applied"])
            self.assertEqual(
                {row["target_digest"] for row in report["installations"]},
                {tree_digest(SKILL_ROOT)},
            )
            self.assertEqual(
                {row["action"] for row in repeated["installations"]}, {"unchanged"}
            )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), '{"keep":true}\n')

    def test_copy_fallback_has_same_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)

            report, exit_code = install_skill(
                SKILL_ROOT, home, ("codex", "claude"), apply=True, copy_mode=True
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                {row["action"] for row in report["installations"]}, {"copy"}
            )
            self.assertEqual(
                {row["target_digest"] for row in report["installations"]},
                {tree_digest(SKILL_ROOT)},
            )

    def test_divergent_existing_target_blocks_all_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            divergent = home / ".claude" / "skills" / "openapi-engineering"
            divergent.mkdir(parents=True)
            (divergent / "SKILL.md").write_text("different\n", encoding="utf-8")
            before = snapshot_tree(home)

            report, exit_code = install_skill(
                SKILL_ROOT, home, ("codex", "claude"), apply=True
            )

            self.assertEqual(exit_code, 1)
            self.assertEqual(report["status"], "conflict")
            self.assertEqual(snapshot_tree(home), before)
            self.assertFalse((home / ".codex" / "skills" / "openapi-engineering").exists())

    def test_cli_defaults_to_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "install_skill.py"),
                    "--home",
                    directory,
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(payload["applied"])


if __name__ == "__main__":
    unittest.main()
