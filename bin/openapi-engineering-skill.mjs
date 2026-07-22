#!/usr/bin/env node

import { spawn } from "node:child_process";
import {
  cp,
  lstat,
  mkdir,
  readFile,
  readlink,
  realpath,
  rename,
  rm,
  symlink,
} from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import {
  configureMaintenanceAutomation,
  configureUsage,
  loadUsageConfig,
} from "../lib/usage/config.mjs";
import { loadUsageEvents, recordUsage } from "../lib/usage/events.mjs";
import { recordFeedback } from "../lib/usage/feedback.mjs";
import { configuredStateRoot, usageStatePaths } from "../lib/usage/paths.mjs";
import { buildUsageSummary } from "../lib/usage/summarize.mjs";
import { synchronizeUsage } from "../lib/usage/git-sync.mjs";
import { checkUsageDue } from "../lib/usage/due.mjs";
import { manageLaunchd } from "../lib/usage/launchd.mjs";
import { runUsageSession } from "../lib/usage/session-launcher.mjs";
import { cleanupUsage } from "../lib/usage/retention.mjs";
import { buildUsageTrends } from "../lib/usage/trends.mjs";
import { treeDigest } from "../lib/usage/tree-digest.mjs";
import { runMaintenanceCycle } from "../lib/usage/maintenance-cycle.mjs";

const PACKAGE_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const PACKAGE = JSON.parse(
  await readFile(join(PACKAGE_ROOT, "package.json"), "utf8"),
);
const BUNDLED_SKILL = join(PACKAGE_ROOT, "skills", "openapi-engineering");
const BUNDLED_MAINTAINER = join(
  PACKAGE_ROOT,
  "skills",
  "openapi-engineering-maintainer",
);
const LAUNCHD_TEMPLATE = join(
  PACKAGE_ROOT,
  "packaging",
  "launchd",
  "com.realpkuasule.openapi-engineering-maintainer.plist",
);
const TARGETS = {
  codex: [".codex", "skills"],
  claude: [".claude", "skills"],
};
const COMPONENTS = {
  runtime: { skillName: "openapi-engineering", source: BUNDLED_SKILL },
  maintainer: {
    skillName: "openapi-engineering-maintainer",
    source: BUNDLED_MAINTAINER,
  },
};

function usage() {
  return `Usage: openapi-engineering-skill <install|verify|uninstall|usage|session|maintenance> [options]

Options:
  --platform <codex|claude>  Select a platform; repeat for both (default: both)
  --component <runtime|maintainer> Select a Skill component; repeat (default: runtime)
  --home <path>              Override the user home directory
  --apply                    Apply install or uninstall; otherwise dry-run
  --copy                     Copy platform targets instead of linking
  --json                     Emit a JSON report
  --help                     Show this help`;
}

async function runMaintenance(argv) {
  const scripts = {
    analyze: "analyze_usage.py",
    propose: "build_proposal.py",
    promote: "promote_candidate.py",
  };
  const command = argv[0];
  if (command === "automation" || command === "cycle") {
    const options = parseMaintenanceArguments(argv);
    const skillSha256 = await treeDigest(BUNDLED_SKILL);
    if (command === "automation") {
      const configured = await configureMaintenanceAutomation({
        home: options.home,
        action: options.action,
        options,
        packageVersion: PACKAGE.version,
        skillSha256,
      });
      return { ...configured, json: options.json, passthrough: false };
    }
    const config = await loadUsageConfig(options.home);
    const cycle = await runMaintenanceCycle({
      home: options.home,
      config,
      options,
      packageVersion: PACKAGE.version,
      skillSha256,
      packageRoot: PACKAGE_ROOT,
    });
    return { ...cycle, json: options.json, passthrough: false };
  }
  if (!scripts[command]) throw new Error("Unsupported maintenance command.");
  const executable = process.env.OPENAPI_ENGINEERING_PYTHON || "python3";
  const script = join(PACKAGE_ROOT, "scripts", "maintenance", scripts[command]);
  const exitCode = await new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(executable, [script, ...argv.slice(1)], {
      cwd: process.cwd(),
      env: process.env,
      stdio: "inherit",
    });
    child.once("error", rejectPromise);
    child.once("close", (code, signal) => {
      if (signal) resolvePromise(2);
      else resolvePromise(Number.isInteger(code) ? code : 2);
    });
  });
  return { exitCode, passthrough: true };
}

function parseMaintenanceArguments(argv) {
  const command = argv[0];
  let start = 1;
  let action = null;
  if (command === "automation") {
    action = argv[1];
    if (!new Set(["status", "configure", "disable"]).has(action)) {
      throw new Error("Unsupported maintenance automation action.");
    }
    start = 2;
  }
  const options = {
    command,
    action,
    home: homedir(),
    stateRoot: null,
    now: null,
    credentialMode: null,
    pythonExecutable: null,
    notification: "none",
    approve: null,
    apply: false,
    json: false,
    adapter: "codex",
    fakeResponse: null,
    fakePlatform: "codex",
    secondaryAdapter: "claude",
    secondaryFakeResponse: null,
    secondaryFakePlatform: "claude",
  };
  const values = new Map([
    ["--home", "home"],
    ["--state-root", "stateRoot"],
    ["--now", "now"],
    ["--credential-mode", "credentialMode"],
    ["--python", "pythonExecutable"],
    ["--notify", "notification"],
    ["--approve", "approve"],
    ["--adapter", "adapter"],
    ["--fake-response", "fakeResponse"],
    ["--fake-platform", "fakePlatform"],
    ["--secondary-adapter", "secondaryAdapter"],
    ["--secondary-fake-response", "secondaryFakeResponse"],
    ["--secondary-fake-platform", "secondaryFakePlatform"],
  ]);
  for (let index = start; index < argv.length; index += 1) {
    const argument = argv[index];
    if (values.has(argument)) {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`${argument} requires a value`);
      options[values.get(argument)] = value;
      index += 1;
    } else if (argument === "--apply") {
      options.apply = true;
    } else if (argument === "--json") {
      options.json = true;
    } else {
      throw new Error(`Unsupported maintenance option: ${argument}`);
    }
  }
  if (command === "cycle") {
    if (!new Set(["codex", "fake"]).has(options.adapter)) {
      throw new Error("Unsupported maintenance analyzer adapter.");
    }
    if (!new Set(["claude", "fake", "none"]).has(options.secondaryAdapter)) {
      throw new Error("Unsupported maintenance secondary adapter.");
    }
  }
  options.home = resolve(options.home);
  if (options.stateRoot) options.stateRoot = resolve(options.stateRoot);
  if (options.fakeResponse) options.fakeResponse = resolve(options.fakeResponse);
  if (options.secondaryFakeResponse) {
    options.secondaryFakeResponse = resolve(options.secondaryFakeResponse);
  }
  return options;
}

function parseSessionArguments(argv) {
  if (argv[0] !== "run") throw new Error("Unsupported session command.");
  const separator = argv.indexOf("--");
  if (separator < 0 || separator === argv.length - 1) {
    throw new Error("Session command arguments must follow --.");
  }
  const options = {
    agent: null,
    projectAlias: null,
    output: null,
    timeoutSeconds: 600,
    warningRssMb: 512,
    hardRssMb: 1024,
    json: false,
    command: argv.slice(separator + 1),
    cwd: process.cwd(),
  };
  const valueOptions = new Map([
    ["--agent", "agent"],
    ["--project-alias", "projectAlias"],
    ["--output", "output"],
    ["--timeout-seconds", "timeoutSeconds"],
    ["--warning-rss-mb", "warningRssMb"],
    ["--hard-rss-mb", "hardRssMb"],
  ]);
  for (let index = 1; index < separator; index += 1) {
    const argument = argv[index];
    if (valueOptions.has(argument)) {
      const value = argv[index + 1];
      if (!value || index + 1 >= separator) throw new Error(`${argument} requires a value`);
      options[valueOptions.get(argument)] = value;
      index += 1;
    } else if (argument === "--json") {
      options.json = true;
    } else {
      throw new Error(`Unsupported session option: ${argument}`);
    }
  }
  if (options.output) options.output = resolve(options.output);
  return options;
}

async function runSession(argv) {
  const options = parseSessionArguments(argv);
  const report = await runUsageSession(options);
  const exitCode = report.status === "passed" ? 0 : report.status === "failed" ? 1 : 2;
  return [report, exitCode, options.json];
}

function parseUsageArguments(argv) {
  if (argv.length === 0) throw new Error("A usage subcommand is required.");
  let command = argv[0];
  let start = 1;
  if (command === "sync" && argv[1] === "configure") {
    command = "sync-configure";
    start = 2;
  } else if (command === "scheduler" && new Set(["status", "install", "uninstall"]).has(argv[1])) {
    command = `scheduler-${argv[1]}`;
    start = 2;
  }
  const options = {
    command,
    home: homedir(),
    stateRoot: null,
    device: null,
    remote: null,
    branch: null,
    coordinator: false,
    apply: false,
    json: false,
    now: null,
    completionReport: null,
    launcherReport: null,
    captureMode: null,
    platform: "unknown",
    platformVersion: null,
    projectAlias: null,
    session: null,
    lifecycleModes: [],
    toolStrategy: null,
    interviewTurns: null,
    boundaryRevisions: null,
    durationMs: null,
    peakRssMb: null,
    toolOverridden: false,
    safetyViolation: false,
    resourceAnomaly: false,
    platformDrift: false,
    rating: null,
    tags: [],
    note: null,
    period: null,
    hour: null,
    minute: null,
    approve: null,
    scope: "local",
    fixAt: null,
  };
  const valueOptions = new Map([
    ["--home", "home"],
    ["--state-root", "stateRoot"],
    ["--device", "device"],
    ["--remote", "remote"],
    ["--branch", "branch"],
    ["--now", "now"],
    ["--completion-report", "completionReport"],
    ["--launcher-report", "launcherReport"],
    ["--capture-mode", "captureMode"],
    ["--platform", "platform"],
    ["--platform-version", "platformVersion"],
    ["--project-alias", "projectAlias"],
    ["--session", "session"],
    ["--tool-strategy", "toolStrategy"],
    ["--interview-turns", "interviewTurns"],
    ["--boundary-revisions", "boundaryRevisions"],
    ["--duration-ms", "durationMs"],
    ["--peak-rss-mb", "peakRssMb"],
    ["--rating", "rating"],
    ["--note", "note"],
    ["--period", "period"],
    ["--hour", "hour"],
    ["--minute", "minute"],
    ["--approve", "approve"],
    ["--scope", "scope"],
    ["--fix-at", "fixAt"],
  ]);
  for (let index = start; index < argv.length; index += 1) {
    const argument = argv[index];
    if (valueOptions.has(argument)) {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`${argument} requires a value`);
      options[valueOptions.get(argument)] = value;
      index += 1;
    } else if (argument === "--lifecycle") {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error("--lifecycle requires a value");
      options.lifecycleModes.push(value);
      index += 1;
    } else if (argument === "--tag") {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error("--tag requires a value");
      options.tags.push(value);
      index += 1;
    } else if (argument === "--coordinator") {
      options.coordinator = true;
    } else if (argument === "--apply") {
      options.apply = true;
    } else if (argument === "--json") {
      options.json = true;
    } else if (argument === "--tool-overridden") {
      options.toolOverridden = true;
    } else if (argument === "--safety-violation") {
      options.safetyViolation = true;
    } else if (argument === "--resource-anomaly") {
      options.resourceAnomaly = true;
    } else if (argument === "--platform-drift") {
      options.platformDrift = true;
    } else {
      throw new Error(`Unsupported usage option: ${argument}`);
    }
  }
  options.home = resolve(options.home);
  if (options.stateRoot) options.stateRoot = resolve(options.stateRoot);
  if (options.completionReport) options.completionReport = resolve(options.completionReport);
  if (options.launcherReport) options.launcherReport = resolve(options.launcherReport);
  return options;
}

async function runUsage(argv) {
  const options = parseUsageArguments(argv);
  if (new Set(["status", "enable", "disable", "sync-configure"]).has(options.command)) {
    const report = await configureUsage(options.home, options.command, options);
    return [report, 0, options.json];
  }
  if (options.command === "record") {
    const config = await loadUsageConfig(options.home);
    const report = await recordUsage({
      home: options.home,
      config,
      options,
      packageVersion: PACKAGE.version,
      skillRoot: BUNDLED_SKILL,
    });
    return [report, 0, options.json];
  }
  if (options.command === "feedback") {
    const config = await loadUsageConfig(options.home);
    const stateRoot = configuredStateRoot(config, options.home, options.stateRoot);
    const paths = usageStatePaths(stateRoot, config.device_alias);
    const report = await recordFeedback({
      home: options.home,
      config,
      options,
      events: await loadUsageEvents(paths.events),
    });
    return [report, 0, options.json];
  }
  if (options.command === "summarize") {
    const config = await loadUsageConfig(options.home);
    const { summary } = await buildUsageSummary({ home: options.home, config, options });
    return [summary, 0, options.json];
  }
  if (options.command === "sync") {
    const config = await loadUsageConfig(options.home);
    const report = await synchronizeUsage({ home: options.home, config, options });
    return [report, report.status === "ok" ? 0 : 1, options.json];
  }
  if (options.command === "due") {
    const config = await loadUsageConfig(options.home);
    const report = await checkUsageDue({ home: options.home, config, options });
    return [report, 0, options.json];
  }
  if (options.command === "cleanup") {
    const config = await loadUsageConfig(options.home);
    const result = await cleanupUsage({ home: options.home, config, options });
    return [result.report, result.exitCode, options.json];
  }
  if (options.command === "trends") {
    const config = await loadUsageConfig(options.home);
    const report = await buildUsageTrends({ home: options.home, config, options });
    return [report, 0, options.json];
  }
  if (options.command.startsWith("scheduler-")) {
    const config = await loadUsageConfig(options.home);
    const action = options.command.slice("scheduler-".length);
    const installedCli = join(
      options.home,
      ".local",
      "share",
      "openapi-engineering-skill",
      PACKAGE.version,
      "bin",
      "openapi-engineering-skill.mjs",
    );
    const installedInfo = await pathInfo(installedCli);
    const result = await manageLaunchd({
      home: options.home,
      config,
      options,
      action,
      nodePath: process.execPath,
      cliPath: installedInfo?.isFile() ? installedCli : fileURLToPath(import.meta.url),
      templatePath: LAUNCHD_TEMPLATE,
    });
    return [result.report, result.exitCode, options.json];
  }
  throw new Error(`Unsupported usage command: ${options.command}`);
}

function parseArguments(argv) {
  if (argv.length === 0 || argv.includes("--help")) {
    return { help: true, json: argv.includes("--json") };
  }
  const command = argv[0];
  if (!new Set(["install", "verify", "uninstall"]).has(command)) {
    throw new Error(`Unsupported command: ${command}`);
  }
  const options = {
    command,
    platforms: [],
    components: [],
    home: homedir(),
    apply: false,
    copy: false,
    json: false,
  };
  for (let index = 1; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--platform" || argument === "--component" || argument === "--home") {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) {
        throw new Error(`${argument} requires a value`);
      }
      index += 1;
      if (argument === "--platform") {
        if (!(value in TARGETS)) {
          throw new Error(`Unsupported platform: ${value}`);
        }
        options.platforms.push(value);
      } else if (argument === "--component") {
        if (!(value in COMPONENTS)) {
          throw new Error(`Unsupported component: ${value}`);
        }
        options.components.push(value);
      } else {
        options.home = value;
      }
    } else if (argument === "--apply") {
      options.apply = true;
    } else if (argument === "--copy") {
      options.copy = true;
    } else if (argument === "--json") {
      options.json = true;
    } else {
      throw new Error(`Unsupported option: ${argument}`);
    }
  }
  if (options.command === "verify" && options.apply) {
    throw new Error("verify does not accept --apply");
  }
  options.platforms = [...new Set(options.platforms)];
  if (options.platforms.length === 0) {
    options.platforms = ["codex", "claude"];
  }
  options.components = [...new Set(options.components)];
  if (options.components.length === 0) options.components = ["runtime"];
  options.home = resolve(options.home);
  return options;
}

async function pathInfo(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

function installationPaths(home) {
  const versionRoot = join(
    home,
    ".local",
    "share",
    "openapi-engineering-skill",
    PACKAGE.version,
  );
  return {
    versionRoot,
    canonical: join(versionRoot, "skills", "openapi-engineering"),
    canonicals: Object.fromEntries(
      Object.entries(COMPONENTS).map(([component, value]) => [
        component,
        join(versionRoot, "skills", value.skillName),
      ]),
    ),
  };
}

async function canonicalStates(versionRoot, canonicals, expectedDigests) {
  const rootInfo = await pathInfo(versionRoot);
  if (!rootInfo) {
    return Object.fromEntries(
      Object.keys(canonicals).map((component) => [component, { state: "missing", digest: null }]),
    );
  }
  if (!rootInfo.isDirectory()) {
    return Object.fromEntries(
      Object.keys(canonicals).map((component) => [component, { state: "conflict", digest: null }]),
    );
  }
  const states = {};
  for (const [component, canonical] of Object.entries(canonicals)) {
    const info = await pathInfo(canonical);
    if (!info?.isDirectory()) {
      states[component] = { state: "conflict", digest: null };
      continue;
    }
    const digest = await treeDigest(canonical);
    states[component] = {
      state: digest === expectedDigests[component] ? "unchanged" : "conflict",
      digest,
    };
  }
  return states;
}

async function managedPreviousCanonical(home, destination, skillName) {
  const roots = [
    {
      path: resolve(home, ".local", "share", "openapi-engineering-skill"),
      legacy: false,
    },
    {
      path: resolve(home, ".local", "share", "openapi-generator-skill"),
      legacy: true,
    },
  ];
  for (const managed of roots) {
    const relativeDestination = relative(managed.path, destination);
    const parts = relativeDestination.split(/[\\/]/).filter(Boolean);
    if (
      relativeDestination.startsWith("..")
      || parts.length !== 3
      || parts[1] !== "skills"
      || parts[2] !== skillName
      || (!managed.legacy && parts[0] === PACKAGE.version)
    ) {
      continue;
    }
    const versionRoot = join(managed.path, parts[0]);
    const rootInfo = await pathInfo(versionRoot);
    const destinationInfo = await pathInfo(destination);
    if (
      !rootInfo?.isDirectory()
      || rootInfo.isSymbolicLink()
      || !destinationInfo?.isDirectory()
      || destinationInfo.isSymbolicLink()
    ) {
      continue;
    }
    if (managed.legacy) {
      const skill = await pathInfo(join(destination, "SKILL.md"));
      if (!parts[0].startsWith("v") || !skill?.isFile() || skill.isSymbolicLink()) continue;
    } else {
      const packagePath = join(versionRoot, "package.json");
      const packageInfo = await pathInfo(packagePath);
      if (!packageInfo?.isFile() || packageInfo.isSymbolicLink()) continue;
      try {
        const metadata = JSON.parse(await readFile(packagePath, "utf8"));
        if (metadata.name !== PACKAGE.name || metadata.version !== parts[0]) continue;
      } catch {
        continue;
      }
    }
    return {
      destination,
      digest: await treeDigest(destination),
      version: parts[0],
    };
  }
  return null;
}

async function targetState(
  target,
  canonical,
  expectedDigest,
  { home = null, skillName = null, allowPrevious = false } = {},
) {
  const info = await pathInfo(target);
  if (!info) return { state: "missing", digest: null };
  if (info.isSymbolicLink()) {
    const destination = resolve(dirname(target), await readlink(target));
    if (destination !== canonical && allowPrevious && home && skillName) {
      const previous = await managedPreviousCanonical(home, destination, skillName);
      if (previous) {
        return {
          state: "managed-previous",
          digest: previous.digest,
          previous_target: previous.destination,
          previous_version: previous.version,
        };
      }
    }
    return {
      state: destination === canonical ? "unchanged" : "conflict",
      digest: destination === canonical ? expectedDigest : null,
    };
  }
  if (!info.isDirectory()) return { state: "conflict", digest: null };
  const digest = await treeDigest(target);
  return {
    state: digest === expectedDigest ? "unchanged" : "conflict",
    digest,
  };
}

function targetRows(home, platforms, components) {
  return components.flatMap((component) =>
    platforms.map((platform) => ({
      platform,
      component,
      target: join(home, ...TARGETS[platform], COMPONENTS[component].skillName),
    })),
  );
}

async function atomicCopyCanonical(versionRoot) {
  const temporary = `${versionRoot}.tmp-${process.pid}`;
  await rm(temporary, { recursive: true, force: true });
  try {
    for (const value of Object.values(COMPONENTS)) {
      await mkdir(dirname(join(temporary, "skills", value.skillName)), { recursive: true });
      await cp(value.source, join(temporary, "skills", value.skillName), { recursive: true });
    }
    for (const directory of ["bin", "lib", "packaging"]) {
      await cp(join(PACKAGE_ROOT, directory), join(temporary, directory), { recursive: true });
    }
    await cp(
      join(PACKAGE_ROOT, "scripts", "maintenance"),
      join(temporary, "scripts", "maintenance"),
      { recursive: true },
    );
    const schemaTarget = join(temporary, "contracts", "schemas");
    await mkdir(schemaTarget, { recursive: true });
    for (const name of [
      "usage-config.schema.json",
      "usage-event.schema.json",
      "user-feedback.schema.json",
      "usage-summary.schema.json",
      "usage-trend.schema.json",
      "maintenance-finding.schema.json",
      "maintenance-analysis.schema.json",
      "maintenance-cycle.schema.json",
      "maintenance-report.schema.json",
      "maintenance-proposal.schema.json",
      "maintenance-promotion.schema.json",
      "retention-plan.schema.json",
    ]) {
      await cp(join(PACKAGE_ROOT, "contracts", "schemas", name), join(schemaTarget, name));
    }
    await cp(join(PACKAGE_ROOT, "package.json"), join(temporary, "package.json"));
    await mkdir(dirname(versionRoot), { recursive: true });
    await rename(temporary, versionRoot);
  } catch (error) {
    await rm(temporary, { recursive: true, force: true });
    throw error;
  }
  return versionRoot;
}

async function install(options) {
  const sourceDigests = Object.fromEntries(
    await Promise.all(
      Object.entries(COMPONENTS).map(async ([component, value]) => [component, await treeDigest(value.source)]),
    ),
  );
  const sourceDigest = sourceDigests.runtime;
  const { versionRoot, canonical, canonicals } = installationPaths(options.home);
  const canonicalChecks = await canonicalStates(versionRoot, canonicals, sourceDigests);
  const useCopy = options.copy || process.platform === "win32";
  const rows = [];
  let conflict = Object.values(canonicalChecks).some((check) => check.state === "conflict");
  for (const row of targetRows(options.home, options.platforms, options.components)) {
    const check = await targetState(
      row.target,
      canonicals[row.component],
      sourceDigests[row.component],
      {
        home: options.home,
        skillName: COMPONENTS[row.component].skillName,
        allowPrevious: !useCopy,
      },
    );
    const action = check.state === "managed-previous"
      ? "would-relink"
      : check.state === "missing"
        ? useCopy
          ? "would-copy"
          : "would-link"
        : check.state;
    conflict ||= action === "conflict";
    rows.push({
      ...row,
      action,
      target_digest: check.digest,
      previous_target: check.previous_target ?? null,
      previous_version: check.previous_version ?? null,
    });
  }
  const report = {
    status: conflict ? "conflict" : "ok",
    command: "install",
    version: PACKAGE.version,
    applied: false,
    source_digest: sourceDigest,
    component_source_digests: sourceDigests,
    canonical: {
      path: canonical,
      action:
        canonicalChecks.runtime.state === "missing" ? "would-copy" : canonicalChecks.runtime.state,
      digest: canonicalChecks.runtime.digest,
    },
    canonicals: Object.entries(canonicals).map(([component, path]) => ({
      component,
      path,
      action: canonicalChecks[component].state === "missing" ? "would-copy" : canonicalChecks[component].state,
      digest: canonicalChecks[component].digest,
    })),
    installations: rows,
  };
  if (conflict) return [report, 1];
  if (!options.apply) return [report, 0];

  const targetMutations = [];
  let createdCanonical = false;
  try {
    if (canonicalChecks.runtime.state === "missing") {
      await atomicCopyCanonical(versionRoot);
      createdCanonical = true;
      report.canonical.action = "copy";
      report.canonical.digest = sourceDigest;
      for (const row of report.canonicals) {
        row.action = "copy";
        row.digest = sourceDigests[row.component];
      }
    }
    for (const row of rows) {
      if (!row.action.startsWith("would-")) continue;
      await mkdir(dirname(row.target), { recursive: true });
      if (row.action === "would-relink") {
        const temporaryLink = `${row.target}.tmp-${process.pid}`;
        await rm(temporaryLink, { force: true });
        await symlink(canonicals[row.component], temporaryLink, "dir");
        await rename(temporaryLink, row.target);
        targetMutations.push({ target: row.target, previous: row.previous_target });
        row.action = "link";
      } else if (useCopy) {
        await cp(canonicals[row.component], row.target, { recursive: true });
        row.action = "copy";
        targetMutations.push({ target: row.target, previous: null });
      } else {
        await symlink(canonicals[row.component], row.target, "dir");
        row.action = "link";
        targetMutations.push({ target: row.target, previous: null });
      }
      row.target_digest = sourceDigests[row.component];
    }
  } catch (error) {
    for (const mutation of targetMutations.reverse()) {
      if (mutation.previous) {
        const temporaryLink = `${mutation.target}.rollback-${process.pid}`;
        await rm(temporaryLink, { force: true });
        await symlink(mutation.previous, temporaryLink, "dir");
        await rename(temporaryLink, mutation.target);
      } else {
        await rm(mutation.target, { recursive: true, force: true });
      }
    }
    if (createdCanonical) {
      await rm(versionRoot, { recursive: true, force: true });
    }
    throw error;
  }
  report.applied = true;
  return [report, 0];
}

async function verify(options) {
  const sourceDigests = Object.fromEntries(
    await Promise.all(
      Object.entries(COMPONENTS).map(async ([component, value]) => [component, await treeDigest(value.source)]),
    ),
  );
  const sourceDigest = sourceDigests.runtime;
  const { versionRoot, canonical, canonicals } = installationPaths(options.home);
  const canonicalChecks = await canonicalStates(versionRoot, canonicals, sourceDigests);
  const rows = [];
  let verified = Object.values(canonicalChecks).every((check) => check.state === "unchanged");
  for (const row of targetRows(options.home, options.platforms, options.components)) {
    const check = await targetState(row.target, canonicals[row.component], sourceDigests[row.component]);
    verified &&= check.state === "unchanged";
    rows.push({
      ...row,
      action: check.state === "unchanged" ? "verified" : check.state,
      target_digest: check.digest,
    });
  }
  return [
    {
      status: verified ? "ok" : "failed",
      command: "verify",
      version: PACKAGE.version,
      verified,
      source_digest: sourceDigest,
      component_source_digests: sourceDigests,
      canonical: {
        path: canonical,
        action: canonicalChecks.runtime.state === "unchanged" ? "verified" : canonicalChecks.runtime.state,
        digest: canonicalChecks.runtime.digest,
      },
      installations: rows,
    },
    verified ? 0 : 1,
  ];
}

async function uninstall(options) {
  const sourceDigests = Object.fromEntries(
    await Promise.all(
      Object.entries(COMPONENTS).map(async ([component, value]) => [component, await treeDigest(value.source)]),
    ),
  );
  const { canonical, canonicals } = installationPaths(options.home);
  const rows = [];
  let conflict = false;
  for (const row of targetRows(options.home, options.platforms, options.components)) {
    const check = await targetState(row.target, canonicals[row.component], sourceDigests[row.component]);
    conflict ||= check.state === "conflict";
    rows.push({
      ...row,
      action:
        check.state === "unchanged"
          ? "would-remove"
          : check.state === "missing"
            ? "unchanged"
            : "conflict",
      target_digest: check.digest,
    });
  }
  const report = {
    status: conflict ? "conflict" : "ok",
    command: "uninstall",
    version: PACKAGE.version,
    applied: false,
    canonical: { path: canonical, action: "preserve" },
    installations: rows,
  };
  if (conflict) return [report, 1];
  if (!options.apply) return [report, 0];
  for (const row of rows) {
    if (row.action !== "would-remove") continue;
    await rm(row.target, { recursive: true, force: true });
    row.action = "remove";
  }
  report.applied = true;
  return [report, 0];
}

function emit(report, json) {
  if (json) {
    console.log(JSON.stringify(report));
    return;
  }
  console.log(`${report.command}: ${report.status} (${report.version})`);
  if (report.canonical) {
    console.log(`canonical: ${report.canonical.action} ${report.canonical.path}`);
  }
  for (const row of report.installations ?? []) {
    console.log(`${row.platform}/${row.component ?? "runtime"}: ${row.action} ${row.target}`);
  }
}

async function main() {
  const wantsJson = process.argv.includes("--json");
  try {
    if (process.argv[2] === "usage") {
      const [report, exitCode, json] = await runUsage(process.argv.slice(3));
      if (json) console.log(JSON.stringify(report));
      else console.log(JSON.stringify(report, null, 2));
      return exitCode;
    }
    if (process.argv[2] === "session") {
      const [report, exitCode, json] = await runSession(process.argv.slice(3));
      if (json) console.log(JSON.stringify(report));
      else console.log(JSON.stringify(report, null, 2));
      return exitCode;
    }
    if (process.argv[2] === "maintenance") {
      const maintenance = await runMaintenance(process.argv.slice(3));
      if (!maintenance.passthrough) {
        if (maintenance.json) console.log(JSON.stringify(maintenance.report ?? maintenance.result));
        else console.log(JSON.stringify(maintenance.report ?? maintenance.result, null, 2));
      }
      return maintenance.exitCode;
    }
    const options = parseArguments(process.argv.slice(2));
    if (options.help) {
      console.log(usage());
      return 0;
    }
    let result;
    if (options.command === "install") result = await install(options);
    if (options.command === "verify") result = await verify(options);
    if (options.command === "uninstall") result = await uninstall(options);
    emit(result[0], options.json);
    return result[1];
  } catch (error) {
    const report = { status: "error", error: error.message };
    if (wantsJson) console.log(JSON.stringify(report));
    else console.error(error.message);
    return Number.isInteger(error.exitCode) ? error.exitCode : 2;
  }
}

process.exitCode = await main();
