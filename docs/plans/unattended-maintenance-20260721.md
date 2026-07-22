# Unattended maintenance gap implementation plan

Date: 2026-07-21

Status: implemented; deterministic verification passed; live AI verification retained as failed

## Objective

Close the gap between the approved self-improvement requirements and the shipped scheduler. The
M4 coordinator must be able to run synchronization, deterministic due evaluation, and bounded AI
analysis without an interactive prompt after an exact, revocable standing authorization. It writes
only private terminal reports and sends a content-free macOS notification. It never changes public
source, GitHub, npm, a target project, or an improvement proposal.

## Contract-First and TDD order

### P0 — authoritative contract and failing acceptance tests

1. Update `docs/openapi-engineering-self-improvement-requirements.md` and
   `contracts/openapi-engineering.openapi.yaml` before runtime code. Raise the control-plane minor
   version, define automation configuration and cycle operations, and preserve exact-approval and
   zero-public-write semantics.
   Files/lines: `docs/openapi-engineering-self-improvement-requirements.md:408-509`;
   `contracts/openapi-engineering.openapi.yaml:651-735, 1560-1645`.
   Verification: OpenAPI validation and operation stability tests first fail against the old
   implementation and then pass.
2. Update `contracts/schemas/usage-config.schema.json`; add
   `contracts/schemas/maintenance-cycle.schema.json` and
   `contracts/schemas/maintenance-report.schema.json` before implementation. Version-1 config must
   migrate only to a disabled version-2 automation state.
   Files/lines: `contracts/schemas/usage-config.schema.json:23-154`;
   `contracts/schemas/maintenance-cycle.schema.json:1-61`;
   `contracts/schemas/maintenance-report.schema.json:1-60`.
   Verification: valid, stale-authorization, migration, and secret/path canary fixtures.
3. Add RED tests in `tests/test_usage_config.py`, `tests/test_launchd_installation.py`, and the new
   `tests/test_unattended_maintenance.py` for exact standing authorization, sync-before-due,
   no-finding zero-model behavior, serial analyzers, idempotence, bounded retry, private reports,
   notification redaction, and zero public writes.
   Files/lines: `tests/test_usage_config.py:40-350`;
   `tests/test_launchd_installation.py:14-108`;
   `tests/test_unattended_maintenance.py:128-332`.
   Verification: run only the new/changed tests and retain the observed RED output before runtime
   implementation.

### P1 — minimum implementation and deterministic evidence

1. Implement configuration migration and authorization binding in `lib/usage/config.mjs` and CLI
   parsing/routing in `bin/openapi-engineering-skill.mjs`. Configuration is dry-run-first; apply
   requires the exact current digest. Qualify and bind an absolute Python 3.11+/jsonschema runtime
   so background execution never relies on launchd `PATH`.
   Files/lines: `lib/usage/config.mjs:1-340`;
   `bin/openapi-engineering-skill.mjs:80-203, 690-704`.
   Verification: configuration tests cover unchanged, revoked, drifted, collector, and unsafe cases.
2. Implement `lib/usage/maintenance-cycle.mjs` and `lib/usage/maintenance-report.mjs`. Use the
   existing sync, due, analyzer, atomic-file, process-watch, and privacy primitives. Never invoke an
   analyzer without a valid finding bundle and standing authorization; never invoke two analyzers
   concurrently.
   Files/lines: `lib/usage/maintenance-cycle.mjs:1-407`;
   `lib/usage/maintenance-report.mjs:1-113`; `lib/usage/due.mjs:1-180`;
   `lib/usage/paths.mjs:20-55`.
   Verification: fake-adapter end-to-end tests assert order, input shape, process cleanup, retry
   checkpoints, report Schema, and unchanged public-tree digest.
3. Change `packaging/launchd/com.realpkuasule.openapi-engineering-maintainer.plist` so the managed M4
   job runs one maintenance cycle. Reuse the existing generic, digest-bound implementation in
   `lib/usage/launchd.mjs`; no runtime change is required there. Do not install or load a real job
   during development.
   Files/lines: `packaging/launchd/com.realpkuasule.openapi-engineering-maintainer.plist:7-16`;
   unchanged reuse at `lib/usage/launchd.mjs:45-173`.
   Verification: temporary-home tests inspect the exact plist and digest-bound lifecycle.
4. Regenerate `contracts/examples/` only through `scripts/capture_contract_examples.py` and update
   acceptance traceability.
   Files/lines: `scripts/capture_contract_examples.py:32, 455-510, 615-660`;
   `contracts/examples/maintenance-cycle-response.json:1-26`;
   `contracts/self-improvement-acceptance-traceability.yaml:182-241`;
   `contracts/schemas/self-improvement-traceability.schema.json:20-45`.
   Verification: captured-example `--check`, Schema validation, and traceability verification.

### P2 — operator UX, documentation, and live smoke

1. Update both Skill contracts and one-hop references so scheduled active-session authorization is
   distinct from interactive one-run authorization. Update `README.md` and `CHANGELOG.md` with setup,
   revoke, reporting, and failure semantics.
   Files/lines: `skills/openapi-engineering/SKILL.md:151-166`;
   `skills/openapi-engineering-maintainer/SKILL.md:10-66`;
   `skills/openapi-engineering-maintainer/references/unattended-cycle.md:1-38`;
   `README.md:45-142`; `CHANGELOG.md:5-26`.
   Verification: Skill package/eval tests and npm dry-run package inventory.
2. Run `uv run python scripts/verify.py --tier deterministic` serially.
   Files/lines: verification-only; no source file changes. Report target is outside the worktree.
   Verification: every deterministic gate passes and no child process survives.
3. After deterministic GREEN, run one real serialized active-CLI smoke with a synthetic sanitized
   finding. It may contact the currently authenticated Codex and risk-required Claude-compatible
   service, but it must use temporary homes and must not access a real project or remote.
   Files/lines: `scripts/maintenance/analyze_usage.py:218-420` and an ephemeral `/tmp` fixture/output;
   no persistent source or user configuration changes.
   Verification: passed or honestly retained blocked/failed report, bounded RSS/timeout evidence,
   reclaimed process group, and deleted temporary credentials.

## Rollback

- Code and contract edits remain Git-scoped and can be reverted without touching installed Skills.
- Runtime authorization has an independent `maintenance automation disable` path and never restores
  a prior authorization during upgrade or rollback.
- Scheduler uninstall removes only the digest-matched managed plist.
- Disabling automation preserves private terminal reports and never deletes usage history.

## Final verification checklist

- [x] OpenAPI 1.3.0 and all JSON Schemas validate.
- [x] Config v1 migrates to disabled config v2 without writing during status.
- [x] Standing authorization is dry-run-first, exact-digest-bound, revocable, and drift-sensitive.
- [x] Scheduler runs sync before due and AI, only on the coordinator.
- [x] No findings means zero analyzer processes.
- [x] Codex and conditional Claude are serialized with 512/1024 MiB resource gates.
- [x] Same period/input/authorization produces at most one terminal analysis.
- [x] Reports are private, Schema-valid, atomic, and free of credential/path/remote canaries.
- [x] macOS notification contains only a fixed content-free message.
- [x] Public source, target projects, GitHub, npm, and proposal state receive zero automatic writes.
- [x] Captured examples, focused tests, full deterministic verification, and live smoke are recorded.

## Verification outcome

- The deterministic tier passed all 26 gates. The full unit suite passed 280 tests with two
  platform-specific skips; all SI-AC-01 through SI-AC-24 checks passed with fresh test execution.
- A user-home active-session probe reached Codex successfully after WebSocket retries and an HTTPS
  fallback, proving that the account session itself remained usable; it does not prove the isolated
  minimal staging path. Both attempts to analyze the immutable synthetic P1 bundle through that
  isolated path ended as `cli-failed` in the Codex primary before a Schema-valid analysis was
  produced, so Claude was correctly not started. The two-attempt boundary was honored and no third
  attempt was made.
- No analyzer process or per-run temporary credential directory survived. The two similarly named
  `/private/tmp/*-auth-probe` directories predate this run (2026-07-19) and were left untouched.
- This live result is retained honestly as failed verification evidence, not represented as a pass.
  The deterministic fake-adapter cycle remains the acceptance proof for serial ordering, terminal
  reporting, retry exhaustion, notification privacy, and unchanged public source.
