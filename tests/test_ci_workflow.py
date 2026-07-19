from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from tests.support import REPO_ROOT


WORKFLOW = REPO_ROOT / ".github" / "workflows" / "verify.yml"


class CiWorkflowTests(unittest.TestCase):
    def test_locked_deterministic_matrix_covers_all_supported_runner_families(self) -> None:
        payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        matrix = payload["jobs"]["deterministic"]["strategy"]["matrix"]["os"]
        self.assertEqual(
            set(matrix), {"ubuntu-latest", "macos-latest", "windows-latest"}
        )
        steps = payload["jobs"]["deterministic"]["steps"]
        commands = "\n".join(str(step.get("run", "")) for step in steps)
        self.assertIn("uv sync --locked", commands)
        self.assertIn("scripts/verify.py --tier deterministic", commands)
        uses = {step.get("uses") for step in steps}
        self.assertIn("actions/setup-node@v4", uses)
        self.assertEqual(payload["permissions"], {"contents": "read"})

    def test_live_forward_and_release_gates_are_manual_and_never_pr_side_effects(self) -> None:
        payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        triggers = payload["on"]
        self.assertIn("workflow_dispatch", triggers)
        forward = payload["jobs"]["live-forward"]
        self.assertIn("workflow_dispatch", forward["if"])
        self.assertIn("self-hosted", forward["runs-on"])
        commands = "\n".join(
            str(step.get("run", "")) for step in forward["steps"]
        )
        self.assertIn("--adapter codex", commands)
        self.assertIn("--adapter claude", commands)
        self.assertLess(commands.index("--adapter codex"), commands.index("--adapter claude"))
        release = payload["jobs"]["release-evidence"]
        self.assertIn("workflow_dispatch", release["if"])
        release_commands = "\n".join(
            str(step.get("run", "")) for step in release["steps"]
        )
        self.assertIn("scripts/verify.py --tier full", release_commands)

    def test_maintainer_analysis_is_manual_serial_and_environment_approved(self) -> None:
        payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        job = payload["jobs"]["live-maintainer"]
        self.assertIn("workflow_dispatch", job["if"])
        self.assertIn("run_maintainer", job["if"])
        self.assertEqual(job["environment"], "live-maintenance")
        self.assertIn("self-hosted", job["runs-on"])
        commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
        self.assertIn("scripts/maintenance/analyze_usage.py", commands)
        self.assertIn("--adapter codex", commands)
        self.assertIn("--secondary-adapter claude", commands)
        self.assertNotIn("&", commands)
        self.assertNotIn("${{ inputs.maintenance_bundle_path }}", commands)
        analysis_step = next(
            step for step in job["steps"] if "analyze_usage.py" in step.get("run", "")
        )
        self.assertEqual(
            analysis_step["env"]["MAINTENANCE_BUNDLE_PATH"],
            "${{ inputs.maintenance_bundle_path }}",
        )


if __name__ == "__main__":
    unittest.main()
