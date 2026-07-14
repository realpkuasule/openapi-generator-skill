from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.support import REPO_ROOT, parse_json_output, run_script


EXAMPLES = REPO_ROOT / "contracts" / "examples"
VALID_PROFILE = EXAMPLES / "governance-profile.valid.yaml"


class ValidateProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.valid_profile = yaml.safe_load(VALID_PROFILE.read_text(encoding="utf-8"))

    def run_profile(self, profile: object):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            return run_script("validate_profile.py", str(path))

    def test_valid_yaml_profile_passes(self) -> None:
        result = run_script("validate_profile.py", str(VALID_PROFILE))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = parse_json_output(result)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["errors"], [])

    def test_schema_rejects_wrong_container_types(self) -> None:
        profile = copy.deepcopy(self.valid_profile)
        profile["intent_history"] = "not-an-array"
        profile["boundaries"] = "not-an-array"
        profile["decision"]["rationale"] = "not-an-array"
        profile["validation"]["gates"] = "not-an-array"
        result = self.run_profile(profile)
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = parse_json_output(result)
        self.assertFalse(payload["valid"])
        self.assertIn("schema-violation", {item["code"] for item in payload["errors"]})

    def test_schema_rejects_invalid_strategy(self) -> None:
        profile = copy.deepcopy(self.valid_profile)
        profile["decision"]["strategy"] = "use-every-generator"
        result = self.run_profile(profile)
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = parse_json_output(result)
        self.assertTrue(any(item["path"] == "$.decision.strategy" for item in payload["errors"]))

    def test_schema_rejects_non_exact_versions(self) -> None:
        for version in ("latest", "*", ">=7", "^7.23.0", "7.x"):
            with self.subTest(version=version):
                profile = copy.deepcopy(self.valid_profile)
                profile["decision"]["tools"][0]["version"] = version
                profile["generation"]["version_pins"][0]["version"] = version
                result = self.run_profile(profile)
                self.assertEqual(result.returncode, 1, result.stderr)
                payload = parse_json_output(result)
                self.assertIn(
                    "non-exact-version", {item["code"] for item in payload["errors"]}
                )

    def test_sensitive_values_are_rejected_and_redacted(self) -> None:
        secret = "do-not-echo-this-value"
        result = run_script(
            "validate_profile.py", str(EXAMPLES / "governance-profile.invalid-secret.yaml")
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = parse_json_output(result)
        self.assertFalse(payload["valid"])
        codes = {finding["code"] for finding in payload["errors"]}
        self.assertIn("sensitive-value", codes)
        self.assertIn("non-exact-version", codes)
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, result.stderr)

    def test_public_digest_is_not_treated_as_a_secret(self) -> None:
        result = self.run_profile(self.valid_profile)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_missing_required_section_fails(self) -> None:
        result = self.run_profile({"profile_version": 1})
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = parse_json_output(result)
        self.assertFalse(payload["valid"])
        self.assertIn("schema-violation", {item["code"] for item in payload["errors"]})

    def test_missing_file_is_load_error(self) -> None:
        result = run_script("validate_profile.py", "/definitely/missing/profile.yaml")
        self.assertEqual(result.returncode, 2)
        payload = parse_json_output(result)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "load-error")

    def test_invalid_yaml_is_a_redacted_json_load_error(self) -> None:
        secret = "must-not-appear"
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.yaml"
            profile.write_text(f'profile: "{secret}\n', encoding="utf-8")
            result = run_script("validate_profile.py", str(profile))
            self.assertEqual(result.returncode, 2)
            payload = parse_json_output(result)
            self.assertEqual(payload["error"]["code"], "load-error")
            self.assertNotIn(secret, result.stdout)
            self.assertNotIn(secret, result.stderr)


if __name__ == "__main__":
    unittest.main()
