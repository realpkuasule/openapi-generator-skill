# npm v0.1.0-rc.2 local gate summary

Date: 2026-07-19

## Distribution contract

- npm package: `@realpkuasule/openapi-engineering-skill@0.1.0-rc.2`.
- Node engine: 20 or newer; runtime dependencies: none; license metadata: `UNLICENSED`.
- No `postinstall`; writes require an explicit CLI `--apply`.
- npm distribution tests: 7/7 passed after three captured RED cases.
- Node and Python installers agree on Skill digest
  `fe590fed8be092f66d2615f6dd6a65a21585d32efb34833712fbb603968cf6c7`.

## Package acceptance

- `npm pack --dry-run --json --ignore-scripts`: 25 allowlisted files.
- Tests, contracts, verification evidence, development scripts, `.git`, `.DS_Store`,
  `__pycache__`, and bytecode are excluded.
- An actual local tarball was installed into an isolated npm prefix with scripts disabled.
- Dry run, install, verify, uninstall dry run, and uninstall apply all passed against an isolated
  home. Both platform targets were removed and the canonical payload was preserved.
- `npm publish --dry-run --access public --tag next` passed its `prepublishOnly` test gate.

## Repository and behavioral gates

- Repository unit suite: 158/158 passed.
- Deterministic tier: 17/17 passed.
- OpenAPI validation and captured-example conformance passed.
- Protected source-tree digest was unchanged during deterministic verification.
- Existing combined Codex/Claude report revalidated against the unchanged Skill digest; acceptance
  traceability AC-01 through AC-12 also passed.
- Maximum resident memory was approximately 106 MB; no swaps were observed.

## Pending publication boundary

The npm registry responded, and the proposed scoped package returned `E404`, consistent with an
unpublished name. The local npm CLI is not authenticated, so no registry write has occurred. npm
identity must be authenticated and confirmed before the irreversible version publication.
