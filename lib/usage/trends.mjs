import { readFile } from "node:fs/promises";

import { canonicalSha256 } from "./canonical-json.mjs";
import { readJsonIfExists } from "./atomic-files.mjs";
import { loadUsageEvents } from "./events.mjs";
import { validateSanitizedEvent } from "./ownership.mjs";
import { assertSafeUsagePath, configuredStateRoot, usageStatePaths } from "./paths.mjs";
import { sanitizeUsageEvent } from "./redact.mjs";

const DAY_MS = 24 * 60 * 60 * 1000;
const MINIMUM_SAMPLES = 5;

function ratio(events, predicate) {
  return events.length === 0 ? null : events.filter(predicate).length / events.length;
}

function windowReport(events, start, end) {
  const selected = events.filter((event) => {
    const timestamp = new Date(event.recorded_at).getTime();
    return Number.isFinite(timestamp) && timestamp >= start.getTime() && timestamp < end.getTime();
  });
  const successRatio = ratio(selected, (event) => event.outcome === "passed");
  const nonpassingRatio = ratio(selected, (event) => event.outcome !== "passed");
  const unverifiedRatio = ratio(selected, (event) => event.gates.unverified > 0);
  const toolOverrideRatio = ratio(selected, (event) => event.tool_overridden);
  const frictionScore = selected.length === 0
    ? null
    : (nonpassingRatio + unverifiedRatio + toolOverrideRatio) / 3;
  return {
    start: start.toISOString(),
    end: end.toISOString(),
    sample_count: selected.length,
    metrics: {
      success_ratio: successRatio,
      nonpassing_ratio: nonpassingRatio,
      unverified_ratio: unverifiedRatio,
      tool_override_ratio: toolOverrideRatio,
      friction_score: frictionScore,
    },
    events: selected,
  };
}

async function resolvedIncidents(path) {
  try {
    const payload = JSON.parse(await readFile(path, "utf8"));
    if (
      !payload
      || Object.keys(payload).length !== 1
      || !Array.isArray(payload.incident_ids)
      || new Set(payload.incident_ids).size !== payload.incident_ids.length
      || payload.incident_ids.some((value) => !/^inc-[a-f0-9]{16,64}$/.test(value))
    ) {
      throw new Error("Resolved incident registry is invalid.");
    }
    return payload.incident_ids;
  } catch (error) {
    if (error.code === "ENOENT") return [];
    if (error instanceof SyntaxError) throw new Error("Resolved incident registry is invalid.");
    throw error;
  }
}

function publicWindow(value) {
  const { events: _events, ...report } = value;
  return report;
}

function comparison(before, after) {
  if (before.sample_count < MINIMUM_SAMPLES || after.sample_count < MINIMUM_SAMPLES) {
    return {
      status: "insufficient",
      reason: `At least ${MINIMUM_SAMPLES} factual samples are required in each 30-day window.`,
      friction_score_delta: null,
    };
  }
  const delta = after.metrics.friction_score - before.metrics.friction_score;
  const rounded = Math.round(delta * 1_000_000) / 1_000_000;
  if (rounded <= -0.05) {
    return { status: "improved", reason: "Factual friction decreased across the boundary.", friction_score_delta: rounded };
  }
  if (rounded >= 0.05) {
    return { status: "worsened", reason: "Factual friction increased across the boundary.", friction_score_delta: rounded };
  }
  return { status: "unchanged", reason: "Factual friction changed by less than five percentage points.", friction_score_delta: rounded };
}

export async function buildUsageTrends({ home, config, options }) {
  if (!config.local_collection_enabled || !config.device_alias) {
    throw new Error("Local collection is disabled.");
  }
  const now = new Date(options.now || new Date().toISOString());
  if (Number.isNaN(now.getTime())) throw new Error("Timestamp is invalid.");
  const fixAt = options.fixAt ? new Date(options.fixAt) : null;
  if (fixAt && (Number.isNaN(fixAt.getTime()) || fixAt >= now)) {
    throw new Error("Fix boundary is invalid.");
  }
  const boundary = fixAt || new Date(now.getTime() - 30 * DAY_MS);
  const beforeStart = new Date(boundary.getTime() - 30 * DAY_MS);
  const afterEnd = fixAt
    ? new Date(Math.min(now.getTime(), boundary.getTime() + 30 * DAY_MS))
    : now;
  const rollingStart = new Date(now.getTime() - 90 * DAY_MS);

  const stateRoot = configuredStateRoot(config, home, options.stateRoot);
  const paths = usageStatePaths(stateRoot, config.device_alias);
  const resolvedPath = `${paths.incidents}/resolved.json`;
  for (const path of [paths.events, paths.aggregateEvents, paths.incidents, resolvedPath]) {
    await assertSafeUsagePath(stateRoot, path);
  }
  const localEvents = await loadUsageEvents(paths.events);
  const aggregateEvents = (await readJsonIfExists(paths.aggregateEvents)) || [];
  if (!Array.isArray(aggregateEvents)) throw new Error("Coordinator aggregate is invalid.");
  const eventMap = new Map();
  function addEvent(event, local) {
    const sanitized = local ? sanitizeUsageEvent(event) : event;
    validateSanitizedEvent(sanitized);
    const prior = eventMap.get(event.event_id);
    if (prior && canonicalSha256(prior.sanitized) !== canonicalSha256(sanitized)) {
      throw new Error("Conflicting duplicate usage event ID.");
    }
    if (!prior || local) eventMap.set(event.event_id, { event, sanitized });
  }
  aggregateEvents.forEach((event) => addEvent(event, false));
  localEvents.forEach((event) => addEvent(event, true));
  const records = [...eventMap.values()].sort((left, right) =>
    left.event.event_id.localeCompare(right.event.event_id));
  const allEvents = records.map((record) => record.event);

  const before = windowReport(allEvents, beforeStart, boundary);
  const after = windowReport(allEvents, boundary, afterEnd);
  const rolling = windowReport(allEvents, rollingStart, now);
  const versions = new Map();
  for (const event of rolling.events) {
    versions.set(event.skill_version, (versions.get(event.skill_version) || 0) + 1);
  }
  const resolved = new Set(await resolvedIncidents(resolvedPath));
  const recurrences = new Map();
  for (const event of after.events) {
    for (const incidentId of event.incident_ids || []) {
      if (!resolved.has(incidentId)) continue;
      if (!recurrences.has(incidentId)) recurrences.set(incidentId, []);
      recurrences.get(incidentId).push(event.event_id);
    }
  }
  const regressions = [...recurrences.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([incidentId, eventIds]) => ({
      rule_id: "SI-REGRESSION-001",
      incident_id: incidentId,
      fingerprint: canonicalSha256({ incident_id: incidentId }),
      event_ids: [...new Set(eventIds)].sort(),
    }));
  const digestInput = {
    events: records.map((record) => ({
      ...record.sanitized,
      incident_ids: [...(record.event.incident_ids || [])].sort(),
    })),
    resolved_incident_ids: [...resolved].sort(),
    now: now.toISOString(),
    fix_at: fixAt?.toISOString() || null,
    minimum_samples: MINIMUM_SAMPLES,
  };
  return {
    schema_version: 1,
    generated_at: now.toISOString(),
    input_sha256: canonicalSha256(digestInput),
    comparison_basis: fixAt ? "fix-boundary" : "adjacent-30d",
    fix_at: fixAt?.toISOString() || null,
    minimum_samples: MINIMUM_SAMPLES,
    windows: {
      before_30d: publicWindow(before),
      after_30d: publicWindow(after),
      rolling_90d: publicWindow(rolling),
    },
    comparison: comparison(before, after),
    version_segments: [...versions.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([skillVersion, sampleCount]) => ({ skill_version: skillVersion, sample_count: sampleCount })),
    regressions,
  };
}
