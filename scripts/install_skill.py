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
TARGETS = {
    "codex": Path(".codex") / "skills" / "openapi-engineering",
    "claude": Path(".claude") / "skills" / "openapi-engineering",
}
IGNORED_NAMES = {".DS_Store", "__pycache__"}


def tree_digest(root: Path) -> str:
    actual = root.resolve()
    hasher = hashlib.sha256()
    for path in sorted(actual.rglob("*")):
        if not path.is_file() or any(part in IGNORED_NAMES for part in path.parts):
            continue
        hasher.update(path.relative_to(actual).as_posix().encode("utf-8"))
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
) -> tuple[dict[str, Any], int]:
    source = source.expanduser().resolve()
    home = home.expanduser().resolve()
    selected = tuple(dict.fromkeys(platforms))
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
        target = home / TARGETS[platform]
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
) -> tuple[dict[str, Any], int]:
    source = source.expanduser().resolve()
    home = home.expanduser().resolve()
    selected = tuple(dict.fromkeys(platforms))
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
        target = home / TARGETS[platform]
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
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--platform", action="append", choices=("codex", "claude"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--copy", action="store_true", dest="copy_mode")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    if args.uninstall and args.copy_mode:
        parser.error("--copy cannot be combined with --uninstall")
    operation = uninstall_skill if args.uninstall else install_skill
    keyword_arguments = {"apply": args.apply}
    if not args.uninstall:
        keyword_arguments["copy_mode"] = args.copy_mode
    report, exit_code = operation(
        args.source,
        args.home,
        tuple(args.platform or ("codex", "claude")),
        **keyword_arguments,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
