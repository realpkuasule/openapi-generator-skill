# OpenAPI Engineering Skill

OpenAPI Engineering Skill is a Contract-First, full-lifecycle engineering skill for Codex and
Claude Code. It inspects the current project, conducts a multi-turn boundary interview, proposes
an explicit work boundary, and waits for approval before making changes.

The skill does not assume that OpenAPI Generator is always the right implementation. Depending on
the project, lifecycle stage, and stated intent, it may select OpenAPI Generator, a language-native
generator, an official SDK, contract-governance tooling, MCP integration, or a documented
`no-codegen` decision.

## Release

The current source release is `v0.1.4`. npm `latest` remains `v0.1.3` because this release boundary
ends after the source tag and push; it does not authorize `npm publish`. npm installation requires
Node.js 20 or newer; repository validation requires Python 3.11 or newer. This repository does not
yet declare an open-source license, so the release is intended for controlled evaluation until the
project owner selects one.

The earlier `v0.1.2` tag is retained as an immutable historical source tag but was never published
to npm; use npm `0.1.3` for new package installations or `v0.1.4` for a pinned source checkout.

## Pinned npm installation

Use the exact `0.1.3` release on every machine. The commands below install both the runtime Skill
and the optional Maintainer Skill for Codex and Claude Code. The first command is a read-only dry
run, the second applies the installation, and the third verifies the installed digests:

```bash
npx --yes @realpkuasule/openapi-engineering-skill@0.1.3 install \
  --component runtime --component maintainer \
  --platform codex --platform claude --json
npx --yes @realpkuasule/openapi-engineering-skill@0.1.3 install \
  --component runtime --component maintainer \
  --platform codex --platform claude --apply --json
npx --yes @realpkuasule/openapi-engineering-skill@0.1.3 verify \
  --component runtime --component maintainer \
  --platform codex --platform claude --json
```

The npm CLI copies a versioned canonical payload to
`~/.local/share/openapi-engineering-skill/0.1.3`, then links Codex and Claude Code to that
immutable tree. It has no `postinstall` script and never writes during `npm install` or the default
dry run.

Omit `--component maintainer` on machines that only need the project-aware runtime Skill. The
Maintainer Skill is required for private self-improvement analysis and never enables collection or
unattended execution by itself. Re-running `install` with a newer pinned release safely plans and
then relinks verified earlier npm or legacy Git canonical symlinks; it preserves the old payload for
rollback. Divergent copies remain conflicts and are never overwritten.

If npm reports `openapi-engineering-skill: command not found` while the current directory is this
source checkout, run the command from another directory or use npm's explicit package form:

```bash
npm exec --yes --package=@realpkuasule/openapi-engineering-skill@0.1.3 -- \
  openapi-engineering-skill verify \
  --component runtime --component maintainer \
  --platform codex --platform claude --json
```

Installing a public release does not require npm authentication. For package publication or when
the registry reports `E401`, verify the active account and use npm's browser login flow:

```bash
npm whoami
npm login --auth-type=web
```

Never place an npm token, password, or one-time code in this repository or in a command recorded by
the Skill.

## Optional self-improvement loop

Collection is disabled by default. Local collection and private Git synchronization are separate
opt-ins. The runtime stores structured completion facts, pseudonymous project identifiers, bounded
feedback tags, and explicit unavailable measurements; it does not store prompts, responses, source,
OpenAPI bodies, paths, credentials, or free-form feedback in the synchronized partition.

On the M4 coordinator, preview each operation before adding `--apply`:

```bash
# Point this at an existing Python 3.11+ environment where `import jsonschema` succeeds.
MAINTENANCE_PYTHON="$PWD/.venv/bin/python"

openapi-engineering-skill usage enable --device m4 --coordinator --json
openapi-engineering-skill usage enable --device m4 --coordinator --apply --json
openapi-engineering-skill usage sync configure \
  --remote git@github.com:OWNER/PRIVATE-USAGE-REPO.git --branch main --json
openapi-engineering-skill usage sync configure \
  --remote git@github.com:OWNER/PRIVATE-USAGE-REPO.git --branch main --apply --json
openapi-engineering-skill maintenance automation configure \
  --credential-mode active-cli-session --python "$MAINTENANCE_PYTHON" \
  --notify macos --json
# Review approval_sha256 from the unchanged dry run, then apply that exact digest:
openapi-engineering-skill maintenance automation configure \
  --credential-mode active-cli-session --python "$MAINTENANCE_PYTHON" --notify macos \
  --approve APPROVAL_SHA256 --apply --json
openapi-engineering-skill usage scheduler install --hour 4 --minute 30 --json
openapi-engineering-skill usage scheduler install --hour 4 --minute 30 --apply --json
```

The standing authorization stores no credential. It binds this coordinator, private-sync binding,
package and Skill identity, a qualified Python 3.11+/jsonschema runtime, Codex-then-Claude analyzer
order, resource limits, maximum two serial attempts, and notification policy. Use an absolute
interpreter from an environment where `import jsonschema` succeeds; the configure dry run rejects
the system or Homebrew interpreter when that dependency is missing. Any bound path, resolved target,
Python version, or jsonschema version change blocks before sync or a model call.
The scheduled job runs `maintenance cycle`: private sync first, then the deterministic due check,
Codex only for an actual finding, and Claude Code only when the risk policy requires it. A terminal
JSON/Markdown report is written privately; the macOS notification is fixed and contains no finding,
project, model, path, or retry detail.

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
openapi-engineering-skill maintenance automation status --json
```

Cleanup is dry-run-first and apply requires the exact displayed digest. Disabling collection,
disabling sync, uninstalling the scheduler, and deleting retained facts are intentionally separate
actions. Summary, finding, incident, proposal, promoted eval, and hold records are long-lived.
Revoke unattended model use independently with
`openapi-engineering-skill maintenance automation disable --apply --json`; this does not delete
reports or disable collection/synchronization.

Maintainer analysis requires Python 3.11 plus the locked repository dependencies. The unattended
authorization records the explicit interpreter so launchd never depends on its restricted `PATH`.
The analyzer accepts only a validated sanitized finding bundle, runs Codex first, and invokes Claude
Code serially only for a risk trigger. Promotion first emits a zero-write plan and requires the exact
proposal digest.

For an npm-only installation without a source checkout, prepare that environment explicitly; the
installer never downloads Python packages or mutates an interpreter automatically:

```bash
# Verify this command resolves to Python 3.11 or newer first.
python3 -m venv "$HOME/.local/share/openapi-engineering-skill/maintenance-python"
"$HOME/.local/share/openapi-engineering-skill/maintenance-python/bin/python" -m pip install \
  'jsonschema[format-nongpl]>=4.23,<5'
export MAINTENANCE_PYTHON="$HOME/.local/share/openapi-engineering-skill/maintenance-python/bin/python"
```

Manual analysis/proposal/promotion commands remain separate from the unattended cycle:

```bash
openapi-engineering-skill maintenance analyze --findings PRIVATE-BUNDLE.json \
  --output PRIVATE-ANALYSIS.json
openapi-engineering-skill maintenance propose --analysis PRIVATE-ANALYSIS.json \
  --candidate PRIVATE-CANDIDATE.json --target-root "$PWD" --skill-root skills/openapi-engineering \
  --skill-version 0.1.3 --config-sha256 CONFIG_SHA256 --output PRIVATE-PROPOSAL.json
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

Scheduled automatic analysis never constructs a proposal or performs promotion, never reads a
target project, and never writes public source, GitHub, or npm. It makes at most two serial attempts
for one immutable input and reports `retry-exhausted` rather than looping. An approved manual
promotion is
limited to allowlisted sanitized fixtures, eval cases, deliberately failing test skeletons, or
traceability candidates; any secret, open question, target drift, symlink, or partial write causes
zero net changes.

## Source installation fallback

Clone and check out the exact release before installing so Codex and Claude Code resolve the same
canonical skill tree:

```bash
git clone git@github.com:realpkuasule/openapi-generator-skill.git
cd openapi-generator-skill
git checkout v0.1.4
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
npx --yes @realpkuasule/openapi-engineering-skill@0.1.3 uninstall \
  --component runtime --component maintainer \
  --platform codex --platform claude --json
npx --yes @realpkuasule/openapi-engineering-skill@0.1.3 uninstall \
  --component runtime --component maintainer \
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
