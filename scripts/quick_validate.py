#!/usr/bin/env python3
"""Minimal repository-local Skill package validation for clean CI runners."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml


MAX_SKILL_NAME_LENGTH = 64
ALLOWED_PROPERTIES = {"name", "description", "license", "allowed-tools", "metadata"}


def validate_skill(skill_path: Path) -> tuple[bool, str]:
    skill_md = skill_path / "SKILL.md"
    if not skill_md.is_file():
        return False, "SKILL.md not found"
    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return False, "Invalid or missing YAML frontmatter"
    try:
        frontmatter: Any = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return False, "Invalid YAML in frontmatter"
    if not isinstance(frontmatter, dict):
        return False, "Frontmatter must be a YAML dictionary"
    unexpected = set(frontmatter) - ALLOWED_PROPERTIES
    if unexpected:
        return False, "Unexpected frontmatter keys: " + ", ".join(sorted(unexpected))
    if "name" not in frontmatter or "description" not in frontmatter:
        return False, "Frontmatter requires name and description"
    name = frontmatter["name"]
    description = frontmatter["description"]
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        return False, "Skill name must be lowercase hyphen-case"
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return False, "Skill name exceeds 64 characters"
    if not isinstance(description, str) or not description.strip():
        return False, "Skill description must be a non-empty string"
    if "<" in description or ">" in description or len(description) > 1024:
        return False, "Skill description contains invalid markup or is too long"
    return True, "Skill is valid!"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        return 2
    valid, message = validate_skill(Path(sys.argv[1]).expanduser().resolve())
    print(message)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
