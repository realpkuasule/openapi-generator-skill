#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable


VCS_DIRECTORIES = {".git", ".hg", ".svn"}
WORKTREE_DIRECTORIES = {".worktrees"}
DEPENDENCY_DIRECTORIES = {".venv", "node_modules", "vendor"}
CACHE_DIRECTORIES = {
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
GENERATED_DIRECTORIES = {"build", "coverage", "dist", "gen", "generated", "out", "target"}

LANGUAGE_SUFFIXES = {
    ".cs": "C#",
    ".go": "Go",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".php": "PHP",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
}

BUILD_MARKERS = {
    "Cargo.toml": "cargo",
    "go.mod": "go-modules",
    "package.json": "npm",
    "pom.xml": "maven",
    "pyproject.toml": "pyproject",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
}

BUILD_LANGUAGES = {
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java",
    "pyproject.toml": "Python",
}

RULE_FILES = {"AGENTS.md", "CLAUDE.md"}
GENERATOR_TERMS = (
    "openapi-generator",
    "openapi-typescript",
    "orval",
    "kiota",
    "nswag",
    "oapi-codegen",
)


def emit(payload: dict[str, Any], pretty: bool) -> None:
    kwargs: dict[str, Any] = {"ensure_ascii": False, "sort_keys": True}
    if pretty:
        kwargs["indent"] = 2
    else:
        kwargs["separators"] = (",", ":")
    print(json.dumps(payload, **kwargs))


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def exclusion_reason(name: str) -> str | None:
    if name in VCS_DIRECTORIES:
        return "vcs"
    if name in WORKTREE_DIRECTORIES:
        return "worktree"
    if name in DEPENDENCY_DIRECTORIES:
        return "dependency"
    if name in CACHE_DIRECTORIES:
        return "cache"
    if name in GENERATED_DIRECTORIES:
        return "generated"
    return None


def matches_explicit_exclude(relative_path: str, excludes: Iterable[str]) -> bool:
    normalized = relative_path.strip("/")
    for exclude in excludes:
        candidate = exclude.strip().strip("/")
        if candidate and (normalized == candidate or normalized.startswith(candidate + "/")):
            return True
    return False


def small_text(path: Path) -> str:
    try:
        if path.stat().st_size > 1_000_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def is_contract_filename(filename: str) -> bool:
    name = filename.lower()
    return any(
        name == f"{kind}.{suffix}" or name.endswith(f".{kind}.{suffix}")
        for kind in ("openapi", "swagger")
        for suffix in ("json", "yaml", "yml")
    )


def inspect(
    root: Path,
    *,
    excludes: tuple[str, ...] = (),
    max_files: int = 100_000,
    max_depth: int = 25,
) -> dict[str, Any]:
    languages: set[str] = set()
    build_systems: set[str] = set()
    contract_files: set[str] = set()
    schema_files: set[str] = set()
    governance_profiles: set[str] = set()
    ci_files: set[str] = set()
    generation_signals: set[str] = set()
    generated_directories: set[str] = set()
    excluded_paths: set[tuple[str, str]] = set()
    warnings: set[tuple[str, str]] = set()
    evidence: set[tuple[str, str]] = set()
    files_scanned = 0
    directories_scanned = 0
    truncated = False

    def on_error(_: OSError) -> None:
        warnings.add(("scan-error", "A directory could not be read."))

    stop = False
    for current, directories, filenames in os.walk(root, followlinks=False, onerror=on_error):
        directories_scanned += 1
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        kept: list[str] = []
        for directory in sorted(directories):
            path = current_path / directory
            rel = relative(path, root)
            reason = exclusion_reason(directory)
            if matches_explicit_exclude(rel, excludes):
                reason = "explicit"
            elif depth >= max_depth:
                reason = "limit"
                truncated = True
            if reason:
                excluded_paths.add((rel, reason))
                if reason == "generated":
                    generated_directories.add(rel)
                    generation_signals.add("generated-output-directory")
                continue
            kept.append(directory)
        directories[:] = kept

        for filename in sorted(filenames):
            if files_scanned >= max_files:
                truncated = True
                stop = True
                break
            path = current_path / filename
            rel = relative(path, root)
            if matches_explicit_exclude(rel, excludes):
                excluded_paths.add((rel, "explicit"))
                continue
            if path.is_symlink() or not path.is_file():
                continue
            files_scanned += 1
            name_lower = path.name.lower()
            rel_lower = rel.lower()

            language = LANGUAGE_SUFFIXES.get(path.suffix.lower())
            if language:
                languages.add(language)

            build_system = BUILD_MARKERS.get(path.name)
            if build_system:
                build_systems.add(build_system)
                evidence.add(("manifest", rel))
                if path.name in BUILD_LANGUAGES:
                    languages.add(BUILD_LANGUAGES[path.name])

            if path.name == "tsconfig.json":
                languages.add("TypeScript")
                evidence.add(("manifest", rel))

            is_contract = is_contract_filename(path.name)
            if is_contract:
                contract_files.add(rel)
                evidence.add(("contract", rel))

            if name_lower.endswith(".schema.json"):
                schema_files.add(rel)
                evidence.add(("schema", rel))

            if rel_lower in {
                ".openapi-engineering/profile.yaml",
                ".openapi-engineering/profile.yml",
                ".openapi-engineering/profile.json",
            }:
                governance_profiles.add(rel)
                evidence.add(("governance", rel))

            if (
                rel_lower.startswith(".github/workflows/")
                and path.suffix.lower() in {".yaml", ".yml"}
            ) or name_lower in {".gitlab-ci.yml", "azure-pipelines.yml"}:
                ci_files.add(rel)
                evidence.add(("ci", rel))

            if path.name in RULE_FILES:
                evidence.add(("project-rule", rel))

            if (
                name_lower in {".openapi-generator-ignore", "openapitools.json"}
                or ".openapi-generator/" in rel_lower
            ):
                generation_signals.add("openapi-generator-config")
                evidence.add(("generator", rel))

            if path.name in BUILD_MARKERS or path.suffix.lower() in {".yaml", ".yml", ".json"}:
                content = small_text(path).lower()
                for term in GENERATOR_TERMS:
                    if term in content:
                        generation_signals.add(f"{term}-config")
                        evidence.add(("generator", rel))

        if stop:
            break

    if truncated:
        warnings.add(("scan-limit", "The scan stopped at a configured depth or file limit."))

    project_signals: list[str] = []
    if any(kind == "project-rule" for kind, _ in evidence):
        project_signals.append("project-rules")
    if contract_files:
        project_signals.append("openapi-contract")
    if schema_files:
        project_signals.append("json-schema")
    if governance_profiles:
        project_signals.append("governance-profile")
    if ci_files:
        project_signals.append("ci")
    if generation_signals:
        project_signals.append("code-generation")

    return {
        "status": "ok",
        "root": str(root),
        "project_signals": project_signals,
        "languages": sorted(languages),
        "build_systems": sorted(build_systems),
        "contract_files": sorted(contract_files),
        "schema_files": sorted(schema_files),
        "governance_profiles": sorted(governance_profiles),
        "ci_files": sorted(ci_files),
        "generation_signals": sorted(generation_signals),
        "generated_directories": sorted(generated_directories),
        "excluded_paths": [
            {"path": path, "reason": reason} for path, reason in sorted(excluded_paths)
        ],
        "warnings": [
            {"code": code, "message": message} for code, message in sorted(warnings)
        ],
        "truncated": truncated,
        "scan_counts": {"files": files_scanned, "directories": directories_scanned},
        "evidence": [
            {"kind": kind, "path": path} for kind, path in sorted(evidence)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect project contract and codegen signals.")
    parser.add_argument("--root", required=True, help="Project directory to inspect.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument(
        "--exclude", action="append", default=[], help="Relative path to exclude; repeatable."
    )
    parser.add_argument(
        "--max-files", type=int, default=100_000, help="Maximum files to inspect."
    )
    parser.add_argument(
        "--max-depth", type=int, default=25, help="Maximum directory depth to inspect."
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        emit(
            {
                "status": "error",
                "error": {"code": "invalid-root", "message": "Root is not a directory."},
            },
            args.pretty,
        )
        return 2
    if args.max_files < 1 or args.max_depth < 0:
        emit(
            {
                "status": "error",
                "error": {
                    "code": "invalid-limit",
                    "message": "max-files must be positive and max-depth cannot be negative.",
                },
            },
            args.pretty,
        )
        return 2

    emit(
        inspect(
            root,
            excludes=tuple(args.exclude),
            max_files=args.max_files,
            max_depth=args.max_depth,
        ),
        args.pretty,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
