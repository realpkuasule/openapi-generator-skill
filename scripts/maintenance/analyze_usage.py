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
    run_claude,
    run_codex,
    run_fake,
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
        primary_blocked = False
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
            )

        sequence = [primary]
        triggers = review_reasons(bundle, semantic, primary_blocked)
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
                        )
                    if not independent(primary, secondary):
                        raise AdapterBlocked("Secondary review is not independent.")
                    sequence.append(secondary)
                    review.update(
                        status="passed",
                        analyzer=secondary,
                        independent=True,
                        result=secondary_semantic,
                    )
                except (AdapterBlocked, AdapterFailure) as exc:
                    review_blocked = True
                    secondary = blocked_analyzer(
                        secondary_platform,
                        bundle,
                        exc.resources if isinstance(exc, AdapterBlocked) else None,
                        warning_limit_bytes=warning_limit_bytes,
                        hard_limit_bytes=hard_limit_bytes,
                    )
                    sequence.append(secondary)
                    review.update(analyzer=secondary, independent=independent(primary, secondary))

        accepted_semantic = semantic or secondary_semantic
        if accepted_semantic is None:
            raise AdapterBlocked("No analyzer produced a valid semantic result.")
        if semantic is not None and secondary_semantic is not None:
            agreements, disagreements = compare_semantics(semantic, secondary_semantic)
            review.update(agreements=agreements, disagreements=disagreements)
        input_sha256 = sha256_value(bundle)
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
