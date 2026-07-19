#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "contracts" / "schemas"
ANALYSIS_SCHEMA = SCHEMA_ROOT / "maintenance-analysis.schema.json"
PROPOSAL_SCHEMA = SCHEMA_ROOT / "maintenance-proposal.schema.json"
CONTRACT_IMPACTS = {"none", "compatible", "breaking", "unknown"}


class ProposalBlocked(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalBlocked("Input JSON could not be loaded.") from exc


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(instance: Any, value_schema: dict[str, Any], message: str) -> None:
    errors = list(
        Draft202012Validator(value_schema, format_checker=FormatChecker()).iter_errors(instance)
    )
    if errors:
        raise ProposalBlocked(message)


def relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ProposalBlocked("Candidate path is invalid.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ProposalBlocked("Candidate path is invalid.")
    return path


def target_path(root: Path, value: Any) -> tuple[str, Path]:
    relative = relative_path(value)
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ProposalBlocked("Candidate path contains a symbolic link.")
    return relative.as_posix(), current


def tree_sha256(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ProposalBlocked("Skill root is invalid.")
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink() or "__pycache__" in path.parts or path.name == ".DS_Store":
            if path.is_symlink():
                raise ProposalBlocked("Skill root contains a symbolic link.")
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_candidate(value: Any) -> dict[str, Any]:
    expected = {
        "candidate_id",
        "contract_impact",
        "target_files",
        "artifacts",
        "open_questions",
        "failing_tests",
        "verification",
        "rollback",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ProposalBlocked("Candidate has an invalid field set.")
    if not isinstance(value["candidate_id"], str) or not value["candidate_id"].startswith("candidate-"):
        raise ProposalBlocked("Candidate ID is invalid.")
    if value["contract_impact"] not in CONTRACT_IMPACTS:
        raise ProposalBlocked("Contract impact is invalid.")
    for field in ("target_files", "failing_tests", "verification", "rollback"):
        if not isinstance(value[field], list) or not value[field]:
            raise ProposalBlocked("Candidate list is invalid.")
    if not isinstance(value["open_questions"], list) or not all(
        isinstance(item, str) and item for item in value["open_questions"]
    ):
        raise ProposalBlocked("Candidate open questions are invalid.")
    if not isinstance(value["artifacts"], list) or not 1 <= len(value["artifacts"]) <= 8:
        raise ProposalBlocked("Candidate artifacts are invalid.")
    artifact_paths = []
    for artifact in value["artifacts"]:
        if not isinstance(artifact, dict) or set(artifact) != {
            "kind",
            "path",
            "media_type",
            "content",
        }:
            raise ProposalBlocked("Candidate artifact has an invalid field set.")
        if artifact["kind"] not in {
            "eval-case",
            "sanitized-fixture",
            "failing-test",
            "traceability-candidate",
        }:
            raise ProposalBlocked("Candidate artifact kind is invalid.")
        if artifact["media_type"] not in {
            "application/json",
            "text/x-python",
            "application/yaml",
        }:
            raise ProposalBlocked("Candidate artifact media type is invalid.")
        if not isinstance(artifact["content"], str) or not 1 <= len(artifact["content"]) <= 100000:
            raise ProposalBlocked("Candidate artifact content is invalid.")
        artifact_paths.append(relative_path(artifact["path"]).as_posix())
    target_files = [relative_path(item).as_posix() for item in value["target_files"]]
    if len(set(artifact_paths)) != len(artifact_paths) or set(artifact_paths) != set(target_files):
        raise ProposalBlocked("Candidate artifacts must exactly match target files.")
    return value


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ProposalBlocked("Output path is a symbolic link.")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an immutable maintenance proposal.")
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, required=True)
    parser.add_argument("--skill-version", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--now")
    args = parser.parse_args()
    try:
        analysis_path = args.analysis.expanduser().resolve()
        analysis = load_json(analysis_path)
        validate(analysis, load_schema(ANALYSIS_SCHEMA), "Analysis does not satisfy its contract.")
        candidate = validate_candidate(load_json(args.candidate.expanduser().resolve()))
        target_root = args.target_root.expanduser().absolute()
        if target_root.is_symlink() or not target_root.is_dir():
            raise ProposalBlocked("Target root is invalid.")
        if not args.config_sha256 or len(args.config_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in args.config_sha256
        ):
            raise ProposalBlocked("Configuration digest is invalid.")
        target_files = []
        for value in sorted(set(candidate["target_files"])):
            name, path = target_path(target_root, value)
            if path.exists() and not path.is_file():
                raise ProposalBlocked("Candidate target is not a regular file.")
            target_files.append(
                {"path": name, "expected_sha256": sha256_file(path) if path.is_file() else None}
            )
        failing_tests = [relative_path(value).as_posix() for value in candidate["failing_tests"]]
        if not set(failing_tests).issubset({item["path"] for item in target_files}):
            raise ProposalBlocked("Failing tests must be included in target files.")
        failing_artifacts = {
            relative_path(item["path"]).as_posix()
            for item in candidate["artifacts"]
            if item["kind"] == "failing-test"
        }
        if set(failing_tests) != failing_artifacts:
            raise ProposalBlocked("Failing tests must exactly match failing-test artifacts.")
        generated_at = args.now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProposalBlocked("Timestamp is invalid.") from exc
        analysis_digest = sha256_file(analysis_path)
        skill_sha256 = tree_sha256(args.skill_root.expanduser().absolute())
        proposal = {
            "schema_version": 2,
            "proposal_id": f"proposal-{sha256_value({'candidate': candidate['candidate_id'], 'analysis': analysis_digest})[:16]}",
            "candidate_id": candidate["candidate_id"],
            "generated_at": generated_at,
            "input_digests": sorted({analysis["input_sha256"], analysis_digest}),
            "skill_version": args.skill_version,
            "skill_sha256": skill_sha256,
            "config_sha256": args.config_sha256,
            "contract_impact": candidate["contract_impact"],
            "target_files": target_files,
            "artifacts": sorted(
                [
                    {
                        "kind": artifact["kind"],
                        "path": relative_path(artifact["path"]).as_posix(),
                        "media_type": artifact["media_type"],
                        "content_sha256": hashlib.sha256(
                            artifact["content"].encode("utf-8")
                        ).hexdigest(),
                        "content": artifact["content"],
                    }
                    for artifact in candidate["artifacts"]
                ],
                key=lambda item: item["path"],
            ),
            "open_questions": candidate["open_questions"],
            "failing_tests": sorted(set(failing_tests)),
            "verification": candidate["verification"],
            "resources": {
                "timeout_seconds": 600,
                "warning_rss_mb": 512,
                "hard_rss_mb": 1024,
                "max_concurrency": 1,
            },
            "rollback": candidate["rollback"],
        }
        proposal["approval_sha256"] = sha256_value(proposal)
        validate(proposal, load_schema(PROPOSAL_SCHEMA), "Proposal does not satisfy its contract.")
        atomic_write_json(args.output.expanduser().resolve(), proposal)
        print(json.dumps(proposal, ensure_ascii=False, sort_keys=True))
        return 0
    except ProposalBlocked as exc:
        print(
            json.dumps(
                {"status": "blocked", "error": {"code": "proposal-blocked", "message": str(exc)}},
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
