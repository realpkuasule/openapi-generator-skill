# OpenAPI Engineering Skill

OpenAPI Engineering Skill is a Contract-First, full-lifecycle engineering skill for Codex and
Claude Code. It inspects the current project, conducts a multi-turn boundary interview, proposes
an explicit work boundary, and waits for approval before making changes.

The skill does not assume that OpenAPI Generator is always the right implementation. Depending on
the project, lifecycle stage, and stated intent, it may select OpenAPI Generator, a language-native
generator, an official SDK, contract-governance tooling, MCP integration, or a documented
`no-codegen` decision.

## Release

The prepared patch release is `v0.1.1`. npm installation requires Node.js 20 or newer;
repository validation requires Python 3.11 or newer. This repository does not yet declare an
open-source license, so the release is intended for controlled evaluation until the
project owner selects one.

## Pinned npm installation

`0.1.1` is currently prepared, not published. Use these commands only after the npm release
gate is approved; until then, use the source installation fallback below. Use the exact release on
every machine. The first command is a read-only dry run, the second applies the installation, and
the third verifies the installed digests:

```bash
npx --yes @realpkuasule/openapi-engineering-skill@0.1.1 install \
  --platform codex --platform claude --json
npx --yes @realpkuasule/openapi-engineering-skill@0.1.1 install \
  --platform codex --platform claude --apply --json
npx --yes @realpkuasule/openapi-engineering-skill@0.1.1 verify \
  --platform codex --platform claude --json
```

The npm CLI copies a versioned canonical payload to
`~/.local/share/openapi-engineering-skill/0.1.1`, then links Codex and Claude Code to that
immutable tree. It has no `postinstall` script and never writes during `npm install` or the default
dry run.

Add `--component maintainer` only on machines where private self-improvement analysis is intended.
Re-running `install` with a newer pinned release safely plans and then relinks verified earlier npm or
legacy Git canonical symlinks; it preserves the old payload for rollback. Divergent copies remain
conflicts and are never overwritten.

## Optional self-improvement loop

Collection is disabled by default. Local collection and private Git synchronization are separate
opt-ins. The runtime stores structured completion facts, pseudonymous project identifiers, bounded
feedback tags, and explicit unavailable measurements; it does not store prompts, responses, source,
OpenAPI bodies, paths, credentials, or free-form feedback in the synchronized partition.

On the M4 coordinator, preview each operation before adding `--apply`:

```bash
openapi-engineering-skill usage enable --device m4 --coordinator --json
openapi-engineering-skill usage enable --device m4 --coordinator --apply --json
openapi-engineering-skill usage sync configure \
  --remote git@github.com:OWNER/PRIVATE-USAGE-REPO.git --branch main --json
openapi-engineering-skill usage sync configure \
  --remote git@github.com:OWNER/PRIVATE-USAGE-REPO.git --branch main --apply --json
openapi-engineering-skill usage scheduler install --hour 4 --minute 30 --json
openapi-engineering-skill usage scheduler install --hour 4 --minute 30 --apply --json
```

On M2 and MBP14, omit `--coordinator`; each machine owns an append-only device partition and can
queue data offline:

```bash
openapi-engineering-skill usage enable --device m2 --apply --json
openapi-engineering-skill usage sync configure \
  --remote git@github.com:OWNER/PRIVATE-USAGE-REPO.git --branch main --apply --json

openapi-engineering-skill usage enable --device mbp14 --apply --json
openapi-engineering-skill usage sync configure \
  --remote git@github.com:OWNER/PRIVATE-USAGE-REPO.git --branch main --apply --json
```

Useful coordinator checks are deterministic and do not invoke a model:

```bash
openapi-engineering-skill usage sync --json
openapi-engineering-skill usage due --now 2026-07-20T12:00:00Z --json
openapi-engineering-skill usage trends \
  --now 2026-07-20T12:00:00Z --fix-at 2026-06-20T00:00:00Z --json
openapi-engineering-skill usage cleanup --scope local --now 2026-07-20T12:00:00Z --json
```

Cleanup is dry-run-first and apply requires the exact displayed digest. Disabling collection,
disabling sync, uninstalling the scheduler, and deleting retained facts are intentionally separate
actions. Summary, finding, incident, proposal, promoted eval, and hold records are long-lived.

Maintainer analysis requires Python 3.11 plus the locked repository dependencies. It accepts only a
validated sanitized finding bundle, runs Codex first, and invokes Claude Code serially only for a
risk trigger. Promotion first emits a zero-write plan and requires the exact proposal digest:

```bash
openapi-engineering-skill maintenance analyze --findings PRIVATE-BUNDLE.json \
  --output PRIVATE-ANALYSIS.json
openapi-engineering-skill maintenance propose --analysis PRIVATE-ANALYSIS.json \
  --candidate PRIVATE-CANDIDATE.json --target-root "$PWD" --skill-root skills/openapi-engineering \
  --skill-version 0.1.1 --config-sha256 CONFIG_SHA256 --output PRIVATE-PROPOSAL.json
openapi-engineering-skill maintenance promote --proposal PRIVATE-PROPOSAL.json \
  --target-root "$PWD" --approve APPROVAL_SHA256
# Repeat the unchanged command with --apply only after reviewing the exact plan.
```

The analysis command defaults to approved API-key environment variables. For a one-person local
installation with existing Codex and Claude Code subscription logins, explicitly add
`--credential-mode active-cli-session`. That mode stages only Codex's private auth file and extracts
only allowlisted Claude Code authentication/provider fields into the controlled child environment;
it never loads hooks, plugins, permissions, MCP configuration, history, projects, or Agent
configuration, and it refuses unsafe credential permissions instead of falling back to the real
home directory. Compatible DeepSeek/MiMo providers are recorded as their actual model, not as an
Anthropic model.

If Codex passed but a required Claude review was blocked or failed, retry only the secondary review
with `--resume-analysis PRIVATE-ANALYSIS.json`. Resume requires an exact current bundle digest,
finding-ID match, valid prior Schema, and a passed Codex primary; it never skips an unrun or failed
primary analysis.

Automatic analysis never reads a target project or writes public source. An approved promotion is
limited to allowlisted sanitized fixtures, eval cases, deliberately failing test skeletons, or
traceability candidates; any secret, open question, target drift, symlink, or partial write causes
zero net changes.

## Source installation fallback

Clone and check out the exact release before installing so Codex and Claude Code resolve the same
canonical skill tree:

```bash
git clone git@github.com:realpkuasule/openapi-generator-skill.git
cd openapi-generator-skill
git checkout v0.1.1
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
npx --yes @realpkuasule/openapi-engineering-skill@0.1.1 uninstall \
  --platform codex --platform claude --json
npx --yes @realpkuasule/openapi-engineering-skill@0.1.1 uninstall \
  --platform codex --platform claude --apply --json
```

The uninstaller removes only managed links or copies that match its safety checks. It preserves the
versioned canonical payload for auditing or later reinstallation. Existing divergent targets are
reported as conflicts and are never overwritten or removed automatically.

## Validation

Install dependencies and run the deterministic validation suite:

```bash
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run python scripts/verify.py --tier deterministic
```

The release plan and evidence are recorded under [`docs/plans`](docs/plans) and
[`docs/verifications`](docs/verifications).
