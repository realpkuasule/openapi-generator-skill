#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "skills" / "openapi-engineering"
COMPONENT_SOURCES = {
    "runtime": DEFAULT_SOURCE,
    "maintainer": REPO_ROOT / "skills" / "openapi-engineering-maintainer",
}
TARGETS = {
    "codex": Path(".codex") / "skills",
    "claude": Path(".claude") / "skills",
}
IGNORED_NAMES = {".DS_Store", "__pycache__"}


def tree_digest(root: Path) -> str:
    actual = root.resolve()
    hasher = hashlib.sha256()
    files = sorted(
        (
            (path.relative_to(actual).as_posix(), path)
            for path in actual.rglob("*")
            if path.is_file() and not any(part in IGNORED_NAMES for part in path.parts)
        ),
        key=lambda item: item[0],
    )
    for relative_name, path in files:
        hasher.update(relative_name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def target_state(target: Path, source: Path, source_digest: str) -> tuple[str, str | None]:
    if target.is_symlink():
        try:
            if target.resolve() == source:
                return "unchanged", source_digest
        except OSError:
            pass
        return "conflict", None
    if not target.exists():
        return "missing", None
    if not target.is_dir():
        return "conflict", None
    digest = tree_digest(target)
    return ("unchanged", digest) if digest == source_digest else ("conflict", digest)


def remove_created(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def install_skill(
    source: Path,
    home: Path,
    platforms: Sequence[str],
    *,
    apply: bool = False,
    copy_mode: bool = False,
    skill_name: str | None = None,
) -> tuple[dict[str, Any], int]:
    source = source.expanduser().resolve()
    home = home.expanduser().resolve()
    selected = tuple(dict.fromkeys(platforms))
    installed_name = skill_name or source.name
    if not source.is_dir() or not (source / "SKILL.md").is_file():
        return {
            "status": "error",
            "applied": False,
            "error": "Source is not an OpenAPI engineering skill directory.",
        }, 2
    if not selected or any(platform not in TARGETS for platform in selected):
        return {
            "status": "error",
            "applied": False,
            "error": "At least one supported platform is required.",
        }, 2

    source_sha256 = tree_digest(source)
    use_copy = copy_mode or os.name == "nt"
    rows: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for platform in selected:
        target = home / TARGETS[platform] / installed_name
        state, current_digest = target_state(target, source, source_sha256)
        if state == "conflict":
            conflicts.append(str(target))
            action = "conflict"
        elif state == "unchanged":
            action = "unchanged"
        elif use_copy:
            action = "would-copy"
        else:
            action = "would-link"
        rows.append(
            {
                "platform": platform,
                "target": str(target),
                "action": action,
                "target_digest": current_digest,
            }
        )

    if conflicts:
        return {
            "status": "conflict",
            "applied": False,
            "source": str(source),
            "source_digest": source_sha256,
            "installations": rows,
            "conflicts": conflicts,
        }, 1
    if not apply:
        return {
            "status": "ok",
            "applied": False,
            "source": str(source),
            "source_digest": source_sha256,
            "installations": rows,
        }, 0

    created: list[Path] = []
    try:
        for row in rows:
            if row["action"] == "unchanged":
                continue
            target = Path(row["target"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if use_copy:
                shutil.copytree(
                    source,
                    target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
                )
                row["action"] = "copy"
            else:
                target.symlink_to(source, target_is_directory=True)
                row["action"] = "link"
            created.append(target)
            row["target_digest"] = tree_digest(target)
            if row["target_digest"] != source_sha256:
                raise OSError("Installed skill digest does not match the source.")
    except OSError as exc:
        for target in reversed(created):
            remove_created(target)
        return {
            "status": "error",
            "applied": False,
            "source": str(source),
            "source_digest": source_sha256,
            "installations": rows,
            "error": str(exc),
        }, 2

    return {
        "status": "ok",
        "applied": True,
        "source": str(source),
        "source_digest": source_sha256,
        "installations": rows,
    }, 0


def uninstall_skill(
    source: Path,
    home: Path,
    platforms: Sequence[str],
    *,
    apply: bool = False,
    skill_name: str | None = None,
) -> tuple[dict[str, Any], int]:
    source = source.expanduser().resolve()
    home = home.expanduser().resolve()
    selected = tuple(dict.fromkeys(platforms))
    installed_name = skill_name or source.name
    if not source.is_dir() or not selected or any(
        platform not in TARGETS for platform in selected
    ):
        return {
            "status": "error",
            "applied": False,
            "error": "A valid source and at least one supported platform are required.",
        }, 2
    source_sha256 = tree_digest(source)
    rows: list[dict[str, Any]] = []
    conflicts: list[str] = []
    for platform in selected:
        target = home / TARGETS[platform] / installed_name
        state, current_digest = target_state(target, source, source_sha256)
        if state == "conflict":
            conflicts.append(str(target))
            action = "conflict"
        elif state == "missing":
            action = "unchanged"
        else:
            action = "remove" if apply else "would-remove"
        rows.append(
            {
                "platform": platform,
                "target": str(target),
                "action": action,
                "target_digest": current_digest,
            }
        )
    if conflicts:
        return {
            "status": "conflict",
            "applied": False,
            "source": str(source),
            "source_digest": source_sha256,
            "installations": rows,
            "conflicts": conflicts,
        }, 1
    if apply:
        for row in rows:
            if row["action"] == "remove":
                remove_created(Path(row["target"]))
                row["target_digest"] = None
    return {
        "status": "ok",
        "applied": apply,
        "source": str(source),
        "source_digest": source_sha256,
        "installations": rows,
    }, 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely install one OpenAPI engineering skill tree for Codex and Claude."
    )
    parser.add_argument("--source", type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--platform", action="append", choices=("codex", "claude"))
    parser.add_argument(
        "--component", action="append", choices=("runtime", "maintainer")
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--copy", action="store_true", dest="copy_mode")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    if args.uninstall and args.copy_mode:
        parser.error("--copy cannot be combined with --uninstall")
    components = tuple(dict.fromkeys(args.component or ("runtime",)))
    if args.source is not None and len(components) != 1:
        parser.error("--source can be used with exactly one --component")
    sources = {
        component: (args.source if args.source is not None else COMPONENT_SOURCES[component])
        for component in components
    }
    platforms = tuple(args.platform or ("codex", "claude"))
    operation = uninstall_skill if args.uninstall else install_skill

    preflight: list[tuple[str, dict[str, Any], int]] = []
    for component, source in sources.items():
        keyword_arguments: dict[str, Any] = {
            "apply": False,
            "skill_name": source.name,
        }
        if not args.uninstall:
            keyword_arguments["copy_mode"] = args.copy_mode
        component_report, component_exit = operation(
            source, args.home, platforms, **keyword_arguments
        )
        preflight.append((component, component_report, component_exit))
    failed = next((row for row in preflight if row[2] != 0), None)
    if failed is not None or not args.apply:
        installations = [
            {**row, "component": component}
            for component, component_report, _exit in preflight
            for row in component_report.get("installations", [])
        ]
        status = failed[1]["status"] if failed is not None else "ok"
        exit_code = failed[2] if failed is not None else 0
        report = {
            "status": status,
            "applied": False,
            "sources": {component: str(source.resolve()) for component, source in sources.items()},
            "installations": installations,
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return exit_code

    applied_reports: list[tuple[str, dict[str, Any]]] = []
    for component, source in sources.items():
        keyword_arguments = {"apply": True, "skill_name": source.name}
        if not args.uninstall:
            keyword_arguments["copy_mode"] = args.copy_mode
        component_report, component_exit = operation(
            source, args.home, platforms, **keyword_arguments
        )
        if component_exit != 0:
            if not args.uninstall:
                for previous_component, _previous_report in reversed(applied_reports):
                    previous_source = sources[previous_component]
                    uninstall_skill(
                        previous_source,
                        args.home,
                        platforms,
                        apply=True,
                        skill_name=previous_source.name,
                    )
            report = {
                "status": component_report["status"],
                "applied": False,
                "sources": {key: str(value.resolve()) for key, value in sources.items()},
                "installations": [
                    {**row, "component": key}
                    for key, previous in applied_reports
                    for row in previous.get("installations", [])
                ]
                + [
                    {**row, "component": component}
                    for row in component_report.get("installations", [])
                ],
            }
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return component_exit
        applied_reports.append((component, component_report))
    report = {
        "status": "ok",
        "applied": True,
        "sources": {component: str(source.resolve()) for component, source in sources.items()},
        "installations": [
            {**row, "component": component}
            for component, component_report in applied_reports
            for row in component_report["installations"]
        ],
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
