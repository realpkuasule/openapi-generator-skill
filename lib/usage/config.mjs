import { canonicalSha256 } from "./canonical-json.mjs";
import { atomicWriteJson, readJsonIfExists } from "./atomic-files.mjs";
import { usageConfigPath } from "./paths.mjs";

const DEVICE_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;
const BRANCH_PATTERN = /^(?!-)(?!.*\.\.)(?!.*[~^:?*\[\]\\])[A-Za-z0-9._/-]{1,200}$/;

export function defaultUsageConfig(stateRoot = "default") {
  return {
    config_version: 1,
    local_collection_enabled: false,
    sync_enabled: false,
    device_alias: null,
    coordinator: false,
    state_root: stateRoot,
    remote: null,
    branch: null,
    sync_authorization: null,
    retention: { local_days: 90, remote_days: 365 },
    feedback: { successful_sample_every: 5 },
    analysis: {
      primary: "codex",
      secondary: "claude",
      max_events: 50,
      timeout_seconds: 600,
      warning_rss_mb: 512,
      hard_rss_mb: 1024,
    },
    schedule: { due_check: "daily", period: "iso-week" },
  };
}

function validateStoredConfig(config) {
  if (!config || config.config_version !== 1) throw new Error("Stored usage configuration is invalid.");
  if (config.device_alias !== null && !DEVICE_PATTERN.test(config.device_alias)) {
    throw new Error("Stored usage configuration is invalid.");
  }
  if (config.branch !== null && !BRANCH_PATTERN.test(config.branch)) {
    throw new Error("Stored usage configuration is invalid.");
  }
  return config;
}

export async function loadUsageConfig(home) {
  const stored = await readJsonIfExists(usageConfigPath(home));
  return stored === null ? defaultUsageConfig() : validateStoredConfig(stored);
}

function validateDevice(alias) {
  if (!alias || !DEVICE_PATTERN.test(alias)) throw new Error("Device alias is invalid.");
}

function validateRemote(remote) {
  if (!remote || remote.length > 2048 || /[\r\n\0]/.test(remote)) {
    throw new Error("Git remote is invalid.");
  }
  if (/^[a-z][a-z0-9+.-]*:\/\/[^/@:]+:[^/@]+@/i.test(remote)) {
    throw new Error("Git remote must not contain credentials.");
  }
}

function validateBranch(branch) {
  if (!branch || !BRANCH_PATTERN.test(branch)) throw new Error("Git branch is invalid.");
}

function syncBinding(config) {
  return canonicalSha256({
    device_alias: config.device_alias,
    remote: config.remote,
    branch: config.branch,
    state_root: config.state_root,
    data_classes: ["sanitized-events", "sanitized-feedback", "summaries", "findings", "analyses", "proposals"],
  });
}

export async function configureUsage(home, action, options) {
  const current = await loadUsageConfig(home);
  if (action === "status") {
    return { status: "ok", action, applied: false, config: current };
  }

  const proposed = structuredClone(current);
  if (action === "enable") {
    validateDevice(options.device);
    const nextStateRoot = options.stateRoot || current.state_root;
    const identityChanged =
      current.device_alias !== options.device || current.state_root !== nextStateRoot;
    proposed.local_collection_enabled = true;
    proposed.device_alias = options.device;
    proposed.coordinator = Boolean(options.coordinator);
    proposed.state_root = nextStateRoot;
    if (identityChanged) {
      proposed.sync_enabled = false;
      proposed.sync_authorization = null;
    }
  } else if (action === "disable") {
    proposed.local_collection_enabled = false;
    proposed.sync_enabled = false;
    proposed.sync_authorization = null;
  } else if (action === "sync-configure") {
    if (!current.local_collection_enabled || !current.device_alias) {
      throw new Error("Local collection must be enabled before synchronization.");
    }
    validateRemote(options.remote);
    validateBranch(options.branch);
    proposed.remote = options.remote;
    proposed.branch = options.branch;
    proposed.sync_enabled = true;
    proposed.sync_authorization = {
      binding_sha256: syncBinding(proposed),
      approved_at: options.now || new Date().toISOString(),
    };
  } else {
    throw new Error("Unsupported usage configuration action.");
  }

  if (options.apply) await atomicWriteJson(usageConfigPath(home), proposed);
  return { status: "ok", action, applied: Boolean(options.apply), config: proposed };
}

export function expectedSyncBinding(config) {
  return syncBinding(config);
}
