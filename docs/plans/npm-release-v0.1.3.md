# npm release plan for v0.1.3

Date: 2026-07-22

Package: `@realpkuasule/openapi-engineering-skill`

Version: `0.1.3`

Baseline tag: `v0.1.2`

## Included change log

- Close inherited standard input during CLI capability probes so version commands cannot block on
  an interactive npm lifecycle TTY.
- Add a regression test for the exact `subprocess.DEVNULL` boundary.
- Carry forward the complete unattended-maintenance implementation tagged at `v0.1.2`, which npm
  did not publish after its safety gate exposed this defect.

## Contract-First impact

The additive contract remains OpenAPI 1.3.0. This patch does not change operations, Schemas,
compatibility, authorization, or generated artifacts; it fixes process isolation in the release
verification harness. Codex and Claude Code retain the same serial cross-platform Skill contract.

## Release boundary

The release updates probe isolation, its TDD regression test, version metadata, captured examples,
and release documentation; creates an annotated `v0.1.3` tag; pushes the current branch and tag to
`origin`; then runs `npm publish --access public`. It does not rewrite `v0.1.2`, merge the branch,
create a GitHub Release, enable automation, install launchd jobs, or access private usage evidence.

## Verification

- [x] The inherited-stdin regression test fails before the fix and passes after it.
- [x] Captured examples and all deterministic gates pass in serial mode.
- [x] Interactive npm `prepublishOnly` passes without a CLI probe timeout.
- [x] The packed tarball completes isolated install, verify, and uninstall checks.
- [ ] The release commit and annotated tag point to the same verified tree.
- [ ] The branch and tag are present on `origin`.
- [ ] npm reports `0.1.3` and the intended `latest` dist-tag after publication.

## Rollback

Before pushing, rollback is deletion of the local release commit and tag. After pushing, do not
rewrite the immutable tag. If npm publication has not happened, leave the source tag and publish a
new patch after repairing the blocker. If publication succeeds but a defect is found, publish a new
patch and optionally deprecate `0.1.3`; npm versions are immutable and must never be reused. Any
dist-tag change requires an explicit, audited command.
