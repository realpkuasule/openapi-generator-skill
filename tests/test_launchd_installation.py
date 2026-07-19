from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_usage_recording import run_usage


@unittest.skipUnless(sys.platform == "darwin", "launchd is a macOS-only scheduler")
class LaunchdInstallationTests(unittest.TestCase):
    def test_install_and_uninstall_are_dry_run_first_and_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_usage(home, "enable", "--device", "m4", "--coordinator", "--apply")
            target = (
                home
                / "Library"
                / "LaunchAgents"
                / "com.realpkuasule.openapi-engineering-maintainer.plist"
            )

            planned, plan = run_usage(
                home, "scheduler", "install", "--hour", "4", "--minute", "30"
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(plan["state"], "would-install")
            self.assertFalse(plan["applied"])
            self.assertFalse(target.exists())

            installed, install = run_usage(
                home,
                "scheduler",
                "install",
                "--hour",
                "4",
                "--minute",
                "30",
                "--apply",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(install["state"], "installed")
            self.assertTrue(install["applied"])
            content = target.read_text(encoding="utf-8")
            self.assertIn("<integer>4</integer>", content)
            self.assertIn("<integer>30</integer>", content)
            self.assertIn("<string>usage</string>", content)
            self.assertIn("<string>due</string>", content)
            self.assertIn("<key>RunAtLoad</key>", content)

            repeated, repeated_payload = run_usage(
                home,
                "scheduler",
                "install",
                "--hour",
                "4",
                "--minute",
                "30",
                "--apply",
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(repeated_payload["state"], "installed")
            self.assertFalse(repeated_payload["applied"])

            dry_remove, remove_plan = run_usage(home, "scheduler", "uninstall")
            self.assertEqual(dry_remove.returncode, 0, dry_remove.stderr)
            self.assertEqual(remove_plan["state"], "would-remove")
            self.assertTrue(target.exists())

            removed, remove = run_usage(home, "scheduler", "uninstall", "--apply")
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertEqual(remove["state"], "removed")
            self.assertTrue(remove["applied"])
            self.assertFalse(target.exists())

    def test_divergent_plist_blocks_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_usage(home, "enable", "--device", "m4", "--coordinator", "--apply")
            run_usage(home, "scheduler", "install", "--apply")
            target = (
                home
                / "Library"
                / "LaunchAgents"
                / "com.realpkuasule.openapi-engineering-maintainer.plist"
            )
            target.write_text(target.read_text(encoding="utf-8") + "<!-- user change -->\n", encoding="utf-8")
            before = target.read_bytes()

            result, payload = run_usage(home, "scheduler", "uninstall", "--apply")

            self.assertEqual(result.returncode, 1)
            self.assertEqual(payload["status"], "conflict")
            self.assertEqual(target.read_bytes(), before)

    def test_collector_cannot_install_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_usage(home, "enable", "--device", "m2", "--apply")

            result, payload = run_usage(home, "scheduler", "install", "--apply")

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "error")
            self.assertFalse((home / "Library" / "LaunchAgents").exists())


if __name__ == "__main__":
    unittest.main()
