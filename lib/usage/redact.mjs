const SANITIZED_EVENT_FIELDS = [
  "schema_version",
  "event_id",
  "session_id",
  "recorded_at",
  "device_alias",
  "skill_version",
  "skill_sha256",
  "platform",
  "capture_mode",
  "anonymous_project_id",
  "lifecycle_modes",
  "tool_strategy",
  "outcome",
  "interview_turns",
  "boundary_revisions",
  "tool_overridden",
  "gates",
  "duration_ms",
  "peak_rss_mb",
  "exit_code",
  "termination_reason",
  "feedback_status",
  "safety_violation",
  "resource_anomaly",
  "platform_drift",
];

export function sanitizeUsageEvent(localEvent) {
  return Object.fromEntries(
    SANITIZED_EVENT_FIELDS.map((field) => [field, structuredClone(localEvent[field])]),
  );
}

export function sanitizeFeedback(localFeedback) {
  const { note: _note, ...sanitized } = localFeedback;
  return sanitized;
}

export function outboundEnvelope(kind, payload) {
  return {
    envelope_version: 1,
    kind,
    payload_sha256: canonicalSha256(payload),
    payload,
  };
}
import { canonicalSha256 } from "./canonical-json.mjs";
