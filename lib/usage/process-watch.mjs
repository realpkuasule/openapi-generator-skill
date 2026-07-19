import { execFile } from "node:child_process";
import { promisify } from "node:util";


const execFileAsync = promisify(execFile);


function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}


export function supportsProcessTreeRss(platform = process.platform) {
  return platform !== "win32";
}


export async function processTreeRssMb(rootPid) {
  if (!supportsProcessTreeRss()) return null;
  const { stdout } = await execFileAsync("ps", ["-axo", "pid=,ppid=,rss="], {
    maxBuffer: 4 * 1024 * 1024,
    env: {
      PATH: process.env.PATH,
      LANG: process.env.LANG || "C",
      LC_ALL: "C",
    },
  });
  const rows = stdout
    .split(/\r?\n/)
    .map((line) => line.trim().split(/\s+/).map(Number))
    .filter(([pid, parent, rss]) =>
      Number.isInteger(pid) && Number.isInteger(parent) && Number.isFinite(rss),
    )
    .map(([pid, parent, rss]) => ({ pid, parent, rss }));
  const owned = new Set([rootPid]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const row of rows) {
      if (owned.has(row.parent) && !owned.has(row.pid)) {
        owned.add(row.pid);
        changed = true;
      }
    }
  }
  const kib = rows
    .filter((row) => owned.has(row.pid))
    .reduce((total, row) => total + row.rss, 0);
  return kib / 1024;
}


function posixGroupExists(pid) {
  try {
    process.kill(-pid, 0);
    return true;
  } catch (error) {
    return error.code === "EPERM";
  }
}


export async function reclaimProcessGroup(child, graceMs = 500) {
  if (process.platform === "win32") {
    try {
      await execFileAsync("taskkill", ["/PID", String(child.pid), "/T", "/F"]);
    } catch (_error) {
      // A completed child has no process tree left to reclaim.
    }
    return child.exitCode !== null || child.signalCode !== null;
  }
  if (!posixGroupExists(child.pid)) return true;
  try {
    process.kill(-child.pid, "SIGTERM");
  } catch (_error) {
    // The group may have exited between the existence check and the signal.
  }
  await delay(graceMs);
  if (posixGroupExists(child.pid)) {
    try {
      process.kill(-child.pid, "SIGKILL");
    } catch (_error) {
      // The group may have exited between checks.
    }
    await delay(50);
  }
  return !posixGroupExists(child.pid);
}
