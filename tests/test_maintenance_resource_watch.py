from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import REPO_ROOT


MAINTENANCE_SCRIPTS = REPO_ROOT / "scripts" / "maintenance"
if str(MAINTENANCE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MAINTENANCE_SCRIPTS))

from adapters import _allowed_environment  # noqa: E402
from process_watch import ProcessLimitExceeded, run_controlled  # noqa: E402


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class MaintenanceResourceWatchTests(unittest.TestCase):
    def test_success_records_peak_rss_warning_and_bounded_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_controlled(
                [
                    sys.executable,
                    "-c",
                    "import time; data=bytearray(12*1024*1024); print('ok'); time.sleep(0.2)",
                ],
                cwd=root,
                env=os.environ.copy(),
                input_text=None,
                timeout_seconds=5,
                warning_limit_bytes=1 * 1024 * 1024,
                hard_limit_bytes=256 * 1024 * 1024,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "ok")
            self.assertEqual(result.resources["measurement_status"], "measured")
            self.assertGreater(result.resources["peak_rss_bytes"], 0)
            self.assertTrue(result.resources["warning_exceeded"])
            self.assertEqual(result.resources["termination_reason"], "exited")
            self.assertFalse(result.resources["process_group_reclaimed"])

    @unittest.skipIf(os.name == "nt", "POSIX process-group ownership test")
    def test_rss_limit_reclaims_only_owned_process_group(self) -> None:
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                child_pid_path = root / "child.pid"
                program = (
                    "import pathlib,subprocess,sys,time; "
                    f"p=subprocess.Popen([sys.executable,'-c',"
                    "'import time; data=bytearray(24*1024*1024); time.sleep(30)']); "
                    f"pathlib.Path({str(child_pid_path)!r}).write_text(str(p.pid)); "
                    "time.sleep(30)"
                )
                with self.assertRaises(ProcessLimitExceeded) as raised:
                    run_controlled(
                        [sys.executable, "-c", program],
                        cwd=root,
                        env=os.environ.copy(),
                        input_text=None,
                        timeout_seconds=5,
                        warning_limit_bytes=8 * 1024 * 1024,
                        hard_limit_bytes=20 * 1024 * 1024,
                    )

                self.assertEqual(raised.exception.reason, "rss-hard-limit")
                self.assertTrue(raised.exception.resources["process_group_reclaimed"])
                self.assertIsNone(unrelated.poll())
                if child_pid_path.is_file():
                    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                    for _ in range(20):
                        if not process_exists(child_pid):
                            break
                        time.sleep(0.05)
                    self.assertFalse(process_exists(child_pid))
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    @unittest.skipIf(os.name == "nt", "POSIX process-group ownership test")
    def test_timeout_reclaims_owned_group_without_touching_unrelated_process(self) -> None:
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        try:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ProcessLimitExceeded) as raised:
                    run_controlled(
                        [sys.executable, "-c", "import time; time.sleep(30)"],
                        cwd=Path(directory),
                        env=os.environ.copy(),
                        input_text=None,
                        timeout_seconds=0.1,
                        warning_limit_bytes=64 * 1024 * 1024,
                        hard_limit_bytes=128 * 1024 * 1024,
                    )
                self.assertEqual(raised.exception.reason, "timeout")
                self.assertTrue(raised.exception.resources["process_group_reclaimed"])
                self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_adapter_environment_forwards_only_platform_specific_approved_auth(self) -> None:
        previous = {name: os.environ.get(name) for name in (
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
            "ANTHROPIC_API_KEY",
        )}
        try:
            os.environ.update(
                OPENAI_API_KEY="openai-test",
                CODEX_API_KEY="codex-test",
                ANTHROPIC_API_KEY="anthropic-test",
            )
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                codex = _allowed_environment(root, "codex")
                claude = _allowed_environment(root, "claude")
            self.assertEqual(codex["OPENAI_API_KEY"], "openai-test")
            self.assertEqual(codex["CODEX_API_KEY"], "codex-test")
            self.assertNotIn("ANTHROPIC_API_KEY", codex)
            self.assertEqual(claude["ANTHROPIC_API_KEY"], "anthropic-test")
            self.assertNotIn("OPENAI_API_KEY", claude)
            self.assertNotIn("CODEX_API_KEY", claude)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    @unittest.skipIf(os.name == "nt", "POSIX watcher mock")
    def test_unavailable_rss_measurement_blocks_and_reclaims_the_owned_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "process_watch._process_tree_rss_bytes", return_value=None
        ):
            with self.assertRaises(ProcessLimitExceeded) as raised:
                run_controlled(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    cwd=Path(directory),
                    env=os.environ.copy(),
                    input_text=None,
                    timeout_seconds=5,
                    warning_limit_bytes=64 * 1024 * 1024,
                    hard_limit_bytes=128 * 1024 * 1024,
                )

        self.assertEqual(raised.exception.reason, "measurement-unsupported")
        self.assertEqual(raised.exception.resources["measurement_status"], "unsupported")
        self.assertIsNone(raised.exception.resources["peak_rss_bytes"])
        self.assertTrue(raised.exception.resources["process_group_reclaimed"])


if __name__ == "__main__":
    unittest.main()
