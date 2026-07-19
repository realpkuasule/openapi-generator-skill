from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from process_watch import (
    ProcessLimitExceeded,
    not_run_evidence,
    run_controlled,
)


DEFAULT_WARNING_LIMIT_BYTES = 512 * 1024 * 1024
DEFAULT_HARD_LIMIT_BYTES = 1024 * 1024 * 1024
MAX_CREDENTIAL_BYTES = 64 * 1024
CLAUDE_ACTIVE_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
}


class AdapterFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid-output",
        resources: dict[str, object] | None = None,
        cli_version: str | None = None,
        model: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.resources = resources
        self.cli_version = cli_version
        self.model = model


class AdapterBlocked(RuntimeError):
    def __init__(
        self,
        message: str,
        resources: dict[str, object] | None = None,
        *,
        code: str = "adapter-blocked",
    ):
        super().__init__(message)
        self.resources = resources
        self.code = code


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
                    "key": {
                        "type": "string",
                        "pattern": "^[a-z0-9][a-z0-9-]{0,63}$",
                    },
                    "finding_ids": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "pattern": "^finding-[a-f0-9]{16,64}$",
                        },
                    },
                },
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "candidate_causes": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "unverified": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
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
    failure_code: str = "adapter-blocked",
) -> dict[str, Any]:
    return {
        "platform": platform,
        "session_id": _session_id(platform, seed),
        "cli_version": None,
        "model": None,
        "status": "blocked",
        "failure_code": failure_code,
        "resources": resources
        or not_run_evidence(warning_limit_bytes, hard_limit_bytes),
    }


def failed_analyzer(
    platform: str,
    seed: Any,
    failure: AdapterFailure,
    *,
    warning_limit_bytes: int = DEFAULT_WARNING_LIMIT_BYTES,
    hard_limit_bytes: int = DEFAULT_HARD_LIMIT_BYTES,
) -> dict[str, Any]:
    return {
        "platform": platform,
        "session_id": _session_id(platform, seed),
        "cli_version": failure.cli_version,
        "model": failure.model,
        "status": "failed",
        "failure_code": failure.code,
        "resources": failure.resources
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
        if not isinstance(cluster["key"], str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,63}", cluster["key"]
        ):
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
        "failure_code": None,
        "resources": not_run_evidence(warning_limit_bytes, hard_limit_bytes),
    }


def _allowed_environment(
    home: Path, platform: str, auth_overrides: dict[str, str] | None = None
) -> dict[str, str]:
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
    if auth_overrides:
        approved = CLAUDE_ACTIVE_ENV_NAMES if platform == "claude" else set()
        if not set(auth_overrides).issubset(approved):
            raise AdapterBlocked("Active CLI authentication contains unsupported fields.")
        allowed.update(auth_overrides)
    return allowed


def _codex_credential_root(source_home: Path | None) -> Path:
    explicit_source = source_home is not None
    base_home = source_home or Path.home()
    override = None if explicit_source else os.environ.get("CODEX_HOME")
    return Path(override).expanduser() if override else base_home / ".codex"


def _private_credential_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AdapterBlocked("Active CLI credential source is unavailable or unsafe.") from exc
    try:
        info = os.fstat(descriptor)
        owner_matches = not hasattr(os, "getuid") or info.st_uid == os.getuid()
        if (
            not stat.S_ISREG(info.st_mode)
            or not owner_matches
            or info.st_mode & 0o077
            or not 0 < info.st_size <= MAX_CREDENTIAL_BYTES
        ):
            raise AdapterBlocked("Active CLI credential source is unavailable or unsafe.")
        chunks: list[bytes] = []
        remaining = MAX_CREDENTIAL_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if not content or len(content) > MAX_CREDENTIAL_BYTES:
            raise AdapterBlocked("Active CLI credential source is unavailable or unsafe.")
        return content
    finally:
        os.close(descriptor)


def _stage_active_codex_credentials(
    target_home: Path, *, source_home: Path | None = None
) -> Path:
    if os.name == "nt":
        raise AdapterBlocked("Active CLI credential ownership checks are unsupported.")
    source_root = _codex_credential_root(source_home)
    try:
        root_info = source_root.lstat()
    except OSError as exc:
        raise AdapterBlocked("Active CLI credential source is unavailable or unsafe.") from exc
    owner_matches = not hasattr(os, "getuid") or root_info.st_uid == os.getuid()
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or not owner_matches
        or root_info.st_mode & 0o022
    ):
        raise AdapterBlocked("Active CLI credential source is unavailable or unsafe.")
    content = _private_credential_bytes(source_root / "auth.json")
    destination = target_home / ".codex" / "auth.json"
    destination.parent.mkdir(parents=True, mode=0o700)
    destination.parent.chmod(0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        destination.chmod(0o600)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    return destination


def _active_claude_environment(
    *, source_home: Path | None = None
) -> tuple[dict[str, str], str | None]:
    explicit_source = source_home is not None
    base_home = source_home or Path.home()
    override = None if explicit_source else os.environ.get("CLAUDE_CONFIG_DIR")
    source_root = Path(override).expanduser() if override else base_home / ".claude"
    try:
        root_info = source_root.lstat()
    except OSError as exc:
        raise AdapterBlocked("Active Claude credential settings are unavailable or unsafe.") from exc
    owner_matches = not hasattr(os, "getuid") or root_info.st_uid == os.getuid()
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or not owner_matches
        or root_info.st_mode & 0o022
    ):
        raise AdapterBlocked("Active Claude credential settings are unavailable or unsafe.")
    try:
        payload = json.loads(_private_credential_bytes(source_root / "settings.json"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AdapterBlocked("Active Claude credential settings are invalid.") from exc
    raw_environment = payload.get("env") if isinstance(payload, dict) else None
    if not isinstance(raw_environment, dict):
        raise AdapterBlocked("Active Claude credential settings are invalid.")
    selected = {
        name: value
        for name, value in raw_environment.items()
        if name in CLAUDE_ACTIVE_ENV_NAMES and isinstance(value, str) and value
    }
    auth_values = [
        selected.get("ANTHROPIC_API_KEY"),
        selected.get("ANTHROPIC_AUTH_TOKEN"),
    ]
    if not any(auth_values) or any(
        value is not None and len(value) > 8192 for value in auth_values
    ):
        raise AdapterBlocked("Active Claude credential settings are invalid.")
    if base_url := selected.get("ANTHROPIC_BASE_URL"):
        parsed = urlsplit(base_url)
        if (
            len(base_url) > 2048
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise AdapterBlocked("Active Claude provider endpoint is invalid.")
    model_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-\[\]]{0,199}$")
    for name, value in selected.items():
        if "MODEL" in name and not model_pattern.fullmatch(value):
            raise AdapterBlocked("Active Claude model identifier is invalid.")
    return selected, selected.get("ANTHROPIC_MODEL")


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


def _claude_command(executable: str, credential_mode: str) -> list[str]:
    command = [executable, "-p", "--bare"]
    command.extend(
        [
            "--permission-mode",
            "plan",
            "--setting-sources",
            "",
            "--tools",
            "",
            "--disallowedTools",
            "*",
            "mcp__*",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-chrome",
            "--no-session-persistence",
            "--max-turns",
            "2",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(SEMANTIC_RESULT_SCHEMA, sort_keys=True, separators=(",", ":")),
        ]
    )
    return command


def run_codex(
    bundle: dict[str, Any],
    finding_ids: set[str],
    timeout_seconds: int,
    warning_limit_bytes: int = DEFAULT_WARNING_LIMIT_BYTES,
    hard_limit_bytes: int = DEFAULT_HARD_LIMIT_BYTES,
    credential_mode: str = "environment",
) -> tuple[dict[str, Any], dict[str, Any]]:
    executable = shutil.which("codex")
    if executable is None:
        raise AdapterBlocked("Codex CLI is unavailable.", code="adapter-unavailable")
    with tempfile.TemporaryDirectory(prefix="openapi-maintainer-codex-") as directory:
        root = Path(directory)
        if credential_mode == "active-cli-session":
            _stage_active_codex_credentials(root)
        output = root / "last-message.json"
        output_schema = root / "semantic-result.schema.json"
        output_schema.write_text(
            json.dumps(SEMANTIC_RESULT_SCHEMA, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        prompt = (
            "Analyze this sanitized OpenAPI Engineering trigger bundle. Return only JSON with "
            "clusters, confidence, candidate_causes, and unverified. Do not request project access "
            "or propose commands. Use lowercase kebab-case cluster keys of at most 64 characters. "
            "Do not use tools.\n"
            + json.dumps(bundle, sort_keys=True, separators=(",", ":"))
        )
        command = [
            executable,
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            str(output_schema),
            "-c",
            'shell_environment_policy.inherit="none"',
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
                f"Codex analysis was blocked by {exc.reason}.",
                exc.resources,
                code="resource-limit",
            ) from exc
        if result.returncode != 0 or not output.is_file():
            raise AdapterFailure(
                "Codex analysis failed.",
                code="cli-failed",
                resources=result.resources,
                cli_version=_cli_version(executable),
            )
        try:
            value = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterFailure(
                "Codex analyzer output is not valid JSON.",
                resources=result.resources,
                cli_version=_cli_version(executable),
            ) from exc
        try:
            semantic = validate_semantic_result(value, finding_ids)
        except AdapterFailure as exc:
            raise AdapterFailure(
                str(exc),
                code=exc.code,
                resources=result.resources,
                cli_version=_cli_version(executable),
            ) from exc
        return semantic, {
            "platform": "codex",
            "session_id": _session_id("codex", bundle),
            "cli_version": _cli_version(executable),
            "model": None,
            "status": "passed",
            "failure_code": None,
            "resources": result.resources,
        }


def run_claude(
    bundle: dict[str, Any],
    finding_ids: set[str],
    timeout_seconds: int,
    warning_limit_bytes: int = DEFAULT_WARNING_LIMIT_BYTES,
    hard_limit_bytes: int = DEFAULT_HARD_LIMIT_BYTES,
    credential_mode: str = "environment",
) -> tuple[dict[str, Any], dict[str, Any]]:
    executable = shutil.which("claude")
    if executable is None:
        raise AdapterBlocked(
            "Claude Code CLI is unavailable.", code="adapter-unavailable"
        )
    with tempfile.TemporaryDirectory(prefix="openapi-maintainer-claude-") as directory:
        root = Path(directory)
        active_environment: dict[str, str] = {}
        active_model = None
        if credential_mode == "active-cli-session":
            active_environment, active_model = _active_claude_environment()
        prompt = (
            "Independently review this sanitized OpenAPI Engineering trigger bundle. "
            "Return only the requested structured result. Do not request project access "
            "and do not propose commands. Use lowercase kebab-case cluster keys of at most 64 "
            "characters.\n"
            + json.dumps(bundle, sort_keys=True, separators=(",", ":"))
        )
        command = _claude_command(executable, credential_mode)
        try:
            result = run_controlled(
                command,
                cwd=root,
                env=_allowed_environment(
                    root, "claude", auth_overrides=active_environment
                ),
                input_text=prompt,
                timeout_seconds=timeout_seconds,
                warning_limit_bytes=warning_limit_bytes,
                hard_limit_bytes=hard_limit_bytes,
            )
        except ProcessLimitExceeded as exc:
            raise AdapterBlocked(
                f"Claude Code review was blocked by {exc.reason}.",
                exc.resources,
                code="resource-limit",
            ) from exc
        if result.returncode != 0:
            failure_code = "cli-failed"
            try:
                failure_message = json.loads(result.stdout)
                if failure_message.get("subtype") == "error_max_turns":
                    failure_code = "turn-limit"
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
            raise AdapterFailure(
                "Claude Code review failed.",
                code=failure_code,
                resources=result.resources,
                cli_version=_cli_version(executable),
                model=active_model,
            )
        try:
            message = json.loads(result.stdout)
            value = message.get("structured_output")
            if value is None and isinstance(message.get("result"), str):
                value = json.loads(message["result"])
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            raise AdapterFailure(
                "Claude Code review output is not valid JSON.",
                resources=result.resources,
                cli_version=_cli_version(executable),
                model=active_model,
            ) from exc
        if message.get("subtype") not in {None, "success"} or value is None:
            raise AdapterFailure(
                "Claude Code review did not produce structured output.",
                resources=result.resources,
                cli_version=_cli_version(executable),
                model=active_model,
            )
        session_seed = message.get("session_id") or bundle
        try:
            semantic = validate_semantic_result(value, finding_ids)
        except AdapterFailure as exc:
            raise AdapterFailure(
                str(exc),
                code=exc.code,
                resources=result.resources,
                cli_version=_cli_version(executable),
                model=active_model,
            ) from exc
        return semantic, {
            "platform": "claude",
            "session_id": _session_id("claude", session_seed),
            "cli_version": _cli_version(executable),
            "model": active_model,
            "status": "passed",
            "failure_code": None,
            "resources": result.resources,
        }
