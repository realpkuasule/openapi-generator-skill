import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { lstat, mkdir, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";

import { atomicWrite, atomicWriteJson } from "./atomic-files.mjs";
import { canonicalSha256 } from "./canonical-json.mjs";
import { expectedSyncBinding } from "./config.mjs";
import {
  remotePartition,
  validateOwnedEnvelope,
  validateSanitizedEvent,
  validateSanitizedFeedback,
} from "./ownership.mjs";
import { assertSafeUsagePath, configuredStateRoot, usageStatePaths } from "./paths.mjs";

const execFileAsync = promisify(execFile);

async function git(arguments_, options = {}) {
  const environment = {
    PATH: process.env.PATH,
    LANG: process.env.LANG || "C",
    LC_ALL: "C",
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_TERMINAL_PROMPT: "0",
    ...options.env,
  };
  return execFileAsync("git", ["-c", "core.hooksPath=/dev/null", ...arguments_], {
    cwd: options.cwd,
    env: environment,
    maxBuffer: 1024 * 1024,
  });
}

async function pathInfo(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function queueFiles(root) {
  const info = await pathInfo(root);
  if (!info) return [];
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("Outbound queue is unsafe.");
  const entries = await readdir(root, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (entry.isSymbolicLink() || !entry.isFile() || !entry.name.endsWith(".json")) {
      throw new Error("Outbound queue contains an unsupported entry.");
    }
    files.push(join(root, entry.name));
  }
  return files.sort();
}

function blocked(pending, reasonCode) {
  return { status: "blocked", synchronized: 0, pending, commit: null, reason_code: reasonCode };
}

async function appendOwnedPayload(worktree, envelope) {
  const partition = remotePartition(envelope);
  const target = join(worktree, ...partition.path.split("/"));
  await assertSafeUsagePath(worktree, target);
  if (partition.format === "json") {
    try {
      const existing = JSON.parse(await readFile(target, "utf8"));
      if (canonicalSha256(existing) !== canonicalSha256(partition.content)) {
        throw new Error("Remote partition contains a conflicting immutable object.");
      }
      return false;
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    await mkdir(dirname(target), { recursive: true, mode: 0o700 });
    await atomicWrite(target, `${JSON.stringify(partition.content, null, 2)}\n`, 0o600);
    return true;
  }
  let rows = [];
  try {
    rows = (await readFile(target, "utf8"))
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  const existing = rows.find((row) => row.event_id === partition.id || row.feedback_id === partition.id);
  if (existing) {
    if (canonicalSha256(existing) !== canonicalSha256(partition.content)) {
      throw new Error("Remote partition contains a conflicting immutable object.");
    }
    return false;
  }
  rows.push(partition.content);
  rows.sort((left, right) => {
    const leftId = left.event_id || left.feedback_id;
    const rightId = right.event_id || right.feedback_id;
    return leftId.localeCompare(rightId);
  });
  await mkdir(dirname(target), { recursive: true, mode: 0o700 });
  await atomicWrite(target, `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`, 0o600);
  return true;
}

async function directoryEntries(root, stateRoot) {
  const info = await pathInfo(root);
  if (!info) return [];
  await assertSafeUsagePath(stateRoot, root);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new Error("Remote aggregate path is unsafe.");
  }
  return readdir(root, { withFileTypes: true });
}

async function remoteRows(worktree, partitionName, validate) {
  const partitionRoot = join(worktree, partitionName);
  const rows = new Map();
  for (const device of await directoryEntries(partitionRoot, worktree)) {
    if (
      device.isSymbolicLink() ||
      !device.isDirectory() ||
      !/^[a-z0-9][a-z0-9-]{0,31}$/.test(device.name)
    ) {
      throw new Error("Remote device partition is invalid.");
    }
    const deviceRoot = join(partitionRoot, device.name);
    for (const entry of await directoryEntries(deviceRoot, worktree)) {
      if (entry.isSymbolicLink() || !entry.isFile() || !/^[0-9]{4}-[0-9]{2}\.jsonl$/.test(entry.name)) {
        throw new Error("Remote month partition is invalid.");
      }
      const path = join(deviceRoot, entry.name);
      await assertSafeUsagePath(worktree, path);
      const values = (await readFile(path, "utf8"))
        .split(/\r?\n/)
        .filter(Boolean)
        .map((line) => JSON.parse(line));
      for (const value of values) {
        validate(value);
        if (
          value.device_alias !== device.name ||
          value.recorded_at.slice(0, 7) !== entry.name.slice(0, 7)
        ) {
          throw new Error("Remote partition ownership is invalid.");
        }
        const id = value.event_id || value.feedback_id;
        if (rows.has(id) && canonicalSha256(rows.get(id)) !== canonicalSha256(value)) {
          throw new Error("Remote aggregate contains a conflicting immutable object.");
        }
        rows.set(id, value);
      }
    }
  }
  return [...rows.values()].sort((left, right) => {
    const leftId = left.event_id || left.feedback_id;
    const rightId = right.event_id || right.feedback_id;
    return leftId.localeCompare(rightId);
  });
}

async function refreshCoordinatorAggregate(worktree, stateRoot, paths) {
  const events = await remoteRows(worktree, "events", validateSanitizedEvent);
  const feedback = await remoteRows(worktree, "feedback", validateSanitizedFeedback);
  for (const target of [paths.aggregateEvents, paths.aggregateFeedback]) {
    await assertSafeUsagePath(stateRoot, target);
  }
  await atomicWriteJson(paths.aggregateEvents, events);
  await atomicWriteJson(paths.aggregateFeedback, feedback);
}

export async function synchronizeUsage({ home, config, options }) {
  if (
    !config.sync_enabled ||
    !config.remote ||
    !config.branch ||
    !config.device_alias ||
    !config.sync_authorization ||
    config.sync_authorization.binding_sha256 !== expectedSyncBinding(config)
  ) {
    return blocked(0, "sync-disabled-or-stale");
  }
  const stateRoot = configuredStateRoot(config, home, options.stateRoot);
  const paths = usageStatePaths(stateRoot, config.device_alias);
  try {
    await assertSafeUsagePath(stateRoot, paths.outbound);
  } catch (_error) {
    return blocked(0, "unsafe-state-path");
  }
  let files;
  let envelopes;
  try {
    files = await queueFiles(paths.outbound);
    envelopes = [];
    for (const path of files) {
      const envelope = validateOwnedEnvelope(JSON.parse(await readFile(path, "utf8")), config);
      if (canonicalSha256(envelope.payload) !== envelope.payload_sha256) {
        throw new Error("Outbound digest does not match.");
      }
      envelopes.push(envelope);
    }
  } catch (_error) {
    return blocked(files?.length || 0, "outbound-validation-failed");
  }
  if (files.length === 0 && !config.coordinator) {
    return { status: "ok", synchronized: 0, pending: 0, commit: null };
  }

  await mkdir(stateRoot, { recursive: true, mode: 0o700 });
  const temporary = await mkdtemp(join(stateRoot, ".sync-"));
  const worktree = join(temporary, "worktree");
  try {
    let remoteHasBranch = false;
    try {
      const result = await git(["ls-remote", "--heads", config.remote, `refs/heads/${config.branch}`]);
      remoteHasBranch = result.stdout.trim().length > 0;
    } catch (_error) {
      return blocked(files.length, "remote-unavailable");
    }
    if (remoteHasBranch) {
      await git(["clone", "--no-tags", "--single-branch", "--branch", config.branch, config.remote, worktree]);
    } else {
      await mkdir(worktree, { recursive: true, mode: 0o700 });
      await git(["init"], { cwd: worktree });
      await git(["checkout", "-b", config.branch], { cwd: worktree });
      await git(["remote", "add", "origin", config.remote], { cwd: worktree });
    }
    await git(["config", "user.name", "OpenAPI Engineering Skill"], { cwd: worktree });
    await git(["config", "user.email", "openapi-engineering@localhost"], { cwd: worktree });
    let changed = false;
    for (const envelope of envelopes) {
      const appended = await appendOwnedPayload(worktree, envelope);
      changed = appended || changed;
    }
    if (changed) {
      await git(["add", "--all", "--", "."], { cwd: worktree });
      const newest = envelopes
        .map((envelope) => envelope.payload.recorded_at)
        .sort()
        .at(-1);
      await git(["commit", "-m", `usage: ${config.device_alias} sanitized batch`], {
        cwd: worktree,
        env: { GIT_AUTHOR_DATE: newest, GIT_COMMITTER_DATE: newest },
      });
      try {
        await git(["push", "origin", `HEAD:refs/heads/${config.branch}`], { cwd: worktree });
      } catch (_error) {
        return blocked(files.length, "push-failed");
      }
    }
    const commit = changed ? (await git(["rev-parse", "HEAD"], { cwd: worktree })).stdout.trim() : null;
    if (config.coordinator) {
      await refreshCoordinatorAggregate(worktree, stateRoot, paths);
    }
    for (const path of files) await rm(path, { force: true });
    return { status: "ok", synchronized: files.length, pending: 0, commit };
  } catch (_error) {
    return blocked(files.length, "git-operation-failed");
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}
