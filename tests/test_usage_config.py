from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, snapshot_tree


CLI = REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"


def run_usage(home: Path, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        ["node", str(CLI), "usage", *arguments, "--home", str(home), "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(result.stdout) if result.stdout else {}
    return result, payload


class UsageConfigTests(unittest.TestCase):
    def test_status_is_read_only_and_defaults_to_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            before = snapshot_tree(home)

            result, payload = run_usage(home, "status")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["action"], "status")
            self.assertFalse(payload["applied"])
            self.assertFalse(payload["config"]["local_collection_enabled"])
            self.assertFalse(payload["config"]["sync_enabled"])
            self.assertEqual(snapshot_tree(home), before)

    def test_enable_is_dry_run_by_default_and_apply_is_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            before = snapshot_tree(home)

            planned, plan = run_usage(home, "enable", "--device", "m4", "--coordinator")

            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertFalse(plan["applied"])
            self.assertTrue(plan["config"]["local_collection_enabled"])
            self.assertTrue(plan["config"]["coordinator"])
            self.assertEqual(snapshot_tree(home), before)

            applied, payload = run_usage(
                home, "enable", "--device", "m4", "--coordinator", "--apply"
            )
            config_path = home / ".config" / "openapi-engineering-skill" / "usage.json"

            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertTrue(payload["applied"])
            self.assertTrue(config_path.is_file())
            self.assertEqual(json.loads(config_path.read_text(encoding="utf-8")), payload["config"])

            repeated, repeated_payload = run_usage(
                home, "enable", "--device", "m4", "--coordinator", "--apply"
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(repeated_payload["config"], payload["config"])

    def test_sync_authorization_is_separate_and_device_change_invalidates_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_usage(home, "enable", "--device", "m4", "--coordinator", "--apply")
            before = snapshot_tree(home)

            planned, plan = run_usage(
                home,
                "sync",
                "configure",
                "--remote",
                "git@example.invalid:owner/private.git",
                "--branch",
                "usage",
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertFalse(plan["applied"])
            self.assertTrue(plan["config"]["sync_enabled"])
            self.assertEqual(snapshot_tree(home), before)

            applied, payload = run_usage(
                home,
                "sync",
                "configure",
                "--remote",
                "git@example.invalid:owner/private.git",
                "--branch",
                "usage",
                "--apply",
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertTrue(payload["config"]["sync_enabled"])
            self.assertRegex(
                payload["config"]["sync_authorization"]["binding_sha256"], r"^[a-f0-9]{64}$"
            )

            changed, changed_payload = run_usage(
                home, "enable", "--device", "m4-renamed", "--coordinator", "--apply"
            )
            self.assertEqual(changed.returncode, 0, changed.stderr)
            self.assertFalse(changed_payload["config"]["sync_enabled"])
            self.assertIsNone(changed_payload["config"]["sync_authorization"])

    def test_unsafe_remote_is_rejected_without_echoing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_usage(home, "enable", "--device", "m4", "--apply")
            canary = "CANARY_PRIVATE_TOKEN_123"
            before = snapshot_tree(home)

            result, payload = run_usage(
                home,
                "sync",
                "configure",
                "--remote",
                f"https://user:{canary}@example.invalid/private.git",
                "--branch",
                "usage",
                "--apply",
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "error")
            self.assertNotIn(canary, result.stdout + result.stderr)
            self.assertEqual(snapshot_tree(home), before)


if __name__ == "__main__":
    unittest.main()
