from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.evals.load_cases import load_cases
from tests.support import REPO_ROOT


EVAL_ROOT = REPO_ROOT / "skills" / "openapi-engineering-maintainer" / "evals"
SKILL_ROOT = REPO_ROOT / "skills" / "openapi-engineering-maintainer"
EXPECTED = {
    "maintainer-ordinary-handoff",
    "maintainer-risk-secondary-review",
    "maintainer-privacy-boundary",
    "maintainer-promotion-approval",
}


class MaintainerEvalTests(unittest.TestCase):
    def test_four_maintainer_cases_validate_and_cover_required_safety_scenarios(self) -> None:
        cases = {item["id"]: item for item in load_cases(EVAL_ROOT)}

        self.assertEqual(set(cases), EXPECTED)
        combined = json.dumps(cases, ensure_ascii=False).casefold()
        for phrase in (
            "ordinary openapi",
            "secondary review",
            "sanitized",
            "exact digest",
            "public source",
        ):
            self.assertIn(phrase, combined)
        for case in cases.values():
            self.assertEqual(
                len(case["input"]["interview_answers"]),
                case["expected"]["minimum_interview_turns"],
            )

    def test_eval_runner_accepts_explicit_maintainer_roots_without_invoking_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "maintainer-dry-run.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "run_skill_evals.py"),
                    "--adapter",
                    "fake",
                    "--dry-run",
                    "--eval-root",
                    str(EVAL_ROOT),
                    "--skill-root",
                    str(SKILL_ROOT),
                    "--report",
                    str(report),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(set(payload["case_ids"]), EXPECTED)
        self.assertEqual(payload["requested_results"], 4)


if __name__ == "__main__":
    unittest.main()
