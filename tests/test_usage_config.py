from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, snapshot_tree, usage_config_path


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


def run_maintenance(home: Path, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        ["node", str(CLI), "maintenance", *arguments, "--home", str(home), "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(result.stdout) if result.stdout else {}
    return result, payload


class UsageConfigTests(unittest.TestCase):
    def test_v1_config_is_read_only_migrated_to_disabled_v2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = usage_config_path(home)
            path.parent.mkdir(parents=True)
            legacy = {
                "config_version": 1,
                "local_collection_enabled": True,
                "sync_enabled": False,
                "device_alias": "m4",
                "coordinator": True,
                "state_root": "default",
                "remote": None,
                "branch": None,
                "sync_authorization": None,
                "retention": {"local_days": 90, "remote_days": 365},
                "feedback": {"successful_sample_every": 5},
                "analysis": {
                    "primary": "codex",
                    "secondary": "claude",
                    "max_events": 50,
                    "timeout_seconds": 600,
                    "warning_rss_mb": 512,
                    "hard_rss_mb": 1024,
                },
                "schedule": {"due_check": "daily", "period": "iso-week"},
            }
            path.write_text(json.dumps(legacy), encoding="utf-8")
            before = path.read_bytes()

            result, payload = run_usage(home, "status")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["config"]["config_version"], 2)
            self.assertFalse(payload["config"]["analysis"]["enabled"])
            self.assertIsNone(payload["config"]["analysis"]["authorization"])
            self.assertEqual(path.read_bytes(), before)

    def test_windows_defaults_are_derived_from_explicit_home_not_ambient_localappdata(self) -> None:
        module = (REPO_ROOT / "lib" / "usage" / "paths.mjs").as_uri()
        script = (
            f'import {{ defaultConfigRoot, defaultStateRoot }} from {json.dumps(module)};'
            "console.log(JSON.stringify({"
            "config: defaultConfigRoot('/isolated-home', 'win32', {LOCALAPPDATA:'/ambient'}),"
            "state: defaultStateRoot('/isolated-home', 'win32', {LOCALAPPDATA:'/ambient'})"
            "}));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["config"].replace("\\", "/"),
            "/isolated-home/AppData/Local/openapi-engineering-skill",
        )
        self.assertEqual(
            payload["state"].replace("\\", "/"),
            "/isolated-home/AppData/Local/openapi-engineering-skill/state",
        )

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
            config_path = usage_config_path(home)

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

    def test_automation_is_exact_digest_bound_revocable_and_drift_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_usage(home, "enable", "--device", "m4", "--coordinator", "--apply")
            run_usage(
                home,
                "sync",
                "configure",
                "--remote",
                "git@example.invalid:owner/private.git",
                "--branch",
                "usage",
                "--apply",
            )
            before = usage_config_path(home).read_bytes()

            planned, plan = run_maintenance(
                home,
                "automation",
                "configure",
                "--credential-mode",
                "active-cli-session",
                "--python",
                sys.executable,
                "--notify",
                "macos",
            )

            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertFalse(plan["applied"])
            self.assertRegex(plan["approval_sha256"], r"^[a-f0-9]{64}$")
            self.assertEqual(usage_config_path(home).read_bytes(), before)

            stale, stale_payload = run_maintenance(
                home,
                "automation",
                "configure",
                "--credential-mode",
                "active-cli-session",
                "--python",
                sys.executable,
                "--notify",
                "macos",
                "--approve",
                "0" * 64,
                "--apply",
            )
            self.assertEqual(stale.returncode, 1)
            self.assertEqual(stale_payload["status"], "stale")
            self.assertEqual(usage_config_path(home).read_bytes(), before)

            applied, configured = run_maintenance(
                home,
                "automation",
                "configure",
                "--credential-mode",
                "active-cli-session",
                "--python",
                sys.executable,
                "--notify",
                "macos",
                "--approve",
                plan["approval_sha256"],
                "--apply",
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertTrue(configured["applied"])
            self.assertTrue(configured["config"]["analysis"]["enabled"])
            self.assertEqual(
                configured["config"]["analysis"]["python_runtime"]["executable"],
                str(Path(sys.executable).absolute()),
            )
            self.assertRegex(
                configured["config"]["analysis"]["python_runtime"]["python_version"],
                r"^\d+\.\d+\.\d+$",
            )
            self.assertEqual(
                configured["config"]["analysis"]["authorization"]["binding_sha256"],
                plan["approval_sha256"],
            )

            changed, changed_payload = run_usage(
                home, "enable", "--device", "m4-renamed", "--coordinator", "--apply"
            )
            self.assertEqual(changed.returncode, 0, changed.stderr)
            self.assertFalse(changed_payload["config"]["analysis"]["enabled"])
            self.assertIsNone(changed_payload["config"]["analysis"]["authorization"])

            disabled, disabled_payload = run_maintenance(
                home, "automation", "disable", "--apply"
            )
            self.assertEqual(disabled.returncode, 0, disabled.stderr)
            self.assertFalse(disabled_payload["config"]["analysis"]["enabled"])

    def test_collector_cannot_authorize_unattended_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_usage(home, "enable", "--device", "m2", "--apply")
            before = snapshot_tree(home)

            result, payload = run_maintenance(
                home,
                "automation",
                "configure",
                "--credential-mode",
                "active-cli-session",
                "--python",
                sys.executable,
                "--notify",
                "macos",
                "--apply",
                "--approve",
                "0" * 64,
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(snapshot_tree(home), before)

    def test_invalid_v2_analysis_authorization_is_rejected_read_only(self) -> None:
        mutations = {
            "enabled-type": lambda config: config["analysis"].__setitem__("enabled", "true"),
            "authorization-shape": lambda config: config["analysis"].__setitem__(
                "authorization", {}
            ),
            "authorization-time": lambda config: config["analysis"]["authorization"].__setitem__(
                "approved_at", "not-a-date-time"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                run_usage(home, "enable", "--device", "m4", "--coordinator", "--apply")
                run_usage(
                    home,
                    "sync",
                    "configure",
                    "--remote",
                    "git@example.invalid:owner/private.git",
                    "--branch",
                    "usage",
                    "--apply",
                )
                planned, plan = run_maintenance(
                    home,
                    "automation",
                    "configure",
                    "--credential-mode",
                    "active-cli-session",
                    "--python",
                    sys.executable,
                )
                self.assertEqual(planned.returncode, 0, planned.stderr)
                applied, _ = run_maintenance(
                    home,
                    "automation",
                    "configure",
                    "--credential-mode",
                    "active-cli-session",
                    "--python",
                    sys.executable,
                    "--approve",
                    plan["approval_sha256"],
                    "--apply",
                )
                self.assertEqual(applied.returncode, 0, applied.stderr)
                path = usage_config_path(home)
                config = json.loads(path.read_text(encoding="utf-8"))
                mutate(config)
                path.write_text(json.dumps(config), encoding="utf-8")
                before = path.read_bytes()

                result, payload = run_usage(home, "status")

                self.assertEqual(result.returncode, 2)
                self.assertEqual(payload["status"], "error")
                self.assertEqual(path.read_bytes(), before)

    def test_automation_rejects_missing_or_unqualified_python_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_usage(home, "enable", "--device", "m4", "--coordinator", "--apply")
            run_usage(
                home,
                "sync",
                "configure",
                "--remote",
                "git@example.invalid:owner/private.git",
                "--branch",
                "usage",
                "--apply",
            )
            before = snapshot_tree(home)

            missing, missing_payload = run_maintenance(
                home,
                "automation",
                "configure",
                "--credential-mode",
                "active-cli-session",
            )
            invalid, invalid_payload = run_maintenance(
                home,
                "automation",
                "configure",
                "--credential-mode",
                "active-cli-session",
                "--python",
                str(home / "missing-python"),
            )

            self.assertEqual(missing.returncode, 2)
            self.assertEqual(missing_payload["status"], "error")
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(invalid_payload["status"], "error")
            self.assertEqual(snapshot_tree(home), before)

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
