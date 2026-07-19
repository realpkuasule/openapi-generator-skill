from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.support import REPO_ROOT
from tests.test_usage_summary import event


SCRIPT = REPO_ROOT / "scripts" / "maintenance" / "analyze_usage.py"
ANALYSIS_SCHEMA = json.loads(
    (REPO_ROOT / "contracts" / "schemas" / "maintenance-analysis.schema.json").read_text(
        encoding="utf-8"
    )
)


def sanitized_event(index: int) -> dict:
    value = event(index)
    for field in ("platform_version", "project_alias", "incident_ids"):
        value.pop(field)
    return value


def finding() -> dict:
    return {
        "schema_version": 1,
        "finding_id": "finding-0123456789abcdef",
        "rule_id": "SI-RESOURCE-001",
        "threshold_version": 1,
        "period_id": "2026-W29",
        "input_sha256": "a" * 64,
        "observed": {
            "metric": "peak_rss_mb",
            "value": 640,
            "comparator": ">",
            "threshold": 512,
            "sample_count": 5,
            "window_days": 30,
        },
        "severity": "P1",
        "requires_secondary_review": True,
        "status": "open",
    }


def run_analysis(bundle: Path, fake: Path, output: Path):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--findings",
            str(bundle),
            "--adapter",
            "fake",
            "--fake-response",
            str(fake),
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
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class MaintenanceAnalysisTests(unittest.TestCase):
    def test_fake_analysis_is_schema_valid_and_secondary_review_remains_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle.json"
            fake = root / "fake.json"
            output = root / "analysis.json"
            bundle.write_text(
                json.dumps({"findings": [finding()], "sanitized_events": [sanitized_event(1)]}),
                encoding="utf-8",
            )
            fake.write_text(
                json.dumps(
                    {
                        "clusters": [
                            {"key": "resource-regression", "finding_ids": ["finding-0123456789abcdef"]}
                        ],
                        "confidence": 0.8,
                        "candidate_causes": ["Resource watcher baseline may be stale."],
                        "unverified": ["No strict launcher sample is attached."],
                    }
                ),
                encoding="utf-8",
            )

            result = run_analysis(bundle, fake, output)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload, json.loads(output.read_text(encoding="utf-8")))
            errors = list(
                Draft202012Validator(
                    ANALYSIS_SCHEMA, format_checker=FormatChecker()
                ).iter_errors(payload)
            )
            self.assertEqual(errors, [], [error.message for error in errors])
            self.assertEqual(payload["primary"]["platform"], "fake")
            self.assertEqual(payload["secondary_review"]["status"], "passed")
            self.assertEqual(
                [row["platform"] for row in payload["analyzer_sequence"]],
                ["fake", "claude"],
            )
            self.assertRegex(payload["input_sha256"], r"^[a-f0-9]{64}$")

    def test_more_than_fifty_events_is_blocked_before_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle.json"
            fake = root / "fake.json"
            output = root / "analysis.json"
            bundle.write_text(
                json.dumps(
                    {
                        "findings": [finding()],
                        "sanitized_events": [sanitized_event(index) for index in range(1, 52)],
                    }
                ),
                encoding="utf-8",
            )
            fake.write_text("{}", encoding="utf-8")

            result = run_analysis(bundle, fake, output)

            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())
            self.assertEqual(json.loads(result.stdout)["status"], "blocked")

    def test_local_fields_and_malformed_adapter_output_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle.json"
            fake = root / "fake.json"
            output = root / "analysis.json"
            unsafe = sanitized_event(1)
            unsafe["project_alias"] = "private-project"
            bundle.write_text(
                json.dumps({"findings": [finding()], "sanitized_events": [unsafe]}),
                encoding="utf-8",
            )
            fake.write_text("{}", encoding="utf-8")
            blocked = run_analysis(bundle, fake, output)
            self.assertEqual(blocked.returncode, 2)
            self.assertFalse(output.exists())

            bundle.write_text(
                json.dumps({"findings": [finding()], "sanitized_events": [sanitized_event(1)]}),
                encoding="utf-8",
            )
            failed = run_analysis(bundle, fake, output)
            self.assertEqual(failed.returncode, 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
