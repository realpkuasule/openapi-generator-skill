from __future__ import annotations

import json
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

from adapters import (  # noqa: E402
    AdapterFailure,
    SEMANTIC_RESULT_SCHEMA,
    _active_claude_environment,
    _allowed_environment,
    _claude_command,
    _stage_active_codex_credentials,
    run_claude,
    validate_semantic_result,
)
from process_watch import (  # noqa: E402
    ControlledProcessResult,
    ProcessLimitExceeded,
    run_controlled,
)


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class MaintenanceResourceWatchTests(unittest.TestCase):
    def test_claude_turn_limit_failure_preserves_measured_resources(self) -> None:
        resources = {
            "measurement_status": "measured",
            "peak_rss_bytes": 320 * 1024 * 1024,
            "warning_limit_bytes": 512 * 1024 * 1024,
            "hard_limit_bytes": 1024 * 1024 * 1024,
            "warning_exceeded": False,
            "termination_reason": "exited",
            "duration_ms": 4200,
            "process_group_reclaimed": False,
        }
        controlled = ControlledProcessResult(
            returncode=1,
            stdout=json.dumps({"subtype": "error_max_turns"}),
            stderr="",
            resources=resources,
        )
        with patch("adapters.shutil.which", return_value="/usr/bin/claude"), patch(
            "adapters._active_claude_environment",
            return_value=({"ANTHROPIC_AUTH_TOKEN": "test"}, "deepseek-test"),
        ), patch("adapters.run_controlled", return_value=controlled), patch(
            "adapters._cli_version", return_value="claude-test"
        ):
            with self.assertRaises(AdapterFailure) as raised:
                run_claude(
                    {"findings": [], "sanitized_events": []},
                    {"finding-0123456789abcdef"},
                    600,
                    credential_mode="active-cli-session",
                )

        self.assertEqual(raised.exception.code, "turn-limit")
        self.assertEqual(raised.exception.resources, resources)
        self.assertEqual(raised.exception.cli_version, "claude-test")
        self.assertEqual(raised.exception.model, "deepseek-test")

    def test_semantic_schema_matches_final_cluster_and_text_constraints(self) -> None:
        cluster = SEMANTIC_RESULT_SCHEMA["properties"]["clusters"]["items"]
        self.assertEqual(
            cluster["properties"]["key"]["pattern"],
            r"^[a-z0-9][a-z0-9-]{0,63}$",
        )
        self.assertTrue(cluster["properties"]["finding_ids"]["uniqueItems"])
        for field in ("candidate_causes", "unverified"):
            item = SEMANTIC_RESULT_SCHEMA["properties"][field]["items"]
            self.assertEqual(item["minLength"], 1)
            self.assertEqual(item["maxLength"], 500)

        invalid = {
            "clusters": [
                {
                    "key": "Peak RSS / memory",
                    "finding_ids": ["finding-8c5f4fbf5d8244f3"],
                }
            ],
            "confidence": 0.8,
            "candidate_causes": ["Bounded cause."],
            "unverified": [],
        }
        with self.assertRaises(AdapterFailure):
            validate_semantic_result(invalid, {"finding-8c5f4fbf5d8244f3"})

    def test_claude_active_session_stays_bare_and_does_not_load_user_state(self) -> None:
        active = _claude_command("claude", "active-cli-session")
        environment = _claude_command("claude", "environment")

        self.assertIn("--bare", active)
        self.assertIn("--bare", environment)
        self.assertIn("--no-session-persistence", active)
        self.assertIn("--disable-slash-commands", active)
        self.assertIn("--no-chrome", active)
        self.assertEqual(
            active[active.index("--setting-sources") + 1], ""
        )
        self.assertEqual(active[active.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", active)
        self.assertEqual(active[active.index("--max-turns") + 1], "2")

    @unittest.skipIf(os.name == "nt", "POSIX credential ownership and mode checks")
    def test_active_claude_environment_extracts_only_allowlisted_provider_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_home = Path(directory)
            source = source_home / ".claude"
            source.mkdir()
            settings = source / "settings.json"
            settings.write_text(
                json.dumps(
                    {
                        "env": {
                            "ANTHROPIC_AUTH_TOKEN": "token-canary",
                            "ANTHROPIC_BASE_URL": "https://provider.invalid",
                            "ANTHROPIC_MODEL": "deepseek-test",
                            "UNSAFE_EXTRA": "must-not-forward",
                        },
                        "hooks": {"SessionStart": ["must-not-load"]},
                        "enabledPlugins": {"must-not-load": True},
                    }
                ),
                encoding="utf-8",
            )
            settings.chmod(0o600)

            extracted, model = _active_claude_environment(source_home=source_home)

            self.assertEqual(
                extracted,
                {
                    "ANTHROPIC_AUTH_TOKEN": "token-canary",
                    "ANTHROPIC_BASE_URL": "https://provider.invalid",
                    "ANTHROPIC_MODEL": "deepseek-test",
                },
            )
            self.assertEqual(model, "deepseek-test")

    @unittest.skipIf(os.name == "nt", "POSIX credential ownership and mode checks")
    def test_active_session_stages_only_the_minimal_codex_credential(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            codex_source = source_home / ".codex"
            codex_source.mkdir(parents=True)
            codex_auth = codex_source / "auth.json"
            codex_auth.write_text('{"token":"codex-canary"}', encoding="utf-8")
            codex_auth.chmod(0o600)
            (codex_source / "config.toml").write_text("must_not_copy = true\n")

            codex_home = root / "codex-target"
            _stage_active_codex_credentials(codex_home, source_home=source_home)

            self.assertEqual(
                (codex_home / ".codex" / "auth.json").read_text(encoding="utf-8"),
                '{"token":"codex-canary"}',
            )
            self.assertFalse((codex_home / ".codex" / "config.toml").exists())
            self.assertEqual(
                (codex_home / ".codex" / "auth.json").stat().st_mode & 0o777,
                0o600,
            )

    @unittest.skipIf(os.name == "nt", "POSIX credential permission checks")
    def test_active_session_rejects_symlink_and_open_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_home = root / "source"
            codex_source = source_home / ".codex"
            codex_source.mkdir(parents=True)
            outside = root / "outside.json"
            outside.write_text('{"token":"outside"}', encoding="utf-8")
            outside.chmod(0o600)
            (codex_source / "auth.json").symlink_to(outside)

            with self.assertRaisesRegex(Exception, "credential"):
                _stage_active_codex_credentials(
                    root / "symlink-target", source_home=source_home
                )

            (codex_source / "auth.json").unlink()
            codex_auth = codex_source / "auth.json"
            codex_auth.write_text('{"token":"open"}', encoding="utf-8")
            codex_auth.chmod(0o644)
            with self.assertRaisesRegex(Exception, "credential"):
                _stage_active_codex_credentials(
                    root / "open-target", source_home=source_home
                )

    @unittest.skipIf(os.name == "nt", "Windows intentionally blocks unsupported RSS sampling")
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

    @unittest.skipUnless(os.name == "nt", "Windows-specific unsupported watcher contract")
    def test_windows_blocks_before_launch_when_rss_measurement_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "process_watch.subprocess.Popen"
        ) as launch:
            with self.assertRaises(ProcessLimitExceeded) as raised:
                run_controlled(
                    [sys.executable, "-c", "print('must not run')"],
                    cwd=Path(directory),
                    env=os.environ.copy(),
                    input_text=None,
                    timeout_seconds=5,
                    warning_limit_bytes=64 * 1024 * 1024,
                    hard_limit_bytes=128 * 1024 * 1024,
                )

        launch.assert_not_called()
        self.assertEqual(raised.exception.reason, "measurement-unsupported")
        self.assertEqual(raised.exception.resources["measurement_status"], "unsupported")

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
