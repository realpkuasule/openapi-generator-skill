from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.support import usage_state_root
from tests.test_usage_git_sync import configure, git, record_one
from tests.test_usage_recording import run_usage


def canonical_sha256(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class UsageMultideviceTests(unittest.TestCase):
    def test_offline_collectors_replay_and_m4_aggregates_all_owned_partitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "private.git"
            self.assertEqual(git("init", "--bare", str(remote)).returncode, 0)

            m2 = root / "m2-home"
            mbp = root / "mbp-home"
            m4 = root / "m4-home"
            for home in (m2, mbp, m4):
                home.mkdir()
            configure(m2, remote, "m2")
            configure(mbp, remote, "mbp14")
            configure(m4, remote, "m4", coordinator=True)

            record_one(m2, 0x21)
            record_one(m2, 0x22)
            record_one(mbp, 0x31)
            record_one(m4, 0x41)
            mbp_sync, _ = run_usage(mbp, "sync")
            m2_sync, _ = run_usage(m2, "sync")
            m4_sync, _ = run_usage(m4, "sync")
            self.assertEqual(mbp_sync.returncode, 0, mbp_sync.stderr)
            self.assertEqual(m2_sync.returncode, 0, m2_sync.stderr)
            self.assertEqual(m4_sync.returncode, 0, m4_sync.stderr)

            repeated, repeated_payload = run_usage(m4, "sync")
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(repeated_payload["synchronized"], 0)

            due_result, due = run_usage(
                m4, "due", "--now", "2026-07-19T18:00:00Z"
            )
            self.assertEqual(due_result.returncode, 0, due_result.stderr)
            self.assertEqual(due["summary"]["sample_count"], 4)
            self.assertEqual(due["summary"]["device_count"], 3)
            aggregate = usage_state_root(m4) / "aggregate" / "events.json"
            self.assertTrue(aggregate.is_file())
            self.assertEqual(len(json.loads(aggregate.read_text(encoding="utf-8"))), 4)

    def test_collector_cannot_forge_coordinator_aggregate_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "private.git"
            git("init", "--bare", str(remote))
            m2 = root / "m2-home"
            m2.mkdir()
            configure(m2, remote, "m2")
            summary = json.loads(
                (
                    Path(__file__).resolve().parents[1]
                    / "contracts"
                    / "examples"
                    / "usage-summary-response.json"
                ).read_text(encoding="utf-8")
            )
            envelope = {
                "envelope_version": 1,
                "kind": "usage-summary",
                "payload_sha256": canonical_sha256(summary),
                "payload": summary,
            }
            outbound = usage_state_root(m2) / "outbound" / "m2"
            outbound.mkdir(parents=True)
            queued = outbound / "forged-summary.json"
            queued.write_text(json.dumps(envelope), encoding="utf-8")

            result, payload = run_usage(m2, "sync")

            self.assertEqual(result.returncode, 1)
            self.assertEqual(payload["status"], "blocked")
            self.assertTrue(queued.is_file())
            self.assertEqual(git("--git-dir", str(remote), "show-ref").stdout, "")

    def test_due_checkpoint_rebuilds_missing_outbound_without_reanalysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "private.git"
            git("init", "--bare", str(remote))
            m4 = root / "m4-home"
            m4.mkdir()
            configure(m4, remote, "m4", coordinator=True)
            record_one(m4, 0x51)
            first, first_payload = run_usage(
                m4, "due", "--now", "2026-07-19T18:00:00Z"
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            outbound = usage_state_root(m4) / "outbound" / "m4"
            for path in outbound.glob("summary-*.json"):
                path.unlink()
            for path in outbound.glob("findings-*.json"):
                path.unlink()

            replay, replay_payload = run_usage(
                m4, "due", "--now", "2026-07-19T20:00:00Z"
            )

            self.assertEqual(replay.returncode, 0, replay.stderr)
            self.assertEqual(replay_payload["status"], "not-due")
            self.assertEqual(replay_payload["input_sha256"], first_payload["input_sha256"])
            self.assertEqual(
                {path.name for path in outbound.glob("*.json") if path.name.startswith(("summary-", "findings-"))},
                {"summary-2026-W29.json", "findings-2026-W29.json"},
            )


if __name__ == "__main__":
    unittest.main()
