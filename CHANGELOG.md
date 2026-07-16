# Changelog

All notable changes to this project are documented in this file.

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
