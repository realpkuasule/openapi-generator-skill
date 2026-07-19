#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from adapters import (
    AdapterBlocked,
    AdapterFailure,
    blocked_analyzer,
    failed_analyzer,
    run_claude,
    run_codex,
    run_fake,
    validate_semantic_result,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "contracts" / "schemas"
ANALYSIS_SCHEMA = SCHEMA_ROOT / "maintenance-analysis.schema.json"
FINDING_SCHEMA = SCHEMA_ROOT / "maintenance-finding.schema.json"
EVENT_SCHEMA = SCHEMA_ROOT / "usage-event.schema.json"


class InputBlocked(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputBlocked("Input JSON could not be loaded.") from exc


def schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def errors_for(instance: Any, value_schema: dict[str, Any]) -> list[str]:
    return [
        error.message
        for error in Draft202012Validator(
            value_schema, format_checker=FormatChecker()
        ).iter_errors(instance)
    ]


def validate_bundle(value: Any, max_events: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"findings", "sanitized_events"}:
        raise InputBlocked("Finding bundle has an invalid field set.")
    if not isinstance(value["findings"], list) or not value["findings"]:
        raise InputBlocked("Finding bundle requires findings.")
    if not isinstance(value["sanitized_events"], list) or len(value["sanitized_events"]) > max_events:
        raise InputBlocked("Finding bundle exceeds the event limit.")
    finding_schema = schema(FINDING_SCHEMA)
    event_schema = schema(EVENT_SCHEMA)
    sanitized_schema = {
        "$schema": event_schema["$schema"],
        "$ref": "#/$defs/sanitized_event",
        "$defs": event_schema["$defs"],
    }
    if any(errors_for(item, finding_schema) for item in value["findings"]):
        raise InputBlocked("Finding bundle contains an invalid finding.")
    if any(errors_for(item, sanitized_schema) for item in value["sanitized_events"]):
        raise InputBlocked("Finding bundle contains a non-sanitized event.")
    return value


def validated_resume_analysis(
    path: Path,
    *,
    input_sha256: str,
    finding_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    value = load_json(path)
    if errors_for(value, schema(ANALYSIS_SCHEMA)):
        raise InputBlocked("Resume analysis does not satisfy the analysis contract.")
    if value["input_sha256"] != input_sha256:
        raise InputBlocked("Resume analysis input digest does not match.")
    if value["finding_ids"] != sorted(finding_ids):
        raise InputBlocked("Resume analysis finding IDs do not match.")

    primary = value["primary"]
    sequence = value["analyzer_sequence"]
    review = value["secondary_review"]
    if (
        primary["platform"] != "codex"
        or primary["status"] != "passed"
        or not sequence
        or sequence[0] != primary
    ):
        raise InputBlocked("Resume analysis does not contain a reusable Codex primary result.")
    if (
        not review["required"]
        or review["status"] not in {"blocked", "failed"}
        or review["result"] is not None
        or any(item["status"] == "passed" for item in sequence[1:])
    ):
        raise InputBlocked("Resume analysis is not eligible for secondary-review recovery.")
    if len(sequence) == 1:
        if review["analyzer"] is not None:
            raise InputBlocked("Resume analysis secondary-review evidence is inconsistent.")
    elif (
        sequence[1] != review["analyzer"]
        or sequence[1]["platform"] != "claude"
        or sequence[1]["status"] not in {"blocked", "failed"}
    ):
        raise InputBlocked("Resume analysis secondary-review evidence is inconsistent.")

    try:
        semantic = validate_semantic_result(
            {
                "clusters": value["clusters"],
                "confidence": value["confidence"],
                "candidate_causes": value["candidate_causes"],
                "unverified": value["unverified"],
            },
            finding_ids,
        )
    except AdapterFailure as exc:
        raise InputBlocked("Resume analysis semantic result is invalid.") from exc
    expected_analysis_id = "analysis-" + sha256_value(
        {
            "input": input_sha256,
            "semantic": semantic,
            "sequence": sequence,
            "review": review,
        }
    )[:16]
    if value["analysis_id"] != expected_analysis_id:
        raise InputBlocked("Resume analysis ID is not self-consistent.")
    return semantic, primary, review["trigger_reasons"]


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise InputBlocked("Output path is a symbolic link.")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def emit_error(status: str, code: str, message: str) -> None:
    print(json.dumps({"status": status, "error": {"code": code, "message": message}}, sort_keys=True))


def review_reasons(
    bundle: dict[str, Any], semantic: dict[str, Any] | None, primary_blocked: bool
) -> list[str]:
    reasons = []
    rule_ids = {item["rule_id"] for item in bundle["findings"]}
    if "SI-SAFETY-001" in rule_ids:
        reasons.append("safety")
    if "SI-PLATFORM-001" in rule_ids:
        reasons.append("platform-drift")
    if any(
        item["severity"] in {"P0", "P1"} or item["requires_secondary_review"]
        for item in bundle["findings"]
    ):
        reasons.append("severity-p0-p1")
    if semantic is not None and semantic["confidence"] < 0.75:
        reasons.append("low-confidence")
    if primary_blocked:
        reasons.append("primary-blocked")
    return reasons


def compare_semantics(
    primary: dict[str, Any], secondary: dict[str, Any]
) -> tuple[list[str], list[str]]:
    agreements = []
    disagreements = []
    comparisons = {
        "cluster-keys": {
            item["key"] for item in primary["clusters"]
        }
        == {item["key"] for item in secondary["clusters"]},
        "candidate-causes": primary["candidate_causes"] == secondary["candidate_causes"],
        "unverified": primary["unverified"] == secondary["unverified"],
        "confidence-band": int(primary["confidence"] * 4) == int(secondary["confidence"] * 4),
    }
    for name, matches in comparisons.items():
        (agreements if matches else disagreements).append(name)
    return agreements, disagreements


def independent(primary: dict[str, Any], secondary: dict[str, Any]) -> bool:
    if primary["platform"] == secondary["platform"]:
        return False
    if primary["session_id"] == secondary["session_id"]:
        return False
    if (
        primary["cli_version"] is not None
        and secondary["cli_version"] is not None
        and primary["cli_version"] == secondary["cli_version"]
    ):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze sanitized maintenance findings.")
    parser.add_argument("--findings", type=Path, required=True)
    parser.add_argument("--adapter", choices=("fake", "codex"), default="codex")
    parser.add_argument(
        "--credential-mode",
        choices=("environment", "active-cli-session"),
        default="environment",
    )
    parser.add_argument("--resume-analysis", type=Path)
    parser.add_argument("--fake-response", type=Path)
    parser.add_argument("--fake-platform", choices=("fake", "codex", "claude"), default="fake")
    parser.add_argument(
        "--secondary-adapter", choices=("none", "fake", "claude"), default="claude"
    )
    parser.add_argument("--secondary-fake-response", type=Path)
    parser.add_argument(
        "--secondary-fake-platform", choices=("fake", "codex", "claude"), default="claude"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--now")
    parser.add_argument("--max-events", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--rss-warning-mb", type=int, default=512)
    parser.add_argument("--rss-hard-mb", type=int, default=1024)
    args = parser.parse_args()
    try:
        if (
            not 1 <= args.max_events <= 50
            or not 1 <= args.timeout_seconds <= 600
            or args.rss_warning_mb < 1
            or args.rss_hard_mb <= args.rss_warning_mb
        ):
            raise InputBlocked("Resource limits are invalid.")
        warning_limit_bytes = args.rss_warning_mb * 1024 * 1024
        hard_limit_bytes = args.rss_hard_mb * 1024 * 1024
        bundle = validate_bundle(load_json(args.findings.resolve()), args.max_events)
        finding_ids = {item["finding_id"] for item in bundle["findings"]}
        input_sha256 = sha256_value(bundle)
        primary_blocked = False
        if args.resume_analysis is not None:
            if args.adapter != "codex" or args.secondary_adapter == "none":
                raise InputBlocked(
                    "Resume analysis requires Codex primary evidence and a secondary adapter."
                )
            semantic, primary, previous_triggers = validated_resume_analysis(
                args.resume_analysis.expanduser().resolve(),
                input_sha256=input_sha256,
                finding_ids=finding_ids,
            )
        else:
            try:
                if args.adapter == "fake":
                    if args.fake_response is None:
                        raise InputBlocked("Fake adapter requires --fake-response.")
                    semantic, primary = run_fake(
                        args.fake_response.resolve(),
                        finding_ids,
                        args.fake_platform,
                        warning_limit_bytes=warning_limit_bytes,
                        hard_limit_bytes=hard_limit_bytes,
                    )
                else:
                    semantic, primary = run_codex(
                        bundle,
                        finding_ids,
                        args.timeout_seconds,
                        warning_limit_bytes,
                        hard_limit_bytes,
                        args.credential_mode,
                    )
            except AdapterBlocked as exc:
                primary_blocked = True
                semantic = None
                primary = blocked_analyzer(
                    "codex",
                    bundle,
                    exc.resources,
                    warning_limit_bytes=warning_limit_bytes,
                    hard_limit_bytes=hard_limit_bytes,
                    failure_code=exc.code,
                )

        sequence = [primary]
        triggers = review_reasons(bundle, semantic, primary_blocked)
        if args.resume_analysis is not None:
            if previous_triggers != triggers:
                raise InputBlocked("Resume analysis review triggers do not match.")
        review = {
            "required": bool(triggers),
            "trigger_reasons": triggers,
            "status": "not-required" if not triggers else "blocked",
            "analyzer": None,
            "independent": False,
            "result": None,
            "agreements": [],
            "disagreements": [],
        }
        secondary_semantic = None
        review_blocked = False
        if triggers:
            if args.secondary_adapter == "none":
                review_blocked = True
            else:
                secondary_platform = (
                    args.secondary_fake_platform
                    if args.secondary_adapter == "fake"
                    else "claude"
                )
                try:
                    if args.secondary_adapter == "fake":
                        if args.secondary_fake_response is None:
                            raise AdapterBlocked(
                                "Fake secondary adapter requires --secondary-fake-response."
                            )
                        secondary_semantic, secondary = run_fake(
                            args.secondary_fake_response.resolve(),
                            finding_ids,
                            secondary_platform,
                            warning_limit_bytes=warning_limit_bytes,
                            hard_limit_bytes=hard_limit_bytes,
                        )
                    else:
                        secondary_semantic, secondary = run_claude(
                            bundle,
                            finding_ids,
                            args.timeout_seconds,
                            warning_limit_bytes,
                            hard_limit_bytes,
                            args.credential_mode,
                        )
                    if not independent(primary, secondary):
                        raise AdapterFailure(
                            "Secondary review is not independent.",
                            code="not-independent",
                            resources=secondary["resources"],
                            cli_version=secondary["cli_version"],
                            model=secondary["model"],
                        )
                    sequence.append(secondary)
                    review.update(
                        status="passed",
                        analyzer=secondary,
                        independent=True,
                        result=secondary_semantic,
                    )
                except (AdapterBlocked, AdapterFailure) as exc:
                    review_blocked = True
                    if isinstance(exc, AdapterBlocked):
                        secondary = blocked_analyzer(
                            secondary_platform,
                            bundle,
                            exc.resources,
                            warning_limit_bytes=warning_limit_bytes,
                            hard_limit_bytes=hard_limit_bytes,
                            failure_code=exc.code,
                        )
                        review_status = "blocked"
                    else:
                        secondary = failed_analyzer(
                            secondary_platform,
                            bundle,
                            exc,
                            warning_limit_bytes=warning_limit_bytes,
                            hard_limit_bytes=hard_limit_bytes,
                        )
                        review_status = "failed"
                    sequence.append(secondary)
                    review.update(
                        status=review_status,
                        analyzer=secondary,
                        independent=independent(primary, secondary),
                    )

        accepted_semantic = semantic or secondary_semantic
        if accepted_semantic is None:
            raise AdapterBlocked("No analyzer produced a valid semantic result.")
        if semantic is not None and secondary_semantic is not None:
            agreements, disagreements = compare_semantics(semantic, secondary_semantic)
            review.update(agreements=agreements, disagreements=disagreements)
        generated_at = args.now or utc_now()
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InputBlocked("Timestamp is invalid.") from exc
        analysis = {
            "schema_version": 1,
            "analysis_id": f"analysis-{sha256_value({'input': input_sha256, 'semantic': accepted_semantic, 'sequence': sequence, 'review': review})[:16]}",
            "generated_at": generated_at,
            "input_sha256": input_sha256,
            "finding_ids": sorted(finding_ids),
            "primary": primary,
            "analyzer_sequence": sequence,
            "secondary_review": review,
            **accepted_semantic,
        }
        validation_errors = errors_for(analysis, schema(ANALYSIS_SCHEMA))
        if validation_errors:
            raise AdapterFailure("Analyzer output does not satisfy the analysis contract.")
        atomic_write_json(args.output.expanduser().resolve(), analysis)
        print(json.dumps(analysis, ensure_ascii=False, sort_keys=True))
        return 2 if primary_blocked or review_blocked else 0
    except InputBlocked as exc:
        emit_error("blocked", "input-blocked", str(exc))
        return 2
    except AdapterBlocked as exc:
        emit_error("blocked", "adapter-blocked", str(exc))
        return 2
    except AdapterFailure as exc:
        emit_error("failed", "adapter-failed", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
