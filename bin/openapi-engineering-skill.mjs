#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  cp,
  lstat,
  mkdir,
  readFile,
  readdir,
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

const PACKAGE_ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const PACKAGE = JSON.parse(
  await readFile(join(PACKAGE_ROOT, "package.json"), "utf8"),
);
const BUNDLED_SKILL = join(PACKAGE_ROOT, "skills", "openapi-engineering");
const IGNORED_NAMES = new Set([".DS_Store", "__pycache__"]);
const TARGETS = {
  codex: [".codex", "skills", "openapi-engineering"],
  claude: [".claude", "skills", "openapi-engineering"],
};

function usage() {
  return `Usage: openapi-engineering-skill <install|verify|uninstall> [options]

Options:
  --platform <codex|claude>  Select a platform; repeat for both (default: both)
  --home <path>              Override the user home directory
  --apply                    Apply install or uninstall; otherwise dry-run
  --copy                     Copy platform targets instead of linking
  --json                     Emit a JSON report
  --help                     Show this help`;
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
    home: homedir(),
    apply: false,
    copy: false,
    json: false,
  };
  for (let index = 1; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--platform" || argument === "--home") {
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

async function listFiles(root, directory = root) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    if (IGNORED_NAMES.has(entry.name)) continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(root, path)));
    } else if (entry.isFile()) {
      files.push(path);
    } else {
      throw new Error(`Unsupported entry in skill payload: ${relative(root, path)}`);
    }
  }
  return files;
}

async function treeDigest(root) {
  const digest = createHash("sha256");
  const files = (await listFiles(root))
    .map((path) => {
      const name = relative(root, path).split("\\").join("/");
      return {
        path,
        name,
        order: process.platform === "win32" ? name.toLowerCase() : name,
      };
    })
    .sort((left, right) =>
      left.order < right.order ? -1 : left.order > right.order ? 1 : 0,
    );
  for (const { path, name } of files) {
    digest.update(name);
    digest.update("\0");
    digest.update(await readFile(path));
    digest.update("\0");
  }
  return digest.digest("hex");
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
  };
}

async function canonicalState(versionRoot, canonical, expectedDigest) {
  const rootInfo = await pathInfo(versionRoot);
  if (!rootInfo) return { state: "missing", digest: null };
  if (!rootInfo.isDirectory()) return { state: "conflict", digest: null };
  const canonicalInfo = await pathInfo(canonical);
  if (!canonicalInfo?.isDirectory()) return { state: "conflict", digest: null };
  const digest = await treeDigest(canonical);
  return {
    state: digest === expectedDigest ? "unchanged" : "conflict",
    digest,
  };
}

async function targetState(target, canonical, expectedDigest) {
  const info = await pathInfo(target);
  if (!info) return { state: "missing", digest: null };
  if (info.isSymbolicLink()) {
    const destination = resolve(dirname(target), await readlink(target));
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

function targetRows(home, platforms) {
  return platforms.map((platform) => ({
    platform,
    target: join(home, ...TARGETS[platform]),
  }));
}

async function atomicCopyCanonical(versionRoot, canonical) {
  const temporary = `${versionRoot}.tmp-${process.pid}`;
  await rm(temporary, { recursive: true, force: true });
  try {
    await mkdir(dirname(join(temporary, "skills", "openapi-engineering")), {
      recursive: true,
    });
    await cp(BUNDLED_SKILL, join(temporary, "skills", "openapi-engineering"), {
      recursive: true,
    });
    await mkdir(dirname(versionRoot), { recursive: true });
    await rename(temporary, versionRoot);
  } catch (error) {
    await rm(temporary, { recursive: true, force: true });
    throw error;
  }
  return canonical;
}

async function install(options) {
  const sourceDigest = await treeDigest(BUNDLED_SKILL);
  const { versionRoot, canonical } = installationPaths(options.home);
  const canonicalCheck = await canonicalState(versionRoot, canonical, sourceDigest);
  const useCopy = options.copy || process.platform === "win32";
  const rows = [];
  let conflict = canonicalCheck.state === "conflict";
  for (const row of targetRows(options.home, options.platforms)) {
    const check = await targetState(row.target, canonical, sourceDigest);
    conflict ||= check.state === "conflict";
    rows.push({
      ...row,
      action:
        check.state === "missing"
          ? useCopy
            ? "would-copy"
            : "would-link"
          : check.state,
      target_digest: check.digest,
    });
  }
  const report = {
    status: conflict ? "conflict" : "ok",
    command: "install",
    version: PACKAGE.version,
    applied: false,
    source_digest: sourceDigest,
    canonical: {
      path: canonical,
      action:
        canonicalCheck.state === "missing" ? "would-copy" : canonicalCheck.state,
      digest: canonicalCheck.digest,
    },
    installations: rows,
  };
  if (conflict) return [report, 1];
  if (!options.apply) return [report, 0];

  const createdTargets = [];
  let createdCanonical = false;
  try {
    if (canonicalCheck.state === "missing") {
      await atomicCopyCanonical(versionRoot, canonical);
      createdCanonical = true;
      report.canonical.action = "copy";
      report.canonical.digest = sourceDigest;
    }
    for (const row of rows) {
      if (!row.action.startsWith("would-")) continue;
      await mkdir(dirname(row.target), { recursive: true });
      if (useCopy) {
        await cp(canonical, row.target, { recursive: true });
        row.action = "copy";
      } else {
        await symlink(canonical, row.target, "dir");
        row.action = "link";
      }
      row.target_digest = sourceDigest;
      createdTargets.push(row.target);
    }
  } catch (error) {
    for (const target of createdTargets.reverse()) {
      await rm(target, { recursive: true, force: true });
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
  const sourceDigest = await treeDigest(BUNDLED_SKILL);
  const { versionRoot, canonical } = installationPaths(options.home);
  const canonicalCheck = await canonicalState(versionRoot, canonical, sourceDigest);
  const rows = [];
  let verified = canonicalCheck.state === "unchanged";
  for (const row of targetRows(options.home, options.platforms)) {
    const check = await targetState(row.target, canonical, sourceDigest);
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
      canonical: {
        path: canonical,
        action: canonicalCheck.state === "unchanged" ? "verified" : canonicalCheck.state,
        digest: canonicalCheck.digest,
      },
      installations: rows,
    },
    verified ? 0 : 1,
  ];
}

async function uninstall(options) {
  const sourceDigest = await treeDigest(BUNDLED_SKILL);
  const { canonical } = installationPaths(options.home);
  const rows = [];
  let conflict = false;
  for (const row of targetRows(options.home, options.platforms)) {
    const check = await targetState(row.target, canonical, sourceDigest);
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
    console.log(`${row.platform}: ${row.action} ${row.target}`);
  }
}

async function main() {
  const wantsJson = process.argv.includes("--json");
  try {
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
    return 2;
  }
}

process.exitCode = await main();
