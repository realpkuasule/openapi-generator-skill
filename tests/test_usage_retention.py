from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.support import REPO_ROOT, snapshot_tree, usage_state_root
from tests.test_usage_recording import run_usage
from tests.test_usage_summary import event
from tests.test_usage_git_sync import configure, git, show


SCHEMA = json.loads(
    (REPO_ROOT / "contracts" / "schemas" / "retention-plan.schema.json").read_text(
        encoding="utf-8"
    )
)


def sanitized(value: dict) -> dict:
    result = dict(value)
    for field in ("platform_version", "project_alias", "incident_ids"):
        result.pop(field)
    return result


def feedback(index: int, recorded_at: str) -> dict:
    return {
        "schema_version": 1,
        "feedback_id": f"fb-{index:016x}",
        "event_id": f"evt-{index:016x}",
        "recorded_at": recorded_at,
        "device_alias": "m4",
        "rating": "met",
        "friction_tags": [],
        "feedback_status": "answered",
        "note": None,
    }


def seed_remote(root: Path, remote: Path) -> Path:
    worktree = root / "seed"
    worktree.mkdir()
    git("init", cwd=worktree)
    git("checkout", "-b", "usage", cwd=worktree)
    git("config", "user.name", "Fixture", cwd=worktree)
    git("config", "user.email", "fixture@localhost", cwd=worktree)
    git("remote", "add", "origin", str(remote), cwd=worktree)
    old = sanitized(event(10, recorded_at="2025-07-18T23:59:59Z", device_alias="m2"))
    boundary = sanitized(event(11, recorded_at="2025-07-19T00:00:00Z", device_alias="m2"))
    event_path = worktree / "events" / "m2" / "2025-07.jsonl"
    event_path.parent.mkdir(parents=True)
    event_path.write_text(json.dumps(old) + "\n" + json.dumps(boundary) + "\n", encoding="utf-8")
    for path in (
        worktree / "summaries" / "2025" / "2025-W29.json",
        worktree / "promoted" / "candidate-keep" / "eval.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"keep":true}\n', encoding="utf-8")
    git("add", "--all", cwd=worktree)
    git("commit", "-m", "seed retention fixture", cwd=worktree)
    git("push", "origin", "HEAD:refs/heads/usage", cwd=worktree)
    return worktree


class UsageRetentionTests(unittest.TestCase):
    def seed(self, home: Path) -> tuple[Path, tuple[Path, ...]]:
        run_usage(home, "enable", "--device", "m4", "--coordinator", "--apply")
        state = usage_state_root(home)
        events = state / "local" / "events" / "m4" / "2026-04.jsonl"
        feedback_path = state / "feedback" / "m4" / "2026-04.jsonl"
        events.parent.mkdir(parents=True)
        feedback_path.parent.mkdir(parents=True)
        old_event = event(1, recorded_at="2026-04-19T23:59:59Z")
        boundary_event = event(2, recorded_at="2026-04-20T00:00:00Z")
        events.write_text(
            json.dumps(old_event) + "\n" + json.dumps(boundary_event) + "\n",
            encoding="utf-8",
        )
        feedback_path.write_text(
            json.dumps(feedback(1, "2026-04-19T23:59:59Z"))
            + "\n"
            + json.dumps(feedback(2, "2026-04-20T00:00:00Z"))
            + "\n",
            encoding="utf-8",
        )
        aggregate = state / "aggregate" / "events.json"
        aggregate.parent.mkdir(parents=True)
        aggregate.write_text(
            json.dumps(
                [
                    sanitized(event(3, recorded_at="2025-07-18T23:59:59Z")),
                    sanitized(event(4, recorded_at="2025-07-19T00:00:00Z")),
                ]
            ),
            encoding="utf-8",
        )
        durable = (
            state / "summaries" / "2026" / "2026-W29.json",
            state / "proposals" / "candidate-keep.json",
            state / "promoted" / "candidate-keep" / "eval.json",
            state / "holds" / "legal-hold.json",
        )
        for path in durable:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("keep\n", encoding="utf-8")
        return state, durable

    def test_cleanup_is_read_only_until_exact_plan_digest_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            state, durable = self.seed(home)
            before = snapshot_tree(state)

            planned, plan = run_usage(
                home, "cleanup", "--now", "2026-07-19T00:00:00Z"
            )

            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertFalse(plan["applied"])
            self.assertEqual(snapshot_tree(state), before)
            self.assertEqual(sum(item["delete_count"] for item in plan["items"]), 3)
            errors = list(
                Draft202012Validator(
                    SCHEMA, format_checker=FormatChecker()
                ).iter_errors(plan)
            )
            self.assertEqual(errors, [], [error.message for error in errors])

            rejected, rejected_payload = run_usage(
                home, "cleanup", "--now", "2026-07-19T00:00:00Z", "--apply"
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(rejected_payload["status"], "error")
            self.assertEqual(snapshot_tree(state), before)

            applied, report = run_usage(
                home,
                "cleanup",
                "--now",
                "2026-07-19T00:00:00Z",
                "--approve",
                plan["plan_sha256"],
                "--apply",
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertTrue(report["applied"])
            local_rows = (
                state / "local" / "events" / "m4" / "2026-04.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(local_rows), 1)
            self.assertEqual(json.loads(local_rows[0])["recorded_at"], "2026-04-20T00:00:00Z")
            aggregate_rows = json.loads(
                (state / "aggregate" / "events.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(aggregate_rows), 1)
            self.assertEqual(aggregate_rows[0]["recorded_at"], "2025-07-19T00:00:00Z")
            for path in durable:
                self.assertEqual(path.read_text(encoding="utf-8"), "keep\n")

            stale, stale_payload = run_usage(
                home,
                "cleanup",
                "--now",
                "2026-07-19T00:00:00Z",
                "--approve",
                plan["plan_sha256"],
                "--apply",
            )
            self.assertEqual(stale.returncode, 1)
            self.assertEqual(stale_payload["status"], "conflict")

    @unittest.skipIf(os.name == "nt", "symlink behavior is platform-specific")
    def test_symlinked_retention_target_is_blocked_without_external_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            run_usage(home, "enable", "--device", "m4", "--apply")
            state = usage_state_root(home)
            external = root / "external"
            external.mkdir()
            marker = external / "events.jsonl"
            marker.write_text("external\n", encoding="utf-8")
            (state / "local").mkdir(parents=True)
            (state / "local" / "events").symlink_to(external, target_is_directory=True)

            result, payload = run_usage(
                home, "cleanup", "--now", "2026-07-19T00:00:00Z", "--apply", "--approve", "a" * 64
            )

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(marker.read_text(encoding="utf-8"), "external\n")

    def test_remote_cleanup_deletes_only_expired_event_rows_and_preserves_durable_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "private.git"
            git("init", "--bare", str(remote))
            seed_remote(root, remote)
            home = root / "home"
            home.mkdir()
            configure(home, remote, "m4", coordinator=True)

            planned, plan = run_usage(
                home,
                "cleanup",
                "--scope",
                "remote",
                "--now",
                "2026-07-19T00:00:00Z",
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(plan["scope"], "remote")
            self.assertEqual(sum(item["delete_count"] for item in plan["items"]), 1)

            applied, report = run_usage(
                home,
                "cleanup",
                "--scope",
                "remote",
                "--now",
                "2026-07-19T00:00:00Z",
                "--approve",
                plan["plan_sha256"],
                "--apply",
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertTrue(report["applied"])
            rows = [
                json.loads(line)
                for line in show(remote, "events/m2/2025-07.jsonl").splitlines()
            ]
            self.assertEqual([row["recorded_at"] for row in rows], ["2025-07-19T00:00:00Z"])
            self.assertEqual(
                json.loads(show(remote, "summaries/2025/2025-W29.json")),
                {"keep": True},
            )
            self.assertEqual(
                json.loads(show(remote, "promoted/candidate-keep/eval.json")),
                {"keep": True},
            )

    def test_remote_head_advance_invalidates_old_cleanup_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "private.git"
            git("init", "--bare", str(remote))
            worktree = seed_remote(root, remote)
            home = root / "home"
            home.mkdir()
            configure(home, remote, "m4", coordinator=True)
            planned, plan = run_usage(
                home, "cleanup", "--scope", "remote", "--now", "2026-07-19T00:00:00Z"
            )
            self.assertEqual(planned.returncode, 0, planned.stderr)
            (worktree / "metadata.txt").write_text("remote advanced\n", encoding="utf-8")
            git("add", "metadata.txt", cwd=worktree)
            git("commit", "-m", "advance remote", cwd=worktree)
            git("push", "origin", "HEAD:refs/heads/usage", cwd=worktree)

            result, payload = run_usage(
                home,
                "cleanup",
                "--scope",
                "remote",
                "--now",
                "2026-07-19T00:00:00Z",
                "--approve",
                plan["plan_sha256"],
                "--apply",
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(payload["status"], "conflict")
            self.assertEqual(
                len(show(remote, "events/m2/2025-07.jsonl").splitlines()),
                2,
            )


if __name__ == "__main__":
    unittest.main()
