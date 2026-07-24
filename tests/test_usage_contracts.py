from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from tests.support import REPO_ROOT


SCHEMA_ROOT = REPO_ROOT / "contracts" / "schemas"
SCHEMA_NAMES = (
    "usage-config.schema.json",
    "usage-event.schema.json",
    "user-feedback.schema.json",
    "usage-summary.schema.json",
    "usage-trend.schema.json",
    "maintenance-finding.schema.json",
    "maintenance-analysis.schema.json",
    "maintenance-cycle.schema.json",
    "maintenance-report.schema.json",
    "maintenance-proposal.schema.json",
    "maintenance-promotion.schema.json",
)


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))


def validator_for(name: str, definition: str | None = None) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    if definition is not None:
        schema = {
            "$schema": schema["$schema"],
            "$ref": f"#/$defs/{definition}",
            "$defs": schema["$defs"],
        }
    return Draft202012Validator(schema, format_checker=FormatChecker())


class UsageContractTests(unittest.TestCase):
    def test_all_usage_schemas_exist_and_are_draft_2020_12(self) -> None:
        for name in SCHEMA_NAMES:
            with self.subTest(schema=name):
                schema = load_schema(name)
                self.assertEqual(
                    schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
                )
                Draft202012Validator.check_schema(schema)

    def test_config_defaults_are_explicit_and_collection_is_disabled(self) -> None:
        config = {
            "config_version": 2,
            "local_collection_enabled": False,
            "sync_enabled": False,
            "device_alias": None,
            "coordinator": False,
            "state_root": "default",
            "remote": None,
            "branch": None,
            "sync_authorization": None,
            "retention": {"local_days": 90, "remote_days": 365},
            "feedback": {"successful_sample_every": 5},
            "analysis": {
                "enabled": False,
                "credential_mode": None,
                "python_runtime": None,
                "notification": "none",
                "authorization": None,
                "primary": "codex",
                "secondary": "claude",
                "max_events": 50,
                "max_attempts_per_input": 2,
                "timeout_seconds": 600,
                "warning_rss_mb": 512,
                "hard_rss_mb": 1024,
            },
            "schedule": {"due_check": "daily", "period": "iso-week"},
        }
        self.assertEqual(list(validator_for("usage-config.schema.json").iter_errors(config)), [])

        unsafe = copy.deepcopy(config)
        unsafe["token"] = "secret-value"
        self.assertTrue(list(validator_for("usage-config.schema.json").iter_errors(unsafe)))

    def test_sanitized_event_cannot_represent_local_or_free_text_fields(self) -> None:
        event = {
            "schema_version": 1,
            "event_id": "evt-0123456789abcdef",
            "session_id": "ses-0123456789abcdef",
            "recorded_at": "2026-07-19T12:00:00Z",
            "device_alias": "m4",
            "skill_version": "0.1.0-rc.2",
            "skill_sha256": "a" * 64,
            "platform": "codex",
            "capture_mode": "best-effort",
            "anonymous_project_id": "b" * 64,
            "lifecycle_modes": ["governance-hardening"],
            "tool_strategy": "governance-only",
            "outcome": "passed",
            "interview_turns": 4,
            "boundary_revisions": 0,
            "tool_overridden": False,
            "gates": {"passed": 3, "failed": 0, "unverified": 0},
            "duration_ms": {"availability": "unavailable", "source": "best-effort"},
            "peak_rss_mb": {"availability": "unavailable", "source": "best-effort"},
            "exit_code": {"availability": "unavailable", "source": "best-effort"},
            "termination_reason": "not-reported",
            "feedback_status": "unknown",
            "safety_violation": False,
            "resource_anomaly": False,
            "platform_drift": False,
        }
        validator = validator_for("usage-event.schema.json", "sanitized_event")
        self.assertEqual(list(validator.iter_errors(event)), [])

        for field, value in (
            ("project_alias", "secret-project"),
            ("project_path", "/Users/person/project"),
            ("note", "raw transcript"),
            ("remote", "git@example.invalid:private/repo.git"),
        ):
            with self.subTest(field=field):
                unsafe = dict(event)
                unsafe[field] = value
                self.assertTrue(list(validator.iter_errors(unsafe)))

    def test_measurements_require_a_value_only_when_available(self) -> None:
        schema = load_schema("usage-event.schema.json")
        measurement_schema = {
            "$schema": schema["$schema"],
            "$ref": "#/$defs/measurement",
            "$defs": schema["$defs"],
        }
        validator = Draft202012Validator(measurement_schema)
        self.assertEqual(
            list(
                validator.iter_errors(
                    {"availability": "available", "source": "launcher", "value": 128}
                )
            ),
            [],
        )
        self.assertTrue(
            list(validator.iter_errors({"availability": "available", "source": "launcher"}))
        )
        self.assertTrue(
            list(
                validator.iter_errors(
                    {"availability": "unavailable", "source": "best-effort", "value": 0}
                )
            )
        )

    def test_feedback_note_exists_only_in_local_definition(self) -> None:
        base = {
            "schema_version": 1,
            "feedback_id": "fb-0123456789abcdef",
            "event_id": "evt-0123456789abcdef",
            "recorded_at": "2026-07-19T12:00:00Z",
            "device_alias": "m4",
            "rating": "friction",
            "friction_tags": ["too-many-questions"],
            "feedback_status": "answered",
        }
        local = dict(base, note="Needs a shorter interview")
        self.assertEqual(
            list(validator_for("user-feedback.schema.json", "local_feedback").iter_errors(local)),
            [],
        )
        self.assertTrue(
            list(
                validator_for("user-feedback.schema.json", "sanitized_feedback").iter_errors(
                    local
                )
            )
        )

    def test_finding_rules_and_proposal_digest_are_strict(self) -> None:
        finding_schema = load_schema("maintenance-finding.schema.json")
        self.assertEqual(
            set(finding_schema["$defs"]["rule_id"]["enum"]),
            {
                "SI-SAFETY-001",
                "SI-PLATFORM-001",
                "SI-FRICTION-001",
                "SI-OVERRIDE-001",
                "SI-UNVERIFIED-001",
                "SI-INTERVIEW-001",
                "SI-RESOURCE-001",
                "SI-REGRESSION-001",
            },
        )
        proposal_schema = load_schema("maintenance-proposal.schema.json")
        self.assertEqual(proposal_schema["properties"]["schema_version"]["const"], 2)
        required = set(proposal_schema["required"])
        self.assertTrue(
            {
                "input_digests",
                "skill_sha256",
                "config_sha256",
                "contract_impact",
                "target_files",
                "artifacts",
                "open_questions",
                "failing_tests",
                "verification",
                "resources",
                "rollback",
                "approval_sha256",
            }.issubset(required)
        )


if __name__ == "__main__":
    unittest.main()
