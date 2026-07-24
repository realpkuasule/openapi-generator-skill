from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.support import REPO_ROOT
from tests.test_maintenance_analysis import finding, sanitized_event


SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "analyze_usage.py"
SCHEMA = json.loads(
    (REPO_ROOT / "contracts" / "schemas" / "maintenance-analysis.schema.json").read_text(
        encoding="utf-8"
    )
)


def semantic(cause: str, *, confidence: float = 0.9) -> dict:
    return {
        "clusters": [
            {
                "key": "resource-regression",
                "finding_ids": ["finding-0123456789abcdef"],
            }
        ],
        "confidence": confidence,
        "candidate_causes": [cause],
        "unverified": [],
    }


def run_review(
    root: Path,
    finding_value: dict,
    primary: dict,
    *,
    secondary: dict | None,
    secondary_adapter: str = "fake",
) -> tuple[subprocess.CompletedProcess[str], dict, Path]:
    bundle = root / "bundle.json"
    primary_path = root / "primary.json"
    secondary_path = root / "secondary.json"
    output = root / "analysis.json"
    bundle.write_text(
        json.dumps(
            {"findings": [finding_value], "sanitized_events": [sanitized_event(1)]}
        ),
        encoding="utf-8",
    )
    primary_path.write_text(json.dumps(primary), encoding="utf-8")
    if secondary is not None:
        secondary_path.write_text(json.dumps(secondary), encoding="utf-8")
    command = [
        sys.executable,
        str(SCRIPT),
        "--findings",
        str(bundle),
        "--adapter",
        "fake",
        "--fake-platform",
        "codex",
        "--fake-response",
        str(primary_path),
        "--secondary-adapter",
        secondary_adapter,
        "--secondary-fake-platform",
        "claude",
        "--secondary-fake-response",
        str(secondary_path),
        "--output",
        str(output),
        "--now",
        "2026-07-19T12:00:00Z",
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, json.loads(result.stdout) if result.stdout else {}, output


class MaintenanceSecondaryReviewTests(unittest.TestCase):
    def test_low_risk_high_confidence_primary_does_not_read_or_run_secondary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            low_risk = finding()
            low_risk["severity"] = "P2"
            low_risk["requires_secondary_review"] = False

            result, payload, output = run_review(
                root,
                low_risk,
                semantic("Primary cause."),
                secondary=None,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertEqual([row["platform"] for row in payload["analyzer_sequence"]], ["codex"])
            self.assertEqual(payload["secondary_review"]["status"], "not-required")
            self.assertEqual(payload["secondary_review"]["trigger_reasons"], [])

    def test_p1_finding_runs_codex_then_independent_claude_and_preserves_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result, payload, _output = run_review(
                root,
                finding(),
                semantic("Primary cause."),
                secondary=semantic("Independent cause.", confidence=0.8),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            errors = list(
                Draft202012Validator(
                    SCHEMA, format_checker=FormatChecker()
                ).iter_errors(payload)
            )
            self.assertEqual(errors, [], [error.message for error in errors])
            self.assertEqual(
                [row["platform"] for row in payload["analyzer_sequence"]],
                ["codex", "claude"],
            )
            review = payload["secondary_review"]
            self.assertEqual(review["status"], "passed")
            self.assertTrue(review["independent"])
            self.assertIn("severity-p0-p1", review["trigger_reasons"])
            self.assertIn("candidate-causes", review["disagreements"])
            self.assertEqual(payload["candidate_causes"], ["Primary cause."])
            self.assertEqual(review["result"]["candidate_causes"], ["Independent cause."])

    def test_low_confidence_triggers_review_and_unavailable_review_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            low_risk = finding()
            low_risk["severity"] = "P2"
            low_risk["requires_secondary_review"] = False

            result, payload, output = run_review(
                root,
                low_risk,
                semantic("Uncertain cause.", confidence=0.4),
                secondary=None,
                secondary_adapter="none",
            )

            self.assertEqual(result.returncode, 2)
            self.assertTrue(output.is_file())
            self.assertEqual(payload["candidate_causes"], ["Uncertain cause."])
            self.assertEqual(payload["secondary_review"]["status"], "blocked")
            self.assertIn("low-confidence", payload["secondary_review"]["trigger_reasons"])
            self.assertEqual(len(payload["analyzer_sequence"]), 1)

    def test_malformed_secondary_preserves_primary_as_failed_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result, payload, output = run_review(
                root,
                finding(),
                semantic("Primary remains authoritative."),
                secondary={"unexpected": True},
            )

            self.assertEqual(result.returncode, 2)
            self.assertTrue(output.is_file())
            self.assertEqual(payload["candidate_causes"], ["Primary remains authoritative."])
            self.assertEqual(payload["secondary_review"]["status"], "failed")
            self.assertEqual(payload["secondary_review"]["result"], None)
            self.assertEqual(payload["analyzer_sequence"][-1]["platform"], "claude")
            self.assertEqual(payload["analyzer_sequence"][-1]["status"], "failed")
            self.assertEqual(
                payload["analyzer_sequence"][-1]["failure_code"], "invalid-output"
            )
            self.assertEqual(
                payload["analyzer_sequence"][-1]["resources"]["measurement_status"],
                "not-run",
            )


if __name__ == "__main__":
    unittest.main()
