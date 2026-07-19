from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.support import REPO_ROOT
from tests.test_usage_summary import event, run_usage, seed


SCHEMA = json.loads(
    (REPO_ROOT / "contracts" / "schemas" / "usage-trend.schema.json").read_text(
        encoding="utf-8"
    )
)


def trend(home: Path, *, fix_at: str | None = None) -> tuple[object, dict]:
    arguments = ["trends", "--now", "2026-07-20T12:00:00Z"]
    if fix_at is not None:
        arguments.extend(["--fix-at", fix_at])
    return run_usage(home, *arguments)


def timeline(before_bad: bool, after_bad: bool) -> list[dict]:
    values = []
    for index in range(1, 6):
        values.append(
            event(
                index,
                recorded_at=f"2026-06-{10 + index:02d}T12:00:00Z",
                outcome="failed" if before_bad else "passed",
                gates={"passed": 0 if before_bad else 1, "failed": 1 if before_bad else 0, "unverified": 1 if before_bad else 0},
                tool_overridden=before_bad,
                skill_version="0.1.0-rc.1",
            )
        )
    for index in range(6, 11):
        values.append(
            event(
                index,
                recorded_at=f"2026-07-{index:02d}T12:00:00Z",
                outcome="failed" if after_bad else "passed",
                gates={"passed": 0 if after_bad else 1, "failed": 1 if after_bad else 0, "unverified": 1 if after_bad else 0},
                tool_overridden=after_bad,
                skill_version="0.1.0-rc.2",
            )
        )
    return values


class UsageTrendTests(unittest.TestCase):
    def test_fix_boundary_reports_improvement_and_version_segments_from_facts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            seed(home, timeline(before_bad=True, after_bad=False))

            result, payload = trend(home, fix_at="2026-06-20T00:00:00Z")

            self.assertEqual(result.returncode, 0, result.stderr)
            errors = list(
                Draft202012Validator(
                    SCHEMA, format_checker=FormatChecker()
                ).iter_errors(payload)
            )
            self.assertEqual(errors, [], [error.message for error in errors])
            self.assertEqual(payload["comparison_basis"], "fix-boundary")
            self.assertEqual(payload["comparison"]["status"], "improved")
            self.assertLess(payload["comparison"]["friction_score_delta"], 0)
            self.assertEqual(
                payload["version_segments"],
                [
                    {"skill_version": "0.1.0-rc.1", "sample_count": 5},
                    {"skill_version": "0.1.0-rc.2", "sample_count": 5},
                ],
            )

    def test_worsening_and_insufficient_samples_are_not_misreported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            seed(home, timeline(before_bad=False, after_bad=True))
            result, worsened = trend(home, fix_at="2026-06-20T00:00:00Z")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(worsened["comparison"]["status"], "worsened")

        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            seed(home, timeline(before_bad=True, after_bad=False)[:2])
            result, insufficient = trend(home, fix_at="2026-06-20T00:00:00Z")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(insufficient["comparison"]["status"], "insufficient")
            self.assertIsNone(insufficient["comparison"]["friction_score_delta"])

    def test_resolved_incident_recurrence_is_deterministic_and_order_independent(self) -> None:
        incident_id = "inc-0123456789abcdef"
        values = timeline(before_bad=True, after_bad=False)
        values[-1]["incident_ids"] = [incident_id]
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first_home = Path(first_dir)
            second_home = Path(second_dir)
            first_state = seed(first_home, values)
            second_state = seed(second_home, list(reversed(values)))
            for state in (first_state, second_state):
                incident_path = state / "incidents" / "resolved.json"
                incident_path.parent.mkdir(parents=True)
                incident_path.write_text(
                    json.dumps({"incident_ids": [incident_id]}), encoding="utf-8"
                )

            first_result, first = trend(first_home, fix_at="2026-06-20T00:00:00Z")
            second_result, second = trend(second_home, fix_at="2026-06-20T00:00:00Z")

            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(first, second)
            self.assertEqual(first["regressions"][0]["rule_id"], "SI-REGRESSION-001")
            self.assertEqual(first["regressions"][0]["incident_id"], incident_id)
            self.assertEqual(first["regressions"][0]["event_ids"], [values[-1]["event_id"]])

    def test_conflicting_duplicate_event_ids_are_rejected_in_every_arrival_order(self) -> None:
        first = event(1, recorded_at="2026-07-10T12:00:00Z")
        conflicting = event(
            1,
            recorded_at="2026-07-10T12:00:00Z",
            outcome="failed",
            gates={"passed": 0, "failed": 1, "unverified": 1},
        )
        for values in ([first, conflicting], [conflicting, first]):
            with self.subTest(outcome=values[0]["outcome"]), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                seed(home, values)
                result, payload = trend(home)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(payload["status"], "error")
                self.assertIn("duplicate", payload["error"].lower())


if __name__ == "__main__":
    unittest.main()
