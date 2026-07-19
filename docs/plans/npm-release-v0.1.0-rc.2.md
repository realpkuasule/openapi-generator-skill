# npm release plan for v0.1.0-rc.2

Date: 2026-07-19

Branch: `codex/npm-distribution-v0.1.0-rc.2`

Package: `@realpkuasule/openapi-engineering-skill`

Version: `0.1.0-rc.2`

## Goal and Contract-First impact

Publish the existing Skill as an npm-distributed, explicitly invoked installer for Codex and
Claude Code. The package must be version-pinned, side-effect free during ordinary `npm install`,
dry-run-first, digest-verifiable, conflict-safe, and reversible.

The behavioral control-plane remains OpenAPI 1.1.0. npm distribution introduces a CLI contract but
does not change HTTP requests, responses, schemas, or lifecycle semantics, so this release has **no
schema change**. `package.json`, the CLI help surface, and executable tests are the distribution
contract. If an OpenAPI operation changes during implementation, update `contracts/openapi.yaml`
and its failing contract test before changing behavior.

## Test-Driven implementation

### P0 — Distribution contract and safe installer

1. `tests/test_npm_distribution.py:1` — first add RED tests for the allowlisted package manifest,
   absence of `postinstall`, dual-platform dry run, versioned canonical payload, conflicts, copy
   fallback, verification, and rollback. Verify with
   `python -m unittest tests.test_npm_distribution -v`.
2. `package.json:1` — declare `@realpkuasule/openapi-engineering-skill@0.1.0-rc.2`, Node 20 support,
   `UNLICENSED`, a single executable, no dependencies, and a publication allowlist. Verify the
   manifest test and `npm pack --dry-run --json` contents.
3. `bin/openapi-engineering-skill.mjs:1` — implement dependency-free `install`, `verify`, and
   `uninstall` commands. Default to both platforms and dry-run; require `--apply` for writes; block
   divergent targets atomically. Verify all temporary-home integration tests on POSIX and Windows
   CI.
4. `README.md:1`, `CHANGELOG.md:1`, `pyproject.toml:3`, and `uv.lock:180` — document pinned npx use,
   rollback, limitations, and aligned RC versions. Verify release metadata tests and lock checks.

### P1 — Package and repository gates

1. Pack the tarball locally and inspect the exact file allowlist, modes, unpacked size, package
   name, and version. Verify that tests, contracts, private evidence, `.git`, and Python tooling are
   absent from the tarball.
2. Install the tarball into an isolated npm prefix and run dry-run, apply, verify, uninstall dry-run,
   and uninstall apply against a temporary home. Verify no writes escape that home.
3. Preserve the 151/151 release-base result and target 158/158 after adding seven npm tests. Run the
   17/17 deterministic tier serially and record memory use.
4. Commit, push, open a PR, and require Ubuntu, macOS, and Windows CI before merge. Verify merged
   `main` and its CI SHA.

### P2 — Immutable GitHub and npm publication

1. Create annotated tag `v0.1.0-rc.2` and a GitHub Prerelease from the verified merge commit.
   Verify local and remote tag peeling resolves to that exact SHA.
2. Run `npm publish --access public --tag next` only after npm identity and package contents are
   confirmed. Verify registry metadata, integrity, provenance fields when available, and that
   `latest` is not modified.
3. Run pinned `npx @realpkuasule/openapi-engineering-skill@0.1.0-rc.2` acceptance from the registry
   against another temporary home. Verify install and rollback digests match the bundled Skill.

## Resource guardrails

- Run package tests and repository gates serially.
- Do not run model-backed evaluations or re-download OpenAPI Generator JARs because the Skill,
  contracts, and behavioral harness are unchanged.
- Use temporary homes and npm prefixes for acceptance; remove them after evidence capture.

## Rollback

- Before npm publication, close the PR or delete the unpublished tag/release if validation fails.
- npm versions are immutable: never overwrite `0.1.0-rc.2`. If a defect is published, deprecate it
  with an explanatory message, move the `next` tag back to the last good version, and release a new
  RC.
- For an installation rollback, run `uninstall` without `--apply`, review `would-remove`, then rerun
  with `--apply`. Preserve the canonical payload for auditability.

## Verification checklist

- [x] npm distribution tests demonstrate RED before implementation and GREEN afterward.
- [x] Package manifest is allowlisted, dependency-free, public, and has no `postinstall`.
- [x] OpenAPI 1.1.0 and captured examples validate with no schema change.
- [x] Unit tests report 158/158 and deterministic gates report 17/17.
- [x] Packed tarball contains only the declared distribution files.
- [x] Local tarball install/apply/verify/uninstall acceptance passes in isolation.
- [ ] PR and merged-main CI pass on Ubuntu, macOS, and Windows.
- [ ] GitHub tag and Prerelease resolve to the verified merge commit.
- [ ] npm `next` resolves to `0.1.0-rc.2`; `latest` is not assigned by this prerelease.
- [ ] Registry-backed npx acceptance passes and produces the expected Skill digest.
