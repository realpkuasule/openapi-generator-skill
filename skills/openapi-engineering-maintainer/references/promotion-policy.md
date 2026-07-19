# Promotion Policy

## Proposal digest

Construct canonical JSON with stable key ordering and UTF-8 encoding. Compute the approval SHA-256 over the proposal with the approval field omitted. Bind:

- every finding, analysis, Skill, harness, and configuration digest;
- contract impact and source-of-truth decision;
- each allowed target relative path and its expected current SHA-256 or explicit absence;
- failing-test paths, validation commands, resource limits, and rollback;
- the private candidate/eval content to materialize.

Any field or target hash change invalidates approval and requires a new proposal digest.

## Approval

Show the proposal summary, exact allowed paths, zero-write preflight result, and full approval SHA-256. Accept only explicit approval of that exact digest. Do not treat installation consent, standing collection/sync opt-in, a historical approval, or approval of a parent plan as approval of a changed proposal.

## Preflight

Immediately before writing:

1. Reload and validate the proposal Schema.
2. Recompute the approval digest.
3. Revalidate every input digest and current target hash.
4. Reject absolute paths, traversal, symlinks, unknown paths, and public source paths.
5. Re-run secret/privacy scanning on every proposed byte.
6. Snapshot the exact approved private targets when Git cannot restore them.
7. Confirm no analyzer, generator, or second paid process is running.

Failure at any step must leave every target unchanged.

## Allowed promotion

Promotion may create only explicitly approved private fixtures, eval cases, failing-test skeletons, or traceability candidates. It must not claim the failing test passes and must not implement the fix automatically.

Handoff to formal development as a new Contract-First boundary: update authoritative Schema/OpenAPI/examples, observe the approved failing test RED, implement the minimum fix, observe GREEN, and run security/resource/rollback gates.

## Atomicity and rollback

Write all candidate files to a same-filesystem temporary directory, validate their final bytes, then rename them as one bounded operation. If any rename fails, restore every target from the exact snapshot and verify before/after hashes. Delete only files created by the approved promotion and only while their digest still matches.
