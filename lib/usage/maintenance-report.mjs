import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { join } from "node:path";

import { atomicWrite, atomicWriteJson } from "./atomic-files.mjs";
import { canonicalSha256 } from "./canonical-json.mjs";
import { assertSafeUsagePath } from "./paths.mjs";


const execFileAsync = promisify(execFile);
const PRIVATE_CONTENT_PATTERN = /(?:\/Users\/|\/home\/|[A-Za-z]:\\|https?:\/\/|git@|-----BEGIN [A-Z ]+PRIVATE KEY-----|\b(?:sk|ghp|github_pat)-[A-Za-z0-9_-]{12,}|\bCANARY\b|CANARY[_-]|\b(?:api[_-]?key|access[_-]?token|password|secret)\b\s*[:=]\s*["']?[A-Za-z0-9_./+\-]{8,})/i;


export function maintenanceNotification(status, _privateContent = null) {
  const messages = {
    completed: "Unattended analysis completed. Open the private report.",
    blocked: "Unattended analysis was blocked. Open the private report.",
    failed: "Unattended analysis failed. Open the private report.",
  };
  return {
    title: "OpenAPI Engineering maintenance",
    message: messages[status] || messages.failed,
  };
}


function singleLine(value) {
  return String(value).replace(/[\r\n]+/g, " ").slice(0, 500);
}


function markdown(report) {
  const lines = [
    "# OpenAPI Engineering private maintenance report",
    "",
    `Status: ${report.status}`,
    "",
    `Period: ${report.period_id}`,
    "",
    `Attempt: ${report.attempt}`,
    "",
    `Findings: ${report.finding_ids.join(", ")}`,
    "",
  ];
  if (report.reason_code) lines.push(`Reason: ${report.reason_code}`, "");
  if (report.analysis) {
    lines.push(`Confidence: ${report.analysis.confidence}`, "", "## Candidate causes", "");
    for (const cause of report.analysis.candidate_causes) {
      lines.push(`- ${singleLine(cause)}`);
    }
    lines.push("", "## Unverified", "");
    if (report.analysis.unverified.length === 0) lines.push("- None reported.");
    for (const item of report.analysis.unverified) lines.push(`- ${singleLine(item)}`);
    lines.push("", "## Analyzer sequence", "");
    for (const analyzer of report.analysis.analyzer_sequence) {
      lines.push(`- ${analyzer.platform}: ${analyzer.status}`);
    }
  } else {
    lines.push("No Schema-valid semantic analysis was produced.");
  }
  lines.push("");
  return `${lines.join("\n")}\n`;
}


function safeAnalysis(analysis) {
  if (analysis === null) return { analysis: null, rejected: false };
  const content = JSON.stringify(analysis);
  if (PRIVATE_CONTENT_PATTERN.test(content)) return { analysis: null, rejected: true };
  return { analysis: structuredClone(analysis), rejected: false };
}


export async function writeMaintenanceReport({ stateRoot, reportsRoot, value }) {
  const sanitized = safeAnalysis(value.analysis ?? null);
  const core = {
    ...value,
    status: sanitized.rejected ? "blocked" : value.status,
    analysis: sanitized.analysis,
    reason_code: sanitized.rejected ? "report-invalid" : value.reason_code,
  };
  const reportId = `report-${canonicalSha256(core).slice(0, 16)}`;
  const report = { report_version: 1, report_id: reportId, ...core };
  const year = report.period_id.slice(0, 4);
  const jsonPath = join(reportsRoot, year, `${reportId}.json`);
  const markdownPath = join(reportsRoot, year, `${reportId}.md`);
  for (const path of [jsonPath, markdownPath]) await assertSafeUsagePath(stateRoot, path);
  const rendered = markdown(report);
  if (PRIVATE_CONTENT_PATTERN.test(rendered)) {
    throw new Error("Private maintenance report failed the content boundary.");
  }
  await atomicWriteJson(jsonPath, report);
  await atomicWrite(markdownPath, rendered, 0o600);
  return { report, jsonPath, markdownPath };
}


export async function sendMaintenanceNotification(policy, status, execute = execFileAsync) {
  if (policy === "none") return "skipped";
  if (policy !== "macos" || process.platform !== "darwin") return "skipped";
  const notification = maintenanceNotification(status);
  const script = `display notification "${notification.message}" with title "${notification.title}"`;
  try {
    await execute("/usr/bin/osascript", ["-e", script], {
      env: { PATH: "/usr/bin:/bin", LANG: "C", LC_ALL: "C" },
      timeout: 10_000,
      maxBuffer: 16 * 1024,
    });
    return "sent";
  } catch (_error) {
    return "failed";
  }
}
