#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable


SCHEMA_NAME = "governance-profile.schema.json"
SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:api_?key|credential|password|private_?key|secret|token)(?:$|_)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)authorization\s*:\s*(?:bearer|basic)[-_\s]+[a-z0-9._~+/=-]{6,}"),
    re.compile(r"(?i)\bbearer[-_\s]+[a-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)[?&](?:api_?key|access_?token|token|secret|password)=[^&\s]+"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_ -]?key|access[_ -]?token|secret|password)"
        r"(?:\s+|\s*[:=]\s*)[a-z0-9._~+/=-]{8,}"
    ),
)


def emit(payload: dict[str, Any], pretty: bool) -> None:
    kwargs: dict[str, Any] = {"ensure_ascii": False, "sort_keys": True}
    if pretty:
        kwargs["indent"] = 2
    else:
        kwargs["separators"] = (",", ":")
    print(json.dumps(payload, **kwargs))


def finding(path: str, code: str, message: str) -> dict[str, str]:
    return {"path": path, "code": code, "message": message}


def load_profile(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "YAML support requires PyYAML; it was not installed automatically."
        ) from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        raise ValueError("Profile is not valid YAML.") from None


def find_schema() -> Path:
    override = os.environ.get("OPENAPI_ENGINEERING_PROFILE_SCHEMA")
    if override:
        path = Path(override).expanduser().resolve()
        if path.is_file():
            return path
        raise RuntimeError("Configured governance profile schema does not exist.")

    script = Path(__file__).resolve()
    for parent in script.parents:
        candidate = parent / "contracts" / "schemas" / SCHEMA_NAME
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "The authoritative governance profile schema was not found; set "
        "OPENAPI_ENGINEERING_PROFILE_SCHEMA to its path."
    )


def load_schema() -> dict[str, Any]:
    try:
        schema = json.loads(find_schema().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("The authoritative governance profile schema is unreadable.") from exc
    if not isinstance(schema, dict):
        raise RuntimeError("The authoritative governance profile schema must be an object.")
    return schema


def json_path(parts: Iterable[Any]) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(part)):
            path += f".{part}"
        else:
            path += f"[{json.dumps(str(part), ensure_ascii=False)}]"
    return path


def schema_finding(error: Any) -> dict[str, str]:
    path = json_path(error.absolute_path)
    if error.validator == "required":
        return finding(path, "schema-violation", "A required field is missing.")
    if error.validator in {"additionalProperties", "unevaluatedProperties"}:
        return finding(path, "schema-violation", "An unexpected field is present.")
    if error.validator == "type":
        return finding(path, "schema-violation", "A value has an invalid type.")
    if error.validator in {"enum", "const"}:
        return finding(path, "schema-violation", "A value is not allowed.")
    if error.validator == "pattern" and path.endswith(".version"):
        return finding(path, "non-exact-version", "Tool versions must use an exact pin.")
    if error.validator in {"format", "pattern", "minLength"}:
        return finding(path, "schema-violation", "A value has an invalid format.")
    return finding(path, "schema-violation", "The profile violates its schema.")


def contains_sensitive_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS)


def find_sensitive_values(value: Any, path: str = "$") -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = json_path_from_parent(path, key)
            if SENSITIVE_KEY.search(str(key)):
                errors.append(
                    finding(
                        child_path,
                        "sensitive-field",
                        "Governance profiles must not contain credential fields.",
                    )
                )
            errors.extend(find_sensitive_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(find_sensitive_values(child, f"{path}[{index}]"))
    elif isinstance(value, str) and contains_sensitive_value(value):
        errors.append(
            finding(
                path,
                "sensitive-value",
                "Governance profiles must not contain credential values.",
            )
        )
    return errors


def json_path_from_parent(parent: str, key: Any) -> str:
    text = str(key)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        return f"{parent}.{text}"
    return f"{parent}[{json.dumps(text, ensure_ascii=False)}]"


def validate(profile: Any, schema: dict[str, Any] | None = None) -> list[dict[str, str]]:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import SchemaError
    except ImportError as exc:
        raise RuntimeError(
            "Profile validation requires jsonschema; it was not installed automatically."
        ) from exc

    authoritative = schema if schema is not None else load_schema()
    try:
        Draft202012Validator.check_schema(authoritative)
    except SchemaError as exc:
        raise RuntimeError("The authoritative governance profile schema is invalid.") from exc

    validator = Draft202012Validator(authoritative, format_checker=FormatChecker())
    errors = [schema_finding(error) for error in validator.iter_errors(profile)]
    errors.extend(find_sensitive_values(profile))
    unique = {(item["path"], item["code"], item["message"]): item for item in errors}
    return [unique[key] for key in sorted(unique)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate an OpenAPI engineering governance profile."
    )
    parser.add_argument("profile", help="YAML or JSON governance profile path.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()
    profile_path = Path(args.profile).expanduser().resolve()

    try:
        profile = load_profile(profile_path)
    except (OSError, ValueError, RuntimeError) as exc:
        emit(
            {
                "status": "error",
                "error": {"code": "load-error", "message": str(exc)},
            },
            args.pretty,
        )
        return 2

    try:
        errors = validate(profile)
    except RuntimeError as exc:
        emit(
            {
                "status": "error",
                "error": {"code": "schema-error", "message": str(exc)},
            },
            args.pretty,
        )
        return 2

    emit(
        {"status": "ok", "valid": not errors, "errors": errors, "warnings": []},
        args.pretty,
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
