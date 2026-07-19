# Changelog

All notable changes to this project are documented in this file.

## [0.1.0-rc.3] - 2026-07-19

### Added

- Opt-in, privacy-preserving usage collection, feedback, aggregation, thresholds, retention, and
  deterministic trend/recurrence reports across coordinator and collector devices.
- Strict launcher and Maintainer analyzer process watchers with timeout, process-group ownership,
  peak RSS evidence, and serial Codex/Claude risk review.
- Approval-bound private proposal and promotion workflows with path allowlists, secret scanning,
  exact target hashes, atomic rollback, and deliberately RED failing-test candidates.
- Explicit runtime and Maintainer installation for both Codex and Claude Code, including safe
  migration from verified legacy Git or earlier npm canonical symlinks.

### Contract impact

- The Contract-First behavioral control-plane is OpenAPI 1.2.0.
- The change is additive for existing OpenAPI engineering operations and introduces new Usage and
  Maintenance schemas and CLI commands. Maintenance proposal Schema v2 requires artifact bytes
  and open-question bindings before promotion.

### Safety and release state

- Collection remains disabled by default and requires explicit local and separate sync opt-ins.
- Model-backed jobs remain manual, serial, environment-approved, and excluded from ordinary CI.
- `0.1.0-rc.3` is prepared but must not be published or tagged until deterministic, cross-platform,
  and approved live evidence gates complete.

### Verified

- OpenAPI 1.2.0, all JSON Schemas, captured examples, and 261/261 tests pass locally.
- The actual npm tarball completes isolated install, digest verification, and uninstall without
  touching real Codex or Claude Code settings.
- Ubuntu, macOS, and Windows deterministic jobs pass on PR #4.

## [0.1.0-rc.2] - 2026-07-19

### Added

- Public npm distribution through `@realpkuasule/openapi-engineering-skill`.
- A dependency-free Node.js CLI with dry-run-first `install`, `verify`, and `uninstall` commands.
- Versioned canonical payload storage shared by Codex and Claude Code installations.
- Atomic conflict detection, copy fallback, digest verification, and safe rollback without an npm
  `postinstall` hook.

### Contract impact

- The Contract-First behavioral control-plane remains OpenAPI 1.1.0 with no schema change.

### Verified

- 158/158 repository tests and the 17/17 deterministic gate passed locally.
- The packed package contains 25 allowlisted files and excludes tests, evidence, caches, and
  development tooling.
- Tarball-based dry run, install, digest verification, rollback preview, and rollback application
  passed in an isolated home.
- The unchanged Skill digest continues to validate against the existing Codex and Claude Code
  forward-evaluation evidence.

### Known limitations

- This is a release candidate for controlled evaluation.
- The npm package and repository are marked `UNLICENSED` until the project owner selects a license.

## [0.1.0-rc.1] - 2026-07-16

### Added

- Contract-First project inspection and a multi-turn boundary interview before implementation.
- Intent-scoped modes across discovery, contract design, generator selection, implementation,
  verification, migration, and governance.
- Decision support for OpenAPI Generator, language-native generators, official SDKs,
  contract-governance tools, MCP integrations, and explicit `no-codegen` outcomes.
- One canonical skill package compatible with both Codex and Claude Code.
- Dry-run-first dual-platform installation, conflict detection, digest verification, and safe
  uninstall support.

### Verified

- 147/147 unit tests and the 17/17 deterministic gate passed before release preparation.
- The full 21/21 gate, Codex and Claude Code adapter suites, equivalence checks, and acceptance
  criteria AC-01 through AC-12 passed on the release base commit.
- Ubuntu, macOS, and Windows CI passed on the release base commit.

### Known limitations

- This is a release candidate for controlled evaluation.
- The repository does not yet declare an open-source license.
