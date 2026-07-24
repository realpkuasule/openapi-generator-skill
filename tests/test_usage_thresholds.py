from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support import usage_state_root
from tests.test_usage_summary import event, run_usage, seed


def summarize(home: Path) -> list[str]:
    result, payload = run_usage(
        home, "summarize", "--period", "iso-week", "--now", "2026-07-19T18:00:00Z"
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return payload["triggered_rule_ids"]


class UsageThresholdTests(unittest.TestCase):
    def test_ratio_rules_are_strictly_above_twenty_percent_with_five_samples(self) -> None:
        for field, rule in (
            ("tool_overridden", "SI-OVERRIDE-001"),
            ("unverified", "SI-UNVERIFIED-001"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                events = [event(index) for index in range(1, 6)]
                if field == "tool_overridden":
                    events[0]["tool_overridden"] = True
                else:
                    events[0]["gates"]["unverified"] = 1
                seed(home, events)
                self.assertNotIn(rule, summarize(home))

                if field == "tool_overridden":
                    events[1]["tool_overridden"] = True
                else:
                    events[1]["gates"]["unverified"] = 1
                state = usage_state_root(home)
                path = state / "local" / "events" / "m4" / "2026-07.jsonl"
                path.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
                self.assertIn(rule, summarize(home))

    def test_interview_and_resource_boundaries_are_strict(self) -> None:
        cases = (
            ([event(i, interview_turns=5) for i in range(1, 6)], "SI-INTERVIEW-001", False),
            ([event(i, interview_turns=6) for i in range(1, 6)], "SI-INTERVIEW-001", True),
            ([event(i, interview_turns=8 if i == 5 else 4) for i in range(1, 6)], "SI-INTERVIEW-001", False),
            ([event(i, interview_turns=9 if i == 5 else 4) for i in range(1, 6)], "SI-INTERVIEW-001", True),
            ([event(1, peak_rss_mb={"availability": "available", "source": "launcher", "value": 512})], "SI-RESOURCE-001", False),
            ([event(1, peak_rss_mb={"availability": "available", "source": "launcher", "value": 513})], "SI-RESOURCE-001", True),
        )
        for index, (events, rule, expected) in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                seed(home, events)
                self.assertEqual(rule in summarize(home), expected)

    def test_immediate_friction_and_regression_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            events = [
                event(1, safety_violation=True),
                event(2, platform_drift=True),
                event(3, incident_ids=["inc-0123456789abcdef"]),
            ]
            feedback = [
                {
                    "schema_version": 1,
                    "feedback_id": f"fb-{index:016x}",
                    "event_id": events[min(index - 1, 2)]["event_id"],
                    "recorded_at": f"2026-07-{15 + index:02d}T12:00:00Z",
                    "device_alias": "m4",
                    "rating": "friction",
                    "friction_tags": ["too-many-questions"],
                    "note": None,
                    "feedback_status": "answered",
                }
                for index in range(1, 4)
            ]
            state = seed(home, events, feedback)
            (state / "incidents").mkdir(parents=True)
            (state / "incidents" / "resolved.json").write_text(
                json.dumps({"incident_ids": ["inc-0123456789abcdef"]}), encoding="utf-8"
            )

            rules = set(summarize(home))

            self.assertTrue(
                {
                    "SI-SAFETY-001",
                    "SI-PLATFORM-001",
                    "SI-FRICTION-001",
                    "SI-REGRESSION-001",
                }.issubset(rules)
            )


if __name__ == "__main__":
    unittest.main()
