# Source release plan for v0.1.4

Date: 2026-07-24

Package: `@realpkuasule/openapi-engineering-skill`

Version: `0.1.4`

Baseline tag: `v0.1.3`

## Included change log

- Distinguish the current source tag from the npm `latest` version so installation commands remain
  executable when npm publication is outside the approved release boundary.
- Document explicit runtime and Maintainer Skill installation and verification for both Codex and
  Claude Code, including the runtime-only opt-out.
- Add source-checkout command-resolution, npm authentication, credential-safety, and complete
  component-uninstall troubleshooting.

## Contract-First impact

The additive contract remains OpenAPI 1.3.0. This documentation patch does not change operations,
Schemas, compatibility, authorization, generated artifacts, or the serial Codex and Claude Code
analysis boundary. Version metadata and captured examples advance together so the source tree
remains internally consistent.

## Release boundary

This release updates README guidance, package and Python version metadata, captured examples,
tests, the changelog, and this plan; creates an annotated `v0.1.4` tag; and pushes the current
branch and tag to `origin`. It does not run `npm publish`, change the npm `latest` dist-tag, merge
the branch, create a pull request or GitHub Release, enable automation, install launchd jobs, or
access private usage evidence.

## TDD and verification

- [x] Release metadata tests were advanced first and failed against the `v0.1.3` tree.
- [x] Captured examples reproduce exactly from their Contract-First sources.
- [x] Release metadata and npm distribution tests pass.
- [x] All 26 deterministic gates and 282 tests pass serially without live model invocation.
- [x] The packed npm artifact passes its isolated lifecycle checks.
- [ ] The release commit and annotated tag point to the same verified tree.
- [ ] The branch and tag are present on `origin`.

## Rollback

Before pushing, rollback is deletion of only the local release commit and tag. After pushing, do
not rewrite the immutable tag; publish a new patch if a defect is found. npm remains at `0.1.3`
unless a separate publication is explicitly authorized. If a later `npm publish` fails or exposes
a defect, never reuse a published version; repair forward with another patch. Any dist-tag change
requires an explicit, audited command.
