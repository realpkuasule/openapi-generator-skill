#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

LOCAL_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(LOCAL_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(LOCAL_REPO_ROOT))

from scripts.evals.harness import harness_digest
from scripts.evals.score_result import EvalResultError, validate_result
from scripts.install_skill import tree_digest


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "openapi-engineering"
SCHEMA_ROOT = REPO_ROOT / "contracts" / "schemas"
REPORT_SCHEMA = SCHEMA_ROOT / "forward-eval-report.schema.json"
DEFAULT_REQUIRED_CASES = (
    "animator-mixed-boundaries",
    "revoice-no-codegen",
    "audit-discovers-upgrade",
    "profile-reuse",
    "untrusted-input",
)
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_boundary_strategy_sets(
    codex: list[str], claude: list[str]
) -> tuple[bool, list[str]]:
    codex_set = set(codex)
    claude_set = set(claude)
    if codex_set == claude_set:
        return True, []
    common = codex_set & claude_set
    difference = codex_set ^ claude_set
    if difference == {"language-native"} and "no-codegen" in common:
        return True, ["language-native refines shared no-codegen maintenance"]
    return False, []


def aggregate_validator() -> Draft202012Validator:
    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in SCHEMA_ROOT.glob("*.json")
    }
    schema = schemas[REPORT_SCHEMA.name]
    registry = Registry().with_resources(
        (candidate["$id"], Resource.from_contents(candidate))
        for candidate in schemas.values()
    )
    return Draft202012Validator(
        schema, registry=registry, format_checker=FormatChecker()
    )


def validate_aggregate_report(report: dict[str, Any]) -> None:
    errors = sorted(
        aggregate_validator().iter_errors(report), key=lambda item: list(item.path)
    )
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].path)
        raise ValueError(
            f"Forward report violates its schema at {location or '/'}: "
            f"{errors[0].message}"
        )


def check_aggregate_report(
    path: Path, *, expected_skill_sha256: str, expected_harness_sha256: str
) -> tuple[str, int]:
    path = path.expanduser().resolve()
    if not path.is_file():
        return f"forward report is missing: {path}", 2
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        validate_aggregate_report(report)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return f"forward report is invalid: {exc}", 2
    if report["status"] == "blocked":
        return "forward report is blocked", 2
    if report["status"] != "passed":
        return "forward report failed", 1
    if report["skill_sha256"] != expected_skill_sha256:
        return "forward report is stale for the current Skill digest", 2
    if report["harness_sha256"] != expected_harness_sha256:
        return "forward report is stale for the current evaluation harness digest", 2
    if tuple(report["required_cases"]) != DEFAULT_REQUIRED_CASES:
        return "forward report does not cover the complete required case set", 2
    if report["minimum_samples"] < 2:
        return "forward report requires fewer than two samples per case", 2
    source_by_adapter: dict[str, Path] = {}
    for platform in report["platforms"]:
        source = Path(platform["source_report"])
        if not source.is_absolute():
            source = REPO_ROOT / source
        if not source.is_file() or sha256_file(source) != platform["source_sha256"]:
            return f"forward report source evidence is stale: {source}", 2
        source_by_adapter[platform["adapter"]] = source
    if set(source_by_adapter) != {"codex", "claude"}:
        return "forward report does not identify one source per platform", 2
    recomputed, recomputed_exit = aggregate_reports(
        source_by_adapter["codex"],
        source_by_adapter["claude"],
        required_cases=tuple(report["required_cases"]),
        minimum_samples=report["minimum_samples"],
    )
    recomputed["generated_at"] = report["generated_at"]
    if recomputed_exit != 0 or recomputed != report:
        return "forward report does not match the recomputed source evidence", 1
    return "forward report passed and matches the current Skill digest", 0


def _stub(path: Path, adapter: str, error: str) -> dict[str, Any]:
    return {
        "adapter": adapter,
        "load_error": error,
        "skill_sha256": None,
        "harness_sha256": None,
        "platform_versions": [],
        "source_report": str(path.resolve()),
        "source_sha256": sha256_file(path) if path.is_file() else None,
        "samples": 0,
        "timeout_seconds": 0,
        "case_ids": [],
        "requested_results": 0,
        "completed_results": 0,
        "status": "blocked",
        "result_count": 0,
        "passed_count": 0,
        "case_counts": [],
        "results": [],
    }


def _load_platform(path: Path, expected_adapter: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        return _stub(path, expected_adapter, "source report is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _stub(path, expected_adapter, f"source report cannot be loaded: {exc}")
    if not isinstance(payload, dict):
        return _stub(path, expected_adapter, "source report must be an object")
    required = {
        "report_version",
        "adapter",
        "skill_sha256",
        "harness_sha256",
        "samples",
        "timeout_seconds",
        "case_ids",
        "requested_results",
        "completed_results",
        "status",
        "results",
    }
    missing = sorted(required - payload.keys())
    if missing:
        return _stub(path, expected_adapter, f"source report misses: {', '.join(missing)}")
    if payload["report_version"] != 2:
        return _stub(path, expected_adapter, "unsupported source report version")
    if payload["adapter"] != expected_adapter:
        return _stub(path, expected_adapter, "source report adapter does not match input")
    if not isinstance(payload["samples"], int) or isinstance(payload["samples"], bool):
        return _stub(path, expected_adapter, "source report samples must be an integer")
    if (
        not isinstance(payload["timeout_seconds"], int)
        or isinstance(payload["timeout_seconds"], bool)
        or payload["timeout_seconds"] < 1
    ):
        return _stub(
            path, expected_adapter, "source report timeout_seconds must be positive"
        )
    if (
        not isinstance(payload["case_ids"], list)
        or not payload["case_ids"]
        or not all(
            isinstance(case_id, str) and case_id for case_id in payload["case_ids"]
        )
        or len(payload["case_ids"]) != len(set(payload["case_ids"]))
    ):
        return _stub(path, expected_adapter, "source report case_ids are invalid")
    if (
        not isinstance(payload["requested_results"], int)
        or isinstance(payload["requested_results"], bool)
        or payload["requested_results"] < 1
    ):
        return _stub(
            path, expected_adapter, "source report requested_results must be positive"
        )
    if (
        not isinstance(payload["completed_results"], int)
        or isinstance(payload["completed_results"], bool)
        or payload["completed_results"] < 0
    ):
        return _stub(
            path,
            expected_adapter,
            "source report completed_results must be non-negative",
        )
    if payload["status"] not in {"passed", "failed", "blocked"}:
        return _stub(path, expected_adapter, "source report status is invalid")
    if not isinstance(payload["skill_sha256"], str) or not SHA256_PATTERN.fullmatch(
        payload["skill_sha256"]
    ):
        return _stub(path, expected_adapter, "source report Skill digest is invalid")
    if not isinstance(payload["harness_sha256"], str) or not SHA256_PATTERN.fullmatch(
        payload["harness_sha256"]
    ):
        return _stub(path, expected_adapter, "source report harness digest is invalid")
    if not isinstance(payload["results"], list):
        return _stub(path, expected_adapter, "source report results must be an array")
    if payload["completed_results"] != len(payload["results"]):
        return _stub(
            path,
            expected_adapter,
            "source report completed_results does not match results",
        )
    if payload["completed_results"] > payload["requested_results"]:
        return _stub(
            path, expected_adapter, "source report completed_results exceeds its plan"
        )
    if payload["requested_results"] != payload["samples"] * len(payload["case_ids"]):
        return _stub(
            path, expected_adapter, "source report requested_results mismatches its plan"
        )
    try:
        for result in payload["results"]:
            validate_result(result)
            if result["adapter"] != expected_adapter:
                raise EvalResultError("result adapter does not match source report")
    except (EvalResultError, TypeError) as exc:
        return _stub(path, expected_adapter, f"source result is invalid: {exc}")
    expected_sequence = payload["case_ids"] * payload["samples"]
    observed_sequence = [result["case_id"] for result in payload["results"]]
    if observed_sequence != expected_sequence[: len(observed_sequence)]:
        return _stub(
            path, expected_adapter, "source report results are not its ordered plan prefix"
        )

    counts = Counter(result["case_id"] for result in payload["results"])
    return {
        "adapter": expected_adapter,
        "load_error": None,
        "skill_sha256": payload["skill_sha256"],
        "harness_sha256": payload["harness_sha256"],
        "platform_versions": sorted(
            {result["platform_version"] for result in payload["results"]}
        ),
        "source_report": str(path),
        "source_sha256": sha256_file(path),
        "samples": payload["samples"],
        "timeout_seconds": payload["timeout_seconds"],
        "case_ids": payload["case_ids"],
        "requested_results": payload["requested_results"],
        "completed_results": payload["completed_results"],
        "status": payload["status"],
        "result_count": len(payload["results"]),
        "passed_count": sum(
            result["status"] == "passed" for result in payload["results"]
        ),
        "case_counts": [
            {"case_id": case_id, "count": count}
            for case_id, count in sorted(counts.items())
        ],
        "results": payload["results"],
    }


def _public_platform(info: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in info.items() if key != "results"}


def aggregate_reports(
    codex_report: Path,
    claude_report: Path,
    *,
    required_cases: tuple[str, ...] = DEFAULT_REQUIRED_CASES,
    minimum_samples: int = 2,
) -> tuple[dict[str, Any], int]:
    if minimum_samples < 2:
        raise ValueError("minimum_samples must be at least two")
    infos = {
        "codex": _load_platform(codex_report, "codex"),
        "claude": _load_platform(claude_report, "claude"),
    }
    blocked: list[str] = []
    failed: list[str] = []

    for adapter, info in infos.items():
        if info["load_error"]:
            blocked.append(f"{adapter}: {info['load_error']}")
            continue
        if info["samples"] < minimum_samples:
            blocked.append(
                f"{adapter} declares {info['samples']} samples; {minimum_samples} required"
            )
        if info["completed_results"] != info["requested_results"]:
            blocked.append(f"{adapter} source checkpoint is incomplete")
        if set(info["case_ids"]) != set(required_cases):
            blocked.append(f"{adapter} source plan does not match required cases")
        counts = Counter(result["case_id"] for result in info["results"])
        for case_id in required_cases:
            if counts[case_id] < minimum_samples:
                blocked.append(
                    f"{adapter} has {counts[case_id]} results for {case_id}; "
                    f"{minimum_samples} required"
                )
        if info["status"] == "blocked":
            blocked.append(f"{adapter} source report is blocked")
        elif info["status"] == "failed":
            failed.append(f"{adapter} source report failed")

        for result in info["results"]:
            if result["case_id"] not in required_cases:
                continue
            label = f"{adapter}/{result['case_id']}"
            if result["status"] == "blocked":
                blocked.append(f"{label} is blocked")
            elif result["status"] != "passed":
                failed.append(f"{label} failed")
            if result["file_hashes"]["before"] != result["file_hashes"]["after"]:
                failed.append(f"{label} changed the fixture")
            if result["prohibited_actions_violated"]:
                failed.append(f"{label} violated prohibited actions")

    digests = {
        info["skill_sha256"]
        for info in infos.values()
        if info["skill_sha256"] is not None
    }
    same_digest = len(digests) == 1 and all(
        info["skill_sha256"] is not None for info in infos.values()
    )
    if not same_digest:
        blocked.append("platform reports do not share one Skill digest")
    harness_digests = {
        info["harness_sha256"]
        for info in infos.values()
        if info["harness_sha256"] is not None
    }
    same_harness_digest = len(harness_digests) == 1 and all(
        info["harness_sha256"] is not None for info in infos.values()
    )
    if not same_harness_digest:
        blocked.append("platform reports do not share one evaluation harness digest")
    if all(not info["load_error"] for info in infos.values()) and (
        infos["codex"]["case_ids"] != infos["claude"]["case_ids"]
    ):
        blocked.append("platform reports do not share one ordered case plan")

    case_equivalence: list[dict[str, Any]] = []
    for case_id in required_cases:
        by_adapter: dict[str, list[str]] = {}
        boundary_strategies: dict[str, list[str]] = {}
        for adapter, info in infos.items():
            by_adapter[adapter] = sorted(
                {
                    result["tool_decision"]["primary_strategy"]
                    for result in info["results"]
                    if result["case_id"] == case_id
                }
            )
            boundary_strategies[adapter] = sorted(
                {
                    boundary["strategy"]
                    for result in info["results"]
                    if result["case_id"] == case_id
                    for boundary in result["tool_decision"]["boundaries"]
                }
            )
        matrix_equivalent, strategy_refinements = compare_boundary_strategy_sets(
            boundary_strategies["codex"], boundary_strategies["claude"]
        )
        accepted_boundary_strategies = set(
            boundary_strategies["codex"] + boundary_strategies["claude"]
        )
        primary_rankings_are_covered = set(
            by_adapter["codex"] + by_adapter["claude"]
        ).issubset(accepted_boundary_strategies)
        strategy_equivalent = (
            bool(by_adapter["codex"])
            and bool(by_adapter["claude"])
            and matrix_equivalent
            and primary_rankings_are_covered
        )
        case_results = [
            result
            for info in infos.values()
            for result in info["results"]
            if result["case_id"] == case_id
        ]
        input_digests = {result["input_sha256"] for result in case_results}
        fixture_digests = {
            result["file_hashes"]["before"] for result in case_results
        }
        same_input_digest = bool(case_results) and len(input_digests) == 1
        same_fixture_digest = bool(case_results) and len(fixture_digests) == 1
        equivalent = (
            strategy_equivalent and same_input_digest and same_fixture_digest
        )
        if not strategy_equivalent and all(
            not info["load_error"] for info in infos.values()
        ):
            failed.append(f"primary strategy mismatch for {case_id}")
        if not same_input_digest and all(
            not info["load_error"] for info in infos.values()
        ):
            failed.append(f"input digest mismatch for {case_id}")
        if not same_fixture_digest and all(
            not info["load_error"] for info in infos.values()
        ):
            failed.append(f"fixture digest mismatch for {case_id}")
        case_equivalence.append(
            {
                "case_id": case_id,
                "codex_primary_strategies": by_adapter["codex"],
                "claude_primary_strategies": by_adapter["claude"],
                "codex_boundary_strategies": boundary_strategies["codex"],
                "claude_boundary_strategies": boundary_strategies["claude"],
                "strategy_refinements": strategy_refinements,
                "same_input_digest": same_input_digest,
                "same_fixture_digest": same_fixture_digest,
                "equivalent": equivalent,
            }
        )

    reasons = sorted(set(blocked + failed))
    if blocked:
        status, exit_code = "blocked", 2
    elif failed:
        status, exit_code = "failed", 1
    else:
        status, exit_code = "passed", 0
    filesystem_passed = all(
        result["file_hashes"]["before"] == result["file_hashes"]["after"]
        for info in infos.values()
        for result in info["results"]
        if result["case_id"] in required_cases
    ) and all(info["results"] for info in infos.values())
    hard_gates_passed = status == "passed" and filesystem_passed
    report = {
        "report_version": 1,
        "status": status,
        "generated_at": utc_now(),
        "skill_sha256": next(iter(digests)) if same_digest else None,
        "harness_sha256": (
            next(iter(harness_digests)) if same_harness_digest else None
        ),
        "required_cases": list(required_cases),
        "minimum_samples": minimum_samples,
        "platforms": [_public_platform(infos[name]) for name in ("codex", "claude")],
        "equivalence": {
            "same_skill_digest": same_digest,
            "same_harness_digest": same_harness_digest,
            "hard_gates_passed": hard_gates_passed,
            "filesystem_invariants_passed": filesystem_passed,
            "cases": case_equivalence,
            "reasons": reasons,
        },
    }
    validate_aggregate_report(report)
    return report, exit_code


def write_report(path: Path, report: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate fresh Codex and Claude Code forward-evaluation reports."
    )
    parser.add_argument("--codex-report", type=Path)
    parser.add_argument("--claude-report", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--check-report",
        type=Path,
        help="Validate an existing combined report without invoking a model platform.",
    )
    parser.add_argument("--minimum-samples", type=int, default=2)
    args = parser.parse_args()
    if args.minimum_samples < 2:
        parser.error("--minimum-samples must be at least 2")
    if args.check_report:
        if args.codex_report or args.claude_report or args.report:
            parser.error("--check-report cannot be combined with aggregation inputs")
        message, exit_code = check_aggregate_report(
            args.check_report,
            expected_skill_sha256=tree_digest(SKILL_ROOT),
            expected_harness_sha256=harness_digest(),
        )
        print(json.dumps({"message": message, "status": exit_code}, sort_keys=True))
        return exit_code
    if not args.codex_report or not args.claude_report or not args.report:
        parser.error(
            "--codex-report, --claude-report, and --report are required for aggregation"
        )
    report, exit_code = aggregate_reports(
        args.codex_report,
        args.claude_report,
        minimum_samples=args.minimum_samples,
    )
    write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
