# Boundary Interview

## Contents

1. Discovery snapshot
2. Question sequence
3. Work-boundary summary
4. Approval rules
5. Scope expansion

## Discovery snapshot

Before asking, summarize only observed evidence:

- project kind and likely stage;
- owned HTTP/process boundaries and third-party integrations;
- contract files and likely sources of truth;
- consumers and languages;
- existing generators, generated directories, CI, and governance profile;
- contradictions or unknowns that affect authority.

Label each item `observed`, `user-decided`, or `inferred`. Do not turn an inference into a default when it changes architecture, writes, dependencies, cost, or security.

## Question sequence

Ask one cluster per turn. Skip resolved clusters unless evidence conflicts.

### 1. Intent and stage

Offer project-specific choices such as:

- assess only;
- design a new contract boundary;
- perform a first integration;
- evolve an existing endpoint;
- audit drift;
- upgrade/troubleshoot/harden/reselect.

Confirm non-goals. An “audit” request does not authorize fixes.

### 2. Contract boundary

Ask which APIs, processes, packages, and consumers are included. Name detected candidates. Confirm exclusions explicitly, especially third-party APIs, domain documents, streaming adapters, and unrelated services.

### 3. Authority and ownership

Resolve:

- spec-first, code-first, hybrid, third-party, or no HTTP contract;
- who owns endpoint/envelope/protocol schemas;
- who owns domain models and persistent documents;
- whether generated types are transport DTOs or domain truth;
- whether vendor APIs must use official SDKs.

Reject dual authority. If OpenAPI and standalone JSON Schema overlap, require a mapping/projection rule and one owner per shape.

### 4. Strategy and outputs

Present 2–4 viable strategies with costs. Include no-codegen when plausible. Ask which outputs are wanted: client, server boundary, types, docs, mocks, tests, MCP, or governance only.

Do not infer that “use OpenAPI” means “generate everything.”

### 5. Execution authority

Confirm exact files/directories, dependency changes, allowed commands, network access, credentials, paid APIs, service starts, test data, and CI changes. Default real services, production, paid calls, and destructive tests to excluded.

### 6. Acceptance and lifecycle

Confirm lint, breaking diff, isolated generation diff, compile/import, fixtures, contract tests, generated-file policy, rollback, ownership, and upgrade window.

## Work-boundary summary

Include every field below even when empty:

```yaml
intent: [selected lifecycle modes]
goals: [observable outcomes]
non_goals: [explicit exclusions]
contract_authority:
  sources_of_truth: []
  ownership_rules: []
boundaries:
  included: []
  excluded: []
tool_decision:
  selected: null
  rejected: []
  rationale: []
  confidence: low | medium | high
files_to_read: []
files_to_change: []
dependencies: []
commands: []
network_and_external_effects: []
deliverables: []
acceptance_gates: []
rollback: []
open_questions: []
```

State: “No modifying action will start until you approve this complete boundary.”

## Approval rules

Valid approval:

- follows the complete summary;
- clearly refers to the whole summary or names approved exceptions;
- leaves no unaccepted open question that changes execution.

Not approval:

- answering one interview question;
- agreeing that a tool looks suitable;
- asking for more detail;
- approving only a spec design while files/commands remain unknown;
- a prior approval before the summary changed.

When approval includes exceptions, revise and re-present the complete summary before acting.

## Scope expansion

Pause and re-propose when discovery requires new files, dependency/tool category, outputs, template forks, real-service access, credentials, breaking migrations, consumer coordination, or reduced validation. Preserve completed in-scope work; report the reason, alternatives, incremental changes, and rollback. Wait again.

