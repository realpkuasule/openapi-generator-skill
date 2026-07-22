import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { lstat, mkdir, readFile, rm } from "node:fs/promises";
import { basename, dirname, join } from "node:path";

import { atomicWriteJson, readJsonIfExists } from "./atomic-files.mjs";
import { canonicalSha256 } from "./canonical-json.mjs";
import {
  expectedAutomationBinding,
  expectedSyncBinding,
  qualifyPythonRuntime,
} from "./config.mjs";
import { checkUsageDue } from "./due.mjs";
import { synchronizeUsage } from "./git-sync.mjs";
import { sendMaintenanceNotification, writeMaintenanceReport } from "./maintenance-report.mjs";
import { assertSafeUsagePath, configuredStateRoot, usageStatePaths } from "./paths.mjs";


const execFileAsync = promisify(execFile);


async function pathInfo(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}


function normalizedSync(value) {
  return {
    status: value.status,
    synchronized: value.synchronized,
    pending: value.pending,
    reason_code: value.reason_code ?? null,
  };
}


function cycleResult({
  cycleId,
  status,
  periodId = null,
  inputSha256 = null,
  authorizationSha256,
  sync,
  findingCount = 0,
  analysisStatus = "not-run",
  reportId = null,
  notification = "not-required",
  attempt = 0,
}) {
  return {
    cycle_version: 1,
    cycle_id: cycleId,
    status,
    period_id: periodId,
    input_sha256: inputSha256,
    authorization_sha256: authorizationSha256,
    sync: normalizedSync(sync),
    finding_count: findingCount,
    analysis_status: analysisStatus,
    report_id: reportId,
    notification,
    attempt,
  };
}


function analyzerArguments({ options, config, bundlePath, outputPath, resumePath = null }) {
  const arguments_ = [
    "--findings",
    bundlePath,
    "--adapter",
    options.adapter,
    "--credential-mode",
    config.analysis.credential_mode,
    "--secondary-adapter",
    options.secondaryAdapter,
    "--output",
    outputPath,
    "--max-events",
    String(config.analysis.max_events),
    "--timeout-seconds",
    String(config.analysis.timeout_seconds),
    "--rss-warning-mb",
    String(config.analysis.warning_rss_mb),
    "--rss-hard-mb",
    String(config.analysis.hard_rss_mb),
  ];
  if (options.now) arguments_.push("--now", options.now);
  if (resumePath) {
    arguments_.push("--resume-analysis", resumePath);
  } else if (options.fakeResponse) {
    arguments_.push("--fake-response", options.fakeResponse);
  }
  if (!resumePath && options.fakePlatform) {
    arguments_.push("--fake-platform", options.fakePlatform);
  }
  if (options.secondaryFakeResponse) {
    arguments_.push("--secondary-fake-response", options.secondaryFakeResponse);
  }
  if (options.secondaryFakePlatform) {
    arguments_.push("--secondary-fake-platform", options.secondaryFakePlatform);
  }
  return arguments_;
}


async function executeAnalyzer({ executable, script, arguments_, cwd, timeoutSeconds }) {
  try {
    const result = await execFileAsync(executable, [script, ...arguments_], {
      cwd,
      env: process.env,
      timeout: 2 * timeoutSeconds * 1000 + 30_000,
      maxBuffer: 1024 * 1024,
    });
    return { exitCode: 0, stdout: result.stdout, stderr: result.stderr };
  } catch (error) {
    const exitCode = Number.isInteger(error.code) ? error.code : 2;
    return { exitCode, stdout: error.stdout || "", stderr: error.stderr || "" };
  }
}


function terminalStatus(exitCode) {
  return exitCode === 1 ? "failed" : "blocked";
}


function terminalReason(exitCode, exhausted = false) {
  if (exhausted) return "retry-exhausted";
  return exitCode === 1 ? "analyzer-failed" : "analyzer-blocked";
}


async function loadAnalysis(path) {
  const info = await pathInfo(path);
  if (!info) return null;
  if (!info.isFile() || info.isSymbolicLink()) throw new Error("Maintenance analysis output is unsafe.");
  return JSON.parse(await readFile(path, "utf8"));
}


async function withCycleLock(stateRoot, lockPath, callback) {
  await assertSafeUsagePath(stateRoot, lockPath);
  await mkdir(dirname(lockPath), { recursive: true, mode: 0o700 });
  try {
    await mkdir(lockPath, { mode: 0o700 });
  } catch (error) {
    if (error.code === "EEXIST") throw new Error("Maintenance cycle is already running.");
    throw error;
  }
  try {
    return await callback();
  } finally {
    await rm(lockPath, { recursive: true, force: true });
  }
}


export async function runMaintenanceCycle({
  home,
  config,
  options,
  packageVersion,
  skillSha256,
  packageRoot,
  notifier = sendMaintenanceNotification,
}) {
  const expectedAuthorization = expectedAutomationBinding(config, packageVersion, skillSha256);
  const preflightId = `cycle-${canonicalSha256({
    authorization: expectedAuthorization,
    stage: "preflight",
  }).slice(0, 16)}`;
  const preflightSync = {
    status: "blocked",
    synchronized: 0,
    pending: 0,
    reason_code: "authorization-stale",
  };
  if (
    !config.local_collection_enabled ||
    !config.coordinator ||
    !config.analysis.enabled ||
    config.analysis.credential_mode !== "active-cli-session" ||
    !config.analysis.authorization ||
    config.analysis.authorization.binding_sha256 !== expectedAuthorization ||
    !config.sync_enabled ||
    !config.sync_authorization ||
    config.sync_authorization.binding_sha256 !== expectedSyncBinding(config)
  ) {
    return {
      result: cycleResult({
        cycleId: preflightId,
        status: "blocked",
        authorizationSha256: expectedAuthorization,
        sync: preflightSync,
      }),
      exitCode: 2,
    };
  }

  try {
    const runtime = await qualifyPythonRuntime(config.analysis.python_runtime.executable);
    if (canonicalSha256(runtime) !== canonicalSha256(config.analysis.python_runtime)) {
      preflightSync.reason_code = "python-runtime-stale";
      return {
        result: cycleResult({
          cycleId: preflightId,
          status: "blocked",
          authorizationSha256: expectedAuthorization,
          sync: preflightSync,
        }),
        exitCode: 2,
      };
    }
  } catch (_error) {
    preflightSync.reason_code = "python-runtime-unavailable";
    return {
      result: cycleResult({
        cycleId: preflightId,
        status: "blocked",
        authorizationSha256: expectedAuthorization,
        sync: preflightSync,
      }),
      exitCode: 2,
    };
  }

  const stateRoot = configuredStateRoot(config, home, options.stateRoot);
  const paths = usageStatePaths(stateRoot, config.device_alias);
  return withCycleLock(stateRoot, join(paths.locks, "maintenance-cycle.lock"), async () => {
    const sync = await synchronizeUsage({ home, config, options });
    if (sync.status !== "ok") {
      return {
        result: cycleResult({
          cycleId: preflightId,
          status: "sync-blocked",
          authorizationSha256: expectedAuthorization,
          sync,
        }),
        exitCode: 2,
      };
    }

    const due = await checkUsageDue({
      home,
      config,
      options: { ...options, includePrivateBundle: true },
    });
    const cycleId = `cycle-${canonicalSha256({
      period_id: due.period_id,
      input_sha256: due.input_sha256,
      authorization_sha256: expectedAuthorization,
    }).slice(0, 16)}`;
    if (due.finding_count === 0) {
      return {
        result: cycleResult({
          cycleId,
          status: "no-findings",
          periodId: due.period_id,
          inputSha256: due.input_sha256,
          authorizationSha256: expectedAuthorization,
          sync,
        }),
        exitCode: 0,
      };
    }
    if (!due.private_bundle) {
      return {
        result: cycleResult({
          cycleId,
          status: "blocked",
          periodId: due.period_id,
          inputSha256: due.input_sha256,
          authorizationSha256: expectedAuthorization,
          sync,
          findingCount: due.finding_count,
        }),
        exitCode: 2,
      };
    }

    const year = due.period_id.slice(0, 4);
    const checkpointPath = join(paths.checkpoints, "maintenance", `${cycleId}.json`);
    const bundlePath = join(paths.analysisBundles, year, `${cycleId}.json`);
    for (const path of [checkpointPath, bundlePath]) await assertSafeUsagePath(stateRoot, path);
    const stored = await readJsonIfExists(checkpointPath);
    const checkpoint = stored || {
      checkpoint_version: 1,
      cycle_id: cycleId,
      period_id: due.period_id,
      input_sha256: due.input_sha256,
      authorization_sha256: expectedAuthorization,
      bundle_sha256: canonicalSha256(due.private_bundle),
      attempts: [],
      terminal_report_id: null,
      terminal_notification: "not-required",
    };
    if (
      checkpoint.checkpoint_version !== 1 ||
      checkpoint.cycle_id !== cycleId ||
      checkpoint.period_id !== due.period_id ||
      checkpoint.input_sha256 !== due.input_sha256 ||
      checkpoint.authorization_sha256 !== expectedAuthorization ||
      checkpoint.bundle_sha256 !== canonicalSha256(due.private_bundle) ||
      !Array.isArray(checkpoint.attempts)
    ) {
      throw new Error("Maintenance cycle checkpoint integrity validation failed.");
    }
    if (checkpoint.terminal_report_id) {
      return {
        result: cycleResult({
          cycleId,
          status: "duplicate",
          periodId: due.period_id,
          inputSha256: due.input_sha256,
          authorizationSha256: expectedAuthorization,
          sync,
          findingCount: due.finding_count,
          analysisStatus: checkpoint.attempts.at(-1)?.status || "blocked",
          reportId: checkpoint.terminal_report_id,
          notification: checkpoint.terminal_notification,
          attempt: checkpoint.attempts.length,
        }),
        exitCode: 0,
      };
    }

    await atomicWriteJson(bundlePath, due.private_bundle);
    const attempt = checkpoint.attempts.length + 1;
    const analysisPath = join(paths.analyses, year, `${cycleId}-attempt-${attempt}.json`);
    await assertSafeUsagePath(stateRoot, analysisPath);
    const previous = checkpoint.attempts.at(-1);
    const resumePath =
      previous?.status === "blocked" && previous.analysis_file && options.adapter === "codex"
        ? join(paths.analyses, year, basename(previous.analysis_file))
        : null;
    const executable = config.analysis.python_runtime.executable;
    const analyzerScript = join(packageRoot, "scripts", "maintenance", "analyze_usage.py");
    const startedAt = options.now || new Date().toISOString();
    const analyzer = await executeAnalyzer({
      executable,
      script: analyzerScript,
      arguments_: analyzerArguments({
        options,
        config,
        bundlePath,
        outputPath: analysisPath,
        resumePath,
      }),
      cwd: packageRoot,
      timeoutSeconds: config.analysis.timeout_seconds,
    });
    const analysis = await loadAnalysis(analysisPath);
    const status = analyzer.exitCode === 0 ? "completed" : terminalStatus(analyzer.exitCode);
    checkpoint.attempts.push({
      attempt,
      status,
      exit_code: analyzer.exitCode,
      analysis_file: analysis ? basename(analysisPath) : null,
      analysis_sha256: analysis ? canonicalSha256(analysis) : null,
    });

    const exhausted = analyzer.exitCode !== 0 && attempt >= config.analysis.max_attempts_per_input;
    if (analyzer.exitCode !== 0 && !exhausted) {
      await atomicWriteJson(checkpointPath, checkpoint);
      return {
        result: cycleResult({
          cycleId,
          status,
          periodId: due.period_id,
          inputSha256: due.input_sha256,
          authorizationSha256: expectedAuthorization,
          sync,
          findingCount: due.finding_count,
          analysisStatus: status,
          attempt,
        }),
        exitCode: analyzer.exitCode === 1 ? 1 : 2,
      };
    }

    const reportStatus = analyzer.exitCode === 0 ? "completed" : terminalStatus(analyzer.exitCode);
    const { report } = await writeMaintenanceReport({
      stateRoot,
      reportsRoot: paths.reports,
      value: {
        cycle_id: cycleId,
        status: reportStatus,
        period_id: due.period_id,
        input_sha256: due.input_sha256,
        authorization_sha256: expectedAuthorization,
        attempt,
        started_at: startedAt,
        finished_at: new Date().toISOString(),
        finding_ids: due.findings.map((finding) => finding.finding_id).sort(),
        analysis,
        reason_code: analyzer.exitCode === 0 ? null : terminalReason(analyzer.exitCode, exhausted),
      },
    });
    const notification = await notifier(config.analysis.notification, report.status);
    checkpoint.terminal_report_id = report.report_id;
    checkpoint.terminal_notification = notification;
    await atomicWriteJson(checkpointPath, checkpoint);
    const resultStatus = exhausted
      ? "retry-exhausted"
      : report.status === "completed"
        ? "completed"
        : report.status;
    const exitCode =
      analyzer.exitCode !== 0
        ? analyzer.exitCode === 1
          ? 1
          : 2
        : report.status === "completed"
          ? 0
          : 2;
    return {
      result: cycleResult({
        cycleId,
        status: resultStatus,
        periodId: due.period_id,
        inputSha256: due.input_sha256,
        authorizationSha256: expectedAuthorization,
        sync,
        findingCount: due.finding_count,
        analysisStatus: report.status,
        reportId: report.report_id,
        notification,
        attempt,
      }),
      exitCode,
    };
  });
}
