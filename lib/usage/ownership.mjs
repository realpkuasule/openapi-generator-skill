const EVENT_FIELDS = new Set([
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
]);

const FEEDBACK_FIELDS = new Set([
  "schema_version",
  "feedback_id",
  "event_id",
  "recorded_at",
  "device_alias",
  "rating",
  "friction_tags",
  "feedback_status",
]);

const SUMMARY_FIELDS = new Set([
  "schema_version",
  "period_id",
  "generated_at",
  "input_sha256",
  "threshold_version",
  "device_count",
  "sample_count",
  "metrics",
  "data_completeness",
  "triggered_rule_ids",
]);

const FINDING_BUNDLE_FIELDS = new Set([
  "schema_version",
  "period_id",
  "input_sha256",
  "findings",
]);

const FINDING_FIELDS = new Set([
  "schema_version",
  "finding_id",
  "rule_id",
  "threshold_version",
  "period_id",
  "input_sha256",
  "observed",
  "severity",
  "requires_secondary_review",
  "status",
]);

function exactFields(value, allowed) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === allowed.size &&
    Object.keys(value).every((key) => allowed.has(key))
  );
}

function containsUnsafeString(value) {
  if (typeof value === "string") {
    return (
      /^(?:\/Users\/|\/home\/|[A-Za-z]:[\\/])/.test(value) ||
      /:\/\//.test(value) ||
      /^git@/i.test(value) ||
      /(?:password|private[_-]?key|access[_-]?token|api[_-]?key|CANARY)/i.test(value)
    );
  }
  if (Array.isArray(value)) return value.some((item) => containsUnsafeString(item));
  if (value && typeof value === "object") {
    return Object.values(value).some((item) => containsUnsafeString(item));
  }
  return false;
}

function validTimestamp(value) {
  return typeof value === "string" && !Number.isNaN(new Date(value).getTime());
}

export function validateSanitizedEvent(payload) {
  if (
    !exactFields(payload, EVENT_FIELDS) ||
    !validTimestamp(payload.recorded_at) ||
    !/^[a-z0-9][a-z0-9-]{0,31}$/.test(payload.device_alias || "") ||
    !/^evt-[a-f0-9]{16,64}$/.test(payload.event_id || "") ||
    containsUnsafeString(payload)
  ) {
    throw new Error("Sanitized remote event is invalid.");
  }
  return payload;
}

export function validateSanitizedFeedback(payload) {
  if (
    !exactFields(payload, FEEDBACK_FIELDS) ||
    !validTimestamp(payload.recorded_at) ||
    !/^[a-z0-9][a-z0-9-]{0,31}$/.test(payload.device_alias || "") ||
    !/^fb-[a-f0-9]{16,64}$/.test(payload.feedback_id || "") ||
    containsUnsafeString(payload)
  ) {
    throw new Error("Sanitized remote feedback is invalid.");
  }
  return payload;
}

export function validateOwnedEnvelope(envelope, config) {
  if (
    !envelope ||
    typeof envelope !== "object" ||
    Array.isArray(envelope) ||
    Object.keys(envelope).sort().join(",") !==
      ["envelope_version", "kind", "payload", "payload_sha256"].sort().join(",") ||
    envelope.envelope_version !== 1 ||
    !/^[a-f0-9]{64}$/.test(envelope.payload_sha256 || "")
  ) {
    throw new Error("Outbound envelope is invalid.");
  }
  const payload = envelope.payload;
  const allowed =
    envelope.kind === "usage-event"
      ? EVENT_FIELDS
      : envelope.kind === "user-feedback"
        ? FEEDBACK_FIELDS
        : envelope.kind === "usage-summary"
          ? SUMMARY_FIELDS
          : envelope.kind === "maintenance-findings"
            ? FINDING_BUNDLE_FIELDS
            : null;
  if (!allowed || !exactFields(payload, allowed)) throw new Error("Outbound payload is invalid.");
  if (envelope.kind === "usage-event" || envelope.kind === "user-feedback") {
    if (payload.device_alias !== config.device_alias || !validTimestamp(payload.recorded_at)) {
      throw new Error("Outbound ownership is invalid.");
    }
  } else if (!config.coordinator) {
    throw new Error("Only the coordinator owns aggregate partitions.");
  }
  if (containsUnsafeString(payload)) throw new Error("Outbound payload failed privacy validation.");
  if (envelope.kind === "usage-event") validateSanitizedEvent(payload);
  if (envelope.kind === "user-feedback") validateSanitizedFeedback(payload);
  if (envelope.kind === "usage-summary") {
    if (
      payload.schema_version !== 1 ||
      payload.threshold_version !== 1 ||
      !/^[0-9]{4}-W[0-9]{2}$/.test(payload.period_id || "") ||
      !validTimestamp(payload.generated_at) ||
      !/^[a-f0-9]{64}$/.test(payload.input_sha256 || "")
    ) {
      throw new Error("Outbound summary is invalid.");
    }
  }
  if (envelope.kind === "maintenance-findings") {
    if (
      payload.schema_version !== 1 ||
      !/^[0-9]{4}-W[0-9]{2}$/.test(payload.period_id || "") ||
      !/^[a-f0-9]{64}$/.test(payload.input_sha256 || "") ||
      !Array.isArray(payload.findings) ||
      payload.findings.some(
        (item) =>
          !exactFields(item, FINDING_FIELDS) ||
          item.period_id !== payload.period_id ||
          item.input_sha256 !== payload.input_sha256 ||
          !/^finding-[a-f0-9]{16,64}$/.test(item.finding_id || ""),
      )
    ) {
      throw new Error("Outbound findings are invalid.");
    }
  }
  return envelope;
}

export function remotePartition(envelope) {
  const payload = envelope.payload;
  if (envelope.kind === "usage-event") {
    const month = payload.recorded_at.slice(0, 7);
    return { path: `events/${payload.device_alias}/${month}.jsonl`, id: payload.event_id, format: "jsonl", content: payload };
  }
  if (envelope.kind === "user-feedback") {
    const month = payload.recorded_at.slice(0, 7);
    return { path: `feedback/${payload.device_alias}/${month}.jsonl`, id: payload.feedback_id, format: "jsonl", content: payload };
  }
  const year = payload.period_id.slice(0, 4);
  if (envelope.kind === "usage-summary") {
    return { path: `summaries/${year}/${payload.period_id}.json`, id: payload.period_id, format: "json", content: payload };
  }
  return {
    path: `findings/${year}/${payload.period_id}.json`,
    id: payload.period_id,
    format: "json",
    content: payload.findings,
  };
}
