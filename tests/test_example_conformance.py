from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.capture_contract_examples import write_text
from tests.support import REPO_ROOT


CAPTURE_SCRIPT = REPO_ROOT / "scripts" / "capture_contract_examples.py"


class ExampleCaptureTests(unittest.TestCase):
    def test_fixture_writer_uses_platform_independent_lf_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "fixture.txt"

            write_text(target, "first\nsecond\n")

            self.assertEqual(target.read_bytes(), b"first\nsecond\n")

    def test_capture_generates_reachable_examples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(CAPTURE_SCRIPT), "--output-dir", directory],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = Path(directory)
            for example in output.glob("*.json"):
                with self.subTest(example=example.name):
                    self.assertNotIn(b"\r\n", example.read_bytes())
            inspection = json.loads((output / "inspect-response.json").read_text())
            comparison = json.loads(
                (output / "generation-comparison-response.json").read_text()
            )
            empirical = json.loads(
                (output / "empirical-gate-response.json").read_text()
            )
            usage_status = json.loads(
                (output / "usage-status-response.json").read_text()
            )
            usage_record = json.loads(
                (output / "usage-record-response.json").read_text()
            )
            usage_summary = json.loads(
                (output / "usage-summary-response.json").read_text()
            )
            usage_due = json.loads(
                (output / "usage-due-response.json").read_text()
            )
            usage_trend = json.loads(
                (output / "usage-trend-response.json").read_text()
            )
            maintenance_finding = json.loads(
                (output / "maintenance-finding-response.json").read_text()
            )
            maintenance_proposal = json.loads(
                (output / "maintenance-proposal-response.json").read_text()
            )
            maintenance_promotion = json.loads(
                (output / "maintenance-promotion-response.json").read_text()
            )
            self.assertEqual(inspection["root"], "/workspace/project")
            self.assertEqual(sum(comparison["summary"].values()), len(comparison["files"]))
            self.assertEqual(empirical["status"], "proposed")
            self.assertEqual(
                empirical["unverified"],
                [gate["name"] for gate in empirical["gates"]],
            )
            self.assertFalse(usage_status["config"]["local_collection_enabled"])
            self.assertTrue(usage_record["recorded"])
            self.assertEqual(usage_summary["period_id"], "2026-W29")
            self.assertEqual(usage_due["findings"], [maintenance_finding])
            self.assertEqual(usage_trend["comparison"]["status"], "insufficient")
            self.assertRegex(maintenance_proposal["approval_sha256"], r"^[a-f0-9]{64}$")
            self.assertEqual(maintenance_promotion["action"], "would-promote")
            self.assertFalse(maintenance_promotion["applied"])

    def test_checked_in_examples_match_capture(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CAPTURE_SCRIPT), "--check"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
