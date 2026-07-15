from __future__ import annotations

import json
import importlib.util
import tempfile
import unittest
from pathlib import Path

from scripts.install_skill import install_skill, uninstall_skill
from tests.support import SKILL_ROOT, snapshot_tree
from tests.test_empirical_gate import build_manifest, run_gate


SNAPSHOT_SCRIPT = SKILL_ROOT / "scripts" / "scope_snapshot.py"
SNAPSHOT_SPEC = importlib.util.spec_from_file_location("scope_snapshot", SNAPSHOT_SCRIPT)
if SNAPSHOT_SPEC is None or SNAPSHOT_SPEC.loader is None:
    raise AssertionError("Unable to load the scope snapshot helper.")
SNAPSHOT_MODULE = importlib.util.module_from_spec(SNAPSHOT_SPEC)
SNAPSHOT_SPEC.loader.exec_module(SNAPSHOT_MODULE)
create_snapshot = SNAPSHOT_MODULE.create_snapshot
restore_snapshot = SNAPSHOT_MODULE.restore_snapshot


class RollbackTests(unittest.TestCase):
    def test_external_snapshot_restores_profile_and_generated_baseline_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            snapshot = Path(directory) / "external-snapshot"
            profile = root / ".openapi-engineering" / "profile.yaml"
            generated = root / "generated"
            profile.parent.mkdir(parents=True)
            generated.mkdir()
            profile.write_text("profile_version: 1\n", encoding="utf-8")
            (generated / "client.py").write_text("VALUE = 1\n", encoding="utf-8")
            before = snapshot_tree(root)

            manifest = create_snapshot(
                root, snapshot, [".openapi-engineering/profile.yaml", "generated"]
            )
            self.assertEqual(snapshot_tree(root), before)
            profile.write_text("profile_version: 999\n", encoding="utf-8")
            (generated / "client.py").write_text("VALUE = 2\n", encoding="utf-8")
            (generated / "unexpected.py").write_text("bad\n", encoding="utf-8")

            report, exit_code = restore_snapshot(
                root,
                snapshot,
                snapshot / "manifest.json",
                manifest["approval_digest"],
            )

            self.assertEqual(exit_code, 0, report)
            self.assertEqual(report["status"], "restored")
            self.assertEqual(snapshot_tree(root), before)

    def test_snapshot_restore_requires_exact_approval_and_is_read_only_on_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            snapshot = Path(directory) / "external-snapshot"
            root.mkdir()
            (root / "state.txt").write_text("accepted\n", encoding="utf-8")
            create_snapshot(root, snapshot, ["state.txt"])
            (root / "state.txt").write_text("candidate\n", encoding="utf-8")
            before = snapshot_tree(root)

            report, exit_code = restore_snapshot(
                root, snapshot, snapshot / "manifest.json", "0" * 64
            )

            self.assertEqual(exit_code, 1)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(snapshot_tree(root), before)

    def test_dual_platform_install_can_be_uninstalled_without_touching_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text('{"keep":true}\n', encoding="utf-8")
            before = snapshot_tree(home)
            installed, install_exit = install_skill(
                SKILL_ROOT, home, ("codex", "claude"), apply=True
            )
            self.assertEqual(install_exit, 0, installed)

            removed, remove_exit = uninstall_skill(
                SKILL_ROOT, home, ("codex", "claude"), apply=True
            )

            self.assertEqual(remove_exit, 0, removed)
            self.assertEqual(snapshot_tree(home), before)

    def test_failed_generation_reclaims_candidate_and_preserves_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            temp_root = root / "tmp"
            temp_root.mkdir()
            manifest_path, manifest = build_manifest(root)
            manifest["commands"][1]["argv"] = [
                manifest["commands"][1]["argv"][0],
                "{artifact}",
                "fail",
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            approval = json.loads(run_gate(manifest_path).stdout)["approval_digest"]
            baseline = Path(manifest["baseline"]["path"])
            before = snapshot_tree(baseline)

            result = run_gate(
                manifest_path,
                "--execute",
                "--approve",
                approval,
                temp_root=temp_root,
            )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(snapshot_tree(baseline), before)
            self.assertEqual(list(temp_root.glob("openapi-empirical-*")), [])


if __name__ == "__main__":
    unittest.main()
