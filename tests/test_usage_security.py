from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.support import usage_state_root
from tests.test_usage_recording import record, run_usage, write_report


class UsageSecurityTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "symlink creation requires platform-specific privileges")
    def test_outbound_symlink_blocks_record_without_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            report = home / "completion.json"
            write_report(report)
            run_usage(home, "enable", "--device", "m4", "--apply")
            state = usage_state_root(home)
            external = root / "external"
            external.mkdir()
            (state / "outbound").mkdir(parents=True)
            (state / "outbound" / "m4").symlink_to(external, target_is_directory=True)

            result, payload = record(home, report, "ses-0000000000000010")

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(list(external.iterdir()), [])
            event_root = state / "local" / "events" / "m4"
            self.assertFalse(event_root.exists())

    @unittest.skipIf(os.name == "nt", "symlink creation requires platform-specific privileges")
    def test_state_root_symlink_blocks_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            report = home / "completion.json"
            write_report(report)
            run_usage(home, "enable", "--device", "m4", "--apply")
            external = root / "external"
            external.mkdir()
            state = usage_state_root(home)
            state.parent.mkdir(parents=True)
            state.symlink_to(external, target_is_directory=True)

            result, payload = record(home, report, "ses-0000000000000011")

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(list(external.iterdir()), [])

    def test_remote_shell_metacharacters_are_never_executed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            marker = root / "executed"
            report = home / "completion.json"
            write_report(report)
            run_usage(home, "enable", "--device", "m4", "--apply")
            remote = f"$(touch {marker})"
            configured, _ = run_usage(
                home,
                "sync",
                "configure",
                "--remote",
                remote,
                "--branch",
                "usage",
                "--apply",
            )
            self.assertEqual(configured.returncode, 0, configured.stderr)
            record(home, report, "ses-0000000000000012")

            result, payload = run_usage(home, "sync")

            self.assertEqual(result.returncode, 1)
            self.assertEqual(payload["status"], "blocked")
            self.assertFalse(marker.exists())

    def test_outbound_envelope_contains_only_digest_and_sanitized_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            report = home / "completion.json"
            write_report(report)
            run_usage(home, "enable", "--device", "m4", "--apply")
            record(home, report, "ses-0000000000000013")
            outbound = usage_state_root(home) / "outbound" / "m4"
            envelope = json.loads(next(outbound.glob("*.json")).read_text(encoding="utf-8"))

            self.assertEqual(
                set(envelope), {"envelope_version", "kind", "payload_sha256", "payload"}
            )
            self.assertEqual(envelope["kind"], "usage-event")
            for forbidden in ("project_alias", "platform_version", "incident_ids", "commands"):
                self.assertNotIn(forbidden, envelope["payload"])


if __name__ == "__main__":
    unittest.main()
