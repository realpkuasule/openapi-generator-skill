from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT
from tests.test_maintenance_analysis import finding, sanitized_event


CLI = REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"


def run_maintenance(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["OPENAPI_ENGINEERING_PYTHON"] = sys.executable
    return subprocess.run(
        ["node", str(CLI), "maintenance", *arguments],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


class MaintenanceCliTests(unittest.TestCase):
    def test_all_contract_commands_have_delegated_help_without_shell(self) -> None:
        for command in ("analyze", "propose", "promote"):
            with self.subTest(command=command):
                result = run_maintenance(command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout.lower())
        source = CLI.read_text(encoding="utf-8")
        self.assertNotIn("shell: true", source)

        analyze_help = run_maintenance("analyze", "--help")
        self.assertIn("--credential-mode", analyze_help.stdout)
        self.assertIn("--resume-analysis", analyze_help.stdout)

    def test_analyze_command_preserves_script_json_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle.json"
            fake = root / "fake.json"
            output = root / "analysis.json"
            bundle.write_text(
                json.dumps(
                    {"findings": [finding()], "sanitized_events": [sanitized_event(1)]}
                ),
                encoding="utf-8",
            )
            fake.write_text(
                json.dumps(
                    {
                        "clusters": [
                            {
                                "key": "resource-regression",
                                "finding_ids": ["finding-0123456789abcdef"],
                            }
                        ],
                        "confidence": 0.9,
                        "candidate_causes": ["Bounded fixture."],
                        "unverified": [],
                    }
                ),
                encoding="utf-8",
            )

            result = run_maintenance(
                "analyze",
                "--findings",
                str(bundle),
                "--adapter",
                "fake",
                "--fake-response",
                str(fake),
                "--fake-platform",
                "codex",
                "--secondary-adapter",
                "fake",
                "--secondary-fake-response",
                str(fake),
                "--secondary-fake-platform",
                "claude",
                "--output",
                str(output),
                "--now",
                "2026-07-19T12:00:00Z",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(output.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
