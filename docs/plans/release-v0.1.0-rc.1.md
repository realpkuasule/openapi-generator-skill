# v0.1.0-rc.1 release plan

Date: 2026-07-16

Branch: `codex/release-v0.1.0-rc.1`

Tag: `v0.1.0-rc.1`

## Goal and Contract-First impact

Publish the first controlled evaluation release, then install that exact release into Codex and
Claude Code from one canonical source tree.

The behavioral control-plane contract remains OpenAPI 1.1.0. This release preparation changes
package versioning, release documentation, and distribution only: **no schema change** is required.
Contract validation and captured-example checks must still run to prove that packaging work did not
introduce drift. If behavior or a request/response shape changes during preparation, stop the
release, update the OpenAPI document first, add a failing contract test, and only then implement the
change.

## Test-Driven sequence

### P0 — Release contract and metadata

1. `tests/test_release_metadata.py:1` — add failing tests for the PEP 440 version, release tag,
   dual-platform installation, rollback, changelog, and Contract-First impact statement.
   Verify with `python -m unittest tests.test_release_metadata -v`; capture the initial RED result.
2. `pyproject.toml:3` and `uv.lock:180` — set package metadata to `0.1.0rc1` and regenerate the lock.
   Verify that both TOML documents parse and the release metadata test is GREEN.
3. `README.md:1` — document the skill boundary interview, adaptive generator decision, pinned
   installation for Codex and Claude Code, verification, and uninstall workflow.
   Verify required commands through the release metadata test and installer dry runs.
4. `CHANGELOG.md:1` — record release scope, evidence, and known limitations.
   Verify the dated `0.1.0-rc.1` section through the release metadata test.
5. `docs/plans/release-v0.1.0-rc.1.md:1` — record contract impact, gates, publication, installation,
   and rollback before executing release mutations.
   Verify the document names OpenAPI 1.1.0, no schema change, and all target platforms.

### P1 — Quality gates and publication

1. Repository-wide tests — preserve the 147/147 release-base result and raise the target to 151/151
   after adding four release contract tests. Verify with unittest discovery and the 17/17
   deterministic gate, serially to control memory use.
2. `docs/verifications/release-v0.1.0-rc.1/` — capture RED/GREEN metadata evidence and final gate
   summaries. Verify evidence paths and commit hashes before publication.
3. GitHub — commit the release preparation, push the branch, open a PR, wait for CI, merge, and
   confirm main CI. Create annotated tag `v0.1.0-rc.1` from the verified merge commit and publish a
   prerelease. Verify the remote tag, release target commit, prerelease flag, and checks.

### P2 — Pinned installation and smoke verification

1. `/Users/zhichao/.local/share/openapi-generator-skill/v0.1.0-rc.1` — clone the exact tag as an
   immutable canonical installation source. Verify `git describe --tags --exact-match` and commit
   equality with the GitHub release target.
2. `/Users/zhichao/.codex/skills/openapi-engineering` and
   `/Users/zhichao/.claude/skills/openapi-engineering` — run installer dry-run, apply, repeat dry-run,
   and quick validation. Verify both platforms resolve the canonical tree and report equal digests.
3. Perform a read-only invocation smoke test for each adapter. Verify project inspection begins
   without write operations and requires the boundary interview before execution approval.

## Resource guardrails

- Run heavyweight gates serially; do not launch model-backed evaluations for release-only changes.
- Check memory before and after each gate and stop if pressure becomes critical.
- Reuse committed evaluation evidence when source digests prove the evaluated skill and harness are
  unchanged; do not re-download large generator JARs solely for packaging metadata.

## Rollback

- Before merge: close the PR and delete the release branch if the gates fail.
- After publication: mark the GitHub prerelease invalid and remove its tag only if the published
  artifact is incorrect; preserve an audit note explaining why.
- Installation: preview and run `scripts/install_skill.py --platform codex --platform claude
  --uninstall --apply`, then verify both managed targets are absent.
- Never overwrite an existing divergent Codex or Claude Code skill directory automatically.

## Final verification checklist

- [x] Release metadata test is RED before implementation and GREEN afterward.
- [x] Package and lock versions are `0.1.0rc1`.
- [x] OpenAPI 1.1.0 validates and captured examples remain conformant.
- [x] Unit tests report 151/151 and deterministic checks report 17/17.
- [x] Release-source digests match the previously verified full-gate evidence.
- [ ] PR and main CI pass on Ubuntu, macOS, and Windows.
- [ ] Annotated tag and GitHub prerelease target the verified main merge commit.
- [ ] Codex and Claude Code installation dry runs are clean and their digests match.
- [ ] Both adapters pass a read-only smoke invocation.
- [x] Rollback commands have been dry-run and recorded.
- [x] The absence of a declared license remains visible as an RC limitation.
