# Source release plan for v0.1.5

Date: 2026-07-24

Package: `@realpkuasule/openapi-engineering-skill`

Version: `0.1.5`

Baseline tag: `v0.1.4`

## Included change log

- Recognize metadata-free canonical payloads created by the historical `0.1.0-rc.2` npm
  installer so newer runtime releases can relink Codex and Claude Code targets in place.
- Preserve conflict behavior for unversioned, structurally invalid, or divergent managed-path
  symlinks while keeping every previous canonical payload available for rollback.
- Advance README, package metadata, release tests, and captured version references together for the
  published patch.

## Contract-First impact

The additive contract remains OpenAPI 1.3.0. This patch does not change operations, Schemas,
compatibility, authorization, generated artifacts, or the serial Codex and Claude Code analysis
boundary. It extends installer recognition for a historical canonical layout that predated bundled
`package.json` metadata, while keeping the existing safety contract unchanged for invalid or
divergent targets.

## Release boundary

This release updates installer behavior, README guidance, package and Python version metadata,
captured examples, tests, the changelog, and this plan; creates an annotated `v0.1.5` tag; pushes
the current branch and tag to `origin`; and runs `npm publish` for npm `0.1.5`. It does not merge
the branch, create a pull request or GitHub Release, enable automation, install launchd jobs, or
access private usage evidence.

## TDD and verification

- [x] Release metadata tests were advanced first and fail until the `v0.1.5` metadata is updated.
- [x] The `0.1.0-rc.2` metadata-free installer layout is covered by a regression test before the
  installer implementation change.
- [x] Release metadata and npm distribution tests pass.
- [x] All deterministic `prepublishOnly` gates pass serially before publication.
- [x] The packed npm artifact passes its isolated lifecycle checks, including historical upgrade
  relinking.
- [ ] The release commit and annotated tag point to the same verified tree.
- [ ] The branch and tag are present on `origin`.
- [ ] npm `0.1.5` is published from the verified tree.

## Rollback

Before pushing, rollback is deletion of only the local release commit and tag. After pushing, do
not rewrite the immutable tag; publish a new patch if a defect is found. After npm publication,
never reuse `0.1.5`; repair forward with `0.1.6` or later. Existing canonical payloads remain on
disk for manual rollback of local installations, and the installer preserves them while relinking
platform targets.
