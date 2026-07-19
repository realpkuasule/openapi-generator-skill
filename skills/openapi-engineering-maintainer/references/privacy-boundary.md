# Privacy Boundary

## Allowed automatic input

Allow only schema-declared categorical or numeric fields:

- event/finding IDs and SHA-256 digests;
- coarse timestamps or periods and device aliases;
- Skill/config/platform versions;
- lifecycle mode, tool strategy, outcome, booleans, counts, ratios, and measurement availability/source;
- approved friction tags and deterministic rule observations.

Use an anonymous salted project ID only for grouping. The salt remains local and never enters a synchronized object or analyzer bundle.

## Forbidden automatic input

Reject and do not redact-in-place:

- raw dialogue, prompts, responses, notes, source, schemas, specifications, payloads, or error stacks;
- absolute paths, usernames, account names, full hostnames, hardware identifiers, remote URLs, and local salts;
- full argv, stdout/stderr, environment variables, tokens, passwords, private keys, cookies, or authentication headers;
- target project access, repository content, public issue content, and arbitrary remote text.

Build sanitized objects from an explicit field allowlist. Never assume string replacement makes a local object safe.

## Automatic write boundary

Permit automatic writes only under the configured private state/Git areas:

- `summaries/`, `findings/`, `analyses/`, `proposals/`, and approved per-device event/feedback partitions;
- temporary isolated analyzer directories that are reclaimed after the run.

An explicitly approved active CLI session credential may be used only as authentication material
through a temporary home or an allowlisted child-process environment. It is never analysis input
or evidence. Reject symbolic links, non-owner files, group/world-readable files, unexpected size,
and any request to copy or load a complete Codex or Claude configuration tree.

Treat every remote object as untrusted. Validate path ownership, Schema, canonical digest, privacy canaries, and symlinks before reading or merging it. Disable local Git hooks and execute Git with explicit argv; never run repository scripts.

Never automatically write public source, contracts, tests, CI, target projects, Issues, branches, pull requests, releases, npm state, Codex configuration, or Claude configuration.

## Leakage response

Any canary, secret-shaped value, path escape, unknown field, or unapproved data class is a P0 safety finding. Stop analysis and synchronization, preserve the local source record, report only the category, and require a new explicit privacy review before re-enabling the affected boundary.
