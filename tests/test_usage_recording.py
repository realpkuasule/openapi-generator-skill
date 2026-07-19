from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, snapshot_tree


CLI = REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"


def run_usage(home: Path, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        ["node", str(CLI), "usage", *arguments, "--home", str(home), "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(result.stdout) if result.stdout else {}
    return result, payload


def write_report(path: Path, *, outcome: str = "passed", unverified: list[str] | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "outcome": outcome,
                "changed_files": [],
                "commands": ["tool --token CANARY_RAW_COMMAND_SECRET"],
                "results": ["contract gate passed"],
                "unverified": unverified or [],
                "risks": [],
                "rollback": [],
                "profile_changes": [],
            }
        ),
        encoding="utf-8",
    )


def record(home: Path, report: Path, session: str, *extra: str):
    return run_usage(
        home,
        "record",
        "--completion-report",
        str(report),
        "--capture-mode",
        "best-effort",
        "--platform",
        "codex",
        "--project-alias",
        "animator",
        "--session",
        session,
        "--lifecycle",
        "governance-hardening",
        "--tool-strategy",
        "governance-only",
        "--interview-turns",
        "4",
        "--boundary-revisions",
        "0",
        "--now",
        "2026-07-19T12:00:00Z",
        *extra,
    )


class UsageRecordingTests(unittest.TestCase):
    def test_disabled_record_is_a_zero_write_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            report = home / "completion.json"
            write_report(report)
            before = snapshot_tree(home)

            result, payload = record(home, report, "ses-0000000000000001")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "disabled")
            self.assertFalse(payload["recorded"])
            self.assertIsNone(payload["event"])
            self.assertEqual(snapshot_tree(home), before)

    def test_record_writes_local_event_and_rebuilt_sanitized_outbound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            report = home / "completion.json"
            write_report(report)
            run_usage(home, "enable", "--device", "m4", "--coordinator", "--apply")

            result, payload = record(home, report, "ses-0000000000000002")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(payload["recorded"])
            self.assertTrue(payload["outbound_queued"])
            self.assertEqual(payload["event"]["project_alias"], "animator")
            self.assertEqual(payload["event"]["duration_ms"]["availability"], "unavailable")

            state = home / ".local" / "state" / "openapi-engineering-skill"
            event_file = state / "local" / "events" / "m4" / "2026-07.jsonl"
            outbound_files = list((state / "outbound" / "m4").glob("*.json"))
            self.assertTrue(event_file.is_file())
            self.assertEqual(len(outbound_files), 1)
            local_event = json.loads(event_file.read_text(encoding="utf-8").strip())
            outbound = json.loads(outbound_files[0].read_text(encoding="utf-8"))
            self.assertEqual(local_event, payload["event"])
            self.assertNotIn("project_alias", outbound)
            self.assertNotIn("platform_version", outbound)
            self.assertNotIn("incident_ids", outbound)

            state_text = "\n".join(
                path.read_text(encoding="utf-8", errors="ignore")
                for path in state.rglob("*")
                if path.is_file()
            )
            self.assertNotIn("CANARY_RAW_COMMAND_SECRET", state_text)

    def test_normal_success_samples_every_fifth_event_and_anomalies_always_ask(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            report = home / "completion.json"
            write_report(report)
            run_usage(home, "enable", "--device", "m4", "--apply")

            required = []
            for index in range(1, 6):
                result, payload = record(home, report, f"ses-{index:016x}")
                self.assertEqual(result.returncode, 0, result.stderr)
                required.append(payload["feedback_required"])
            self.assertEqual(required, [False, False, False, False, True])

            write_report(report, outcome="failed")
            result, failed = record(home, report, "ses-0000000000000006")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(failed["feedback_required"])

            write_report(report, unverified=["live model not run"])
            result, unverified = record(home, report, "ses-0000000000000007")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(unverified["feedback_required"])

    def test_repeated_session_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            report = home / "completion.json"
            write_report(report)
            run_usage(home, "enable", "--device", "m4", "--apply")

            first_result, first = record(home, report, "ses-0000000000000008")
            second_result, second = record(home, report, "ses-0000000000000008")

            self.assertEqual(first_result.returncode, 0, first_result.stderr)
            self.assertEqual(second_result.returncode, 0, second_result.stderr)
            self.assertEqual(second["status"], "duplicate")
            self.assertFalse(second["recorded"])
            self.assertEqual(second["event"], first["event"])
            state = home / ".local" / "state" / "openapi-engineering-skill"
            lines = (state / "local" / "events" / "m4" / "2026-07.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(len(list((state / "outbound" / "m4").glob("*.json"))), 1)

    def test_feedback_is_append_only_and_note_never_enters_outbound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            report = home / "completion.json"
            write_report(report, outcome="failed")
            run_usage(home, "enable", "--device", "m4", "--apply")
            record(home, report, "ses-0000000000000009")

            result, payload = run_usage(
                home,
                "feedback",
                "--session",
                "ses-0000000000000009",
                "--rating",
                "friction",
                "--tag",
                "too-many-questions",
                "--note",
                "Interview was longer than needed",
                "--now",
                "2026-07-19T12:05:00Z",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["rating"], "friction")
            self.assertEqual(payload["note"], "Interview was longer than needed")
            state = home / ".local" / "state" / "openapi-engineering-skill"
            feedback_file = state / "feedback" / "m4" / "2026-07.jsonl"
            self.assertTrue(feedback_file.is_file())
            outbound = json.loads(
                next((state / "outbound" / "m4").glob("feedback-*.json")).read_text(
                    encoding="utf-8"
                )
            )
            self.assertNotIn("note", outbound)

            duplicate, duplicate_payload = run_usage(
                home,
                "feedback",
                "--session",
                "ses-0000000000000009",
                "--rating",
                "met",
            )
            self.assertEqual(duplicate.returncode, 1)
            self.assertEqual(duplicate_payload["status"], "error")
            self.assertEqual(len(feedback_file.read_text(encoding="utf-8").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
