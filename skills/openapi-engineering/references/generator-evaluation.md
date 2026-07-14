# Generator Evaluation

Run this only after the work boundary approves temporary generation, commands, dependencies, and network access.

## Representative fixture

Build the smallest contract that contains the project's risky features: nullable/optional semantics, enums, oneOf/anyOf/allOf, discriminators, additional properties, auth, errors, uploads, streaming/event semantics, headers, pagination, dates, and external schema projections. Include only features the project actually needs.

## Seven-step empirical gate

1. Validate and lint the contract with pinned tools; preserve exact errors and warnings.
2. Generate with an exact tool version and committed-equivalent config into a fresh temporary directory.
3. Inventory output, runtime dependencies, warnings, and generation metadata; reject unexpected network or post-generation actions.
4. Compare against the accepted baseline with `scripts/compare_generation.py`; inspect every added, removed, and changed file.
5. Compile/import the generated target and run formatter/type checks only when approved and non-mutating to source.
6. Run representative fixture and contract tests for serialization, auth, errors, risky schema features, and adapters.
7. Decide adopt, conditionally adopt, fall back, or reject; record evidence, version pin, limitations, rollback, and revisit trigger.

Do not generate directly into the project until all applicable temporary-directory gates pass and the approved boundary permits that output path.

## Interpret results

- A `stable` label is supporting evidence, not proof for the project's feature set.
- A successful generation command is insufficient without compile/import and fixture evidence.
- A small unsupported feature may justify one thin hand-written adapter.
- Repeated post-generation patches, broad template forks, or disabled validation are rejection signals.
- If only type extraction is needed, compare a language-native type generator.
- For vendor APIs, compare the official SDK before generated clients.
- For no owned boundary, reject code generation unless a concrete consumer-sync problem remains.

## Upgrade comparison

Preserve the previous tool, config, contract digest, and generated baseline. Verify release notes from an official source, run both versions from clean directories, compare outputs, and test consumers. Never call an upgrade complete while generated diffs or target tests remain unexplained.

## Result record

Capture:

- input contract and digest;
- tool, exact version, distribution, and config;
- command and environment constraints;
- output directory and file counts;
- warnings and unsupported features;
- diff summary;
- compile/import and fixture results;
- required adapters/templates;
- decision and rejected alternatives;
- rollback and revisit triggers.

