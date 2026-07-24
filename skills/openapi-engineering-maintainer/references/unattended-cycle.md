# Unattended Maintenance Cycle

## Eligibility

Run an unattended cycle only when all of these are true:

- usage collection and private Git synchronization are enabled;
- the current device is the configured coordinator;
- analysis is explicitly enabled with `active-cli-session` credential mode;
- an exact-digest standing authorization is present and current;
- the cycle input is produced by the deterministic runtime, not supplied as free text.

The standing authorization binds the device alias, coordinator role, state directory, synchronization remote and branch, package version, Skill digest, a qualified absolute Python 3.11+/jsonschema executable and its resolved runtime versions, analyzer order, resource limits, retry limit, and notification policy. Configure it dry-run-first and apply only the exact displayed digest. Never rely on launchd's restricted `PATH`. Any binding or runtime-target change invalidates it and blocks before synchronization credentials or analyzer credentials are used.

## Fixed sequence

Execute one serial sequence:

1. Validate configuration, standing authorization, the bound Python/jsonschema runtime, ownership, privacy, and lock state.
2. Synchronize the private Git partition. A synchronization failure is terminal and invokes no analyzer.
3. Run the deterministic due calculation and persist its bounded analysis bundle.
4. If no finding exists, return `no-findings` with zero analyzer attempts and no analysis report.
5. Run Codex as primary. Run Claude Code only after Codex exits and only when the deterministic risk policy requires independent review.
6. Make max 2 serial attempts for the same immutable input. Resume a valid passed primary only under the analysis-workflow rules.
7. After analysis reaches a terminal result, write schema-valid private JSON and Markdown reports atomically, then optionally send the fixed notification.

Do not run proposal construction or promotion from this sequence. Do not edit source, contracts, tests, CI, GitHub, npm, Agent configuration, or any target project.

## Terminal outcomes

Every cycle returns a bounded status such as `completed`, `no-findings`, `sync-blocked`, `blocked`, `failed`, or `retry-exhausted`. Only a cycle that launched analysis produces a private terminal analysis report. Re-running the same terminal immutable input reuses the same deterministic report identity and must not create duplicate analysis attempts.

The private report records the cycle and input digests, deterministic rules, actual analyzer sequence, attempt count, bounded resource evidence, private artifact paths, public-source tree hash, authorization state, unverified items, and rollback guidance. The fixed notification contains none of that detail; it only tells the user that maintenance reached a terminal state and that the private report is ready.
