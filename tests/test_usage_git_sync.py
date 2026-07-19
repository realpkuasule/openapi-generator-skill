from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import usage_state_root
from tests.test_usage_recording import record, run_usage, write_report


def git(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def configure(home: Path, remote: Path, device: str, coordinator: bool = False) -> None:
    enable = ["enable", "--device", device]
    if coordinator:
        enable.append("--coordinator")
    enable.append("--apply")
    result, _ = run_usage(home, *enable)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    result, _ = run_usage(
        home,
        "sync",
        "configure",
        "--remote",
        str(remote),
        "--branch",
        "usage",
        "--apply",
        "--now",
        "2026-07-19T12:00:00Z",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)


def record_one(home: Path, index: int) -> None:
    report = home / "completion.json"
    write_report(report)
    result, _ = record(home, report, f"ses-{index:016x}")
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)


def show(remote: Path, path: str) -> str:
    result = git("--git-dir", str(remote), "show", f"usage:{path}")
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout


class UsageGitSyncTests(unittest.TestCase):
    def test_due_queues_and_syncs_coordinator_aggregate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "private.git"
            self.assertEqual(git("init", "--bare", str(remote)).returncode, 0)
            home = root / "m4-home"
            home.mkdir()
            configure(home, remote, "m4", coordinator=True)
            report = home / "completion.json"
            write_report(report)
            recorded, _ = record(
                home,
                report,
                "ses-00000000000000a1",
                "--peak-rss-mb",
                "640",
            )
            self.assertEqual(recorded.returncode, 0, recorded.stderr)
            first_sync, _ = run_usage(home, "sync")
            self.assertEqual(first_sync.returncode, 0, first_sync.stderr)

            due_result, due = run_usage(
                home, "due", "--now", "2026-07-19T18:00:00Z"
            )
            self.assertEqual(due_result.returncode, 0, due_result.stderr)
            outbound = usage_state_root(home) / "outbound" / "m4"
            self.assertEqual(
                {path.name for path in outbound.glob("*.json")},
                {"summary-2026-W29.json", "findings-2026-W29.json"},
            )

            sync_result, sync = run_usage(home, "sync")

            self.assertEqual(sync_result.returncode, 0, sync_result.stderr)
            self.assertEqual(sync["synchronized"], 2)
            self.assertEqual(
                json.loads(show(remote, "summaries/2026/2026-W29.json")),
                due["summary"],
            )
            self.assertEqual(
                json.loads(show(remote, "findings/2026/2026-W29.json")),
                due["findings"],
            )

    def test_sync_pushes_sanitized_event_and_clears_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "private.git"
            self.assertEqual(git("init", "--bare", str(remote)).returncode, 0)
            home = root / "m4-home"
            home.mkdir()
            configure(home, remote, "m4", coordinator=True)
            record_one(home, 1)

            result, payload = run_usage(home, "sync")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["synchronized"], 1)
            self.assertEqual(payload["pending"], 0)
            self.assertRegex(payload["commit"], r"^[a-f0-9]{40,64}$")
            rows = [json.loads(line) for line in show(remote, "events/m4/2026-07.jsonl").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertNotIn("project_alias", rows[0])
            outbound = usage_state_root(home) / "outbound" / "m4"
            self.assertEqual(list(outbound.glob("*.json")), [])

    def test_multiple_devices_append_only_to_owned_partitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "private.git"
            git("init", "--bare", str(remote))
            for index, device in enumerate(("m2", "mbp14", "m4"), start=1):
                home = root / f"{device}-home"
                home.mkdir()
                configure(home, remote, device, coordinator=device == "m4")
                record_one(home, index)
                result, _ = run_usage(home, "sync")
                self.assertEqual(result.returncode, 0, result.stderr)

            for device in ("m2", "mbp14", "m4"):
                rows = show(remote, f"events/{device}/2026-07.jsonl").splitlines()
                self.assertEqual(len(rows), 1)
                self.assertEqual(json.loads(rows[0])["device_alias"], device)

    def test_tampered_digest_blocks_sync_and_preserves_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "private.git"
            git("init", "--bare", str(remote))
            home = root / "home"
            home.mkdir()
            configure(home, remote, "m4", coordinator=True)
            record_one(home, 4)
            outbound = usage_state_root(home) / "outbound" / "m4"
            queued = next(outbound.glob("*.json"))
            envelope = json.loads(queued.read_text(encoding="utf-8"))
            envelope["payload_sha256"] = "0" * 64
            queued.write_text(json.dumps(envelope), encoding="utf-8")

            result, payload = run_usage(home, "sync")

            self.assertEqual(result.returncode, 1)
            self.assertEqual(payload["status"], "blocked")
            self.assertTrue(queued.is_file())
            self.assertEqual(git("--git-dir", str(remote), "show-ref").stdout, "")

    def test_remote_failure_never_drops_outbound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "missing" / "private.git"
            home = root / "home"
            home.mkdir()
            configure(home, remote, "m4", coordinator=True)
            record_one(home, 5)
            outbound = usage_state_root(home) / "outbound" / "m4"
            before = {path.name for path in outbound.glob("*.json")}

            result, payload = run_usage(home, "sync")

            self.assertEqual(result.returncode, 1)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual({path.name for path in outbound.glob("*.json")}, before)


if __name__ == "__main__":
    unittest.main()
