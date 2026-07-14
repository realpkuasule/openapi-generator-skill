# Decision Framework

Choose a strategy from project evidence, not from the Skill name.

## Candidate strategies

### `openapi-generator`

Prefer when an owned, stable contract serves multiple languages/consumers and the exact target generators pass representative compile/import and fixture gates. Account for output size, runtime dependencies, template maintenance, upgrades, and unsupported OAS features.

### `language-native`

Prefer for a narrow stack when native tooling produces smaller, idiomatic output and cross-language consistency is not the primary goal. Examples may include type-only clients, framework-native route/schema export, or ecosystem-specific server/client generation. Verify current official documentation before naming a tool.

### `official-sdk`

Prefer for third-party APIs when the vendor maintains a suitable SDK, especially for auth, retries, streaming, uploads, pagination, or rapid API evolution. Do not regenerate a vendor client merely because an OpenAPI document exists.

### `governance-only`

Prefer when lint, breaking diff, mock, contract test, docs, or drift detection create value but generated application code does not. Keep handwritten adapters small and typed/tested in the project language.

### `mcp`

Prefer when the goal is agent discovery and invocation of an existing API. Choose runtime proxy versus generated MCP only after considering tool count, auth, prompts, security, and maintenance. Do not confuse Agent exposure with application SDK generation.

### `no-codegen`

Prefer when there is no owned HTTP/process boundary, one simple consumer, an official SDK already owns the integration, or generated output/custom templates cost more than a tested thin adapter. Record the maintenance alternative: language types, fixtures, adapter tests, or governance gates.

## Required evidence

Evaluate:

- project stage and expected lifetime;
- owned versus third-party boundary;
- number and languages of consumers;
- source of truth and schema ownership;
- OpenAPI version and used features;
- target generator/tool status and current release risks;
- representative generate/compile/import/fixture result;
- generated output size, readability, runtime dependencies, and security surface;
- custom template or patch burden;
- generated-file commit/review policy;
- official SDK quality, license, support window, and platform coverage;
- team build/CI capability and decommission cost.

## Decision procedure

1. Confirm a real contract boundary exists. If not, select `no-codegen` unless governance alone has value.
2. Separate owned boundaries from vendor APIs. Evaluate each independently.
3. Define one source of truth and ownership per model family.
4. Remove candidates that cannot meet required OAS/protocol features.
5. Compare the smallest viable candidates, including official SDK and no-codegen.
6. Require an empirical gate for every generator under serious consideration.
7. Select only when benefits, gates, ownership, version pins, rollback, and maintenance are explicit.

## Output

Record:

```yaml
strategy: openapi-generator | language-native | official-sdk | governance-only | mcp | no-codegen
selected_tools: []
rejected_options:
  - option: null
    reason: null
rationale: []
evidence: []
confidence: low | medium | high
conditions: []
revisit_triggers: []
```

Use low confidence when no representative spike or official-source verification exists. Do not conceal an evidence gap with a numeric score.

