from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support import parse_json_output, run_script, snapshot_tree


class InspectProjectTests(unittest.TestCase):
    def make_project(self, root: Path) -> None:
        (root / "contracts").mkdir()
        (root / "schemas").mkdir()
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".openapi-engineering").mkdir()
        (root / "package.json").write_text(
            json.dumps(
                {
                    "scripts": {"generate:api": "openapi-generator-cli generate"},
                    "devDependencies": {
                        "@openapitools/openapi-generator-cli": "2.25.2"
                    },
                }
            ),
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
        (root / "tsconfig.json").write_text('{"compilerOptions":{}}', encoding="utf-8")
        (root / "AGENTS.md").write_text("Project rules\n", encoding="utf-8")
        (root / "contracts" / "openapi.yaml").write_text(
            "openapi: 3.0.3\ninfo: {title: Fixture, version: 1.0.0}\npaths: {}\n",
            encoding="utf-8",
        )
        (root / "schemas" / "domain.schema.json").write_text(
            '{"$schema":"https://json-schema.org/draft/2020-12/schema"}',
            encoding="utf-8",
        )
        (root / ".github" / "workflows" / "ci.yml").write_text(
            "name: CI\n", encoding="utf-8"
        )
        (root / ".openapi-engineering" / "profile.yaml").write_text(
            "profile_version: 1\n", encoding="utf-8"
        )

    def test_inspection_finds_project_signals_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_project(root)
            before = snapshot_tree(root)

            result = run_script("inspect_project.py", "--root", str(root))

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = parse_json_output(result)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["root"], str(root.resolve()))
            self.assertEqual(payload["languages"], ["Python", "TypeScript"])
            self.assertEqual(payload["build_systems"], ["npm", "pyproject"])
            self.assertEqual(payload["contract_files"], ["contracts/openapi.yaml"])
            self.assertEqual(payload["schema_files"], ["schemas/domain.schema.json"])
            self.assertEqual(
                payload["governance_profiles"], [".openapi-engineering/profile.yaml"]
            )
            self.assertEqual(payload["ci_files"], [".github/workflows/ci.yml"])
            self.assertIn("openapi-generator-config", payload["generation_signals"])
            self.assertEqual(payload["generated_directories"], [])
            self.assertFalse(payload["truncated"])
            self.assertGreater(payload["scan_counts"]["files"], 0)
            self.assertEqual(snapshot_tree(root), before)

    def test_worktrees_and_generated_outputs_do_not_pollute_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_project(root)
            stale = root / ".worktrees" / "stale" / "contracts"
            stale.mkdir(parents=True)
            (stale / "openapi.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
            generated = root / "generated" / "python-fastapi"
            generated.mkdir(parents=True)
            (generated / "openapi.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
            before = snapshot_tree(root)

            result = run_script("inspect_project.py", "--root", str(root))

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = parse_json_output(result)
            self.assertEqual(payload["contract_files"], ["contracts/openapi.yaml"])
            self.assertEqual(payload["generated_directories"], ["generated"])
            excluded = {item["path"]: item["reason"] for item in payload["excluded_paths"]}
            self.assertEqual(excluded[".worktrees"], "worktree")
            self.assertEqual(excluded["generated"], "generated")
            self.assertEqual(snapshot_tree(root), before)

    def test_generator_configuration_is_not_misclassified_as_a_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_project(root)
            (root / "openapitools.json").write_text(
                '{"generator-cli":{"version":"7.14.0"}}', encoding="utf-8"
            )

            result = run_script("inspect_project.py", "--root", str(root))

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = parse_json_output(result)
            self.assertEqual(payload["contract_files"], ["contracts/openapi.yaml"])
            self.assertIn("openapi-generator-config", payload["generation_signals"])

    def test_file_limit_is_explicit_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_project(root)
            first = run_script(
                "inspect_project.py", "--root", str(root), "--max-files", "2"
            )
            second = run_script(
                "inspect_project.py", "--root", str(root), "--max-files", "2"
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            payload = parse_json_output(first)
            self.assertTrue(payload["truncated"])
            self.assertEqual(payload["scan_counts"]["files"], 2)
            self.assertIn("scan-limit", {item["code"] for item in payload["warnings"]})

    def test_output_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_project(root)
            first = run_script("inspect_project.py", "--root", str(root))
            second = run_script("inspect_project.py", "--root", str(root))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)

    def test_missing_root_returns_json_error(self) -> None:
        result = run_script("inspect_project.py", "--root", "/definitely/not/a/project")
        self.assertNotEqual(result.returncode, 0)
        payload = parse_json_output(result)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "invalid-root")


if __name__ == "__main__":
    unittest.main()
