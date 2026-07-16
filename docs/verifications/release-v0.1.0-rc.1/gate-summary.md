# v0.1.0-rc.1 local gate summary

Date: 2026-07-16

## Current release preparation

- Release metadata contract: 4/4 passed after captured RED evidence.
- Repository unit suite: 151/151 passed.
- Deterministic tier: 17/17 passed.
- OpenAPI validation and captured-example conformance: passed within the deterministic tier.
- Protected source-tree digest before and after deterministic verification:
  `9c532287767051bb23ab1f366ab30f46abc27ba9701b28b84570c2647275bfb5`.
- Maximum resident memory: approximately 72 MB for the standalone unit run and 69 MB for the
  deterministic run; no swaps were observed.

## Reused full-lifecycle evidence

The release preparation has no diff under `contracts/`, `skills/`, or `scripts/`. The existing
combined forward report revalidated against the current Skill digest
`fe590fed8be092f66d2615f6dd6a65a21585d32efb34833712fbb603968cf6c7` and Harness digest
`719f0a29467bc6be41457ef7ec3a9ba7aad7fec43d6b996caec2080478c94303`:

- Codex: 10/10 passed.
- Claude Code: 10/10 passed.
- Cross-platform semantic equivalence: 5/5 cases passed.
- Acceptance traceability: AC-01 through AC-12 passed.
- Existing full report: 21/21 gates passed.

The empirical adoption and upgrade commands were not re-executed because their pinned 7.22.0 and
7.23.0 JARs were deliberately removed from `/tmp` after the prior successful run. Re-downloading
large artifacts would add resource and network cost without testing any changed behavioral source.
The committed reports and manifests remain the release-base evidence.

## Installation preflight

The dual-platform installer dry run found no existing target conflict. It proposed links for both
`~/.codex/skills/openapi-engineering` and `~/.claude/skills/openapi-engineering`, with source digest
`fe590fed8be092f66d2615f6dd6a65a21585d32efb34833712fbb603968cf6c7`.
