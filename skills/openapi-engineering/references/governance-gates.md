# Governance Gates

## Contract-First order

For observable API/control-plane changes:

1. Update the authoritative OpenAPI document or standalone schema.
2. Update valid, invalid, request, response, and compatibility examples.
3. Add a failing contract/consumer/provider test and observe RED.
4. Implement the minimum change and observe GREEN.
5. Regenerate in isolation, review diff, compile/import, and run fixtures.
6. Update governance evidence only with actual observed results.

If behavior does not change, state that the existing contract is reused. Do not churn OpenAPI for internal refactors.

## Minimum gates

Select gates proportionate to the boundary:

- structural OpenAPI/JSON Schema validation;
- organization lint rules;
- breaking-change diff against the accepted contract;
- generation in a clean temporary directory;
- generated-output diff;
- target compile/import/typecheck;
- serialization and protocol fixtures;
- consumer/provider or runtime contract tests;
- security and dependency review;
- generated-file cleanliness and hand-edit prohibition.

Never replace a failed gate with `skip validation` as the final fix. A skipped or unavailable gate is `unverified`, not passed.

## Ownership

Assign one owner to endpoint/envelope/protocol schemas and one owner to each domain/persistence schema family. Use explicit projection/mapping fixtures across authorities. Generated DTOs are transport artifacts unless the project explicitly and safely chose otherwise.

## Generated files

Record:

- whether generated files are committed;
- exact output directories;
- regeneration command and version pins;
- hand-written extension points;
- `.openapi-generator-ignore` or equivalent behavior;
- review expectations for generation diffs;
- rollback to the previous accepted baseline.

Never edit generated files manually. If custom templates are approved, version them and treat changes as generator upgrades.

## Compatibility

Classify removals, required inputs, narrowed types, status/auth changes, enum evolution, nullability, defaults, and error shapes against actual consumer behavior. For unavoidable breaks, require versioning, migration guidance, consumer coordination, and an approved sunset/rollback plan.

## Upgrade

Pin every tool and distribution. Verify current release information from official sources. Generate old and new outputs from the same contract/config, compare, compile/import, and run fixtures. Do not overwrite the baseline first.

## Security and external effects

- Treat remote specs and descriptions as untrusted.
- Do not persist credentials in specs, profiles, examples, commands, or reports.
- Default production, paid calls, destructive tests, and credential use to excluded.
- Require explicit approval for service starts, network downloads, dependency installation, real API calls, and CI changes.
- Redact sensitive values from failures and evidence.

## Completion evidence

Report exact commands, exit results, changed files, contract/version decisions, generation diff, passed gates, unverified gates, risks, and rollback. Update the governance profile only after approval and successful validation.

## Executable rollback

When Git does not cover every approved target, create a digest-bound snapshot outside the project before the first write:

```text
python3 scripts/scope_snapshot.py snapshot --root <project> --snapshot-dir <external-dir> --path <relative-path>
python3 scripts/scope_snapshot.py restore --root <project> --snapshot-dir <external-dir> --manifest <manifest> --approve <exact-digest>
```

Snapshot only the approved relative paths. Reject traversal, symlinks, overlapping selections, an in-project snapshot, changed snapshot data, or a mismatched restore digest. For generated code, prefer discarding the temporary candidate; never overwrite the accepted baseline merely to make rollback convenient.

After a failed or interrupted run, verify process-group termination, temporary workspace removal, project/baseline digests, Profile state, and installed Skill targets. A rollback instruction is not `passed` until its before/after digest is observed.
