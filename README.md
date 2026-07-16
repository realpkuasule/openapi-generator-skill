# OpenAPI Engineering Skill

OpenAPI Engineering Skill is a Contract-First, full-lifecycle engineering skill for Codex and
Claude Code. It inspects the current project, conducts a multi-turn boundary interview, proposes
an explicit work boundary, and waits for approval before making changes.

The skill does not assume that OpenAPI Generator is always the right implementation. Depending on
the project, lifecycle stage, and stated intent, it may select OpenAPI Generator, a language-native
generator, an official SDK, contract-governance tooling, MCP integration, or a documented
`no-codegen` decision.

## Release candidate

The current evaluation release is `v0.1.0-rc.1`. It requires Python 3.11 or newer. This repository
does not yet declare an open-source license; the release candidate is intended for controlled
evaluation until the project owner selects one.

## Pinned dual-platform installation

Clone and check out the exact release before installing so Codex and Claude Code resolve the same
canonical skill tree:

```bash
git clone git@github.com:realpkuasule/openapi-generator-skill.git
cd openapi-generator-skill
git checkout v0.1.0-rc.1
python3 scripts/install_skill.py --platform codex --platform claude
python3 scripts/install_skill.py --platform codex --platform claude --apply
```

The first command is a dry run. The second creates links on POSIX systems, or copies when explicitly
requested with `--copy`. Re-run the dry run to verify that both targets are unchanged and have the
same digest:

```bash
python3 scripts/install_skill.py --platform codex --platform claude
```

Default targets are `~/.codex/skills/openapi-engineering` and
`~/.claude/skills/openapi-engineering`. Existing divergent targets are reported as conflicts and
are not overwritten.

## Rollback

Preview removal, then apply it:

```bash
python3 scripts/install_skill.py --platform codex --platform claude --uninstall
python3 scripts/install_skill.py --platform codex --platform claude --uninstall --apply
```

The uninstaller removes only managed links or copies that match its safety checks. It does not
delete the checked-out release source.

## Validation

Install dependencies and run the deterministic validation suite:

```bash
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run python scripts/verify.py --tier deterministic
```

The release plan and evidence are recorded under [`docs/plans`](docs/plans) and
[`docs/verifications`](docs/verifications).
