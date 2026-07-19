# Self-improvement implementation gate summary

Date: 2026-07-19

Prepared release: `0.1.0-rc.3` (not tagged or published)

## Deterministic result

- Status: `passed`
- Gates: 26/26 passed
- Unit and integration tests: 269/269 passed, serial execution (2 Windows-specific assertions skipped locally)
- SI acceptance: SI-AC-01 through SI-AC-18 passed; `acceptance_complete: true`
- Contract: OpenAPI 3.1 document version 1.2.0; all Draft 2020-12 Schemas and captured examples passed
- Packaging: runtime and Maintainer Skill validation passed; npm dry pack allowlist and isolated
  real-tarball install, verify, and uninstall lifecycle passed
- Integrity: protected source-tree digest was unchanged by verification
- Runtime observation: system-wide memory-free percentage was 63–64% around the final serial
  deterministic and traceability runs, with no residual verifier or analyzer process.

Authoritative machine reports:

- `final-report.json` — deterministic gate report
- `final-report.xml` — JUnit projection
- `traceability-report.json` — fresh SI-AC-01 through SI-AC-18 execution and artifact digests
- `final-report-evidence/` — per-gate command output and SHA-256 evidence

## Implemented lifecycle

- Explicit local and separate private-sync opt-in, structured completion recording, redaction, feedback sampling, summaries, deterministic thresholds, offline replay, multi-device aggregation, retention, cleanup, and launchd scheduling.
- Strict session launcher and analyzer process watchers with owned process groups, timeout, peak RSS, warning/hard limits, and unsupported-watcher blocking.
- Codex primary analysis with risk-triggered serial independent Claude review; ordinary CI remains model-free.
- Explicit `active-cli-session` authentication for users without OpenAI/Anthropic API keys, with
  minimal Codex credential staging and allowlisted Claude-compatible provider environment fields.
- Digest-bound `--resume-analysis` recovery reuses a passed Codex primary result and reruns only a
  previously blocked/failed Claude review; analyzer failures retain safe failure codes and resources.
- Approval-bound proposal Schema v2 and zero-write-first promotion with content digests, open questions, secret scanning, path allowlists, target hash revalidation, and verified rollback.
- 30/90-day factual trend comparison, minimum sample gates, version segments, and resolved-incident recurrence detection.
- Explicit Maintainer installation and safe relink migration from verified earlier npm or legacy Git canonical symlinks.

## External release gates

Completed outside the local development run:

- PR #4 GitHub-hosted deterministic CI passed on Ubuntu, macOS, and Windows.
- Approved live Maintainer analysis passed in strict serial order. Codex used CLI
  `0.145.0-alpha.18`; Claude Code `2.1.152` used the configured `deepseek-v4-pro[1m]` compatible
  model. Peak RSS was 154,697,728 and 337,559,552 bytes respectively, both below the 512 MiB
  warning boundary. The committed evidence is sanitized in `live-maintainer-evidence.json`.

The following remain separately approval-bound:

- The `v0.1.0-rc.3` tag, GitHub prerelease, npm publish/dist-tag changes, and registry-backed
  M4/M2/MBP14 acceptance remain separate gates.

Until those gates pass, `0.1.0-rc.3` is release-ready source, not a published install target.
