import { createHash } from "node:crypto";
import { lstat, readFile, rm } from "node:fs/promises";
import { join, relative, resolve } from "node:path";

import { atomicWrite, atomicWriteJson, readJsonIfExists } from "./atomic-files.mjs";
import { assertSafeUsagePath, configuredStateRoot, usageStatePaths } from "./paths.mjs";

const LABEL = "com.realpkuasule.openapi-engineering-maintainer";

function sha256(content) {
  return createHash("sha256").update(content).digest("hex");
}

function xml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

async function pathInfo(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function assertNoManagedSymlink(home, target) {
  const rel = relative(resolve(home), resolve(target));
  if (rel === ".." || rel.startsWith("../") || rel.startsWith("..\\")) {
    throw new Error("Scheduler target escapes the configured home.");
  }
  let current = resolve(home);
  for (const component of rel.split(/[\\/]/).filter(Boolean)) {
    current = join(current, component);
    const info = await pathInfo(current);
    if (info?.isSymbolicLink()) throw new Error("Scheduler target contains a symbolic link.");
  }
}

async function renderTemplate({ templatePath, nodePath, cliPath, home, stateRoot, hour, minute }) {
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) throw new Error("Scheduler hour is invalid.");
  if (!Number.isInteger(minute) || minute < 0 || minute > 59) throw new Error("Scheduler minute is invalid.");
  const template = await readFile(templatePath, "utf8");
  return template
    .replaceAll("__NODE__", xml(nodePath))
    .replaceAll("__CLI__", xml(cliPath))
    .replaceAll("__HOME__", xml(home))
    .replaceAll("__HOUR__", String(hour))
    .replaceAll("__MINUTE__", String(minute))
    .replaceAll("__STDOUT__", xml(join(stateRoot, "logs", "launchd.stdout.log")))
    .replaceAll("__STDERR__", xml(join(stateRoot, "logs", "launchd.stderr.log")));
}

async function installationState(target, manifestPath) {
  const targetInfo = await pathInfo(target);
  const manifest = await readJsonIfExists(manifestPath);
  if (!targetInfo && manifest === null) return { state: "missing", digest: null, manifest: null };
  if (!targetInfo?.isFile() || targetInfo.isSymbolicLink() || manifest === null) {
    return { state: "conflict", digest: null, manifest };
  }
  const content = await readFile(target);
  const digest = sha256(content);
  if (
    manifest.manifest_version !== 1 ||
    manifest.label !== LABEL ||
    manifest.target !== target ||
    manifest.sha256 !== digest
  ) {
    return { state: "conflict", digest, manifest };
  }
  return { state: "installed", digest, manifest };
}

export async function manageLaunchd({
  home,
  config,
  options,
  action,
  nodePath,
  cliPath,
  templatePath,
}) {
  if (process.platform !== "darwin") throw new Error("launchd is available only on macOS.");
  if (!config.local_collection_enabled || !config.coordinator) {
    throw new Error("Only an enabled coordinator may manage the scheduler.");
  }
  const stateRoot = configuredStateRoot(config, home, options.stateRoot);
  const paths = usageStatePaths(stateRoot, config.device_alias);
  const target = join(home, "Library", "LaunchAgents", `${LABEL}.plist`);
  const manifestPath = join(paths.checkpoints, "launchd.json");
  await assertNoManagedSymlink(home, target);
  await assertSafeUsagePath(stateRoot, manifestPath);
  const current = await installationState(target, manifestPath);

  if (action === "status") {
    return {
      report: {
        status: current.state === "conflict" ? "conflict" : "ok",
        action,
        applied: false,
        state: current.state,
        target,
        sha256: current.digest,
      },
      exitCode: current.state === "conflict" ? 1 : 0,
    };
  }
  if (current.state === "conflict") {
    return {
      report: { status: "conflict", action, applied: false, state: "conflict", target, sha256: current.digest },
      exitCode: 1,
    };
  }
  if (action === "uninstall") {
    if (current.state === "missing") {
      return {
        report: { status: "ok", action, applied: false, state: "removed", target, sha256: null },
        exitCode: 0,
      };
    }
    if (!options.apply) {
      return {
        report: { status: "ok", action, applied: false, state: "would-remove", target, sha256: current.digest },
        exitCode: 0,
      };
    }
    await rm(target, { force: true });
    await rm(manifestPath, { force: true });
    return {
      report: { status: "ok", action, applied: true, state: "removed", target, sha256: current.digest },
      exitCode: 0,
    };
  }
  if (action !== "install") throw new Error("Scheduler action is invalid.");

  const content = await renderTemplate({
    templatePath,
    nodePath,
    cliPath,
    home,
    stateRoot,
    hour: Number(options.hour ?? 3),
    minute: Number(options.minute ?? 0),
  });
  const digest = sha256(content);
  if (current.state === "installed" && current.digest === digest) {
    return {
      report: { status: "ok", action, applied: false, state: "installed", target, sha256: digest },
      exitCode: 0,
    };
  }
  if (!options.apply) {
    return {
      report: { status: "ok", action, applied: false, state: "would-install", target, sha256: digest },
      exitCode: 0,
    };
  }
  await atomicWrite(target, content, 0o600);
  await atomicWriteJson(manifestPath, {
    manifest_version: 1,
    label: LABEL,
    target,
    sha256: digest,
  });
  return {
    report: { status: "ok", action, applied: true, state: "installed", target, sha256: digest },
    exitCode: 0,
  };
}
