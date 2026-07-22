# npm release plan for v0.1.2

Date: 2026-07-22

Package: `@realpkuasule/openapi-engineering-skill`

Version: `0.1.2`

Baseline tag: `v0.1.1`

## Included change log

- Add exact-digest standing authorization for unattended coordinator maintenance without storing
  model credentials.
- Add a bounded serial maintenance cycle that synchronizes private evidence, evaluates due
  findings, invokes Codex and risk-required Claude Code, and writes private terminal reports.
- Bind scheduled execution to a qualified absolute Python 3.11+/jsonschema runtime and fail closed
  on identity or dependency drift.
- Add OpenAPI operations, strict Schemas, captured examples, acceptance traceability, tests, and
  operator documentation for the complete lifecycle.

## Contract-First impact

This patch publishes the additive contract for the OpenAPI 1.3.0 unattended-maintenance control
plane prepared since `v0.1.1`. Existing Usage and Maintenance operations retain their semantics;
new automation, cycle, report, and version-two configuration contracts are additive contract
capabilities. Codex and Claude Code remain serial and share the same cross-platform Skill contract.

## Release boundary

The release updates version metadata, release documentation, captured examples, and tests; creates
an annotated `v0.1.2` tag; pushes the current branch and tag to `origin`; then runs `npm publish
--access public`. It does not merge the branch, create a GitHub Release, enable collection or
automation, install launchd jobs, access a private evidence repository, or change any user machine's
Skill installation.

## Verification

- [x] Release metadata tests fail before the version bump and pass after it.
- [x] Captured examples and the full deterministic suite pass in serial mode.
- [x] The packed tarball completes isolated install, verify, and uninstall checks.
- [ ] The release commit and annotated tag point to the same verified tree.
- [ ] The branch and tag are present on `origin`.
- [ ] npm reports `0.1.2` and the intended `latest` dist-tag after publication.

## Rollback

Before pushing, rollback is deletion of the local release commit and tag. After pushing, do not
rewrite the published tag. If npm publication has not happened, leave the pushed release commit and
publish later after authentication is restored. If npm publication succeeds but a defect is found,
publish a new patch and optionally deprecate `0.1.2`; npm versions are immutable and must never be
reused. Any dist-tag change requires an explicit, audited command.
