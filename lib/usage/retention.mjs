import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { lstat, mkdir, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { join, relative } from "node:path";

import { atomicWrite, atomicWriteJson } from "./atomic-files.mjs";
import { canonicalSha256 } from "./canonical-json.mjs";
import { assertSafeUsagePath, configuredStateRoot, usageStatePaths } from "./paths.mjs";
import { expectedSyncBinding } from "./config.mjs";
import { validateSanitizedEvent, validateSanitizedFeedback } from "./ownership.mjs";


const DAY_MS = 24 * 60 * 60 * 1000;
const execFileAsync = promisify(execFile);


async function git(arguments_, options = {}) {
  return execFileAsync("git", ["-c", "core.hooksPath=/dev/null", ...arguments_], {
    cwd: options.cwd,
    env: {
      PATH: process.env.PATH,
      LANG: process.env.LANG || "C",
      LC_ALL: "C",
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_CONFIG_GLOBAL: "/dev/null",
      GIT_TERMINAL_PROMPT: "0",
      ...options.env,
    },
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


function timestamp(value) {
  const parsed = new Date(value?.recorded_at).getTime();
  if (!Number.isFinite(parsed)) throw new Error("Retention input has an invalid timestamp.");
  return parsed;
}


async function jsonlFiles(root, stateRoot) {
  await assertSafeUsagePath(stateRoot, root);
  const info = await pathInfo(root);
  if (!info) return [];
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("Retention path is unsafe.");
  const files = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name);
    if (entry.isSymbolicLink()) throw new Error("Retention path contains a symbolic link.");
    if (entry.isDirectory()) files.push(...(await jsonlFiles(path, stateRoot)));
    else if (entry.isFile() && entry.name.endsWith(".jsonl")) files.push(path);
    else throw new Error("Retention path contains an unsupported entry.");
  }
  return files.sort();
}


async function readJsonLines(path) {
  return (await readFile(path, "utf8"))
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}


function itemFor(stateRoot, path, kind, content, rows, cutoff) {
  const retained = rows.filter((row) => timestamp(row) >= cutoff);
  const deleteCount = rows.length - retained.length;
  if (deleteCount === 0) return null;
  return {
    report: {
      path: relative(stateRoot, path).split("\\").join("/"),
      kind,
      sha256: createHash("sha256").update(content).digest("hex"),
      delete_count: deleteCount,
      retain_count: retained.length,
    },
    path,
    content,
    retained,
  };
}


async function localOperations(stateRoot, paths, localCutoff) {
  const operations = [];
  for (const [root, kind] of [
    [paths.events, "local-event"],
    [paths.feedback, "local-feedback"],
  ]) {
    for (const path of await jsonlFiles(root, stateRoot)) {
      await assertSafeUsagePath(stateRoot, path);
      const content = await readFile(path, "utf8");
      const operation = itemFor(
        stateRoot,
        path,
        kind,
        content,
        await readJsonLines(path),
        localCutoff,
      );
      if (operation) operations.push(operation);
    }
  }
  return operations;
}


async function aggregateOperations(stateRoot, paths, remoteCutoff) {
  const operations = [];
  for (const [path, kind] of [
    [paths.aggregateEvents, "aggregate-event"],
    [paths.aggregateFeedback, "aggregate-feedback"],
  ]) {
    await assertSafeUsagePath(stateRoot, path);
    const info = await pathInfo(path);
    if (!info) continue;
    if (!info.isFile() || info.isSymbolicLink()) throw new Error("Aggregate retention path is unsafe.");
    const content = await readFile(path, "utf8");
    const rows = JSON.parse(content);
    if (!Array.isArray(rows)) throw new Error("Aggregate retention input is invalid.");
    const operation = itemFor(stateRoot, path, kind, content, rows, remoteCutoff);
    if (operation) operations.push(operation);
  }
  return operations;
}


function contentDigest(content) {
  return createHash("sha256").update(content).digest("hex");
}


async function remoteRetentionOperations(worktree, cutoff) {
  const operations = [];
  for (const [partition, kind, validate] of [
    ["events", "remote-event", validateSanitizedEvent],
    ["feedback", "remote-feedback", validateSanitizedFeedback],
  ]) {
    const partitionRoot = join(worktree, partition);
    const partitionInfo = await pathInfo(partitionRoot);
    if (!partitionInfo) continue;
    await assertSafeUsagePath(worktree, partitionRoot);
    if (!partitionInfo.isDirectory() || partitionInfo.isSymbolicLink()) {
      throw new Error("Remote retention partition is unsafe.");
    }
    for (const device of await readdir(partitionRoot, { withFileTypes: true })) {
      if (
        device.isSymbolicLink() ||
        !device.isDirectory() ||
        !/^[a-z0-9][a-z0-9-]{0,31}$/.test(device.name)
      ) {
        throw new Error("Remote retention device partition is invalid.");
      }
      const deviceRoot = join(partitionRoot, device.name);
      await assertSafeUsagePath(worktree, deviceRoot);
      for (const entry of await readdir(deviceRoot, { withFileTypes: true })) {
        if (
          entry.isSymbolicLink() ||
          !entry.isFile() ||
          !/^[0-9]{4}-[0-9]{2}\.jsonl$/.test(entry.name)
        ) {
          throw new Error("Remote retention month partition is invalid.");
        }
        const path = join(deviceRoot, entry.name);
        await assertSafeUsagePath(worktree, path);
        const content = await readFile(path, "utf8");
        const rows = content
          .split(/\r?\n/)
          .filter(Boolean)
          .map((line) => JSON.parse(line));
        for (const row of rows) {
          validate(row);
          if (
            row.device_alias !== device.name ||
            row.recorded_at.slice(0, 7) !== entry.name.slice(0, 7)
          ) {
            throw new Error("Remote retention ownership is invalid.");
          }
        }
        const operation = itemFor(worktree, path, kind, content, rows, cutoff);
        if (operation) {
          operation.report.path = `remote/${relative(worktree, path).split("\\").join("/")}`;
          operations.push(operation);
        }
      }
    }
  }
  return operations.sort((left, right) => left.report.path.localeCompare(right.report.path));
}


async function prepareRemote(config, stateRoot, cutoff) {
  if (
    !config.coordinator ||
    !config.sync_enabled ||
    !config.remote ||
    !config.branch ||
    !config.sync_authorization ||
    config.sync_authorization.binding_sha256 !== expectedSyncBinding(config)
  ) {
    throw new Error("Remote cleanup requires current coordinator synchronization authorization.");
  }
  await mkdir(stateRoot, { recursive: true, mode: 0o700 });
  const temporary = await mkdtemp(join(stateRoot, ".retention-"));
  const worktree = join(temporary, "worktree");
  try {
    const remote = await git([
      "ls-remote",
      "--heads",
      config.remote,
      `refs/heads/${config.branch}`,
    ]);
    if (!remote.stdout.trim()) {
      return { temporary, worktree, head: null, operations: [] };
    }
    await git([
      "clone",
      "--no-tags",
      "--single-branch",
      "--branch",
      config.branch,
      config.remote,
      worktree,
    ]);
    const head = (await git(["rev-parse", "HEAD"], { cwd: worktree })).stdout.trim();
    const operations = await remoteRetentionOperations(worktree, cutoff);
    return { temporary, worktree, head, operations };
  } catch (error) {
    await rm(temporary, { recursive: true, force: true });
    throw error;
  }
}


function reportFor({ scope, now, localCutoff, remoteCutoff, sourceRevision, operations }) {
  const planBase = {
    plan_version: 1,
    scope,
    generated_at: now.toISOString(),
    local_cutoff: new Date(localCutoff).toISOString(),
    remote_cutoff: new Date(remoteCutoff).toISOString(),
    items: operations.map((operation) => operation.report),
    source_revision: sourceRevision,
  };
  return {
    ...planBase,
    status: "ok",
    plan_sha256: canonicalSha256(planBase),
    applied: false,
  };
}


export async function cleanupUsage({ home, config, options }) {
  if (!config.local_collection_enabled || !config.device_alias) {
    throw new Error("Local collection is disabled.");
  }
  const now = new Date(options.now || new Date().toISOString());
  if (Number.isNaN(now.getTime())) throw new Error("Timestamp is invalid.");
  const stateRoot = configuredStateRoot(config, home, options.stateRoot);
  const paths = usageStatePaths(stateRoot, config.device_alias);
  const localCutoff = now.getTime() - config.retention.local_days * DAY_MS;
  const remoteCutoff = now.getTime() - config.retention.remote_days * DAY_MS;
  if (!new Set(["local", "remote"]).has(options.scope)) {
    throw new Error("Cleanup scope is invalid.");
  }
  if (options.scope === "remote") {
    const prepared = await prepareRemote(config, stateRoot, remoteCutoff);
    try {
      const report = reportFor({
        scope: "remote",
        now,
        localCutoff,
        remoteCutoff,
        sourceRevision: prepared.head,
        operations: prepared.operations,
      });
      if (!options.apply) return { report, exitCode: 0 };
      if (!options.approve) throw new Error("Cleanup apply requires --approve.");
      if (options.approve !== report.plan_sha256) {
        return { report: { ...report, status: "conflict" }, exitCode: 1 };
      }
      for (const operation of prepared.operations) {
        const current = await readFile(operation.path, "utf8");
        if (contentDigest(current) !== operation.report.sha256) {
          return { report: { ...report, status: "conflict" }, exitCode: 1 };
        }
        if (operation.retained.length === 0) await rm(operation.path);
        else {
          await atomicWrite(
            operation.path,
            `${operation.retained.map((row) => JSON.stringify(row)).join("\n")}\n`,
          );
        }
      }
      if (prepared.operations.length > 0) {
        await git(["config", "user.name", "OpenAPI Engineering Skill"], { cwd: prepared.worktree });
        await git(["config", "user.email", "openapi-engineering@localhost"], { cwd: prepared.worktree });
        await git(["add", "--all", "--", "."], { cwd: prepared.worktree });
        await git(["commit", "-m", "usage: apply approved remote retention"], {
          cwd: prepared.worktree,
          env: { GIT_AUTHOR_DATE: now.toISOString(), GIT_COMMITTER_DATE: now.toISOString() },
        });
        try {
          await git(["push", "origin", `HEAD:refs/heads/${config.branch}`], {
            cwd: prepared.worktree,
          });
        } catch (_error) {
          return { report: { ...report, status: "conflict" }, exitCode: 1 };
        }
      }
      return { report: { ...report, applied: true }, exitCode: 0 };
    } finally {
      await rm(prepared.temporary, { recursive: true, force: true });
    }
  }
  const operations = [
    ...(await localOperations(stateRoot, paths, localCutoff)),
    ...(await aggregateOperations(stateRoot, paths, remoteCutoff)),
  ].sort((left, right) => left.report.path.localeCompare(right.report.path));
  const report = reportFor({
    scope: "local",
    now,
    localCutoff,
    remoteCutoff,
    sourceRevision: null,
    operations,
  });
  if (!options.apply) return { report, exitCode: 0 };
  if (!options.approve) throw new Error("Cleanup apply requires --approve.");
  if (options.approve !== report.plan_sha256) {
    return { report: { ...report, status: "conflict" }, exitCode: 1 };
  }

  for (const operation of operations) {
    await assertSafeUsagePath(stateRoot, operation.path);
    const current = await readFile(operation.path, "utf8");
    if (contentDigest(current) !== operation.report.sha256) {
      return { report: { ...report, status: "conflict" }, exitCode: 1 };
    }
  }
  const completed = [];
  try {
    for (const operation of operations) {
      if (operation.retained.length === 0) {
        await rm(operation.path);
      } else if (operation.report.kind.startsWith("aggregate-")) {
        await atomicWriteJson(operation.path, operation.retained);
      } else {
        await atomicWrite(
          operation.path,
          `${operation.retained.map((row) => JSON.stringify(row)).join("\n")}\n`,
        );
      }
      completed.push(operation);
    }
  } catch (error) {
    for (const operation of completed.reverse()) {
      await atomicWrite(operation.path, operation.content);
    }
    throw error;
  }
  return { report: { ...report, applied: true }, exitCode: 0 };
}
