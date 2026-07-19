# npm release plan for v0.1.0-rc.3

Date: 2026-07-19

Package: `@realpkuasule/openapi-engineering-skill`

Version: `0.1.0-rc.3`

## Contract-First impact

This release prepares the self-improvement lifecycle designed in OpenAPI 1.2.0. It is an
**additive contract** for existing inspection and generation operations, with new Usage,
Maintenance, retention, trend, analysis, proposal, and promotion contracts. The required
proposal artifact/open-question fields are intentionally stricter pre-release behavior.

## Test-Driven release boundary

- Run all JSON Schema/OpenAPI/example tests before runtime tests.
- Run the full deterministic suite serially and record peak RSS and swap.
- Run `npm pack --dry-run --json --ignore-scripts`, then install the tarball in a temporary home.
- Verify dry-run, apply, verify, earlier npm relink, legacy Git migration, scheduler, cleanup,
  promotion rollback, and uninstall without touching real Agent settings.
- Run the manual self-hosted Codex primary and risk-triggered Claude review only after environment
  approval. Never run either model in ordinary PR CI.

## Publication boundary

Do not create `v0.1.0-rc.3`, a GitHub release, npm publication, or dist-tag change as part of code
implementation. After all evidence is approved, publish once with `npm publish --access public
--tag next`; npm versions are immutable and `0.1.0-rc.2` must never be overwritten.

## Rollback

- Before publication, discard the release commit or prepare a corrected RC.
- After publication, deprecate a defective RC and move `next` back to the last good version.
- Installation rollback is dry-run-first `uninstall`; preserved versioned canonical payloads and
  legacy source trees are never deleted automatically.

## Verification checklist

- [x] OpenAPI 1.2.0, JSON Schemas, and captured examples pass with no drift.
- [x] Full deterministic suite passes serially with bounded RSS and zero swap.
- [x] npm allowlist and isolated tarball lifecycle pass.
- [x] Ubuntu, macOS, and Windows deterministic CI pass.
- [ ] Approved Codex and Claude Code live evidence passes without public-source changes.
- [ ] Git tag, GitHub prerelease, npm publication, registry integrity, and cross-machine npx checks
      receive separate owner approval.
