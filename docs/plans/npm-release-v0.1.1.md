# npm release plan for v0.1.1

Date: 2026-07-21

Package: `@realpkuasule/openapi-engineering-skill`

Version: `0.1.1`

Baseline tag: `v0.1.0-rc.2`

## Included change log

- Add the privacy-safe self-improvement lifecycle and Maintainer Skill.
- Add active CLI session analysis and digest-bound secondary-review recovery.
- Harden cross-platform deterministic CI, line endings, Skill digests, and packaged lifecycle
  verification.

## Contract-First impact

This patch publishes the additive contract for the OpenAPI 1.2.0 Usage and Maintenance control
plane prepared since the baseline tag. The release-only version changes do not alter operations,
schemas, compatibility, or contract authority. Codex and Claude Code compatibility remains within
the same cross-platform Skill contract.

## Release boundary

This task updates version metadata, release documentation, captured examples, and tests; creates an
annotated `v0.1.1` tag; and pushes the branch and tag. It does not merge the branch, create a GitHub
Release, run `npm publish`, or change npm dist-tags.

## Verification and rollback

- [x] Release metadata RED test becomes GREEN.
- [x] Captured examples and the full deterministic suite pass in serial mode.
- [ ] The release commit and annotated tag point to the same verified tree.
- [ ] The branch and tag are present on `origin`.

Before pushing, rollback is deletion of the local release commit/tag. After pushing, any remote tag
deletion, npm deprecation, or dist-tag change requires separate explicit approval; do not rewrite a
published npm version.
