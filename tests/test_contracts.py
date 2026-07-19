from __future__ import annotations

import json
import unittest
import warnings
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker, RefResolver
from openapi_spec_validator import validate_url

from tests.support import REPO_ROOT


CONTRACT_ROOT = REPO_ROOT / "contracts"
SCHEMA_ROOT = CONTRACT_ROOT / "schemas"
EXAMPLE_ROOT = CONTRACT_ROOT / "examples"
OPENAPI_PATH = CONTRACT_ROOT / "openapi-engineering.openapi.yaml"
PROFILE_SCHEMA_PATH = SCHEMA_ROOT / "governance-profile.schema.json"
EVAL_SCHEMA_PATH = SCHEMA_ROOT / "eval-case.schema.json"
EMPIRICAL_SCHEMA_PATH = SCHEMA_ROOT / "empirical-gate.schema.json"


def walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.openapi = load_yaml(OPENAPI_PATH)
        cls.schemas = {
            path.name: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(SCHEMA_ROOT.glob("*.json"))
        }

    def test_openapi_is_valid_and_operations_are_stable(self) -> None:
        validate_url(OPENAPI_PATH.resolve().as_uri())
        self.assertEqual(self.openapi["openapi"], "3.1.0")
        self.assertEqual(self.openapi["info"]["version"], "1.2.0")
        self.assertEqual(self.openapi["x-runtime"], "cli-only")
        self.assertNotIn("servers", self.openapi)
        expected = {
            "/v1/inspections": "inspectProject",
            "/v1/profile-validations": "validateGovernanceProfile",
            "/v1/profile-state-comparisons": "compareGovernanceProfileState",
            "/v1/profile-state-applications": "applyGovernanceProfileProposal",
            "/v1/generation-comparisons": "compareGeneration",
            "/v1/empirical-gates": "runEmpiricalGeneratorGate",
            "/v1/evaluation-runs": "runSkillEvaluation",
            "/v1/acceptance-traceability-checks": "checkAcceptanceTraceability",
            "/v1/scope-snapshots": "manageScopeSnapshot",
            "/v1/evaluation-report-aggregations": "aggregateSkillEvaluations",
            "/v1/usage/configuration": "configureUsage",
            "/v1/usage/events": "recordUsageEvent",
            "/v1/usage/feedback": "recordUsageFeedback",
            "/v1/usage/synchronizations": "synchronizeUsage",
            "/v1/usage/summaries": "summarizeUsage",
            "/v1/usage/due-checks": "checkUsageDue",
            "/v1/usage/schedulers": "configureUsageScheduler",
            "/v1/usage/sessions": "runUsageSession",
            "/v1/usage/cleanups": "cleanupUsageRetention",
            "/v1/usage/trends": "analyzeUsageTrends",
            "/v1/maintenance/analyses": "analyzeMaintenanceFindings",
            "/v1/maintenance/proposals": "buildMaintenanceProposal",
            "/v1/maintenance/promotions": "promoteMaintenanceProposal",
        }
        observed = {
            path: item["post"]["operationId"]
            for path, item in self.openapi["paths"].items()
        }
        self.assertEqual(observed, expected)
        for item in self.openapi["paths"].values():
            operation = item["post"]
            self.assertIn("x-cli-command", operation)
            self.assertIn("x-cli-exit-codes", operation)
        evaluation_response = self.openapi["components"]["schemas"]["EvaluationRunResponse"]
        self.assertIn("skill_sha256", evaluation_response["required"])
        self.assertIn("harness_sha256", evaluation_response["required"])
        self.assertIn("timeout_seconds", evaluation_response["required"])
        self.assertIn("case_ids", evaluation_response["required"])
        self.assertIn("requested_results", evaluation_response["required"])
        self.assertIn("completed_results", evaluation_response["required"])
        self.assertEqual(evaluation_response["properties"]["report_version"]["const"], 2)
        evaluation_request = self.openapi["components"]["schemas"]["EvaluationRunRequest"]
        self.assertIn("resume", evaluation_request["properties"])
        self.assertIn("retry_nonpassing", evaluation_request["properties"])

    def test_all_json_schemas_are_valid_draft_2020_12(self) -> None:
        expected = {
            "acceptance-traceability.schema.json",
            "completion-report.schema.json",
            "empirical-gate.schema.json",
            "eval-case.schema.json",
            "eval-result.schema.json",
            "forward-eval-report.schema.json",
            "forward-observation.schema.json",
            "governance-profile.schema.json",
            "scope-snapshot.schema.json",
            "self-improvement-traceability.schema.json",
            "verification-report.schema.json",
            "usage-config.schema.json",
            "usage-event.schema.json",
            "user-feedback.schema.json",
            "usage-summary.schema.json",
            "usage-trend.schema.json",
            "maintenance-finding.schema.json",
            "maintenance-analysis.schema.json",
            "maintenance-proposal.schema.json",
            "maintenance-promotion.schema.json",
            "retention-plan.schema.json",
        }
        self.assertEqual(set(self.schemas), expected)
        for name, schema in self.schemas.items():
            with self.subTest(schema=name):
                self.assertEqual(
                    schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
                )
                Draft202012Validator.check_schema(schema)

    def test_all_refs_resolve_to_files_and_internal_targets(self) -> None:
        refs = {
            node["$ref"]
            for node in walk(self.openapi)
            if isinstance(node, dict) and "$ref" in node
        }
        internal_names = set(self.openapi["components"]["schemas"])
        for ref in sorted(refs):
            with self.subTest(ref=ref):
                if ref.startswith("#/components/schemas/"):
                    self.assertIn(ref.rsplit("/", 1)[-1], internal_names)
                elif ref.startswith("#/components/responses/"):
                    self.assertIn(
                        ref.rsplit("/", 1)[-1], self.openapi["components"]["responses"]
                    )
                else:
                    target = (OPENAPI_PATH.parent / ref.split("#", 1)[0]).resolve()
                    self.assertTrue(target.is_file(), f"Missing local $ref target: {ref}")

    def test_profile_examples_follow_the_authoritative_schema(self) -> None:
        schema = self.schemas[PROFILE_SCHEMA_PATH.name]
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        valid = load_yaml(EXAMPLE_ROOT / "governance-profile.valid.yaml")
        self.assertEqual(list(validator.iter_errors(valid)), [])

        for filename in (
            "governance-profile.invalid-secret.yaml",
            "governance-profile.invalid-structure.yaml",
        ):
            with self.subTest(filename=filename):
                errors = list(validator.iter_errors(load_yaml(EXAMPLE_ROOT / filename)))
                self.assertTrue(errors, f"{filename} unexpectedly satisfies the schema")

    def test_profile_contract_supports_all_strategies_and_evidence(self) -> None:
        schema = self.schemas[PROFILE_SCHEMA_PATH.name]
        strategies = set(schema["$defs"]["strategy"]["enum"])
        self.assertEqual(
            strategies,
            {
                "openapi-generator",
                "language-native",
                "official-sdk",
                "governance-only",
                "mcp",
                "no-codegen",
            },
        )
        decision_required = set(schema["properties"]["decision"]["required"])
        self.assertTrue(
            {"confidence", "conditions", "revisit_triggers"}.issubset(decision_required)
        )
        evidence_required = set(schema["properties"]["evidence"]["required"])
        self.assertTrue(
            {
                "input_digests",
                "observed_commands",
                "gate_results",
                "risks",
                "rollback",
            }.issubset(evidence_required)
        )

    def test_empirical_manifest_requires_pins_and_examples_conform(self) -> None:
        schema = self.schemas[EMPIRICAL_SCHEMA_PATH.name]
        manifest_schema = {
            "$schema": schema["$schema"],
            "$ref": "#/$defs/manifest",
            "$defs": schema["$defs"],
        }
        validator = Draft202012Validator(
            manifest_schema, format_checker=FormatChecker()
        )
        request = json.loads(
            (EXAMPLE_ROOT / "empirical-gate-request.json").read_text(encoding="utf-8")
        )
        self.assertEqual(list(validator.iter_errors(request)), [])

        unpinned = json.loads(json.dumps(request))
        unpinned["generator"]["version"] = "latest"
        self.assertTrue(list(validator.iter_errors(unpinned)))

        report = json.loads(
            (EXAMPLE_ROOT / "empirical-gate-response.json").read_text(encoding="utf-8")
        )
        report_errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report)
        )
        self.assertEqual(report_errors, [], [error.message for error in report_errors])

    def test_response_examples_match_openapi_schemas(self) -> None:
        mapping = {
            "inspect-response.json": "InspectionResponse",
            "profile-validation-response.json": "ProfileValidationResponse",
            "profile-state-response.json": "ProfileStateComparisonResponse",
            "generation-comparison-response.json": "GenerationComparisonResponse",
            "empirical-gate-response.json": "EmpiricalGateReport",
            "error-response.json": "ErrorResponse",
            "usage-status-response.json": "UsageConfigurationResult",
            "usage-record-response.json": "UsageRecordResult",
            "usage-summary-response.json": "UsageSummary",
            "maintenance-finding-response.json": "MaintenanceFinding",
            "maintenance-proposal-response.json": "MaintenanceProposal",
            "usage-due-response.json": "UsageDueResult",
        }
        external_schema_mapping = {
            "UsageConfiguration": ("usage-config.schema.json", None),
            "LocalUsageEvent": ("usage-event.schema.json", "local_event"),
            "UsageSummary": ("usage-summary.schema.json", None),
            "MaintenanceFinding": ("maintenance-finding.schema.json", None),
            "MaintenanceProposal": ("maintenance-proposal.schema.json", None),
        }
        for filename, schema_name in mapping.items():
            with self.subTest(filename=filename):
                instance = json.loads((EXAMPLE_ROOT / filename).read_text(encoding="utf-8"))
                if schema_name == "EmpiricalGateReport":
                    schema = self.schemas[EMPIRICAL_SCHEMA_PATH.name]
                    errors = list(
                        Draft202012Validator(
                            schema, format_checker=FormatChecker()
                        ).iter_errors(instance)
                    )
                elif schema_name in external_schema_mapping:
                    filename, definition = external_schema_mapping[schema_name]
                    schema = self.schemas[filename]
                    if definition is not None:
                        schema = {
                            "$schema": schema["$schema"],
                            "$ref": f"#/$defs/{definition}",
                            "$defs": schema["$defs"],
                        }
                    errors = list(
                        Draft202012Validator(
                            schema, format_checker=FormatChecker()
                        ).iter_errors(instance)
                    )
                elif schema_name == "UsageDueResult":
                    schema = json.loads(
                        json.dumps(self.openapi["components"]["schemas"][schema_name])
                    )
                    schema["properties"]["summary"] = self.schemas[
                        "usage-summary.schema.json"
                    ]
                    schema["properties"]["findings"]["items"] = self.schemas[
                        "maintenance-finding.schema.json"
                    ]
                    errors = list(
                        Draft202012Validator(
                            schema, format_checker=FormatChecker()
                        ).iter_errors(instance)
                    )
                else:
                    schema = self.openapi["components"]["schemas"][schema_name]
                    resolver = RefResolver(
                        base_uri=OPENAPI_PATH.resolve().as_uri(), referrer=self.openapi
                    )
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", DeprecationWarning)
                        errors = list(
                            Draft202012Validator(
                                schema, resolver=resolver
                            ).iter_errors(instance)
                        )
                self.assertEqual(errors, [], [error.message for error in errors])

    def test_response_examples_are_reachable_outputs(self) -> None:
        inspection = json.loads(
            (EXAMPLE_ROOT / "inspect-response.json").read_text(encoding="utf-8")
        )
        derived = {
            key: signal
            for key, signal in (
                ("contract_files", "openapi-contract"),
                ("schema_files", "json-schema"),
                ("governance_profiles", "governance-profile"),
                ("ci_files", "ci"),
                ("generation_signals", "code-generation"),
            )
        }
        for key, signal in derived.items():
            if inspection[key]:
                self.assertIn(signal, inspection["project_signals"])

        comparison = json.loads(
            (EXAMPLE_ROOT / "generation-comparison-response.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(sum(comparison["summary"].values()), len(comparison["files"]))
        observed: dict[str, int] = {}
        for row in comparison["files"]:
            observed[row["state"]] = observed.get(row["state"], 0) + 1
        for state, count in comparison["summary"].items():
            self.assertEqual(observed.get(state, 0), count)

    def test_openapi_links_every_response_example(self) -> None:
        external_values = {
            node["externalValue"]
            for node in walk(self.openapi)
            if isinstance(node, dict) and "externalValue" in node
        }
        self.assertEqual(
            external_values,
            {
                "./examples/error-response.json",
                "./examples/empirical-gate-request.json",
                "./examples/empirical-gate-response.json",
                "./examples/inspect-response.json",
                "./examples/profile-validation-response.json",
                "./examples/profile-state-response.json",
                "./examples/generation-comparison-response.json",
                "./examples/usage-status-response.json",
                "./examples/usage-record-response.json",
                "./examples/usage-summary-response.json",
                "./examples/usage-trend-response.json",
                "./examples/maintenance-proposal-response.json",
                "./examples/maintenance-promotion-response.json",
                "./examples/usage-due-response.json",
            },
        )


if __name__ == "__main__":
    unittest.main()
