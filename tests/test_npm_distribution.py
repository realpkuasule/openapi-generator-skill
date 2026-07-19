from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.install_skill import tree_digest
from tests.support import REPO_ROOT, SKILL_ROOT, snapshot_tree


PACKAGE_JSON = REPO_ROOT / "package.json"
NODE_INSTALLER = REPO_ROOT / "bin" / "openapi-engineering-skill.mjs"
PACKAGE_NAME = "@realpkuasule/openapi-engineering-skill"
PACKAGE_VERSION = "0.1.0-rc.2"
RELEASE_PLAN = REPO_ROOT / "docs" / "plans" / "npm-release-v0.1.0-rc.2.md"
NPM = shutil.which("npm") or "npm"


def run_cli(home: Path, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [
            "node",
            str(NODE_INSTALLER),
            *arguments,
            "--home",
            str(home),
            "--json",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(result.stdout) if result.stdout else {}
    return result, payload


class NpmDistributionTests(unittest.TestCase):
    def test_package_manifest_is_pinned_allowlisted_and_has_no_postinstall(self) -> None:
        manifest = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))

        self.assertEqual(manifest["name"], PACKAGE_NAME)
        self.assertEqual(manifest["version"], PACKAGE_VERSION)
        self.assertEqual(manifest["license"], "UNLICENSED")
        self.assertEqual(manifest["type"], "module")
        self.assertEqual(manifest["engines"]["node"], ">=20")
        self.assertEqual(
            manifest["bin"],
            {"openapi-engineering-skill": "bin/openapi-engineering-skill.mjs"},
        )
        self.assertEqual(
            manifest["files"],
            [
                "bin/",
                "skills/openapi-engineering/",
                "!skills/openapi-engineering/**/__pycache__/",
                "!skills/openapi-engineering/**/*.pyc",
                "!skills/openapi-engineering/**/*.pyo",
                "!skills/openapi-engineering/**/.DS_Store",
                "README.md",
                "CHANGELOG.md",
            ],
        )
        self.assertEqual(manifest["publishConfig"], {"access": "public"})
        self.assertNotIn("postinstall", manifest.get("scripts", {}))
        self.assertEqual(manifest.get("dependencies", {}), {})

    def test_packed_files_exclude_caches_tests_evidence_and_development_tools(self) -> None:
        result = subprocess.run(
            [NPM, "pack", "--dry-run", "--json", "--ignore-scripts"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        packed = json.loads(result.stdout)[0]
        paths = {item["path"] for item in packed["files"]}

        self.assertIn("bin/openapi-engineering-skill.mjs", paths)
        self.assertIn("skills/openapi-engineering/SKILL.md", paths)
        self.assertFalse(any("__pycache__" in path for path in paths))
        self.assertFalse(any(path.endswith((".pyc", ".pyo")) for path in paths))
        self.assertFalse(
            any(
                path.startswith(prefix)
                for path in paths
                for prefix in ("contracts/", "docs/", "scripts/", "tests/")
            )
        )

    def test_release_plan_records_contract_impact_publish_and_rollback(self) -> None:
        content = RELEASE_PLAN.read_text(encoding="utf-8")

        for required in (
            PACKAGE_NAME,
            PACKAGE_VERSION,
            "Contract-First",
            "OpenAPI 1.1.0",
            "no schema change",
            "npm publish",
            "rollback",
        ):
            self.assertIn(required, content)

    def test_install_dry_run_is_read_only_and_defaults_to_both_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            before = snapshot_tree(home)

            result, payload = run_cli(home, "install")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(payload["status"], "ok")
            self.assertFalse(payload["applied"])
            self.assertEqual(payload["canonical"]["action"], "would-copy")
            expected = "would-copy" if os.name == "nt" else "would-link"
            self.assertEqual(
                {row["platform"] for row in payload["installations"]},
                {"codex", "claude"},
            )
            self.assertEqual(
                {row["action"] for row in payload["installations"]}, {expected}
            )
            self.assertEqual(snapshot_tree(home), before)

    def test_apply_installs_versioned_canonical_tree_and_verify_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)

            installed, install_payload = run_cli(home, "install", "--apply")
            verified, verify_payload = run_cli(home, "verify")

            canonical = (
                home
                / ".local"
                / "share"
                / "openapi-engineering-skill"
                / PACKAGE_VERSION
                / "skills"
                / "openapi-engineering"
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(install_payload["applied"])
            self.assertTrue(verify_payload["verified"])
            self.assertEqual(install_payload["source_digest"], tree_digest(SKILL_ROOT))
            self.assertEqual(verify_payload["source_digest"], tree_digest(SKILL_ROOT))
            self.assertTrue(canonical.is_dir())
            self.assertEqual(tree_digest(canonical), tree_digest(SKILL_ROOT))
            self.assertEqual(
                {row["action"] for row in verify_payload["installations"]},
                {"verified"},
            )

    def test_divergent_target_blocks_all_install_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            divergent = home / ".claude" / "skills" / "openapi-engineering"
            divergent.mkdir(parents=True)
            (divergent / "SKILL.md").write_text("different\n", encoding="utf-8")
            before = snapshot_tree(home)

            result, payload = run_cli(home, "install", "--apply")

            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(payload["status"], "conflict")
            self.assertEqual(snapshot_tree(home), before)
            self.assertFalse(
                (home / ".codex" / "skills" / "openapi-engineering").exists()
            )

    def test_copy_mode_and_uninstall_preserve_canonical_source_and_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text('{"keep":true}\n', encoding="utf-8")

            installed, _ = run_cli(home, "install", "--apply", "--copy")
            dry_run, dry_payload = run_cli(home, "uninstall")
            before_apply = snapshot_tree(home)
            removed, removed_payload = run_cli(home, "uninstall", "--apply")

            canonical = (
                home
                / ".local"
                / "share"
                / "openapi-engineering-skill"
                / PACKAGE_VERSION
                / "skills"
                / "openapi-engineering"
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertEqual(
                {row["action"] for row in dry_payload["installations"]},
                {"would-remove"},
            )
            self.assertNotEqual(snapshot_tree(home), before_apply)
            self.assertEqual(
                {row["action"] for row in removed_payload["installations"]},
                {"remove"},
            )
            self.assertTrue(canonical.is_dir())
            self.assertEqual(settings.read_text(encoding="utf-8"), '{"keep":true}\n')


if __name__ == "__main__":
    unittest.main()
