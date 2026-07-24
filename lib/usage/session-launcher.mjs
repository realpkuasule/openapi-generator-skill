import { spawn } from "node:child_process";

import { atomicWriteJson } from "./atomic-files.mjs";
import { canonicalSha256 } from "./canonical-json.mjs";
import {
  processTreeRssMb,
  reclaimProcessGroup,
  supportsProcessTreeRss,
} from "./process-watch.mjs";


function iso(timestamp) {
  return new Date(timestamp).toISOString();
}


function boundedNumber(value, name, minimum, maximum) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} is invalid.`);
  }
  return parsed;
}


export async function runUsageSession(options) {
  if (!new Set(["codex", "claude"]).has(options.agent)) {
    throw new Error("Session agent is invalid.");
  }
  if (!options.projectAlias || options.projectAlias.length > 80) {
    throw new Error("Project alias is invalid.");
  }
  if (!Array.isArray(options.command) || options.command.length === 0) {
    throw new Error("Session command is required.");
  }
  if (options.command.some((item) => typeof item !== "string" || /[\0\r\n]/.test(item))) {
    throw new Error("Session command contains an invalid argument.");
  }
  const timeoutSeconds = boundedNumber(options.timeoutSeconds, "Session timeout", 0.05, 600);
  const warningRssMb = boundedNumber(options.warningRssMb, "RSS warning", 1, 1024 * 1024);
  const hardRssMb = boundedNumber(options.hardRssMb, "RSS hard limit", 2, 1024 * 1024);
  if (hardRssMb <= warningRssMb) throw new Error("RSS hard limit must exceed the warning.");

  const started = Date.now();
  const base = {
    report_version: 1,
    agent: options.agent,
    command_sha256: canonicalSha256(options.command),
    started_at: iso(started),
  };
  if (!supportsProcessTreeRss()) {
    const report = {
      ...base,
      status: "blocked",
      finished_at: iso(Date.now()),
      duration_ms: Date.now() - started,
      peak_rss_mb: { availability: "unavailable", source: "unsupported" },
      exit_code: { availability: "unavailable", source: "unsupported" },
      termination_reason: "unsupported",
      warning_exceeded: false,
      hard_limit_exceeded: false,
      process_group_reclaimed: true,
    };
    if (options.output) await atomicWriteJson(options.output, report);
    return report;
  }

  let child;
  try {
    child = spawn(options.command[0], options.command.slice(1), {
      cwd: options.cwd,
      env: process.env,
      detached: true,
      shell: false,
      stdio: "ignore",
    });
  } catch (_error) {
    const report = {
      ...base,
      status: "blocked",
      finished_at: iso(Date.now()),
      duration_ms: Date.now() - started,
      peak_rss_mb: { availability: "unavailable", source: "not-reported" },
      exit_code: { availability: "unavailable", source: "spawn-failed" },
      termination_reason: "spawn-failed",
      warning_exceeded: false,
      hard_limit_exceeded: false,
      process_group_reclaimed: true,
    };
    if (options.output) await atomicWriteJson(options.output, report);
    return report;
  }

  let peakRssMb = 0;
  let terminationReason = null;
  let sampleStopped = false;
  const sample = async () => {
    while (!sampleStopped) {
      try {
        const rss = await processTreeRssMb(child.pid);
        if (rss !== null) peakRssMb = Math.max(peakRssMb, rss);
        if (rss !== null && rss > hardRssMb && terminationReason === null) {
          terminationReason = "rss-limit";
          await reclaimProcessGroup(child);
        }
      } catch (_error) {
        // A process can exit between ps snapshots; the exit event remains authoritative.
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  };
  const sampler = sample();
  const timeout = setTimeout(async () => {
    if (terminationReason === null) {
      terminationReason = "timeout";
      await reclaimProcessGroup(child);
    }
  }, timeoutSeconds * 1000);
  const exit = await new Promise((resolve) => {
    child.once("error", (error) => resolve({ code: null, signal: null, error }));
    child.once("exit", (code, signal) => resolve({ code, signal, error: null }));
  });
  clearTimeout(timeout);
  sampleStopped = true;
  await sampler;
  const reclaimed = await reclaimProcessGroup(child);
  const finished = Date.now();
  if (terminationReason === null) {
    if (exit.error) terminationReason = "spawn-failed";
    else if (exit.signal) terminationReason = "signal";
    else if (exit.code === 0) terminationReason = "completed";
    else terminationReason = "nonzero-exit";
  }
  const warningExceeded = peakRssMb > warningRssMb;
  const hardLimitExceeded = terminationReason === "rss-limit";
  const status =
    terminationReason === "completed"
      ? "passed"
      : new Set(["timeout", "rss-limit", "spawn-failed", "unsupported"]).has(
            terminationReason,
          )
        ? "blocked"
        : "failed";
  const report = {
    ...base,
    status,
    finished_at: iso(finished),
    duration_ms: finished - started,
    peak_rss_mb: { availability: "available", source: "system", value: peakRssMb },
    exit_code:
      Number.isInteger(exit.code) && exit.code >= 0
        ? { availability: "available", source: "launcher", value: exit.code }
        : {
            availability: "unavailable",
            source: terminationReason === "spawn-failed" ? "spawn-failed" : "killed",
          },
    termination_reason: terminationReason,
    warning_exceeded: warningExceeded,
    hard_limit_exceeded: hardLimitExceeded,
    process_group_reclaimed: reclaimed,
  };
  if (options.output) await atomicWriteJson(options.output, report);
  return report;
}
