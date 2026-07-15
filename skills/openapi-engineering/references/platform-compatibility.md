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

## Real forward validation

Run Codex and Claude Code against the same canonical Skill tree digest and the same
evaluation harness digest (runner, adapters, scorer, and Schemas), compact fixture, case
input, and scripted user answers. Use at least two independent samples for Animator,
Revoice, scope expansion, profile reuse, and untrusted input on each platform. Expected
values remain scorer-side and are never sent to the tested agent.

Codex runs `gpt-5.4-mini` with low reasoning in a temporary `HOME` and `CODEX_HOME`,
an explicit global read-only sandbox on every resumable invocation, no approvals, no
user config or exec-policy rules. Its final JSON may stream normally and is then checked
locally against the complete forward-observation Schema. Claude Code runs resumable
print sessions in a temporary `HOME` and `CLAUDE_CONFIG_DIR`, plan mode, read-only
discovery tools, no Chrome, and no MCP servers; both its CLI structured output and the
local Schema gate are enforced.

Use an already authenticated CLI. When its authentication state includes a configuration
file, copy only that required file into the temporary directory; never symlink it to the
real Agent home. Platform keychain access remains a separately approved external
credential boundary.
Pass an explicit environment allowlist for process, locale, certificate, and proxy
operation, and do not forward arbitrary parent-process secrets, Python/Node injection
settings, or real home paths to the evaluated CLI. A platform-authentication environment
variable may be forwarded only through a platform-specific named allowlist when that
adapter exposes no shell/process tool to the evaluated model; never forward it to an
adapter that can inspect process environment.

Every sample uses a fresh temporary project copy and a bounded total timeout. Record CLI
versions, timeout, Skill SHA-256, harness SHA-256, transcript, semantic decisions,
unverified items, and project tree hashes. A static/fake result, mismatched Skill or
harness digest, missing sample, file mutation, unavailable platform, or failed hard gate
cannot count as a live forward pass. Persist release evidence outside the Skill tree so
recording results does not change the tested Skill digest. Atomically checkpoint the
report after every completed sample. Resume only when the adapter, ordered case/sample
plan, timeout, Skill digest, and harness digest exactly match the checkpoint. A complete
matched checkpoint may retry only failed or blocked slots; never rerun or replace a
passing slot, and checkpoint every replacement.

Run live samples sequentially by default. Do not start Codex and Claude Code forward
batches concurrently on a resource-constrained workstation. After a timeout or
interruption, verify that the CLI process and both temporary directories were reclaimed
before retrying; retain the failed report instead of silently replacing it. Start each
CLI invocation in an isolated process group. On timeout, terminate the complete group
and force-kill any survivors so a CLI child process cannot outlive its sample. Apply the
same process-group cleanup when the runner is interrupted.

## Installation

Run `python3 scripts/install_skill.py --home <temporary-home>` first. It is dry-run by default and plans both Codex and Claude Code targets from the same canonical Skill directory. Use `--apply` only after the installation paths and external configuration boundary are approved. Use `--copy` for Windows or environments where directory links are unavailable.

The installer must preflight every selected target before writing, reject divergent existing directories, compare complete Skill tree digests after link/copy, and leave unrelated Agent settings unchanged. Repeating an identical installation is `unchanged`; it must not create a second behavioral source.

## Script portability

Invoke scripts with `python3` or the platform's configured Python 3 executable. Keep JSON stdout, stable sorting, and explicit exit codes. Never auto-install PyYAML: JSON profiles work without it, while YAML validation must report the missing optional parser clearly.

Avoid Bash-only logic in core scripts so Windows projects can use the same helpers.
