import { lstat } from "node:fs/promises";
import { isAbsolute, join, relative, resolve } from "node:path";

export function defaultConfigRoot(home, platform = process.platform) {
  if (platform === "win32") {
    return join(home, "AppData", "Local", "openapi-engineering-skill");
  }
  return join(home, ".config", "openapi-engineering-skill");
}

export function defaultStateRoot(home, platform = process.platform) {
  if (platform === "win32") {
    return join(home, "AppData", "Local", "openapi-engineering-skill", "state");
  }
  return join(home, ".local", "state", "openapi-engineering-skill");
}

export function usageConfigPath(home) {
  return join(defaultConfigRoot(home), "usage.json");
}

export function configuredStateRoot(config, home, override = null) {
  if (override) return resolve(override);
  return config.state_root === "default" ? defaultStateRoot(home) : resolve(config.state_root);
}

export function usageStatePaths(stateRoot, deviceAlias = null) {
  const device = deviceAlias || "unconfigured";
  return {
    root: stateRoot,
    salt: join(stateRoot, "salt"),
    events: join(stateRoot, "local", "events", device),
    feedback: join(stateRoot, "feedback", device),
    outbound: join(stateRoot, "outbound", device),
    checkpoints: join(stateRoot, "checkpoints"),
    summaries: join(stateRoot, "summaries"),
    findings: join(stateRoot, "findings"),
    incidents: join(stateRoot, "incidents"),
    aggregateEvents: join(stateRoot, "aggregate", "events.json"),
    aggregateFeedback: join(stateRoot, "aggregate", "feedback.json"),
    locks: join(stateRoot, "locks"),
  };
}

async function safeLstat(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

export async function assertSafeUsagePath(stateRoot, target) {
  const root = resolve(stateRoot);
  const resolvedTarget = resolve(target);
  const relativeTarget = relative(root, resolvedTarget);
  if (isAbsolute(relativeTarget) || relativeTarget === ".." || relativeTarget.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`)) {
    throw new Error("Usage state path escapes the configured root.");
  }
  const rootInfo = await safeLstat(root);
  if (rootInfo && (rootInfo.isSymbolicLink() || !rootInfo.isDirectory())) {
    throw new Error("Usage state root is unsafe.");
  }
  if (!relativeTarget) return;
  let current = root;
  for (const component of relativeTarget.split(/[\\/]/).filter(Boolean)) {
    current = join(current, component);
    const info = await safeLstat(current);
    if (info?.isSymbolicLink()) throw new Error("Usage state path contains a symbolic link.");
  }
}
