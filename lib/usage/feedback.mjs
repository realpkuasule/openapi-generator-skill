import { appendFile, lstat, mkdir, readFile, readdir, rm } from "node:fs/promises";
import { basename, join } from "node:path";

import { atomicWriteJson } from "./atomic-files.mjs";
import { canonicalSha256 } from "./canonical-json.mjs";
import { assertSafeUsagePath, configuredStateRoot, usageStatePaths } from "./paths.mjs";
import { outboundEnvelope, sanitizeFeedback } from "./redact.mjs";

const RATINGS = new Set(["met", "friction", "wrong-decision", "execution-error", "skipped"]);
const TAGS = new Set([
  "too-many-questions",
  "boundary-mismatch",
  "wrong-tool",
  "generation-quality",
  "verification-gap",
  "platform-drift",
  "resource-usage",
  "other",
]);

async function pathInfo(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function feedbackFiles(root) {
  const info = await pathInfo(root);
  if (!info) return [];
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("Feedback state path is unsafe.");
  const files = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isSymbolicLink()) throw new Error("Feedback state contains a symbolic link.");
    if (entry.isDirectory()) files.push(...(await feedbackFiles(path)));
    else if (entry.isFile() && basename(path).endsWith(".jsonl")) files.push(path);
  }
  return files;
}

export async function loadUsageFeedback(root) {
  const values = [];
  for (const path of (await feedbackFiles(root)).sort()) {
    const content = await readFile(path, "utf8");
    try {
      values.push(...content.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line)));
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error("Feedback log is invalid.");
      throw error;
    }
  }
  return values;
}

async function withFeedbackLock(lockPath, callback) {
  await mkdir(join(lockPath, ".."), { recursive: true, mode: 0o700 });
  try {
    await mkdir(lockPath, { mode: 0o700 });
  } catch (error) {
    if (error.code === "EEXIST") throw new Error("Usage state is busy.");
    throw error;
  }
  try {
    return await callback();
  } finally {
    await rm(lockPath, { recursive: true, force: true });
  }
}

function conflict(message) {
  const error = new Error(message);
  error.exitCode = 1;
  return error;
}

export async function recordFeedback({ home, config, options, events }) {
  if (!config.local_collection_enabled || !config.device_alias) {
    throw new Error("Local collection is disabled.");
  }
  const event = events.find((candidate) => candidate.session_id === options.session);
  if (!event) throw conflict("Feedback session was not found.");
  if (!RATINGS.has(options.rating)) throw new Error("Feedback rating is invalid.");
  const tags = [...new Set(options.tags || [])].sort();
  if (tags.some((tag) => !TAGS.has(tag))) throw new Error("Feedback tag is invalid.");
  if (!["met", "skipped"].includes(options.rating) && tags.length === 0) {
    throw new Error("A friction tag is required for this rating.");
  }
  if (options.note !== null && options.note !== undefined && options.note.length > 2000) {
    throw new Error("Feedback note is too long.");
  }
  const recordedAt = new Date(options.now || new Date().toISOString());
  if (Number.isNaN(recordedAt.getTime())) throw new Error("Timestamp is invalid.");
  const stateRoot = configuredStateRoot(config, home, options.stateRoot);
  const paths = usageStatePaths(stateRoot, config.device_alias);
  const month = `${recordedAt.getUTCFullYear()}-${String(recordedAt.getUTCMonth() + 1).padStart(2, "0")}`;
  for (const target of [paths.feedback, paths.outbound, paths.locks]) {
    await assertSafeUsagePath(stateRoot, target);
  }

  return withFeedbackLock(join(paths.locks, "feedback.lock"), async () => {
    const prior = await loadUsageFeedback(paths.feedback);
    if (prior.some((feedback) => feedback.event_id === event.event_id)) {
      throw conflict("Feedback already exists for this event.");
    }
    const feedback = {
      schema_version: 1,
      feedback_id: `fb-${canonicalSha256({ event_id: event.event_id }).slice(0, 16)}`,
      event_id: event.event_id,
      recorded_at: recordedAt.toISOString(),
      device_alias: config.device_alias,
      rating: options.rating,
      friction_tags: tags,
      note: options.note || null,
      feedback_status: options.rating === "skipped" ? "skipped" : "answered",
    };
    await atomicWriteJson(
      join(paths.outbound, `feedback-${feedback.feedback_id}.json`),
      outboundEnvelope("user-feedback", sanitizeFeedback(feedback)),
    );
    await mkdir(paths.feedback, { recursive: true, mode: 0o700 });
    await appendFile(join(paths.feedback, `${month}.jsonl`), `${JSON.stringify(feedback)}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
    return feedback;
  });
}

export function isAnomalousEvent(event) {
  return (
    event.outcome !== "passed" ||
    event.gates.failed > 0 ||
    event.gates.unverified > 0 ||
    event.tool_overridden ||
    event.safety_violation ||
    event.resource_anomaly ||
    event.platform_drift
  );
}

export function shouldRequestFeedback(event, successfulEventCount, sampleEvery = 5) {
  if (isAnomalousEvent(event)) return true;
  return successfulEventCount > 0 && successfulEventCount % sampleEvery === 0;
}
