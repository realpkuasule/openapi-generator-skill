# Analysis Workflow

## Contents

1. Eligible input
2. Primary analysis
3. Secondary review
4. Output validation
5. Failure handling

## Eligible input

Consume only the deterministic runtime's maintenance-analysis request:

- one or more validated `maintenance-finding` objects;
- zero to 50 validated sanitized usage events;
- one threshold/config version and immutable input digest;
- no target project path or free-form transcript.

Recompute the canonical digest before analyzer invocation. If no finding remains after validation, return without invoking a model.

## Primary analysis

Use Codex as the primary analyzer. Give it the stable rule IDs, observed metrics, thresholds, sanitized categorical evidence, and the required output Schema. Ask for clusters, candidate causes, confidence, and explicit unverified items. Do not send expected conclusions or commands to execute.

Run in an isolated temporary home with the narrowest available read-only mode. Forward only the documented process/locale/certificate environment allowlist. Do not forward arbitrary parent environment variables.

## Secondary review

Require Claude Code review only when at least one condition holds:

- safety or unauthorized-write finding;
- Codex/Claude platform drift finding;
- P0 or P1 candidate;
- primary confidence below the configured threshold;
- primary result is blocked.

Run Claude only after the Codex process group has exited and its temporary directory has been reclaimed. Require a genuinely different platform/session. If Claude is unavailable, keep the primary result and set the review status to `blocked`; do not run Codex again as a substitute.

## Output validation

Accept only a `maintenance-analysis` object with:

- the exact input digest and finding IDs;
- actual analyzer platform, CLI/model version when observable, and status;
- deterministic cluster keys referencing known findings;
- bounded candidate-cause and unverified strings;
- a secondary-review state consistent with the trigger risk.

Reject extra fields, unknown finding IDs, commands, absolute paths, remote URLs, credentials, and output that claims an unrun gate passed.

## Failure handling

Use these terminal states:

- `passed`: required analyzers exited successfully and output passed Schema/privacy gates;
- `failed`: an analyzer ran but failed, returned malformed output, or contradicted immutable evidence;
- `blocked`: authorization, independent platform, timeout, resource, or prerequisite prevented required work.

On timeout or RSS hard limit, terminate the complete child process group, retain bounded evidence, remove both temporary directories, and verify no child survived. Never terminate a user-owned process by name.
