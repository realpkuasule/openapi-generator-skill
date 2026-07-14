# Platform Compatibility

## Single source

Maintain one canonical `openapi-engineering/` directory for Codex and Claude Code. Do not fork `SKILL.md` by platform. Use only `name` and `description` in common frontmatter.

Codex may read `agents/openai.yaml` for UI metadata. Claude Code must be able to ignore that file and execute the same core workflow.

## Interaction fallback

Use a structured question UI when available. Otherwise ask one ordinary conversational question cluster, wait for the answer, and continue across turns. Never collapse the interview and approval into a single assumed action because a platform lacks a UI helper.

## Tool fallback

- Use bundled Python scripts for deterministic project inspection, profile validation, and directory comparison.
- Do not require a platform-specific MCP for core behavior.
- When an optional MCP or connector is approved, keep an equivalent CLI/file workflow where practical.
- Do not encode Codex or Claude-only tool names in the common workflow.

## Packaging checks

For both platforms verify:

- the same `SKILL.md` triggers for assessment, design, integration, evolution, audit, upgrade, troubleshooting, governance, and decommissioning;
- read-only discovery happens before interview questions;
- no mutation happens before a complete approved boundary;
- scope expansion returns to proposed;
- no-codegen and official SDK remain valid decisions;
- completion reports contain actual evidence and unverified items.

## Installation

Run `python3 scripts/install_skill.py --home <temporary-home>` first. It is dry-run by default and plans both Codex and Claude Code targets from the same canonical Skill directory. Use `--apply` only after the installation paths and external configuration boundary are approved. Use `--copy` for Windows or environments where directory links are unavailable.

The installer must preflight every selected target before writing, reject divergent existing directories, compare complete Skill tree digests after link/copy, and leave unrelated Agent settings unchanged. Repeating an identical installation is `unchanged`; it must not create a second behavioral source.

## Script portability

Invoke scripts with `python3` or the platform's configured Python 3 executable. Keep JSON stdout, stable sorting, and explicit exit codes. Never auto-install PyYAML: JSON profiles work without it, while YAML validation must report the missing optional parser clearly.

Avoid Bash-only logic in core scripts so Windows projects can use the same helpers.
