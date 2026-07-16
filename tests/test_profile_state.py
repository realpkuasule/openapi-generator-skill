from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.support import REPO_ROOT, parse_json_output, run_script, snapshot_tree


VALID_PROFILE = REPO_ROOT / "contracts" / "examples" / "governance-profile.valid.yaml"


class ProfileStateTests(unittest.TestCase):
    def make_inputs(
        self,
        root: Path,
        *,
        contracts: list[str] | None = None,
        schemas: list[str] | None = None,
        truncated: bool = False,
        user_decided_contract: bool = False,
    ) -> tuple[Path, Path]:
        profile = yaml.safe_load(VALID_PROFILE.read_text(encoding="utf-8"))
        if user_decided_contract:
            profile["statements"].append(
                {
                    "subject": "contract.sources_of_truth",
                    "value": json.dumps(
                        profile["contract"]["sources_of_truth"], sort_keys=True
                    ),
                    "provenance": "user-decided",
                    "evidence_paths": [],
                }
            )
        profile_path = root / "profile.yaml"
        profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
        observed_contracts = (
            contracts if contracts is not None else ["contracts/openapi.yaml"]
        )
        observed_schemas = (
            schemas if schemas is not None else ["contracts/domain.schema.json"]
        )
        inspection = {
            "status": "ok",
            "root": "/workspace/project",
            "contract_files": observed_contracts,
            "schema_files": observed_schemas,
            "truncated": truncated,
            "evidence": [
                {"kind": "contract", "path": path}
                for path in observed_contracts
            ]
            + [
                {"kind": "schema", "path": path}
                for path in observed_schemas
            ],
        }
        inspection_path = root / "inspection.json"
        inspection_path.write_text(json.dumps(inspection), encoding="utf-8")
        return profile_path, inspection_path

    def test_check_reports_unchanged_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile, inspection = self.make_inputs(root)
            before = snapshot_tree(root)

            result = run_script(
                "profile_state.py",
                "check",
                "--profile",
                str(profile),
                "--inspection",
                str(inspection),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = parse_json_output(result)
            self.assertEqual(payload["state"], "unchanged")
            self.assertEqual(payload["changes"], [])
            self.assertIsNone(payload["proposal"])
            self.assertEqual(snapshot_tree(root), before)

    def test_check_separates_observed_change_conflict_and_unknown(self) -> None:
        cases = (
            (False, False, "changed", 0),
            (False, True, "conflict", 1),
            (True, False, "unknown", 0),
        )
        for truncated, user_decided, state, exit_code in cases:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                profile, inspection = self.make_inputs(
                    root,
                    contracts=["contracts/current.yaml"],
                    schemas=[],
                    truncated=truncated,
                    user_decided_contract=user_decided,
                )
                result = run_script(
                    "profile_state.py",
                    "check",
                    "--profile",
                    str(profile),
                    "--inspection",
                    str(inspection),
                )
                self.assertEqual(result.returncode, exit_code, result.stderr)
                payload = parse_json_output(result)
                self.assertEqual(payload["state"], state)
                self.assertEqual(payload["changes"][0]["provenance"], (
                    "user-decided" if user_decided else "observed"
                ))

    def test_propose_is_read_only_and_emits_approval_bound_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile, inspection = self.make_inputs(
                root, contracts=["contracts/current.yaml"], schemas=[]
            )
            before = snapshot_tree(root)

            result = run_script(
                "profile_state.py",
                "propose",
                "--profile",
                str(profile),
                "--inspection",
                str(inspection),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = parse_json_output(result)
            proposal = payload["proposal"]
            self.assertTrue(proposal["requires_approval"])
            self.assertEqual(
                proposal["proposed_profile"]["contract"]["sources_of_truth"],
                ["contracts/current.yaml"],
            )
            self.assertRegex(proposal["approval_digest"], r"^[a-f0-9]{64}$")
            self.assertEqual(snapshot_tree(root), before)

    def test_check_reports_only_relevant_tool_and_output_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile, inspection = self.make_inputs(root)
            observed = json.loads(inspection.read_text(encoding="utf-8"))
            observed["generation_signals"] = ["orval-config"]
            observed["generated_directories"] = ["web/generated"]
            inspection.write_text(json.dumps(observed), encoding="utf-8")

            result = run_script(
                "profile_state.py",
                "check",
                "--profile",
                str(profile),
                "--inspection",
                str(inspection),
            )

            self.assertEqual(result.returncode, 1)
            payload = parse_json_output(result)
            self.assertEqual(payload["state"], "conflict")
            self.assertEqual(
                {change["path"] for change in payload["changes"]},
                {"/decision/tools", "/generation/output_directories"},
            )
            self.assertTrue(
                all(change["provenance"] == "user-decided" for change in payload["changes"])
            )
            self.assertIsNone(payload["proposal"])

    def test_apply_requires_exact_digest_and_rejects_stale_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile, inspection = self.make_inputs(
                root, contracts=["contracts/current.yaml"], schemas=[]
            )
            proposed = run_script(
                "profile_state.py",
                "propose",
                "--profile",
                str(profile),
                "--inspection",
                str(inspection),
            )
            proposal_payload = parse_json_output(proposed)["proposal"]
            proposal_path = root / "proposal.json"
            proposal_path.write_text(json.dumps(proposal_payload), encoding="utf-8")
            before = profile.read_bytes()

            denied = run_script(
                "profile_state.py",
                "apply",
                "--profile",
                str(profile),
                "--proposal",
                str(proposal_path),
                "--approve",
                "0" * 64,
            )
            self.assertEqual(denied.returncode, 1)
            self.assertEqual(profile.read_bytes(), before)

            tampered = copy.deepcopy(proposal_payload)
            tampered["approval_digest"] = "1" * 64
            proposal_path.write_text(json.dumps(tampered), encoding="utf-8")
            forged = run_script(
                "profile_state.py",
                "apply",
                "--profile",
                str(profile),
                "--proposal",
                str(proposal_path),
                "--approve",
                tampered["approval_digest"],
            )
            self.assertEqual(forged.returncode, 1)
            self.assertEqual(profile.read_bytes(), before)
            proposal_path.write_text(json.dumps(proposal_payload), encoding="utf-8")

            stale = yaml.safe_load(profile.read_text(encoding="utf-8"))
            stale["project"]["stage"] = "active"
            profile.write_text(yaml.safe_dump(stale, sort_keys=False), encoding="utf-8")
            stale_before = profile.read_bytes()
            rejected = run_script(
                "profile_state.py",
                "apply",
                "--profile",
                str(profile),
                "--proposal",
                str(proposal_path),
                "--approve",
                proposal_payload["approval_digest"],
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertEqual(profile.read_bytes(), stale_before)

    def test_approved_apply_updates_only_profile_and_result_remains_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile, inspection = self.make_inputs(
                root, contracts=["contracts/current.yaml"], schemas=[]
            )
            proposed = parse_json_output(
                run_script(
                    "profile_state.py",
                    "propose",
                    "--profile",
                    str(profile),
                    "--inspection",
                    str(inspection),
                )
            )["proposal"]
            proposal_path = root / "proposal.json"
            proposal_path.write_text(json.dumps(proposed), encoding="utf-8")

            applied = run_script(
                "profile_state.py",
                "apply",
                "--profile",
                str(profile),
                "--proposal",
                str(proposal_path),
                "--approve",
                proposed["approval_digest"],
            )

            self.assertEqual(applied.returncode, 0, applied.stderr)
            payload = parse_json_output(applied)
            self.assertTrue(payload["applied"])
            updated = yaml.safe_load(profile.read_text(encoding="utf-8"))
            self.assertEqual(
                updated["contract"]["sources_of_truth"],
                ["contracts/current.yaml"],
            )
            validated = run_script("validate_profile.py", str(profile))
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)


if __name__ == "__main__":
    unittest.main()
