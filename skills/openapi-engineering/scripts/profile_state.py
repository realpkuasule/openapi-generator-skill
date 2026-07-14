#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from validate_profile import load_profile, validate


SUBJECT = "contract.sources_of_truth"
JSON_POINTER = "/contract/sources_of_truth"


def emit(payload: dict[str, Any], pretty: bool) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
        )
    )


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


def load_valid_profile(path: Path) -> dict[str, Any]:
    profile = load_profile(path)
    if not isinstance(profile, dict):
        raise ValueError("Profile must be an object.")
    findings = validate(profile)
    if findings:
        raise ValueError("Profile does not satisfy the authoritative schema.")
    return profile


def observed_sources(inspection: dict[str, Any]) -> list[str]:
    contracts = inspection.get("contract_files", [])
    schemas = inspection.get("schema_files", [])
    if not isinstance(contracts, list) or not isinstance(schemas, list):
        raise ValueError("Inspection contract_files and schema_files must be arrays.")
    if not all(isinstance(item, str) for item in contracts + schemas):
        raise ValueError("Inspection contract and schema paths must be strings.")
    return sorted(set(contracts + schemas))


def evidence_paths(inspection: dict[str, Any], kinds: set[str]) -> list[str]:
    rows = inspection.get("evidence", [])
    if not isinstance(rows, list):
        return []
    return sorted(
        {
            row["path"]
            for row in rows
            if isinstance(row, dict)
            and row.get("kind") in kinds
            and isinstance(row.get("path"), str)
        }
    )


def observed_tools(inspection: dict[str, Any]) -> list[str]:
    signals = inspection.get("generation_signals", [])
    if not isinstance(signals, list) or not all(isinstance(item, str) for item in signals):
        raise ValueError("Inspection generation_signals must be an array of strings.")
    return sorted(
        {
            signal.removesuffix("-config")
            for signal in signals
            if signal.endswith("-config")
        }
    )


def output_sets_equivalent(profile_paths: list[str], observed_paths: list[str]) -> bool:
    def overlaps(left: str, right: str) -> bool:
        return left == right or left.startswith(right + "/") or right.startswith(left + "/")

    return all(any(overlaps(path, observed) for observed in observed_paths) for path in profile_paths) and all(
        any(overlaps(path, observed) for path in profile_paths) for observed in observed_paths
    )


def changed_item(
    path: str,
    profile_value: Any,
    observed_value: Any,
    *,
    state: str,
    provenance: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "path": path,
        "state": state,
        "profile_value": profile_value,
        "observed_value": observed_value,
        "provenance": provenance,
        "evidence_paths": evidence,
    }


def source_provenance(profile: dict[str, Any]) -> str:
    statements = profile.get("statements", [])
    if not isinstance(statements, list):
        return "inferred"
    for statement in statements:
        if (
            isinstance(statement, dict)
            and statement.get("subject") == SUBJECT
            and statement.get("provenance") == "user-decided"
        ):
            return "user-decided"
    return "observed"


def compare(profile: dict[str, Any], inspection: dict[str, Any]) -> dict[str, Any]:
    current = sorted(set(profile["contract"]["sources_of_truth"]))
    observed = observed_sources(inspection)
    profile_sha256 = digest(profile)
    truncated = inspection.get("truncated") is True
    changes: list[dict[str, Any]] = []
    if current != observed:
        provenance = source_provenance(profile)
        state = "unknown" if truncated else "conflict" if provenance == "user-decided" else "changed"
        changes.append(
            changed_item(
                JSON_POINTER,
                current,
                observed,
                state=state,
                provenance=provenance,
                evidence=evidence_paths(inspection, {"contract", "schema"}),
            )
        )

    if "generation_signals" in inspection:
        current_tools = sorted({tool["name"] for tool in profile["decision"]["tools"]})
        tools = observed_tools(inspection)
        if current_tools != tools:
            changes.append(
                changed_item(
                    "/decision/tools",
                    current_tools,
                    tools,
                    state="unknown" if truncated else "conflict",
                    provenance="user-decided",
                    evidence=evidence_paths(inspection, {"generator"}),
                )
            )

    if "generated_directories" in inspection:
        current_outputs = sorted(set(profile["generation"]["output_directories"]))
        outputs = inspection["generated_directories"]
        if not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs):
            raise ValueError("Inspection generated_directories must be an array of strings.")
        outputs = sorted(set(outputs))
        if not output_sets_equivalent(current_outputs, outputs):
            changes.append(
                changed_item(
                    "/generation/output_directories",
                    current_outputs,
                    outputs,
                    state="unknown" if truncated else "conflict",
                    provenance="user-decided",
                    evidence=outputs,
                )
            )

    states = {change["state"] for change in changes}
    if "conflict" in states:
        state = "conflict"
    elif "unknown" in states:
        state = "unknown"
    elif "changed" in states:
        state = "changed"
    else:
        state = "unchanged"
    return {
        "status": "ok",
        "state": state,
        "profile_sha256": profile_sha256,
        "changes": changes,
        "proposal": None,
        "warnings": [],
    }


def propose(profile: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    if comparison["state"] != "changed":
        return comparison
    change = next(
        item for item in comparison["changes"] if item["path"] == JSON_POINTER
    )
    candidate = copy.deepcopy(profile)
    candidate["contract"]["sources_of_truth"] = change["observed_value"]
    candidate["statements"] = [
        statement
        for statement in candidate["statements"]
        if not (
            statement.get("subject") == SUBJECT
            and statement.get("provenance") == "observed"
        )
    ]
    candidate["statements"].append(
        {
            "subject": SUBJECT,
            "value": json.dumps(change["observed_value"], ensure_ascii=False, sort_keys=True),
            "provenance": "observed",
            "evidence_paths": change["evidence_paths"],
        }
    )
    findings = validate(candidate)
    if findings:
        raise ValueError("Proposed profile does not satisfy the authoritative schema.")
    proposed_sha256 = digest(candidate)
    approval_digest = hashlib.sha256(
        f"{comparison['profile_sha256']}:{proposed_sha256}".encode("ascii")
    ).hexdigest()
    comparison["proposal"] = {
        "status": "proposed",
        "profile_sha256": comparison["profile_sha256"],
        "proposed_profile_sha256": proposed_sha256,
        "approval_digest": approval_digest,
        "requires_approval": True,
        "operations": [
            {
                "op": "replace",
                "path": JSON_POINTER,
                "value": change["observed_value"],
            }
        ],
        "proposed_profile": candidate,
    }
    return comparison


def apply_proposal(
    profile_path: Path, proposal_path: Path, approval_digest: str
) -> tuple[dict[str, Any], int]:
    profile = load_valid_profile(profile_path)
    proposal = load_json_object(proposal_path)
    required = {
        "status",
        "profile_sha256",
        "proposed_profile_sha256",
        "approval_digest",
        "requires_approval",
        "operations",
        "proposed_profile",
    }
    if not required.issubset(proposal):
        raise ValueError("Proposal is missing required fields.")
    if proposal["status"] != "proposed" or proposal["requires_approval"] is not True:
        raise ValueError("Proposal is not approval-bound.")
    if approval_digest != proposal["approval_digest"]:
        return error("approval-mismatch", "Approval digest does not match the proposal."), 1
    if digest(profile) != proposal["profile_sha256"]:
        return error("stale-profile", "Profile changed after the proposal was created."), 1

    candidate = proposal["proposed_profile"]
    if digest(candidate) != proposal["proposed_profile_sha256"]:
        return error("proposal-digest-mismatch", "Proposed profile digest does not match."), 1
    expected_approval = hashlib.sha256(
        f"{proposal['profile_sha256']}:{proposal['proposed_profile_sha256']}".encode("ascii")
    ).hexdigest()
    if proposal["approval_digest"] != expected_approval:
        return error("approval-digest-invalid", "Proposal approval digest is invalid."), 1
    findings = validate(candidate)
    if findings:
        raise ValueError("Proposed profile does not satisfy the authoritative schema.")

    temporary = profile_path.with_name(f".{profile_path.name}.tmp")
    if profile_path.suffix.lower() == ".json":
        content = json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    else:
        import yaml

        content = yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False)
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(profile_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "status": "ok",
        "applied": True,
        "profile": str(profile_path.resolve()),
        "profile_sha256": digest(candidate),
    }, 0


def error(code: str, message: str) -> dict[str, Any]:
    return {"status": "error", "error": {"code": code, "message": message}}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check, propose, or apply governance profile state changes."
    )
    parser.add_argument("command", choices=("check", "propose", "apply"))
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--inspection", type=Path)
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--approve")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    profile_path = args.profile.expanduser().resolve()

    try:
        if args.command == "apply":
            if args.proposal is None or args.approve is None:
                raise ValueError("apply requires --proposal and --approve.")
            payload, exit_code = apply_proposal(
                profile_path, args.proposal.expanduser().resolve(), args.approve
            )
        else:
            if args.inspection is None:
                raise ValueError("check and propose require --inspection.")
            profile = load_valid_profile(profile_path)
            inspection = load_json_object(args.inspection.expanduser().resolve())
            payload = compare(profile, inspection)
            if args.command == "propose":
                payload = propose(profile, payload)
            exit_code = 1 if payload["state"] == "conflict" else 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        payload = error("load-or-validation-error", str(exc))
        exit_code = 2

    emit(payload, args.pretty)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
