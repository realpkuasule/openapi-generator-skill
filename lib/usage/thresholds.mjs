import { canonicalSha256 } from "./canonical-json.mjs";

const RULES = {
  safety: { id: "SI-SAFETY-001", severity: "P0" },
  platform: { id: "SI-PLATFORM-001", severity: "P0" },
  friction: { id: "SI-FRICTION-001", severity: "P2" },
  override: { id: "SI-OVERRIDE-001", severity: "P1" },
  unverified: { id: "SI-UNVERIFIED-001", severity: "P1" },
  interview: { id: "SI-INTERVIEW-001", severity: "P2" },
  resource: { id: "SI-RESOURCE-001", severity: "P1" },
  regression: { id: "SI-REGRESSION-001", severity: "P0" },
};

function finding(rule, periodId, inputSha256, observed) {
  return {
    schema_version: 1,
    finding_id: `finding-${canonicalSha256({ rule_id: rule.id, period_id: periodId, input_sha256: inputSha256 }).slice(0, 16)}`,
    rule_id: rule.id,
    threshold_version: 1,
    period_id: periodId,
    input_sha256: inputSha256,
    observed,
    severity: rule.severity,
    requires_secondary_review: rule.severity === "P0" || rule.severity === "P1",
    status: "open",
  };
}

function observed(metric, value, comparator, threshold, sampleCount, windowDays) {
  return {
    metric,
    value,
    comparator,
    threshold,
    sample_count: sampleCount,
    window_days: windowDays,
  };
}

export function evaluateThresholds({
  events,
  feedback,
  metrics,
  periodId,
  inputSha256,
  resolvedIncidentIds = [],
}) {
  const findings = [];
  if (events.some((event) => event.safety_violation)) {
    findings.push(finding(RULES.safety, periodId, inputSha256, observed("safety_violation", 1, ">=", 1, events.length, null)));
  }
  if (events.some((event) => event.platform_drift)) {
    findings.push(finding(RULES.platform, periodId, inputSha256, observed("platform_drift", 1, ">=", 1, events.length, null)));
  }

  const frictionCounts = new Map();
  for (const item of feedback) {
    for (const tag of item.friction_tags || []) {
      frictionCounts.set(tag, (frictionCounts.get(tag) || 0) + 1);
    }
  }
  const frictionMax = Math.max(0, ...frictionCounts.values());
  if (frictionMax >= 3) {
    findings.push(finding(RULES.friction, periodId, inputSha256, observed("friction_count", frictionMax, ">=", 3, feedback.length, 30)));
  }

  if (events.length >= 5 && metrics.tool_override_ratio > 0.2) {
    findings.push(finding(RULES.override, periodId, inputSha256, observed("tool_override_ratio", metrics.tool_override_ratio, ">", 0.2, events.length, 30)));
  }
  if (events.length >= 5 && metrics.unverified_ratio > 0.2) {
    findings.push(finding(RULES.unverified, periodId, inputSha256, observed("unverified_ratio", metrics.unverified_ratio, ">", 0.2, events.length, 30)));
  }
  if ((metrics.interview_median ?? 0) > 5 || (metrics.interview_max ?? 0) > 8) {
    const useMaximum = (metrics.interview_max ?? 0) > 8;
    findings.push(
      finding(
        RULES.interview,
        periodId,
        inputSha256,
        observed(
          useMaximum ? "interview_max" : "interview_median",
          useMaximum ? metrics.interview_max : metrics.interview_median,
          ">",
          useMaximum ? 8 : 5,
          events.length,
          30,
        ),
      ),
    );
  }
  const resourceAbsolute = (metrics.peak_rss_max_mb ?? 0) > 512;
  const resourceRelative =
    metrics.peak_rss_baseline_mb !== null &&
    metrics.peak_rss_max_mb !== null &&
    metrics.peak_rss_max_mb > metrics.peak_rss_baseline_mb * 2;
  if (resourceAbsolute || resourceRelative) {
    findings.push(
      finding(
        RULES.resource,
        periodId,
        inputSha256,
        observed(
          resourceRelative ? "peak_rss_baseline_multiple" : "peak_rss_mb",
          resourceRelative
            ? metrics.peak_rss_max_mb / metrics.peak_rss_baseline_mb
            : metrics.peak_rss_max_mb,
          ">",
          resourceRelative ? 2 : 512,
          events.length,
          30,
        ),
      ),
    );
  }

  const resolved = new Set(resolvedIncidentIds);
  if (events.some((event) => (event.incident_ids || []).some((id) => resolved.has(id)))) {
    findings.push(finding(RULES.regression, periodId, inputSha256, observed("resolved_incident_recurrence", 1, ">=", 1, events.length, null)));
  }
  return findings.sort((left, right) => left.rule_id.localeCompare(right.rule_id));
}
