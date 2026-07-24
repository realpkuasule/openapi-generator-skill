import { execFile } from "node:child_process";
import { constants } from "node:fs";
import { access, realpath, stat } from "node:fs/promises";
import { isAbsolute, resolve } from "node:path";
import { promisify } from "node:util";

import { canonicalSha256 } from "./canonical-json.mjs";
import { atomicWriteJson, readJsonIfExists } from "./atomic-files.mjs";
import { usageConfigPath } from "./paths.mjs";

const DEVICE_PATTERN = /^[a-z0-9][a-z0-9-]{0,31}$/;
const BRANCH_PATTERN = /^(?!-)(?!.*\.\.)(?!.*[~^:?*\[\]\\])[A-Za-z0-9._/-]{1,200}$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const DATE_TIME_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const VERSION_PATTERN = /^[0-9]+\.[0-9]+\.[0-9]+$/;
const execFileAsync = promisify(execFile);
const ANALYSIS_FIELDS = new Set([
  "enabled",
  "credential_mode",
  "python_runtime",
  "notification",
  "authorization",
  "primary",
  "secondary",
  "max_events",
  "max_attempts_per_input",
  "timeout_seconds",
  "warning_rss_mb",
  "hard_rss_mb",
]);
const PYTHON_RUNTIME_FIELDS = new Set([
  "executable",
  "realpath",
  "python_version",
  "jsonschema_version",
]);

function exactFields(value, fields) {
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === fields.size &&
    Object.keys(value).every((key) => fields.has(key))
  );
}

function validDateTime(value) {
  return (
    typeof value === "string" &&
    DATE_TIME_PATTERN.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

function validAuthorization(value) {
  return (
    exactFields(value, new Set(["binding_sha256", "approved_at"])) &&
    SHA256_PATTERN.test(value.binding_sha256) &&
    validDateTime(value.approved_at)
  );
}

function validPythonRuntime(value) {
  return (
    exactFields(value, PYTHON_RUNTIME_FIELDS) &&
    typeof value.executable === "string" &&
    value.executable.length <= 4096 &&
    !/[\r\n\0]/.test(value.executable) &&
    isAbsolute(value.executable) &&
    typeof value.realpath === "string" &&
    value.realpath.length <= 4096 &&
    !/[\r\n\0]/.test(value.realpath) &&
    isAbsolute(value.realpath) &&
    VERSION_PATTERN.test(value.python_version) &&
    typeof value.jsonschema_version === "string" &&
    /^[A-Za-z0-9][A-Za-z0-9.+-]{0,99}$/.test(value.jsonschema_version)
  );
}

export async function qualifyPythonRuntime(executable) {
  if (
    typeof executable !== "string" ||
    !isAbsolute(executable) ||
    executable.length > 4096 ||
    /[\r\n\0]/.test(executable)
  ) {
    throw new Error("Maintenance Python runtime must be an absolute executable path.");
  }
  const normalized = resolve(executable);
  try {
    const [info, target] = await Promise.all([
      stat(normalized),
      realpath(normalized),
      access(normalized, constants.X_OK),
    ]);
    if (!info.isFile()) throw new Error("not a file");
    const probe = await execFileAsync(
      normalized,
      [
        "-c",
        "import importlib.metadata,json,sys; " +
          "assert sys.version_info >= (3,11); " +
          "print(json.dumps({'python_version':'.'.join(map(str,sys.version_info[:3])),'jsonschema_version':importlib.metadata.version('jsonschema')}))",
      ],
      {
        env: {
          PATH: "/usr/bin:/bin",
          LANG: "C.UTF-8",
          LC_ALL: "C.UTF-8",
          PYTHONDONTWRITEBYTECODE: "1",
          PYTHONNOUSERSITE: "1",
        },
        timeout: 10_000,
        maxBuffer: 4096,
      },
    );
    const versions = JSON.parse(probe.stdout);
    const runtime = {
      executable: normalized,
      realpath: target,
      python_version: versions.python_version,
      jsonschema_version: versions.jsonschema_version,
    };
    if (!validPythonRuntime(runtime)) throw new Error("invalid runtime metadata");
    return runtime;
  } catch (_error) {
    throw new Error("Maintenance Python runtime must be Python 3.11+ with jsonschema available.");
  }
}

function defaultAnalysis() {
  return {
    enabled: false,
    credential_mode: null,
    python_runtime: null,
    notification: "none",
    authorization: null,
    primary: "codex",
    secondary: "claude",
    max_events: 50,
    max_attempts_per_input: 2,
    timeout_seconds: 600,
    warning_rss_mb: 512,
    hard_rss_mb: 1024,
  };
}

function disabledAnalysis(value = {}) {
  return {
    ...defaultAnalysis(),
    ...value,
    enabled: false,
    credential_mode: null,
    python_runtime: null,
    notification: "none",
    authorization: null,
  };
}

export function defaultUsageConfig(stateRoot = "default") {
  return {
    config_version: 2,
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
    analysis: defaultAnalysis(),
    schedule: { due_check: "daily", period: "iso-week" },
  };
}

function validateStoredConfig(config) {
  if (!config || !new Set([1, 2]).has(config.config_version)) {
    throw new Error("Stored usage configuration is invalid.");
  }
  if (config.device_alias !== null && !DEVICE_PATTERN.test(config.device_alias)) {
    throw new Error("Stored usage configuration is invalid.");
  }
  if (config.branch !== null && !BRANCH_PATTERN.test(config.branch)) {
    throw new Error("Stored usage configuration is invalid.");
  }
  if (config.config_version === 1) {
    return {
      ...structuredClone(config),
      config_version: 2,
      analysis: disabledAnalysis(config.analysis),
    };
  }
  const analysis = config.analysis;
  if (
    !exactFields(analysis, ANALYSIS_FIELDS) ||
    typeof analysis.enabled !== "boolean" ||
    analysis.primary !== "codex" ||
    analysis.secondary !== "claude" ||
    analysis.max_attempts_per_input !== 2 ||
    !Number.isInteger(analysis.max_events) ||
    analysis.max_events < 1 ||
    analysis.max_events > 50 ||
    !Number.isInteger(analysis.timeout_seconds) ||
    analysis.timeout_seconds < 1 ||
    analysis.timeout_seconds > 600 ||
    !Number.isInteger(analysis.warning_rss_mb) ||
    !Number.isInteger(analysis.hard_rss_mb) ||
    analysis.warning_rss_mb < 1 ||
    analysis.hard_rss_mb <= analysis.warning_rss_mb ||
    !new Set(["none", "macos"]).has(analysis.notification) ||
    !new Set([null, "active-cli-session"]).has(analysis.credential_mode)
  ) {
    throw new Error("Stored usage configuration is invalid.");
  }
  if (
    analysis.enabled
      ? analysis.credential_mode !== "active-cli-session" ||
        !validPythonRuntime(analysis.python_runtime) ||
        !validAuthorization(analysis.authorization)
      : analysis.credential_mode !== null ||
        analysis.python_runtime !== null ||
        analysis.notification !== "none" ||
        analysis.authorization !== null
  ) {
    throw new Error("Stored usage configuration is invalid.");
  }
  return structuredClone(config);
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

function automationBinding(config, packageVersion, skillSha256) {
  return canonicalSha256({
    authorization_version: 1,
    config_version: config.config_version,
    device_alias: config.device_alias,
    coordinator: config.coordinator,
    state_root: config.state_root,
    sync_binding_sha256: config.sync_authorization?.binding_sha256 ?? null,
    package_version: packageVersion,
    skill_sha256: skillSha256,
    analysis: {
      credential_mode: config.analysis.credential_mode,
      python_runtime: config.analysis.python_runtime,
      notification: config.analysis.notification,
      primary: config.analysis.primary,
      secondary: config.analysis.secondary,
      max_events: config.analysis.max_events,
      max_attempts_per_input: config.analysis.max_attempts_per_input,
      timeout_seconds: config.analysis.timeout_seconds,
      warning_rss_mb: config.analysis.warning_rss_mb,
      hard_rss_mb: config.analysis.hard_rss_mb,
    },
  });
}

function invalidateAutomation(config) {
  config.analysis = disabledAnalysis(config.analysis);
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
      current.device_alias !== options.device ||
      current.state_root !== nextStateRoot ||
      current.coordinator !== Boolean(options.coordinator);
    proposed.local_collection_enabled = true;
    proposed.device_alias = options.device;
    proposed.coordinator = Boolean(options.coordinator);
    proposed.state_root = nextStateRoot;
    if (identityChanged) {
      proposed.sync_enabled = false;
      proposed.sync_authorization = null;
      invalidateAutomation(proposed);
    }
  } else if (action === "disable") {
    proposed.local_collection_enabled = false;
    proposed.sync_enabled = false;
    proposed.sync_authorization = null;
    invalidateAutomation(proposed);
  } else if (action === "sync-configure") {
    if (!current.local_collection_enabled || !current.device_alias) {
      throw new Error("Local collection must be enabled before synchronization.");
    }
    validateRemote(options.remote);
    validateBranch(options.branch);
    const previousBinding = current.sync_authorization?.binding_sha256 ?? null;
    proposed.remote = options.remote;
    proposed.branch = options.branch;
    proposed.sync_enabled = true;
    proposed.sync_authorization = {
      binding_sha256: syncBinding(proposed),
      approved_at: options.now || new Date().toISOString(),
    };
    if (previousBinding !== proposed.sync_authorization.binding_sha256) {
      invalidateAutomation(proposed);
    }
  } else {
    throw new Error("Unsupported usage configuration action.");
  }

  if (options.apply) await atomicWriteJson(usageConfigPath(home), proposed);
  return { status: "ok", action, applied: Boolean(options.apply), config: proposed };
}

export function expectedSyncBinding(config) {
  return syncBinding(config);
}

export function expectedAutomationBinding(config, packageVersion, skillSha256) {
  return automationBinding(config, packageVersion, skillSha256);
}

export async function configureMaintenanceAutomation({
  home,
  action,
  options,
  packageVersion,
  skillSha256,
}) {
  const current = await loadUsageConfig(home);
  if (action === "status") {
    const expected = current.analysis.enabled
      ? automationBinding(current, packageVersion, skillSha256)
      : null;
    let runtimeStale = false;
    if (current.analysis.enabled) {
      try {
        const runtime = await qualifyPythonRuntime(current.analysis.python_runtime.executable);
        runtimeStale = canonicalSha256(runtime) !== canonicalSha256(current.analysis.python_runtime);
      } catch (_error) {
        runtimeStale = true;
      }
    }
    const stale =
      current.analysis.enabled &&
      (current.analysis.authorization?.binding_sha256 !== expected || runtimeStale);
    return {
      report: {
        status: stale ? "stale" : "ok",
        action,
        applied: false,
        approval_sha256: expected,
        config: current,
      },
      exitCode: stale ? 1 : 0,
    };
  }

  const proposed = structuredClone(current);
  if (action === "disable") {
    invalidateAutomation(proposed);
    if (options.apply) await atomicWriteJson(usageConfigPath(home), proposed);
    return {
      report: {
        status: "ok",
        action,
        applied: Boolean(options.apply),
        approval_sha256: null,
        config: proposed,
      },
      exitCode: 0,
    };
  }
  if (action !== "configure") throw new Error("Unsupported maintenance automation action.");
  if (
    !current.local_collection_enabled ||
    !current.coordinator ||
    !current.device_alias ||
    !current.sync_enabled ||
    !current.sync_authorization ||
    current.sync_authorization.binding_sha256 !== syncBinding(current)
  ) {
    throw new Error("An enabled coordinator with current sync authorization is required.");
  }
  if (options.credentialMode !== "active-cli-session") {
    throw new Error("Unattended analysis requires active-cli-session credential mode.");
  }
  if (!new Set(["none", "macos"]).has(options.notification)) {
    throw new Error("Maintenance notification policy is invalid.");
  }
  const pythonRuntime = await qualifyPythonRuntime(options.pythonExecutable);
  proposed.analysis = {
    ...proposed.analysis,
    enabled: true,
    credential_mode: options.credentialMode,
    python_runtime: pythonRuntime,
    notification: options.notification,
    authorization: null,
  };
  const approval = automationBinding(proposed, packageVersion, skillSha256);
  const approvedAt = options.now || new Date().toISOString();
  if (!validDateTime(approvedAt)) {
    throw new Error("Maintenance authorization timestamp is invalid.");
  }
  proposed.analysis.authorization = {
    binding_sha256: approval,
    approved_at: approvedAt,
  };
  if (options.apply && options.approve !== approval) {
    return {
      report: {
        status: "stale",
        action,
        applied: false,
        approval_sha256: approval,
        config: current,
      },
      exitCode: 1,
    };
  }
  if (options.apply) await atomicWriteJson(usageConfigPath(home), proposed);
  return {
    report: {
      status: "ok",
      action,
      applied: Boolean(options.apply),
      approval_sha256: approval,
      config: proposed,
    },
    exitCode: 0,
  };
}
