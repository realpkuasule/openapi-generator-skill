from __future__ import annotations

import hashlib
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
PACKAGE_VERSION = "0.1.2"
RELEASE_PLAN = REPO_ROOT / "docs" / "plans" / "npm-release-v0.1.2.md"
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
    def test_python_skill_digest_uses_platform_neutral_relative_name_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "a" / "item.txt"
            nested.parent.mkdir()
            nested.write_bytes(b"nested")
            (root / "a0.txt").write_bytes(b"flat")
            expected = hashlib.sha256()
            for name, content in (("a/item.txt", b"nested"), ("a0.txt", b"flat")):
                expected.update(name.encode("utf-8"))
                expected.update(b"\0")
                expected.update(content)
                expected.update(b"\0")

            self.assertEqual(tree_digest(root), expected.hexdigest())

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
                "lib/usage/",
                "packaging/launchd/",
                "skills/openapi-engineering/",
                "!skills/openapi-engineering/**/__pycache__/",
                "!skills/openapi-engineering/**/*.pyc",
                "!skills/openapi-engineering/**/*.pyo",
                "!skills/openapi-engineering/**/.DS_Store",
                "skills/openapi-engineering-maintainer/",
                "!skills/openapi-engineering-maintainer/**/__pycache__/",
                "!skills/openapi-engineering-maintainer/**/*.pyc",
                "!skills/openapi-engineering-maintainer/**/*.pyo",
                "!skills/openapi-engineering-maintainer/**/.DS_Store",
                "scripts/maintenance/",
                "!scripts/maintenance/**/__pycache__/",
                "!scripts/maintenance/**/*.pyc",
                "contracts/schemas/usage-*.json",
                "contracts/schemas/user-feedback.schema.json",
                "contracts/schemas/maintenance-*.json",
                "contracts/schemas/retention-plan.schema.json",
                "README.md",
                "CHANGELOG.md",
            ],
        )
        self.assertEqual(manifest["publishConfig"], {"access": "public"})
        self.assertNotIn("postinstall", manifest.get("scripts", {}))
        self.assertEqual(manifest.get("dependencies", {}), {})
        self.assertEqual(
            manifest["scripts"]["prepublishOnly"],
            "python3 scripts/verify.py --tier deterministic",
        )

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
        self.assertIn("skills/openapi-engineering-maintainer/SKILL.md", paths)
        self.assertIn("lib/usage/config.mjs", paths)
        self.assertIn("lib/usage/maintenance-cycle.mjs", paths)
        self.assertIn("lib/usage/maintenance-report.mjs", paths)
        self.assertIn(
            "packaging/launchd/com.realpkuasule.openapi-engineering-maintainer.plist", paths
        )
        self.assertIn("scripts/maintenance/analyze_usage.py", paths)
        self.assertIn("contracts/schemas/usage-event.schema.json", paths)
        self.assertIn("contracts/schemas/maintenance-cycle.schema.json", paths)
        self.assertIn("contracts/schemas/maintenance-report.schema.json", paths)
        self.assertIn("contracts/schemas/retention-plan.schema.json", paths)
        self.assertIn(
            "skills/openapi-engineering-maintainer/references/unattended-cycle.md", paths
        )
        self.assertIn(
            "skills/openapi-engineering-maintainer/evals/unattended-cycle.yaml", paths
        )
        self.assertIn("scripts/maintenance/process_watch.py", paths)
        self.assertFalse(any("__pycache__" in path for path in paths))
        self.assertFalse(any(path.endswith((".pyc", ".pyo")) for path in paths))
        self.assertFalse(any(path.startswith(prefix) for path in paths for prefix in ("docs/", "tests/")))
        self.assertFalse(
            any(
                path.startswith("contracts/")
                and not path.startswith("contracts/schemas/")
                for path in paths
            )
        )

    def test_real_tarball_installs_verifies_and_uninstalls_in_an_isolated_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packages = root / "packages"
            consumer = root / "consumer"
            home = root / "home"
            packages.mkdir()
            packed = subprocess.run(
                [
                    NPM,
                    "pack",
                    "--ignore-scripts",
                    "--json",
                    "--pack-destination",
                    str(packages),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(packed.returncode, 0, packed.stderr)
            tarball = packages / json.loads(packed.stdout)[0]["filename"]
            installed_package = subprocess.run(
                [
                    NPM,
                    "install",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                    "--offline",
                    "--package-lock=false",
                    "--prefix",
                    str(consumer),
                    str(tarball),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(installed_package.returncode, 0, installed_package.stderr)
            packaged_cli = (
                consumer
                / "node_modules"
                / "@realpkuasule"
                / "openapi-engineering-skill"
                / "bin"
                / "openapi-engineering-skill.mjs"
            )

            def packaged(*arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
                result = subprocess.run(
                    ["node", str(packaged_cli), *arguments, "--home", str(home), "--json"],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                return result, json.loads(result.stdout) if result.stdout else {}

            applied, apply_payload = packaged("install", "--apply")
            verified, verify_payload = packaged("verify")
            removed, remove_payload = packaged("uninstall", "--apply")

            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertTrue(apply_payload["applied"])
            self.assertTrue(verify_payload["verified"])
            self.assertTrue(remove_payload["applied"])
            self.assertEqual(
                {row["action"] for row in remove_payload["installations"]},
                {"remove"},
            )
            self.assertFalse((home / ".codex" / "skills" / "openapi-engineering").exists())
            self.assertFalse((home / ".claude" / "skills" / "openapi-engineering").exists())
            self.assertTrue(
                (
                    home
                    / ".local"
                    / "share"
                    / "openapi-engineering-skill"
                    / PACKAGE_VERSION
                    / "skills"
                    / "openapi-engineering"
                ).is_dir()
            )

    def test_release_plan_records_contract_impact_publish_and_rollback(self) -> None:
        content = RELEASE_PLAN.read_text(encoding="utf-8")

        for required in (
            PACKAGE_NAME,
            PACKAGE_VERSION,
            "Contract-First",
            "OpenAPI 1.3.0",
            "additive contract",
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

    def test_maintainer_component_is_explicit_and_installs_on_both_platforms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)

            installed, install_payload = run_cli(
                home,
                "install",
                "--component",
                "runtime",
                "--component",
                "maintainer",
                "--apply",
            )
            verified, verify_payload = run_cli(
                home,
                "verify",
                "--component",
                "runtime",
                "--component",
                "maintainer",
            )

            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(
                {(row["platform"], row["component"]) for row in install_payload["installations"]},
                {
                    ("codex", "runtime"),
                    ("claude", "runtime"),
                    ("codex", "maintainer"),
                    ("claude", "maintainer"),
                },
            )
            self.assertTrue(
                (home / ".codex" / "skills" / "openapi-engineering-maintainer").exists()
            )
            self.assertTrue(
                (home / ".claude" / "skills" / "openapi-engineering-maintainer").exists()
            )
            self.assertTrue(verify_payload["verified"])

    @unittest.skipIf(os.name == "nt", "versioned symlink migration is POSIX-only")
    def test_install_safely_relinks_a_verified_older_npm_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            installed, _payload = run_cli(home, "install", "--apply")
            self.assertEqual(installed.returncode, 0, installed.stderr)
            managed = home / ".local" / "share" / "openapi-engineering-skill"
            current = managed / PACKAGE_VERSION
            older = managed / "0.1.0-rc.1"
            current.rename(older)
            package = json.loads((older / "package.json").read_text(encoding="utf-8"))
            package["version"] = "0.1.0-rc.1"
            (older / "package.json").write_text(json.dumps(package), encoding="utf-8")
            for platform in (".codex", ".claude"):
                target = home / platform / "skills" / "openapi-engineering"
                target.unlink()
                target.symlink_to(older / "skills" / "openapi-engineering", target_is_directory=True)

            planned, plan = run_cli(home, "install")

            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(
                {row["action"] for row in plan["installations"]}, {"would-relink"}
            )
            self.assertFalse(current.exists())

            upgraded, upgrade = run_cli(home, "install", "--apply")
            verified, verification = run_cli(home, "verify")

            self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual({row["action"] for row in upgrade["installations"]}, {"link"})
            self.assertTrue(verification["verified"])
            self.assertTrue(older.is_dir())

    @unittest.skipIf(os.name == "nt", "legacy source symlink migration is POSIX-only")
    def test_install_migrates_legacy_git_canonical_without_deleting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            legacy = (
                home
                / ".local"
                / "share"
                / "openapi-generator-skill"
                / "v0.1.0-rc.1"
                / "skills"
                / "openapi-engineering"
            )
            legacy.parent.mkdir(parents=True)
            shutil.copytree(SKILL_ROOT, legacy)
            for platform in (".codex", ".claude"):
                target = home / platform / "skills" / "openapi-engineering"
                target.parent.mkdir(parents=True)
                target.symlink_to(legacy, target_is_directory=True)

            planned, plan = run_cli(home, "install")
            applied, _application = run_cli(home, "install", "--apply")
            verified, verification = run_cli(home, "verify")

            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual({row["action"] for row in plan["installations"]}, {"would-relink"})
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertTrue(verification["verified"])
            self.assertTrue(legacy.is_dir())


if __name__ == "__main__":
    unittest.main()
