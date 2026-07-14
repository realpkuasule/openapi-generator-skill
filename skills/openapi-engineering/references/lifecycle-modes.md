# Lifecycle Modes

Activate only modes needed for the current request. List each active mode in the work-boundary summary.

## Assess & Select

- Use for “should we use OpenAPI/codegen?” or tool comparison.
- Ask about real boundaries, consumers, sources of truth, maintenance cost, and official SDKs.
- Deliver a selected strategy, rejected options, evidence gaps, and optionally no-codegen.
- Do not install or generate during assessment unless a separately approved empirical spike is added.

## Initial Design

- Use before an owned API or process boundary exists.
- Resolve protocol scope, source of truth, model ownership, compatibility policy, errors, auth, streaming, and versioning.
- Update the authoritative contract and examples before implementation.
- Avoid defining OpenAPI for internal code that has no HTTP/process boundary.

## First Integration

- Use to add the first generator/governance chain.
- Confirm versions, config, outputs, generated-file policy, hand-written extension points, CI, and rollback.
- Run the empirical generator gate before writing project outputs.
- Deliver reproducible commands and gates, not only generated files.

## Daily Evolution

- Use for endpoint/schema additions, removals, or behavior changes.
- Start with contract/examples and a breaking-change assessment.
- Add a failing consumer/provider test before implementation.
- Regenerate only approved outputs and review the generation diff.

## Audit & Drift

- Use to compare contract, implementation, generated artifacts, profile, and CI.
- Default to read-only. Report drift, severity, evidence, and proposed fixes.
- Do not fix findings without a new approved write boundary.

## Upgrade & Migration

- Use for OpenAPI, generator, template, framework, runtime, or SDK upgrades.
- Verify the target release and breaking changes from official sources.
- Generate into an isolated directory, compare, compile/import, run fixtures, and preserve rollback.
- Never overwrite the accepted baseline before gates pass.

## Troubleshoot

- Use for validation, generation, compile, serialization, auth, or runtime failures.
- Create the smallest representative failing contract/test.
- Distinguish spec defects, unsupported features, config errors, template defects, and runtime mismatches.
- Prefer a small adapter or different tool over an accumulating post-generation patch stack.

## Governance Hardening

- Use to establish ownership, lint, breaking diff, generation diff, compile/import, fixtures, contract tests, CI, and review rules.
- Match rigor to boundary impact; do not add code generation merely to enable governance.
- Record the gates and their owners in the governance profile.

## Reselect & Decommission

- Use when generated output costs exceed benefits or target support declines.
- Compare replacement, official SDK, governance-only, and no-codegen.
- Preserve consumer compatibility and plan removal of configs, dependencies, generated artifacts, and CI.
- Prove the replacement before deleting the existing path.

## Combining modes

Common combinations:

- Assess & Select + Initial Design for a new boundary;
- Daily Evolution + Audit & Drift for an uncertain existing contract;
- Troubleshoot + Upgrade & Migration only when the defect is version-specific;
- Reselect & Decommission + Governance Hardening to retain compatibility gates without codegen.

If a newly needed mode expands files, dependencies, external effects, or acceptance risk, re-propose the boundary.

