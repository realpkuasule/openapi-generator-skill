import { createHash, randomBytes } from "node:crypto";
import {
  appendFile,
  lstat,
  mkdir,
  readFile,
  readdir,
  rm,
} from "node:fs/promises";
import { basename, join, relative } from "node:path";

import { atomicWrite, atomicWriteJson } from "./atomic-files.mjs";
import { canonicalSha256 } from "./canonical-json.mjs";
import { isAnomalousEvent, shouldRequestFeedback } from "./feedback.mjs";
import { assertSafeUsagePath, configuredStateRoot, usageStatePaths } from "./paths.mjs";
import { outboundEnvelope, sanitizeUsageEvent } from "./redact.mjs";

const SESSION_PATTERN = /^ses-[a-f0-9]{16,64}$/;
const PLATFORM_VALUES = new Set(["codex", "claude", "unknown"]);
const CAPTURE_MODES = new Set(["best-effort", "launcher"]);
const OUTCOMES = new Set(["passed", "partial", "failed", "blocked"]);

async function pathInfo(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function listFiles(root) {
  const info = await pathInfo(root);
  if (!info) return [];
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("Usage state path is unsafe.");
  const files = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isSymbolicLink()) throw new Error("Usage state contains a symbolic link.");
    if (entry.isDirectory()) files.push(...(await listFiles(path)));
    else if (entry.isFile()) files.push(path);
  }
  return files;
}

async function treeDigest(root) {
  const digest = createHash("sha256");
  const files = (await listFiles(root)).sort((a, b) =>
    relative(root, a).localeCompare(relative(root, b)),
  );
  for (const path of files) {
    digest.update(relative(root, path).split("\\").join("/"));
    digest.update("\0");
    digest.update(await readFile(path));
    digest.update("\0");
  }
  return digest.digest("hex");
}

function validateReport(report) {
  if (!report || typeof report !== "object" || !OUTCOMES.has(report.outcome)) {
    throw new Error("Completion Report is invalid.");
  }
  for (const field of [
    "changed_files",
    "commands",
    "results",
    "unverified",
    "risks",
    "rollback",
    "profile_changes",
  ]) {
    if (!Array.isArray(report[field])) throw new Error("Completion Report is invalid.");
  }
  return report;
}

function integerOption(value, name, fallback = 0) {
  if (value === null || value === undefined) return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 0) throw new Error(`${name} must be a non-negative integer.`);
  return parsed;
}

function measurement(value, captureMode) {
  if (value === null || value === undefined) {
    return { availability: "unavailable", source: captureMode === "launcher" ? "not-reported" : "best-effort" };
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) throw new Error("Measurement must be non-negative.");
  return { availability: "available", source: captureMode === "launcher" ? "launcher" : "completion-report", value: parsed };
}

function validateLauncherReport(report, platform) {
  const required = new Set([
    "report_version",
    "status",
    "agent",
    "command_sha256",
    "started_at",
    "finished_at",
    "duration_ms",
    "peak_rss_mb",
    "exit_code",
    "termination_reason",
    "warning_exceeded",
    "hard_limit_exceeded",
    "process_group_reclaimed",
  ]);
  if (
    !report ||
    typeof report !== "object" ||
    Array.isArray(report) ||
    Object.keys(report).length !== required.size ||
    Object.keys(report).some((key) => !required.has(key)) ||
    report.report_version !== 1 ||
    !new Set(["passed", "failed", "blocked"]).has(report.status) ||
    report.agent !== platform ||
    !/^[a-f0-9]{64}$/.test(report.command_sha256 || "") ||
    !Number.isFinite(report.duration_ms) ||
    report.duration_ms < 0 ||
    report.process_group_reclaimed !== true
  ) {
    throw new Error("Launcher report is invalid.");
  }
  return report;
}

async function loadOrCreateSalt(path) {
  try {
    const value = (await readFile(path, "utf8")).trim();
    if (!/^[a-f0-9]{64}$/.test(value)) throw new Error("Local usage salt is invalid.");
    return value;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  const value = randomBytes(32).toString("hex");
  await atomicWrite(path, `${value}\n`);
  return value;
}

async function readJsonLines(path) {
  try {
    const content = await readFile(path, "utf8");
    return content
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch (error) {
    if (error.code === "ENOENT") return [];
    if (error instanceof SyntaxError) throw new Error("Usage event log is invalid.");
    throw error;
  }
}

export async function loadUsageEvents(eventsRoot) {
  const files = (await listFiles(eventsRoot)).filter((path) => basename(path).endsWith(".jsonl"));
  const events = [];
  for (const path of files.sort()) events.push(...(await readJsonLines(path)));
  return events;
}

function cleanSuccessfulCount(events) {
  return events.filter((event) => event.outcome === "passed" && !isAnomalousEvent(event)).length;
}

async function withLock(lockPath, callback) {
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

export async function recordUsage({ home, config, options, packageVersion, skillRoot }) {
  if (!config.local_collection_enabled) {
    return {
      status: "disabled",
      recorded: false,
      feedback_required: false,
      outbound_queued: false,
      event: null,
    };
  }
  if (!config.device_alias) throw new Error("Local collection has no device alias.");
  if (!options.completionReport) throw new Error("--completion-report is required");
  if (!SESSION_PATTERN.test(options.session || "")) throw new Error("Session ID is invalid.");
  if (!PLATFORM_VALUES.has(options.platform)) throw new Error("Platform is invalid.");
  if (!CAPTURE_MODES.has(options.captureMode)) throw new Error("Capture mode is invalid.");
  if (!options.projectAlias || options.projectAlias.length > 80) throw new Error("Project alias is invalid.");

  const report = validateReport(JSON.parse(await readFile(options.completionReport, "utf8")));
  let launcher = null;
  if (options.captureMode === "launcher") {
    if (!options.launcherReport) throw new Error("--launcher-report is required for launcher mode.");
    if (options.durationMs !== null || options.peakRssMb !== null) {
      throw new Error("Launcher measurements cannot be supplied manually.");
    }
    launcher = validateLauncherReport(
      JSON.parse(await readFile(options.launcherReport, "utf8")),
      options.platform,
    );
  } else if (options.launcherReport) {
    throw new Error("--launcher-report requires launcher capture mode.");
  }
  const recordedAt = options.now || new Date().toISOString();
  const timestamp = new Date(recordedAt);
  if (Number.isNaN(timestamp.getTime())) throw new Error("Timestamp is invalid.");
  const stateRoot = configuredStateRoot(config, home, options.stateRoot);
  const paths = usageStatePaths(stateRoot, config.device_alias);
  const month = `${timestamp.getUTCFullYear()}-${String(timestamp.getUTCMonth() + 1).padStart(2, "0")}`;
  const eventLog = join(paths.events, `${month}.jsonl`);
  const eventId = `evt-${canonicalSha256({ session_id: options.session }).slice(0, 16)}`;

  for (const target of [paths.salt, paths.events, paths.outbound, paths.locks]) {
    await assertSafeUsagePath(stateRoot, target);
  }

  return withLock(join(paths.locks, "events.lock"), async () => {
    const priorEvents = await loadUsageEvents(paths.events);
    const duplicate = priorEvents.find((event) => event.session_id === options.session);
    if (duplicate) {
      const outboundPath = join(paths.outbound, `${duplicate.event_id}.json`);
      if (!(await pathInfo(outboundPath))) {
        const sanitized = sanitizeUsageEvent(duplicate);
        await atomicWriteJson(outboundPath, outboundEnvelope("usage-event", sanitized));
      }
      return {
        status: "duplicate",
        recorded: false,
        feedback_required: shouldRequestFeedback(
          duplicate,
          cleanSuccessfulCount(priorEvents),
          config.feedback.successful_sample_every,
        ),
        outbound_queued: true,
        event: duplicate,
      };
    }

    const salt = await loadOrCreateSalt(paths.salt);
    const peakRss = launcher
      ? structuredClone(launcher.peak_rss_mb)
      : measurement(options.peakRssMb, options.captureMode);
    const event = {
      schema_version: 1,
      event_id: eventId,
      session_id: options.session,
      recorded_at: timestamp.toISOString(),
      device_alias: config.device_alias,
      skill_version: packageVersion,
      skill_sha256: await treeDigest(skillRoot),
      platform: options.platform,
      platform_version: options.platformVersion || null,
      capture_mode: options.captureMode,
      anonymous_project_id: canonicalSha256({ salt, project_alias: options.projectAlias }),
      project_alias: options.projectAlias,
      lifecycle_modes: [...new Set(options.lifecycleModes || [])].sort(),
      tool_strategy: options.toolStrategy || "undecided",
      outcome: report.outcome,
      interview_turns: integerOption(options.interviewTurns, "Interview turns"),
      boundary_revisions: integerOption(options.boundaryRevisions, "Boundary revisions"),
      tool_overridden: Boolean(options.toolOverridden),
      gates: {
        passed: report.results.length,
        failed: report.outcome === "failed" ? 1 : 0,
        unverified: report.unverified.length,
      },
      duration_ms: launcher
        ? { availability: "available", source: "launcher", value: launcher.duration_ms }
        : measurement(options.durationMs, options.captureMode),
      peak_rss_mb: peakRss,
      exit_code: launcher
        ? structuredClone(launcher.exit_code)
        : { availability: "unavailable", source: "best-effort" },
      termination_reason: launcher ? launcher.termination_reason : "not-reported",
      feedback_status: "unknown",
      safety_violation: Boolean(options.safetyViolation),
      resource_anomaly:
        Boolean(options.resourceAnomaly) ||
        (peakRss.availability === "available" && peakRss.value > config.analysis.warning_rss_mb),
      platform_drift: Boolean(options.platformDrift),
      incident_ids: [],
    };
    const outboundPath = join(paths.outbound, `${event.event_id}.json`);
    const sanitized = sanitizeUsageEvent(event);
    await atomicWriteJson(outboundPath, outboundEnvelope("usage-event", sanitized));
    await mkdir(paths.events, { recursive: true, mode: 0o700 });
    await appendFile(eventLog, `${JSON.stringify(event)}\n`, { encoding: "utf8", mode: 0o600 });
    const allEvents = [...priorEvents, event];
    return {
      status: "ok",
      recorded: true,
      feedback_required: shouldRequestFeedback(
        event,
        cleanSuccessfulCount(allEvents),
        config.feedback.successful_sample_every,
      ),
      outbound_queued: true,
      event,
    };
  });
}
