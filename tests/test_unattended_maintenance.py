from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from tests.support import REPO_ROOT, usage_state_root
from tests.test_usage_summary import event, seed


CLI = REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"
SCHEMA_ROOT = REPO_ROOT / "contracts" / "schemas"


def run_cli(home: Path, family: str, *arguments: str):
    result = subprocess.run(
        ["node", str(CLI), family, *arguments, "--home", str(home), "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, json.loads(result.stdout) if result.stdout else {}


def git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], text=True, capture_output=True, check=False
    )


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def authorize(
    home: Path,
    remote: Path,
    *,
    notification: str = "none",
    python_executable: str = sys.executable,
) -> None:
    configured, _ = run_cli(
        home,
        "usage",
        "sync",
        "configure",
        "--remote",
        str(remote),
        "--branch",
        "usage",
        "--apply",
        "--now",
        "2026-07-19T12:00:00Z",
    )
    if configured.returncode != 0:
        raise AssertionError(configured.stderr or configured.stdout)
    planned, plan = run_cli(
        home,
        "maintenance",
        "automation",
        "configure",
        "--credential-mode",
        "active-cli-session",
        "--python",
        python_executable,
        "--notify",
        notification,
    )
    if planned.returncode != 0:
        raise AssertionError(planned.stderr or planned.stdout)
    applied, _ = run_cli(
        home,
        "maintenance",
        "automation",
        "configure",
        "--credential-mode",
        "active-cli-session",
        "--python",
        python_executable,
        "--notify",
        notification,
        "--approve",
        plan["approval_sha256"],
        "--apply",
    )
    if applied.returncode != 0:
        raise AssertionError(applied.stderr or applied.stdout)


def semantic(path: Path, cause: str) -> None:
    path.write_text(
        json.dumps(
            {
                "clusters": [],
                "confidence": 0.9,
                "candidate_causes": [cause],
                "unverified": [],
            }
        ),
        encoding="utf-8",
    )


def cycle_arguments(primary: Path, secondary: Path) -> tuple[str, ...]:
    return (
        "cycle",
        "--now",
        "2026-07-19T18:00:00Z",
        "--adapter",
        "fake",
        "--fake-platform",
        "codex",
        "--fake-response",
        str(primary),
        "--secondary-adapter",
        "fake",
        "--secondary-fake-platform",
        "claude",
        "--secondary-fake-response",
        str(secondary),
    )


class UnattendedMaintenanceTests(unittest.TestCase):
    def test_python_runtime_drift_blocks_before_sync_or_analyzer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            seed(home, [event(index) for index in range(1, 6)])
            wrapper = root / "maintenance-python"
            wrapper.write_text(
                f"#!/bin/sh\nexec {json.dumps(sys.executable)} \"$@\"\n",
                encoding="utf-8",
            )
            wrapper.chmod(0o700)
            authorize(home, root / "unreachable.git", python_executable=str(wrapper))
            wrapper.unlink()
            missing_primary = root / "must-not-be-read-primary.json"
            missing_secondary = root / "must-not-be-read-secondary.json"

            status_result, status = run_cli(
                home, "maintenance", "automation", "status"
            )
            result, payload = run_cli(
                home,
                "maintenance",
                *cycle_arguments(missing_primary, missing_secondary),
            )

            self.assertEqual(status_result.returncode, 1)
            self.assertEqual(status["status"], "stale")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["sync"]["reason_code"], "python-runtime-unavailable")
            self.assertEqual(payload["analysis_status"], "not-run")
            self.assertIsNone(payload["report_id"])

    def test_sync_blocked_and_no_findings_never_read_analyzer_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            seed(home, [event(1), event(2)])
            missing_remote = root / "missing" / "private.git"
            authorize(home, missing_remote)
            missing_primary = root / "must-not-be-read-primary.json"
            missing_secondary = root / "must-not-be-read-secondary.json"

            blocked_result, blocked = run_cli(
                home,
                "maintenance",
                *cycle_arguments(missing_primary, missing_secondary),
            )

            self.assertEqual(blocked_result.returncode, 2)
            self.assertEqual(blocked["status"], "sync-blocked")
            self.assertEqual(blocked["analysis_status"], "not-run")
            self.assertIsNone(blocked["report_id"])

            remote = root / "private.git"
            self.assertEqual(git("init", "--bare", str(remote)).returncode, 0)
            authorize(home, remote)
            no_findings_result, no_findings = run_cli(
                home,
                "maintenance",
                *cycle_arguments(missing_primary, missing_secondary),
            )
            self.assertEqual(no_findings_result.returncode, 0, no_findings_result.stderr)
            self.assertEqual(no_findings["status"], "no-findings")
            self.assertEqual(no_findings["finding_count"], 0)
            self.assertEqual(no_findings["analysis_status"], "not-run")
            self.assertEqual(list((usage_state_root(home) / "reports").rglob("*.json")), [])

    def test_finding_runs_serial_analysis_once_and_writes_private_terminal_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            events = [event(index) for index in range(1, 6)]
            events[-1]["peak_rss_mb"] = {
                "availability": "available",
                "source": "launcher",
                "value": 640,
            }
            seed(home, events)
            remote = root / "private.git"
            self.assertEqual(git("init", "--bare", str(remote)).returncode, 0)
            authorize(home, remote)
            primary = root / "primary.json"
            secondary = root / "secondary.json"
            semantic(primary, "Primary bounded cause.")
            semantic(secondary, "Independent bounded cause.")
            before_public = tree_hash(REPO_ROOT)

            first_result, first = run_cli(
                home, "maintenance", *cycle_arguments(primary, secondary)
            )
            second_result, second = run_cli(
                home, "maintenance", *cycle_arguments(primary, secondary)
            )

            self.assertEqual(first_result.returncode, 0, first_result.stderr or first_result.stdout)
            self.assertEqual(first["status"], "completed")
            self.assertEqual(first["analysis_status"], "completed")
            self.assertEqual(first["attempt"], 1)
            self.assertRegex(first["report_id"], r"^report-[a-f0-9]{16}$")
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(second["report_id"], first["report_id"])

            reports = usage_state_root(home) / "reports" / "2026"
            json_reports = list(reports.glob("*.json"))
            markdown_reports = list(reports.glob("*.md"))
            self.assertEqual(len(json_reports), 1)
            self.assertEqual(len(markdown_reports), 1)
            report = json.loads(json_reports[0].read_text(encoding="utf-8"))
            schemas = {
                path.name: json.loads(path.read_text(encoding="utf-8"))
                for path in SCHEMA_ROOT.glob("*.json")
            }
            registry = Registry().with_resources(
                (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
            )
            errors = list(
                Draft202012Validator(
                    schemas["maintenance-report.schema.json"],
                    registry=registry,
                    format_checker=FormatChecker(),
                ).iter_errors(report)
            )
            self.assertEqual(errors, [], [error.message for error in errors])
            self.assertEqual(
                [row["platform"] for row in report["analysis"]["analyzer_sequence"]],
                ["codex", "claude"],
            )
            private_text = json_reports[0].read_text() + markdown_reports[0].read_text()
            self.assertNotIn(str(home), private_text)
            self.assertNotIn(str(remote), private_text)
            self.assertEqual(tree_hash(REPO_ROOT), before_public)

    def test_notification_payload_is_fixed_and_contains_no_report_content(self) -> None:
        module = (REPO_ROOT / "lib" / "usage" / "maintenance-report.mjs").as_uri()
        canary = "CANARY_PRIVATE_ANALYSIS_TEXT"
        script = (
            f'import {{ maintenanceNotification }} from {json.dumps(module)};'
            f"console.log(JSON.stringify(maintenanceNotification('completed', {json.dumps(canary)})));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(canary, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["title"], "OpenAPI Engineering maintenance")
        self.assertEqual(payload["message"], "Unattended analysis completed. Open the private report.")

    def test_report_rejects_secret_canary_before_rendering(self) -> None:
        module = (REPO_ROOT / "lib" / "usage" / "maintenance-report.mjs").as_uri()
        with tempfile.TemporaryDirectory() as directory:
            state_root = Path(directory)
            value = {
                "cycle_id": "cycle-" + "1" * 16,
                "status": "completed",
                "period_id": "2026-W29",
                "input_sha256": "2" * 64,
                "authorization_sha256": "3" * 64,
                "attempt": 1,
                "started_at": "2026-07-19T18:00:00Z",
                "finished_at": "2026-07-19T18:00:01Z",
                "finding_ids": ["finding-" + "4" * 16],
                "analysis": {
                    "confidence": 0.9,
                    "candidate_causes": ["CANARY_PRIVATE_TOKEN_123456789"],
                    "unverified": [],
                    "analyzer_sequence": [{"platform": "codex", "status": "passed"}],
                },
                "reason_code": None,
            }
            script = (
                f'import {{ writeMaintenanceReport }} from {json.dumps(module)};'
                f"const value={json.dumps(value)};"
                f"const result=await writeMaintenanceReport({{stateRoot:{json.dumps(str(state_root))},"
                f"reportsRoot:{json.dumps(str(state_root / 'reports'))},value}});"
                "console.log(JSON.stringify(result.report));"
            )
            result = subprocess.run(
                ["node", "--input-type=module", "--eval", script],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("CANARY_PRIVATE_TOKEN_123456789", result.stdout)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["reason_code"], "report-invalid")
            self.assertIsNone(report["analysis"])

    def test_failed_analysis_retries_once_then_reports_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            events = [event(index) for index in range(1, 6)]
            events[-1]["peak_rss_mb"] = {
                "availability": "available",
                "source": "launcher",
                "value": 640,
            }
            seed(home, events)
            remote = root / "private.git"
            self.assertEqual(git("init", "--bare", str(remote)).returncode, 0)
            authorize(home, remote)
            invalid = root / "invalid.json"
            invalid.write_text("{}", encoding="utf-8")
            arguments = cycle_arguments(invalid, invalid)

            first_result, first = run_cli(home, "maintenance", *arguments)
            second_result, second = run_cli(home, "maintenance", *arguments)
            third_result, third = run_cli(home, "maintenance", *arguments)

            self.assertEqual(first_result.returncode, 1)
            self.assertEqual(first["status"], "failed")
            self.assertEqual(first["attempt"], 1)
            self.assertIsNone(first["report_id"])
            self.assertEqual(second_result.returncode, 1)
            self.assertEqual(second["status"], "retry-exhausted")
            self.assertEqual(second["attempt"], 2)
            self.assertRegex(second["report_id"], r"^report-[a-f0-9]{16}$")
            self.assertEqual(third_result.returncode, 0)
            self.assertEqual(third["status"], "duplicate")
            self.assertEqual(third["report_id"], second["report_id"])


if __name__ == "__main__":
    unittest.main()
