from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT


CLI = REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"


def run_usage(home: Path, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        ["node", str(CLI), "usage", *arguments, "--home", str(home), "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, json.loads(result.stdout) if result.stdout else {}


def event(index: int, **overrides) -> dict:
    value = {
        "schema_version": 1,
        "event_id": f"evt-{index:016x}",
        "session_id": f"ses-{index:016x}",
        "recorded_at": f"2026-07-{14 + index:02d}T12:00:00Z",
        "device_alias": "m4",
        "skill_version": "0.1.0-rc.2",
        "skill_sha256": "a" * 64,
        "platform": "codex",
        "platform_version": None,
        "capture_mode": "best-effort",
        "anonymous_project_id": "b" * 64,
        "project_alias": "fixture",
        "lifecycle_modes": ["governance-hardening"],
        "tool_strategy": "governance-only",
        "outcome": "passed",
        "interview_turns": 4,
        "boundary_revisions": 0,
        "tool_overridden": False,
        "gates": {"passed": 1, "failed": 0, "unverified": 0},
        "duration_ms": {"availability": "unavailable", "source": "best-effort"},
        "peak_rss_mb": {"availability": "unavailable", "source": "best-effort"},
        "exit_code": {"availability": "unavailable", "source": "best-effort"},
        "termination_reason": "not-reported",
        "feedback_status": "unknown",
        "safety_violation": False,
        "resource_anomaly": False,
        "platform_drift": False,
        "incident_ids": [],
    }
    value.update(overrides)
    return value


def seed(home: Path, events: list[dict], feedback: list[dict] | None = None) -> Path:
    run_usage(home, "enable", "--device", "m4", "--coordinator", "--apply")
    state = home / ".local" / "state" / "openapi-engineering-skill"
    event_path = state / "local" / "events" / "m4" / "2026-07.jsonl"
    event_path.parent.mkdir(parents=True)
    event_path.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
    if feedback:
        feedback_path = state / "feedback" / "m4" / "2026-07.jsonl"
        feedback_path.parent.mkdir(parents=True)
        feedback_path.write_text(
            "".join(json.dumps(item) + "\n" for item in feedback), encoding="utf-8"
        )
    return state


class UsageSummaryTests(unittest.TestCase):
    def test_weekly_summary_is_deterministic_and_reports_data_completeness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            events = [
                event(1),
                event(
                    2,
                    peak_rss_mb={"availability": "available", "source": "launcher", "value": 256},
                    duration_ms={"availability": "available", "source": "launcher", "value": 900},
                ),
            ]
            seed(home, events)

            first_result, first = run_usage(
                home, "summarize", "--period", "iso-week", "--now", "2026-07-19T18:00:00Z"
            )
            second_result, second = run_usage(
                home, "summarize", "--period", "iso-week", "--now", "2026-07-19T18:00:00Z"
            )

            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(first, second)
            self.assertEqual(first["period_id"], "2026-W29")
            self.assertEqual(first["sample_count"], 2)
            self.assertEqual(first["metrics"]["peak_rss_max_mb"], 256)
            self.assertEqual(first["data_completeness"], {
                "available_measurements": 2,
                "unavailable_measurements": 2,
            })

    def test_empty_summary_does_not_invoke_or_invent_findings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            seed(home, [])

            result, payload = run_usage(
                home, "summarize", "--period", "iso-week", "--now", "2026-07-19T18:00:00Z"
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["sample_count"], 0)
            self.assertEqual(payload["triggered_rule_ids"], [])
            self.assertIsNone(payload["metrics"]["tool_override_ratio"])
            self.assertIsNone(payload["metrics"]["unverified_ratio"])


if __name__ == "__main__":
    unittest.main()
