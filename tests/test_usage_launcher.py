from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.support import REPO_ROOT
from tests.test_usage_recording import run_usage, write_report


CLI = REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"


def run_session(root: Path, *command: str, **limits: str):
    output = root / "launcher.json"
    argv = [
        "node",
        str(CLI),
        "session",
        "run",
        "--agent",
        "codex",
        "--project-alias",
        "fixture",
        "--output",
        str(output),
        "--timeout-seconds",
        limits.get("timeout", "5"),
        "--warning-rss-mb",
        limits.get("warning", "512"),
        "--hard-rss-mb",
        limits.get("hard", "1024"),
        "--json",
        "--",
        *command,
    ]
    result = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, json.loads(result.stdout) if result.stdout else {}, output


class UsageLauncherTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Windows intentionally blocks unsupported RSS sampling")
    def test_completed_child_records_strict_facts_without_raw_output_or_argv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, payload, output = run_session(
                root,
                sys.executable,
                "-c",
                "print('CANARY_CHILD_OUTPUT_SECRET')",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["exit_code"]["value"], 0)
            self.assertEqual(payload["termination_reason"], "completed")
            self.assertTrue(payload["process_group_reclaimed"])
            self.assertRegex(payload["command_sha256"], r"^[a-f0-9]{64}$")
            serialized = json.dumps(payload)
            self.assertNotIn("CANARY_CHILD_OUTPUT_SECRET", serialized)
            self.assertNotIn("print(", serialized)

    @unittest.skipUnless(os.name == "nt", "Windows-specific unsupported launcher contract")
    def test_windows_launcher_blocks_before_starting_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result, payload, output = run_session(
                Path(directory),
                sys.executable,
                "-c",
                "print('must not run')",
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(payload, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["termination_reason"], "unsupported")
            self.assertEqual(payload["peak_rss_mb"]["source"], "unsupported")

    @unittest.skipIf(os.name == "nt", "POSIX process-group isolation is asserted here")
    def test_timeout_kills_only_owned_group_and_leaves_existing_process_alive(self) -> None:
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            with tempfile.TemporaryDirectory() as directory:
                result, payload, _output = run_session(
                    Path(directory),
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                    timeout="0.2",
                )

                self.assertEqual(result.returncode, 2)
                self.assertEqual(payload["status"], "blocked")
                self.assertEqual(payload["termination_reason"], "timeout")
                self.assertTrue(payload["process_group_reclaimed"])
                self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    @unittest.skipIf(os.name == "nt", "RSS process-tree sampling is POSIX in P1")
    def test_rss_hard_limit_terminates_owned_child_after_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result, payload, _output = run_session(
                Path(directory),
                sys.executable,
                "-c",
                "import time; value=bytearray(40*1024*1024); time.sleep(30)",
                timeout="5",
                warning="10",
                hard="20",
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["termination_reason"], "rss-limit")
            self.assertTrue(payload["warning_exceeded"])
            self.assertTrue(payload["hard_limit_exceeded"])
            self.assertGreater(payload["peak_rss_mb"]["value"], 20)
            self.assertTrue(payload["process_group_reclaimed"])

    @unittest.skipIf(os.name == "nt", "Windows intentionally blocks unsupported RSS sampling")
    def test_launcher_record_uses_bounded_report_facts_and_rejects_manual_spoofing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            completion = root / "completion.json"
            write_report(completion)
            run_usage(home, "enable", "--device", "m4", "--apply")
            launched, report, launcher_path = run_session(
                root,
                sys.executable,
                "-c",
                "raise SystemExit(0)",
            )
            self.assertEqual(launched.returncode, 0, launched.stderr)

            result, payload = run_usage(
                home,
                "record",
                "--completion-report",
                str(completion),
                "--capture-mode",
                "launcher",
                "--launcher-report",
                str(launcher_path),
                "--platform",
                "codex",
                "--project-alias",
                "fixture",
                "--session",
                "ses-00000000000001a1",
                "--tool-strategy",
                "governance-only",
                "--now",
                "2026-07-19T12:00:00Z",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["event"]["duration_ms"]["source"], "launcher")
            self.assertEqual(payload["event"]["exit_code"], report["exit_code"])
            self.assertEqual(
                payload["event"]["termination_reason"], report["termination_reason"]
            )

            spoofed, spoofed_payload = run_usage(
                home,
                "record",
                "--completion-report",
                str(completion),
                "--capture-mode",
                "launcher",
                "--launcher-report",
                str(launcher_path),
                "--duration-ms",
                "1",
                "--platform",
                "codex",
                "--project-alias",
                "fixture",
                "--session",
                "ses-00000000000001a2",
            )
            self.assertEqual(spoofed.returncode, 2)
            self.assertEqual(spoofed_payload["status"], "error")


if __name__ == "__main__":
    unittest.main()
