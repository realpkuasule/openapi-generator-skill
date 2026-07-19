from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from process_watch import (
    ProcessLimitExceeded,
    not_run_evidence,
    run_controlled,
)


DEFAULT_WARNING_LIMIT_BYTES = 512 * 1024 * 1024
DEFAULT_HARD_LIMIT_BYTES = 1024 * 1024 * 1024


class AdapterFailure(RuntimeError):
    pass


class AdapterBlocked(RuntimeError):
    def __init__(self, message: str, resources: dict[str, object] | None = None):
        super().__init__(message)
        self.resources = resources


EXPECTED_RESULT_FIELDS = {
    "clusters",
    "confidence",
    "candidate_causes",
    "unverified",
}

SEMANTIC_RESULT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(EXPECTED_RESULT_FIELDS),
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key", "finding_ids"],
                "properties": {
                    "key": {"type": "string"},
                    "finding_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "candidate_causes": {"type": "array", "items": {"type": "string"}},
        "unverified": {"type": "array", "items": {"type": "string"}},
    },
}


def _digest(value: Any) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _session_id(platform: str, seed: Any) -> str:
    return f"analysis-session-{_digest({'platform': platform, 'seed': seed})[:16]}"


def blocked_analyzer(
    platform: str,
    seed: Any,
    resources: dict[str, object] | None = None,
    *,
    warning_limit_bytes: int = DEFAULT_WARNING_LIMIT_BYTES,
    hard_limit_bytes: int = DEFAULT_HARD_LIMIT_BYTES,
) -> dict[str, Any]:
    return {
        "platform": platform,
        "session_id": _session_id(platform, seed),
        "cli_version": None,
        "model": None,
        "status": "blocked",
        "resources": resources
        or not_run_evidence(warning_limit_bytes, hard_limit_bytes),
    }


def validate_semantic_result(value: Any, finding_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != EXPECTED_RESULT_FIELDS:
        raise AdapterFailure("Analyzer output has an invalid field set.")
    if not isinstance(value["confidence"], (int, float)) or isinstance(value["confidence"], bool):
        raise AdapterFailure("Analyzer confidence is invalid.")
    if not 0 <= value["confidence"] <= 1:
        raise AdapterFailure("Analyzer confidence is invalid.")
    for field in ("candidate_causes", "unverified"):
        if not isinstance(value[field], list) or not all(
            isinstance(item, str) and 0 < len(item) <= 500 for item in value[field]
        ):
            raise AdapterFailure("Analyzer text output is invalid.")
    if not isinstance(value["clusters"], list):
        raise AdapterFailure("Analyzer clusters are invalid.")
    for cluster in value["clusters"]:
        if not isinstance(cluster, dict) or set(cluster) != {"key", "finding_ids"}:
            raise AdapterFailure("Analyzer cluster is invalid.")
        if not isinstance(cluster["key"], str) or not cluster["key"]:
            raise AdapterFailure("Analyzer cluster key is invalid.")
        ids = cluster["finding_ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) != len(set(ids))
            or not set(ids).issubset(finding_ids)
        ):
            raise AdapterFailure("Analyzer cluster references unknown findings.")
    return value


def run_fake(
    path: Path,
    finding_ids: set[str],
    platform: str = "fake",
    *,
    warning_limit_bytes: int = DEFAULT_WARNING_LIMIT_BYTES,
    hard_limit_bytes: int = DEFAULT_HARD_LIMIT_BYTES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterFailure("Fake analyzer output could not be loaded.") from exc
    return validate_semantic_result(value, finding_ids), {
        "platform": platform,
        "session_id": _session_id(platform, value),
        "cli_version": f"fake-{platform}",
        "model": f"fake-{platform}",
        "status": "passed",
        "resources": not_run_evidence(warning_limit_bytes, hard_limit_bytes),
    }


def _allowed_environment(home: Path, platform: str) -> dict[str, str]:
    allowed = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": "C.UTF-8",
    }
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
        if value := os.environ.get(name):
            allowed[name] = value
    auth_names = {
        "codex": ("OPENAI_API_KEY", "CODEX_API_KEY"),
        "claude": ("ANTHROPIC_API_KEY",),
    }
    for name in auth_names.get(platform, ()):
        if value := os.environ.get(name):
            allowed[name] = value
    return allowed


def _cli_version(executable: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "--version"],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0][:100] if result.returncode == 0 and value else None


def run_codex(
    bundle: dict[str, Any],
    finding_ids: set[str],
    timeout_seconds: int,
    warning_limit_bytes: int = DEFAULT_WARNING_LIMIT_BYTES,
    hard_limit_bytes: int = DEFAULT_HARD_LIMIT_BYTES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    executable = shutil.which("codex")
    if executable is None:
        raise AdapterBlocked("Codex CLI is unavailable.")
    with tempfile.TemporaryDirectory(prefix="openapi-maintainer-codex-") as directory:
        root = Path(directory)
        output = root / "last-message.json"
        prompt = (
            "Analyze this sanitized OpenAPI Engineering trigger bundle. Return only JSON with "
            "clusters, confidence, candidate_causes, and unverified. Do not request project access "
            "or propose commands.\n" + json.dumps(bundle, sort_keys=True, separators=(",", ":"))
        )
        command = [
            executable,
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--output-last-message",
            str(output),
            "-",
        ]
        try:
            result = run_controlled(
                command,
                cwd=root,
                env=_allowed_environment(root, "codex"),
                input_text=prompt,
                timeout_seconds=timeout_seconds,
                warning_limit_bytes=warning_limit_bytes,
                hard_limit_bytes=hard_limit_bytes,
            )
        except ProcessLimitExceeded as exc:
            raise AdapterBlocked(
                f"Codex analysis was blocked by {exc.reason}.", exc.resources
            ) from exc
        if result.returncode != 0 or not output.is_file():
            raise AdapterFailure("Codex analysis failed.")
        try:
            value = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterFailure("Codex analyzer output is not valid JSON.") from exc
        return validate_semantic_result(value, finding_ids), {
            "platform": "codex",
            "session_id": _session_id("codex", bundle),
            "cli_version": _cli_version(executable),
            "model": None,
            "status": "passed",
            "resources": result.resources,
        }


def run_claude(
    bundle: dict[str, Any],
    finding_ids: set[str],
    timeout_seconds: int,
    warning_limit_bytes: int = DEFAULT_WARNING_LIMIT_BYTES,
    hard_limit_bytes: int = DEFAULT_HARD_LIMIT_BYTES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    executable = shutil.which("claude")
    if executable is None:
        raise AdapterBlocked("Claude Code CLI is unavailable.")
    with tempfile.TemporaryDirectory(prefix="openapi-maintainer-claude-") as directory:
        root = Path(directory)
        prompt = (
            "Independently review this sanitized OpenAPI Engineering trigger bundle. "
            "Return only the requested structured result. Do not request project access "
            "and do not propose commands.\n"
            + json.dumps(bundle, sort_keys=True, separators=(",", ":"))
        )
        command = [
            executable,
            "-p",
            "--bare",
            "--permission-mode",
            "plan",
            "--tools",
            "",
            "--disallowedTools",
            "*",
            "mcp__*",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--max-turns",
            "1",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(SEMANTIC_RESULT_SCHEMA, sort_keys=True, separators=(",", ":")),
        ]
        try:
            result = run_controlled(
                command,
                cwd=root,
                env=_allowed_environment(root, "claude"),
                input_text=prompt,
                timeout_seconds=timeout_seconds,
                warning_limit_bytes=warning_limit_bytes,
                hard_limit_bytes=hard_limit_bytes,
            )
        except ProcessLimitExceeded as exc:
            raise AdapterBlocked(
                f"Claude Code review was blocked by {exc.reason}.", exc.resources
            ) from exc
        if result.returncode != 0:
            raise AdapterFailure("Claude Code review failed.")
        try:
            message = json.loads(result.stdout)
            value = message.get("structured_output")
            if value is None and isinstance(message.get("result"), str):
                value = json.loads(message["result"])
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            raise AdapterFailure("Claude Code review output is not valid JSON.") from exc
        if message.get("subtype") not in {None, "success"} or value is None:
            raise AdapterFailure("Claude Code review did not produce structured output.")
        session_seed = message.get("session_id") or bundle
        return validate_semantic_result(value, finding_ids), {
            "platform": "claude",
            "session_id": _session_id("claude", session_seed),
            "cli_version": _cli_version(executable),
            "model": None,
            "status": "passed",
            "resources": result.resources,
        }
