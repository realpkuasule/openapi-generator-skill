import { readFile } from "node:fs/promises";

import { canonicalSha256 } from "./canonical-json.mjs";
import { loadUsageEvents } from "./events.mjs";
import { loadUsageFeedback } from "./feedback.mjs";
import { assertSafeUsagePath, configuredStateRoot, usageStatePaths } from "./paths.mjs";
import { evaluateThresholds } from "./thresholds.mjs";
import { readJsonIfExists } from "./atomic-files.mjs";
import { validateSanitizedEvent, validateSanitizedFeedback } from "./ownership.mjs";
import { sanitizeUsageEvent } from "./redact.mjs";

const DAY_MS = 24 * 60 * 60 * 1000;

function median(values) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
}

function isoWeekWindow(now) {
  const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const day = date.getUTCDay() || 7;
  const start = new Date(date.getTime() - (day - 1) * DAY_MS);
  const end = new Date(start.getTime() + 7 * DAY_MS);
  const thursday = new Date(start.getTime() + 3 * DAY_MS);
  const yearStart = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((thursday.getTime() - yearStart.getTime()) / DAY_MS + 1) / 7);
  return {
    start,
    end,
    periodId: `${thursday.getUTCFullYear()}-W${String(week).padStart(2, "0")}`,
    generatedAt: end.toISOString(),
  };
}

function periodWindow(period, now) {
  if (period === "iso-week") return isoWeekWindow(now);
  if (period === "30d" || period === "90d") {
    const days = Number.parseInt(period, 10);
    const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
    return {
      start: new Date(end.getTime() - days * DAY_MS),
      end,
      periodId: `rolling-${period}-${end.toISOString().slice(0, 10)}`,
      generatedAt: end.toISOString(),
    };
  }
  throw new Error("Summary period is invalid.");
}

function inWindow(timestamp, window) {
  const value = new Date(timestamp).getTime();
  return Number.isFinite(value) && value >= window.start.getTime() && value < window.end.getTime();
}

async function resolvedIncidentIds(path) {
  try {
    const payload = JSON.parse(await readFile(path, "utf8"));
    if (!payload || !Array.isArray(payload.incident_ids)) throw new Error("Resolved incidents are invalid.");
    return payload.incident_ids;
  } catch (error) {
    if (error.code === "ENOENT") return [];
    if (error instanceof SyntaxError) throw new Error("Resolved incidents are invalid.");
    throw error;
  }
}

export async function buildUsageSummary({ home, config, options }) {
  if (!config.local_collection_enabled || !config.device_alias) {
    throw new Error("Local collection is disabled.");
  }
  const now = new Date(options.now || new Date().toISOString());
  if (Number.isNaN(now.getTime())) throw new Error("Timestamp is invalid.");
  const window = periodWindow(options.period || "iso-week", now);
  const stateRoot = configuredStateRoot(config, home, options.stateRoot);
  const paths = usageStatePaths(stateRoot, config.device_alias);
  for (const target of [
    paths.events,
    paths.feedback,
    paths.incidents,
    paths.aggregateEvents,
    paths.aggregateFeedback,
  ]) {
    await assertSafeUsagePath(stateRoot, target);
  }
  const localEvents = await loadUsageEvents(paths.events);
  const localFeedback = await loadUsageFeedback(paths.feedback);
  const aggregateEvents = (await readJsonIfExists(paths.aggregateEvents)) || [];
  const aggregateFeedback = (await readJsonIfExists(paths.aggregateFeedback)) || [];
  if (!Array.isArray(aggregateEvents) || !Array.isArray(aggregateFeedback)) {
    throw new Error("Coordinator aggregate is invalid.");
  }
  aggregateEvents.forEach(validateSanitizedEvent);
  aggregateFeedback.forEach(validateSanitizedFeedback);
  const eventMap = new Map(aggregateEvents.map((event) => [event.event_id, event]));
  for (const event of localEvents) eventMap.set(event.event_id, event);
  const feedbackMap = new Map(
    aggregateFeedback.map((item) => [item.feedback_id, item]),
  );
  for (const item of localFeedback) feedbackMap.set(item.feedback_id, item);
  const allEvents = [...eventMap.values()];
  const allFeedback = [...feedbackMap.values()];
  const events = allEvents.filter((event) => inWindow(event.recorded_at, window));
  const feedbackStart = new Date(now.getTime() - 30 * DAY_MS);
  const feedback = allFeedback.filter((item) => {
    const value = new Date(item.recorded_at).getTime();
    return Number.isFinite(value) && value >= feedbackStart.getTime() && value <= now.getTime();
  });
  const outcomes = { passed: 0, partial: 0, failed: 0, blocked: 0 };
  for (const event of events) outcomes[event.outcome] += 1;
  const interview = events.map((event) => event.interview_turns);
  const currentRss = events
    .filter((event) => event.peak_rss_mb.availability === "available")
    .map((event) => event.peak_rss_mb.value);
  const baselineRss = allEvents
    .filter(
      (event) =>
        new Date(event.recorded_at).getTime() < window.start.getTime() &&
        event.peak_rss_mb.availability === "available",
    )
    .map((event) => event.peak_rss_mb.value);
  let availableMeasurements = 0;
  let unavailableMeasurements = 0;
  for (const event of events) {
    for (const measurement of [event.duration_ms, event.peak_rss_mb]) {
      if (measurement.availability === "available") availableMeasurements += 1;
      else unavailableMeasurements += 1;
    }
  }
  const metrics = {
    outcomes,
    tool_override_ratio:
      events.length === 0 ? null : events.filter((event) => event.tool_overridden).length / events.length,
    unverified_ratio:
      events.length === 0
        ? null
        : events.filter((event) => event.gates.unverified > 0).length / events.length,
    interview_median: median(interview),
    interview_max: interview.length === 0 ? null : Math.max(...interview),
    peak_rss_max_mb: currentRss.length === 0 ? null : Math.max(...currentRss),
    peak_rss_baseline_mb: median(baselineRss),
  };
  const inputSha256 = canonicalSha256({
    events: [...events].sort((left, right) => left.event_id.localeCompare(right.event_id)),
    feedback: [...feedback].sort((left, right) => left.feedback_id.localeCompare(right.feedback_id)),
    period_id: window.periodId,
    threshold_version: 1,
  });
  const findings = evaluateThresholds({
    events,
    feedback,
    metrics,
    periodId: window.periodId,
    inputSha256,
    resolvedIncidentIds: await resolvedIncidentIds(`${paths.incidents}/resolved.json`),
  });
  const summary = {
    schema_version: 1,
    period_id: window.periodId,
    generated_at: window.generatedAt,
    input_sha256: inputSha256,
    threshold_version: 1,
    device_count: new Set(events.map((event) => event.device_alias)).size,
    sample_count: events.length,
    metrics,
    data_completeness: {
      available_measurements: availableMeasurements,
      unavailable_measurements: unavailableMeasurements,
    },
    triggered_rule_ids: findings.map((finding) => finding.rule_id),
  };
  const sanitizedEvents = events
    .map((event) => sanitizeUsageEvent(event))
    .sort((left, right) => {
      const timestamp = left.recorded_at.localeCompare(right.recorded_at);
      return timestamp === 0 ? left.event_id.localeCompare(right.event_id) : timestamp;
    });
  return { summary, findings, sanitizedEvents, stateRoot };
}
