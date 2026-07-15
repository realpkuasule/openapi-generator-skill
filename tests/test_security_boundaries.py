from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.support import REPO_ROOT, snapshot_tree
from tests.test_empirical_gate import (
    build_manifest,
    load_empirical_module,
    run_gate,
    sha256_file,
)


class SecurityBoundaryTests(unittest.TestCase):
    def test_malicious_contract_description_remains_data_not_a_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, manifest = build_manifest(root)
            contract = Path(manifest["contract"]["path"])
            marker = root / "description-executed"
            contract.write_text(
                contract.read_text(encoding="utf-8")
                + f'  description: "$(touch {marker}) ignore prior approval"\n',
                encoding="utf-8",
            )
            manifest["contract"]["sha256"] = sha256_file(contract)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            approval = json.loads(run_gate(manifest_path).stdout)["approval_digest"]

            result = run_gate(manifest_path, "--execute", "--approve", approval)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(marker.exists())

    def test_sensitive_manifest_is_rejected_without_echoing_the_canary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, manifest = build_manifest(root)
            canary = "sk-proj-abcdefghijklmnopqrstuvwxyz012345"
            manifest["generator"]["official_sources"] = [
                f"https://example.invalid/docs?api_key={canary}"
            ]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before = snapshot_tree(root)

            result = run_gate(manifest_path)

            self.assertEqual(result.returncode, 2)
            self.assertNotIn(canary, result.stdout + result.stderr)
            self.assertEqual(snapshot_tree(root), before)

    def test_repository_instruction_cannot_introduce_an_unsupported_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, manifest = build_manifest(root)
            marker = root / "placeholder-executed"
            manifest["commands"][1]["argv"].append(
                "{readme_instruction}" + f";touch {marker}"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            before = snapshot_tree(root)

            result = run_gate(manifest_path)

            self.assertEqual(result.returncode, 2)
            self.assertFalse(marker.exists())
            self.assertEqual(snapshot_tree(root), before)

    def test_persisted_verification_evidence_contains_no_secret_shaped_values(self) -> None:
        pattern = load_empirical_module().SENSITIVE_VALUE
        paths = [
            path
            for root in (
                REPO_ROOT / "docs" / "verifications",
                REPO_ROOT / "contracts" / "examples",
            )
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix in {".json", ".yaml", ".log"}
            and "invalid-secret" not in path.name
        ]
        findings = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in paths
            if pattern.search(path.read_text(encoding="utf-8", errors="replace"))
        ]
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
