from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_usage_summary import event, run_usage, seed


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class UsageDueTests(unittest.TestCase):
    def test_non_coordinator_is_blocked_without_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            run_usage(home, "enable", "--device", "m2", "--apply")
            state = home / ".local" / "state" / "openapi-engineering-skill"
            before = tree_hash(state)

            result, payload = run_usage(home, "due", "--now", "2026-07-19T18:00:00Z")

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(tree_hash(state), before)

    def test_no_findings_checkpoint_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            state = seed(home, [event(1), event(2)])

            first_result, first = run_usage(
                home, "due", "--now", "2026-07-19T18:00:00Z"
            )
            after_first = tree_hash(state)
            second_result, second = run_usage(
                home, "due", "--now", "2026-07-19T20:00:00Z"
            )

            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(first["status"], "no-findings")
            self.assertFalse(first["eligible_for_analysis"])
            self.assertEqual(first["finding_count"], 0)
            self.assertEqual(second["status"], "not-due")
            self.assertEqual(second["input_sha256"], first["input_sha256"])
            self.assertEqual(tree_hash(state), after_first)
            self.assertTrue((state / "summaries" / "2026" / "2026-W29.json").is_file())
            self.assertTrue((state / "findings" / "2026" / "2026-W29.json").is_file())

    def test_finding_is_eligible_once_and_later_input_does_not_rerun_week(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            events = [event(index) for index in range(1, 6)]
            events[-1]["peak_rss_mb"] = {
                "availability": "available",
                "source": "launcher",
                "value": 513,
            }
            state = seed(home, events)

            first_result, first = run_usage(
                home, "due", "--now", "2026-07-19T18:00:00Z"
            )
            event_path = state / "local" / "events" / "m4" / "2026-07.jsonl"
            with event_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event(6, recorded_at="2026-07-19T19:00:00Z")) + "\n")
            second_result, second = run_usage(
                home, "due", "--now", "2026-07-19T20:00:00Z"
            )

            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(first["status"], "due")
            self.assertTrue(first["eligible_for_analysis"])
            self.assertEqual(first["finding_count"], 1)
            self.assertEqual(first["findings"][0]["rule_id"], "SI-RESOURCE-001")
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(second["status"], "not-due")
            self.assertEqual(second["input_sha256"], first["input_sha256"])


if __name__ == "__main__":
    unittest.main()
