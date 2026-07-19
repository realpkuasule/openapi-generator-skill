from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, snapshot_tree, usage_config_path, usage_state_root
from tests.test_usage_git_sync import configure, git, show
from tests.test_usage_recording import record, write_report


ANALYZE = REPO_ROOT / "scripts" / "maintenance" / "analyze_usage.py"
PROPOSE = REPO_ROOT / "scripts" / "maintenance" / "build_proposal.py"
SKILL_ROOT = REPO_ROOT / "skills" / "openapi-engineering"
PROTECTED = (
    REPO_ROOT / "bin",
    REPO_ROOT / "contracts",
    REPO_ROOT / "lib",
    REPO_ROOT / "packaging",
    REPO_ROOT / "scripts",
    REPO_ROOT / "skills",
)


def protected_snapshot() -> dict[str, str]:
    result: dict[str, str] = {}
    for root in PROTECTED:
        for name, digest in snapshot_tree(root).items():
            if "__pycache__" in Path(name).parts or name.endswith(".pyc"):
                continue
            result[f"{root.name}/{name}"] = digest
    for path in (REPO_ROOT / "package.json",):
        result[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def python_json(script: Path, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, json.loads(result.stdout) if result.stdout else {}


class SelfImprovementE2ETests(unittest.TestCase):
    def test_opt_in_to_private_proposal_is_offline_reproducible_and_source_read_only(self) -> None:
        before = protected_snapshot()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            home.mkdir()
            remote = root / "private.git"
            self.assertEqual(git("init", "--bare", str(remote)).returncode, 0)
            configure(home, remote, "m4", coordinator=True)

            completion = home / "completion.json"
            write_report(completion)
            recorded_result, recorded = record(
                home,
                completion,
                "ses-00000000000000e2",
                "--peak-rss-mb",
                "640",
            )
            self.assertEqual(recorded_result.returncode, 0, recorded_result.stderr)
            self.assertTrue(recorded["recorded"])
            outbound_dir = usage_state_root(home) / "outbound" / "m4"
            envelope = json.loads(next(outbound_dir.glob("*.json")).read_text(encoding="utf-8"))
            self.assertNotIn("project_alias", envelope["payload"])

            from tests.test_usage_summary import run_usage

            sync_result, sync = run_usage(home, "sync")
            self.assertEqual(sync_result.returncode, 0, sync_result.stderr)
            self.assertEqual(sync["synchronized"], 1)
            remote_events = [
                json.loads(line)
                for line in show(remote, "events/m4/2026-07.jsonl").splitlines()
            ]
            self.assertEqual(remote_events, [envelope["payload"]])

            due_result, due = run_usage(home, "due", "--now", "2026-07-19T18:00:00Z")
            self.assertEqual(due_result.returncode, 0, due_result.stderr)
            self.assertEqual(due["status"], "due")
            self.assertEqual(due["findings"][0]["rule_id"], "SI-RESOURCE-001")

            bundle = root / "finding-bundle.json"
            fake = root / "fake-analysis.json"
            analysis = root / "private" / "analysis.json"
            bundle.write_text(
                json.dumps(
                    {
                        "findings": due["findings"],
                        "sanitized_events": remote_events,
                    }
                ),
                encoding="utf-8",
            )
            finding_id = due["findings"][0]["finding_id"]
            fake.write_text(
                json.dumps(
                    {
                        "clusters": [
                            {"key": "resource-regression", "finding_ids": [finding_id]}
                        ],
                        "confidence": 0.9,
                        "candidate_causes": ["Strict launcher evidence should be added."],
                        "unverified": ["No strict launcher sample is available."],
                    }
                ),
                encoding="utf-8",
            )
            analyzed_result, analyzed = python_json(
                ANALYZE,
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
                str(analysis),
                "--now",
                "2026-07-19T18:05:00Z",
            )
            self.assertEqual(analyzed_result.returncode, 0, analyzed_result.stderr)
            self.assertEqual(analyzed["finding_ids"], [finding_id])

            candidate_root = root / "candidate-root"
            candidate_root.mkdir()
            candidate = root / "candidate.json"
            proposal = root / "private" / "proposal.json"
            candidate.write_text(
                json.dumps(
                    {
                        "candidate_id": "candidate-00000000000000e2",
                        "contract_impact": "compatible",
                        "target_files": ["tests/test_usage_resource_regression.py"],
                        "artifacts": [
                            {
                                "kind": "failing-test",
                                "path": "tests/test_usage_resource_regression.py",
                                "media_type": "text/x-python",
                                "content": "def test_approved_candidate_remains_red():\n    assert False\n",
                            }
                        ],
                        "open_questions": [],
                        "failing_tests": ["tests/test_usage_resource_regression.py"],
                        "verification": ["Observe RED before implementation."],
                        "rollback": ["Remove only the digest-matched candidate test."],
                    }
                ),
                encoding="utf-8",
            )
            config = usage_config_path(home)
            proposed_result, proposed = python_json(
                PROPOSE,
                "--analysis",
                str(analysis),
                "--candidate",
                str(candidate),
                "--target-root",
                str(candidate_root),
                "--skill-root",
                str(SKILL_ROOT),
                "--skill-version",
                "0.1.0-rc.2",
                "--config-sha256",
                hashlib.sha256(config.read_bytes()).hexdigest(),
                "--output",
                str(proposal),
                "--now",
                "2026-07-19T18:10:00Z",
            )
            self.assertEqual(proposed_result.returncode, 0, proposed_result.stderr)
            self.assertEqual(proposed, json.loads(proposal.read_text(encoding="utf-8")))
            self.assertRegex(proposed["approval_sha256"], r"^[a-f0-9]{64}$")
            self.assertFalse((candidate_root / "tests" / "test_usage_resource_regression.py").exists())

        self.assertEqual(protected_snapshot(), before)


if __name__ == "__main__":
    unittest.main()
