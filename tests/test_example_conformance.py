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
            inspection = json.loads((output / "inspect-response.json").read_text())
            comparison = json.loads(
                (output / "generation-comparison-response.json").read_text()
            )
            empirical = json.loads(
                (output / "empirical-gate-response.json").read_text()
            )
            self.assertEqual(inspection["root"], "/workspace/project")
            self.assertEqual(sum(comparison["summary"].values()), len(comparison["files"]))
            self.assertEqual(empirical["status"], "proposed")
            self.assertEqual(
                empirical["unverified"],
                [gate["name"] for gate in empirical["gates"]],
            )

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
