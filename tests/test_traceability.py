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


SCRIPT = REPO_ROOT / "scripts" / "check_traceability.py"
MANIFEST = REPO_ROOT / "contracts" / "acceptance-traceability.yaml"
SCHEMA = REPO_ROOT / "contracts" / "schemas" / "acceptance-traceability.schema.json"
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


class TraceabilityTests(unittest.TestCase):
    def test_all_twelve_requirements_have_machine_passing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            result = run_traceability(
                "--manifest", str(MANIFEST), "--report", str(report_path)
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(
                [row["id"] for row in payload["requirements"]],
                [f"AC-{index:02d}" for index in range(1, 13)],
            )
            self.assertEqual(
                {row["computed_status"] for row in payload["requirements"]},
                {"passed"},
            )
            self.assertEqual(payload["completion_report"]["unverified"], [])
            self.assertEqual(json.loads(report_path.read_text()), payload)

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

    def test_missing_evidence_cannot_be_counted_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.yaml"
            write_manifest(
                manifest,
                lambda payload: payload["requirements"][6]["evidence"][0].update(
                    path="docs/verifications/p2-20260715/missing.json"
                ),
            )

            result = run_traceability(
                "--manifest", str(manifest), "--report", str(root / "report.json")
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            ac07 = next(row for row in payload["requirements"] if row["id"] == "AC-07")
            self.assertEqual(ac07["computed_status"], "failed")
            self.assertTrue(ac07["reasons"])

    def test_static_only_declaration_and_fake_forward_evidence_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.yaml"

            def mutate(payload):
                payload["requirements"][11]["status"] = "static-only"
                payload["requirements"][4]["evidence"][0]["path"] = (
                    "docs/verifications/p1-20260714/deterministic-report-final.json"
                )

            write_manifest(manifest, mutate)
            result = run_traceability(
                "--manifest", str(manifest), "--report", str(root / "report.json")
            )

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            statuses = {row["id"]: row["computed_status"] for row in payload["requirements"]}
            self.assertEqual(statuses["AC-05"], "failed")
            self.assertEqual(statuses["AC-12"], "failed")

    def test_check_report_rejects_stale_or_tampered_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            created = run_traceability(
                "--manifest", str(MANIFEST), "--report", str(report)
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)

            checked = run_traceability(
                "--manifest", str(MANIFEST), "--check-report", str(report)
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

            payload = json.loads(report.read_text(encoding="utf-8"))
            payload["requirements"][0]["computed_status"] = "failed"
            report.write_text(json.dumps(payload), encoding="utf-8")
            tampered = run_traceability(
                "--manifest", str(MANIFEST), "--check-report", str(report)
            )
            self.assertEqual(tampered.returncode, 1)


if __name__ == "__main__":
    unittest.main()
