from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from scripts import verify
from tests.support import REPO_ROOT


REPORT_SCHEMA = REPO_ROOT / "contracts" / "schemas" / "verification-report.schema.json"


class VerifyRunnerTests(unittest.TestCase):
    def test_failed_required_gate_makes_report_failed_and_exit_one(self) -> None:
        gate = verify.Gate("failing", ["fixture-command", "--check"])
        completed = subprocess.CompletedProcess(gate.command, 7, "out", "err")
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.verify.subprocess.run", return_value=completed
        ):
            report, exit_code = verify.run_verification(
                "deterministic", Path(directory) / "report.json", gates=[gate]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["gates"][0]["status"], "failed")
        self.assertEqual(report["gates"][0]["exit_code"], 7)

    def test_missing_required_validator_is_blocked_and_exit_two(self) -> None:
        gate = verify.Gate(
            "missing-validator",
            ["fixture-command"],
            required_paths=[Path("/definitely/missing/quick_validate.py")],
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.verify.subprocess.run"
        ) as run:
            report, exit_code = verify.run_verification(
                "deterministic", Path(directory) / "report.json", gates=[gate]
            )

        run.assert_not_called()
        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"][0]["status"], "blocked")
        self.assertIsNone(report["gates"][0]["exit_code"])

    def test_passed_report_conforms_to_schema_and_records_evidence_digest(self) -> None:
        gate = verify.Gate("passing", ["fixture-command", "--check"])
        completed = subprocess.CompletedProcess(gate.command, 0, "ok\n", "")
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.verify.subprocess.run", return_value=completed
        ) as run:
            report_path = Path(directory) / "report.json"
            report, exit_code = verify.run_verification(
                "deterministic", report_path, gates=[gate]
            )

            persisted = json.loads(report_path.read_text(encoding="utf-8"))
            evidence = Path(report["gates"][0]["evidence"])
            self.assertTrue(evidence.is_file())
            self.assertRegex(report["gates"][0]["evidence_sha256"], r"^[a-f0-9]{64}$")

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report, persisted)
        schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
        errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report)
        )
        self.assertEqual(errors, [], [error.message for error in errors])
        _, kwargs = run.call_args
        self.assertFalse(kwargs.get("shell", False))

    def test_forward_tier_is_blocked_without_combined_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report, exit_code = verify.run_verification(
                "forward", Path(directory) / "report.json"
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["gates"][0]["status"], "blocked")

    def test_forward_tier_validates_existing_report_without_invoking_models(self) -> None:
        completed = subprocess.CompletedProcess(
            ["fixture-forward-check"], 0, "passed\n", ""
        )
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.verify.subprocess.run", return_value=completed
        ) as run:
            forward_report = Path(directory) / "forward.json"
            forward_report.write_text("{}", encoding="utf-8")
            report, exit_code = verify.run_verification(
                "forward",
                Path(directory) / "verification.json",
                forward_report=forward_report,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "passed")
        command = run.call_args.args[0]
        self.assertIn("--check-report", command)
        self.assertNotIn("run_skill_evals.py", " ".join(command))

    def test_previous_gate_logs_are_removed_before_a_new_run(self) -> None:
        gate = verify.Gate("passing", ["fixture-command"])
        completed = subprocess.CompletedProcess(gate.command, 0, "ok\n", "")
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.verify.subprocess.run", return_value=completed
        ):
            report_path = Path(directory) / "report.json"
            evidence_dir = Path(directory) / "report-evidence"
            evidence_dir.mkdir()
            stale = evidence_dir / "99-stale.log"
            stale.write_text("obsolete\n", encoding="utf-8")

            verify.run_verification("deterministic", report_path, gates=[gate])

            self.assertFalse(stale.exists())

    def test_full_tier_is_blocked_until_every_release_evidence_path_is_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report, exit_code = verify.run_verification(
                "full", Path(directory) / "report.json"
            )

        self.assertEqual(exit_code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("release evidence", report["gates"][0]["risk"])

    def test_full_evidence_gates_only_check_existing_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / f"evidence-{index}.json" for index in range(6)]
            for path in paths:
                path.write_text("{}", encoding="utf-8")

            gates = verify.full_evidence_gates(
                forward_report=paths[0],
                empirical_manifest=paths[1],
                empirical_report=paths[2],
                upgrade_manifest=paths[3],
                upgrade_report=paths[4],
                traceability_report=paths[5],
            )

        self.assertEqual(
            [gate.name for gate in gates],
            [
                "combined-forward-report",
                "empirical-adoption-report",
                "empirical-upgrade-report",
                "acceptance-traceability-report",
            ],
        )
        commands = "\n".join(" ".join(gate.command) for gate in gates)
        self.assertEqual(commands.count("--check-report"), 4)
        self.assertNotIn("run_skill_evals.py", commands)
        self.assertNotIn("--execute", commands)

    def test_junit_output_records_each_gate_without_command_output(self) -> None:
        gate = verify.Gate("passing", ["fixture-command"])
        completed = subprocess.CompletedProcess(gate.command, 0, "secret output", "")
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.verify.subprocess.run", return_value=completed
        ):
            root = Path(directory)
            junit = root / "verification.xml"
            report, exit_code = verify.run_verification(
                "deterministic",
                root / "report.json",
                gates=[gate],
                junit_path=junit,
            )
            suite = ET.parse(junit).getroot()

        self.assertEqual(exit_code, 0)
        self.assertEqual(int(suite.attrib["tests"]), len(report["gates"]))
        self.assertNotIn("secret output", ET.tostring(suite, encoding="unicode"))


if __name__ == "__main__":
    unittest.main()
