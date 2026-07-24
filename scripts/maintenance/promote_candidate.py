#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "contracts" / "schemas"
PROPOSAL_SCHEMA = SCHEMA_ROOT / "maintenance-proposal.schema.json"
PROMOTION_SCHEMA = SCHEMA_ROOT / "maintenance-promotion.schema.json"
EVAL_SCHEMA = SCHEMA_ROOT / "eval-case.schema.json"

ALLOWED_PATHS = {
    "eval-case": re.compile(
        r"^skills/openapi-engineering-maintainer/evals/[a-z0-9][a-z0-9._-]*\.json$"
    ),
    "sanitized-fixture": re.compile(
        r"^skills/openapi-engineering-maintainer/evals/fixtures/[a-z0-9][a-z0-9._-]*\.json$"
    ),
    "failing-test": re.compile(r"^tests/test_maintenance_candidate_[a-z0-9_]+\.py$"),
    "traceability-candidate": re.compile(
        r"^contracts/self-improvement-candidates/[a-z0-9][a-z0-9._-]*\.(json|yaml)$"
    ),
}
MEDIA_TYPES = {
    "eval-case": {"application/json"},
    "sanitized-fixture": {"application/json"},
    "failing-test": {"text/x-python"},
    "traceability-candidate": {"application/json", "application/yaml"},
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]{12,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\b\s*[:=]\s*['\"]?[A-Za-z0-9_./+-]{12,}"
    ),
)
FORBIDDEN_FIXTURE_KEYS = {
    "note",
    "project_alias",
    "project_path",
    "raw_prompt",
    "transcript",
    "remote",
    "token",
    "secret",
}


class PromotionBlocked(RuntimeError):
    pass


class PromotionConflict(PromotionBlocked):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionBlocked("Proposal JSON could not be loaded.") from exc


def load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(value: Any, schema_path: Path, message: str) -> None:
    errors = list(
        Draft202012Validator(
            load_schema(schema_path), format_checker=FormatChecker()
        ).iter_errors(value)
    )
    if errors:
        raise PromotionBlocked(message)


def relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PromotionBlocked("Promotion path is invalid.")
    path = PurePosixPath(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise PromotionBlocked("Promotion path is invalid.")
    return path


def target_path(root: Path, value: Any) -> tuple[str, Path]:
    relative = relative_path(value)
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise PromotionBlocked("Promotion path contains a symbolic link.")
    return relative.as_posix(), current


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def validate_artifact(artifact: dict[str, Any]) -> bytes:
    kind = artifact["kind"]
    path = artifact["path"]
    if not ALLOWED_PATHS[kind].fullmatch(path):
        raise PromotionBlocked("Artifact path is outside the approved promotion allowlist.")
    if artifact["media_type"] not in MEDIA_TYPES[kind]:
        raise PromotionBlocked("Artifact media type does not match its kind.")
    content = artifact["content"].encode("utf-8")
    if sha256_bytes(content) != artifact["content_sha256"]:
        raise PromotionConflict("Artifact content digest is stale.")
    text = artifact["content"]
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        raise PromotionBlocked("Artifact failed secret scanning.")
    if kind in {"eval-case", "sanitized-fixture"}:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PromotionBlocked("JSON promotion artifact is invalid.") from exc
        if kind == "eval-case":
            validate(parsed, EVAL_SCHEMA, "Promoted eval case does not satisfy its contract.")
        elif any(key.lower() in FORBIDDEN_FIXTURE_KEYS for key in _walk_keys(parsed)):
            raise PromotionBlocked("Sanitized fixture contains a local-only field.")
    return content


def _write_temp(parent: Path, name: str, content: bytes) -> Path:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=parent)
    path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _restore(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    temporary = _write_temp(path.parent, path.name, content)
    os.replace(temporary, path)


def promote(
    *,
    proposal_path: Path,
    target_root: Path,
    approval_sha256: str,
    apply: bool,
    replace_artifact: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
) -> dict[str, Any]:
    proposal_path = proposal_path.expanduser().resolve()
    proposal = load_json(proposal_path)
    validate(proposal, PROPOSAL_SCHEMA, "Proposal does not satisfy its contract.")
    canonical_proposal = dict(proposal)
    declared_approval = canonical_proposal.pop("approval_sha256")
    recomputed_approval = sha256_value(canonical_proposal)
    if declared_approval != recomputed_approval or approval_sha256 != declared_approval:
        raise PromotionConflict("Proposal approval digest does not match exactly.")
    if proposal["open_questions"]:
        raise PromotionBlocked("Proposal still contains open questions.")

    root = target_root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise PromotionBlocked("Promotion target root is invalid.")
    targets = {item["path"]: item for item in proposal["target_files"]}
    artifacts = {item["path"]: item for item in proposal["artifacts"]}
    if len(artifacts) != len(proposal["artifacts"]) or set(artifacts) != set(targets):
        raise PromotionBlocked("Proposal artifacts do not exactly match target files.")

    rows = []
    prepared = []
    for name in sorted(artifacts):
        artifact = artifacts[name]
        normalized, path = target_path(root, name)
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise PromotionBlocked("Promotion target is not a regular file.")
        current_bytes = path.read_bytes() if path.is_file() else None
        current_sha256 = sha256_bytes(current_bytes) if current_bytes is not None else None
        expected_sha256 = targets[name]["expected_sha256"]
        if current_sha256 != expected_sha256:
            raise PromotionConflict("Promotion target digest is stale.")
        content = validate_artifact(artifact)
        rows.append(
            {
                "kind": artifact["kind"],
                "path": normalized,
                "expected_sha256": expected_sha256,
                "current_sha256": current_sha256,
                "content_sha256": artifact["content_sha256"],
                "state": "would-create" if current_bytes is None else "would-replace",
            }
        )
        prepared.append((path, content, current_bytes))

    core = {
        "proposal_id": proposal["proposal_id"],
        "approval_sha256": declared_approval,
        "target_files": rows,
    }
    report = {
        "schema_version": 1,
        "status": "ok",
        "action": "would-promote",
        "applied": False,
        **core,
        "plan_sha256": sha256_value(core),
    }
    validate(report, PROMOTION_SCHEMA, "Promotion plan does not satisfy its contract.")
    if not apply:
        return report

    created_directories: list[Path] = []
    temporary_files: list[Path] = []
    replaced: list[tuple[Path, bytes | None]] = []
    try:
        for path, content, _snapshot in prepared:
            missing = []
            current = path.parent
            while current != root and not current.exists():
                missing.append(current)
                current = current.parent
            path.parent.mkdir(parents=True, exist_ok=True)
            created_directories.extend(reversed(missing))
            target_path(root, path.relative_to(root).as_posix())
            temporary_files.append(_write_temp(path.parent, path.name, content))

        for (path, _content, snapshot), temporary in zip(prepared, temporary_files):
            _normalized, checked_path = target_path(root, path.relative_to(root).as_posix())
            current = checked_path.read_bytes() if checked_path.is_file() else None
            if current != snapshot:
                raise PromotionConflict("Promotion target changed during apply.")
            replace_artifact(temporary, path)
            replaced.append((path, snapshot))
        temporary_files.clear()
    except Exception as exc:
        for path, snapshot in reversed(replaced):
            _restore(path, snapshot)
            restored = path.read_bytes() if path.is_file() else None
            if restored != snapshot:
                raise PromotionBlocked("Promotion rollback verification failed.") from exc
        for temporary in temporary_files:
            temporary.unlink(missing_ok=True)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise PromotionBlocked("Promotion write failed and snapshots were restored.") from exc

    report["action"] = "promoted"
    report["applied"] = True
    for row in report["target_files"]:
        row["state"] = "created" if row["current_sha256"] is None else "replaced"
    validate(report, PROMOTION_SCHEMA, "Promotion result does not satisfy its contract.")
    return report


def emit_error(status: str, code: str, message: str) -> None:
    print(json.dumps({"status": status, "error": {"code": code, "message": message}}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan or apply an exact approval-bound maintenance promotion."
    )
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--approve", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        report = promote(
            proposal_path=args.proposal,
            target_root=args.target_root,
            approval_sha256=args.approve,
            apply=args.apply,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except PromotionConflict as exc:
        emit_error("conflict", "promotion-conflict", str(exc))
        return 1
    except PromotionBlocked as exc:
        emit_error("blocked", "promotion-blocked", str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
