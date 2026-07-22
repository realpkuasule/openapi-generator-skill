from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker, RefResolver

from tests.support import REPO_ROOT


SCRIPT = REPO_ROOT / "scripts" / "check_self_improvement_traceability.py"
MANIFEST = REPO_ROOT / "contracts" / "self-improvement-acceptance-traceability.yaml"
SCHEMA = (
    REPO_ROOT
    / "contracts"
    / "schemas"
    / "self-improvement-traceability.schema.json"
)
COMPLETION_SCHEMA = REPO_ROOT / "contracts" / "schemas" / "completion-report.schema.json"


def run_traceability(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def write_manifest(path: Path, mutate) -> None:
    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class SelfImprovementTraceabilityTests(unittest.TestCase):
    def test_all_twenty_four_are_loaded_enforced_and_freshly_executed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            result = run_traceability("--manifest", str(MANIFEST), "--report", str(report))

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "passed")
            self.assertTrue(payload["acceptance_complete"])
            self.assertEqual(
                [row["id"] for row in payload["requirements"]],
                [f"SI-AC-{index:02d}" for index in range(1, 25)],
            )
            self.assertTrue(
                all(
                    row["configured"] and row["loaded"] and row["enforced"] and row["passing"]
                    for row in payload["requirements"]
                )
            )
            self.assertEqual(
                {row["computed_status"] for row in payload["requirements"]},
                {"passed"},
            )
            self.assertEqual(json.loads(report.read_text(encoding="utf-8")), payload)

            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            completion = json.loads(COMPLETION_SCHEMA.read_text(encoding="utf-8"))
            resolver = RefResolver(
                base_uri=SCHEMA.resolve().as_uri(),
                referrer=schema,
                store={completion["$id"]: completion},
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                errors = list(
                    Draft202012Validator(
                        schema,
                        resolver=resolver,
                        format_checker=FormatChecker(),
                    ).iter_errors(payload)
                )
            self.assertEqual(errors, [], [error.message for error in errors])

    def test_missing_contract_or_test_selector_is_a_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.yaml"

            def mutate(payload):
                payload["requirements"][0]["contracts"] = ["contracts/missing.json"]
                payload["requirements"][1]["tests"] = [
                    "tests.test_usage_config.UsageConfigTests.test_missing_gate"
                ]

            write_manifest(manifest, mutate)
            result = run_traceability(
                "--manifest", str(manifest), "--report", str(root / "report.json")
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertFalse(payload["requirements"][0]["loaded"])
            self.assertFalse(payload["requirements"][1]["enforced"])

    def test_blocked_declaration_never_counts_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.yaml"
            write_manifest(
                manifest,
                lambda payload: payload["requirements"][10].update(status="blocked"),
            )

            result = run_traceability(
                "--manifest", str(manifest), "--report", str(root / "report.json")
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["requirements"][10]["computed_status"], "blocked")

    def test_check_report_rejects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            created = run_traceability(
                "--manifest", str(MANIFEST), "--report", str(report)
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            checked = run_traceability(
                "--manifest", str(MANIFEST), "--check-report", str(report)
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["requirements"][0]["passing"] = False
            report.write_text(json.dumps(payload), encoding="utf-8")
            tampered = run_traceability(
                "--manifest", str(MANIFEST), "--check-report", str(report)
            )
            self.assertEqual(tampered.returncode, 1)


if __name__ == "__main__":
    unittest.main()
