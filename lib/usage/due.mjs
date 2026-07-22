import { join } from "node:path";

import { atomicWriteJson, readJsonIfExists } from "./atomic-files.mjs";
import { canonicalSha256 } from "./canonical-json.mjs";
import { assertSafeUsagePath, usageStatePaths } from "./paths.mjs";
import { buildUsageSummary } from "./summarize.mjs";
import { outboundEnvelope } from "./redact.mjs";

function yearFromPeriod(periodId) {
  return periodId.slice(0, 4);
}

async function queueAggregates(stateRoot, paths, summary, findings) {
  const summaryOutbound = join(paths.outbound, `summary-${summary.period_id}.json`);
  const findingsOutbound = join(paths.outbound, `findings-${summary.period_id}.json`);
  for (const path of [summaryOutbound, findingsOutbound]) {
    await assertSafeUsagePath(stateRoot, path);
  }
  await atomicWriteJson(summaryOutbound, outboundEnvelope("usage-summary", summary));
  await atomicWriteJson(
    findingsOutbound,
    outboundEnvelope("maintenance-findings", {
      schema_version: 1,
      period_id: summary.period_id,
      input_sha256: summary.input_sha256,
      findings,
    }),
  );
}

function boundedBundle(findings, sanitizedEvents, maxEvents) {
  return {
    findings,
    sanitized_events: sanitizedEvents.slice(-maxEvents),
  };
}

async function loadAcceptedBundle({ stateRoot, path, expectedSha256 }) {
  await assertSafeUsagePath(stateRoot, path);
  const bundle = await readJsonIfExists(path);
  if (!bundle || canonicalSha256(bundle) !== expectedSha256) {
    throw new Error("Due analysis bundle integrity validation failed.");
  }
  return bundle;
}

export async function checkUsageDue({ home, config, options }) {
  if (!config.local_collection_enabled) throw new Error("Local collection is disabled.");
  if (!config.coordinator) throw new Error("Only the configured coordinator may run due checks.");
  const { summary, findings, sanitizedEvents, stateRoot } = await buildUsageSummary({
    home,
    config,
    options: { ...options, period: "iso-week" },
  });
  const paths = usageStatePaths(stateRoot, config.device_alias);
  const year = yearFromPeriod(summary.period_id);
  const summaryPath = join(paths.summaries, year, `${summary.period_id}.json`);
  const findingsPath = join(paths.findings, year, `${summary.period_id}.json`);
  const checkpointPath = join(paths.checkpoints, "due", `${summary.period_id}.json`);
  const bundlePath = join(
    paths.analysisBundles,
    year,
    `${summary.period_id}-${summary.input_sha256}.json`,
  );
  for (const path of [summaryPath, findingsPath, checkpointPath]) {
    await assertSafeUsagePath(stateRoot, path);
  }

  const checkpoint = await readJsonIfExists(checkpointPath);
  if (checkpoint !== null) {
    const acceptedSummary = await readJsonIfExists(summaryPath);
    const acceptedFindings = await readJsonIfExists(findingsPath);
    if (
      !acceptedSummary ||
      !Array.isArray(acceptedFindings) ||
      checkpoint.summary_sha256 !== canonicalSha256(acceptedSummary) ||
      checkpoint.findings_sha256 !== canonicalSha256(acceptedFindings)
    ) {
      throw new Error("Due checkpoint integrity validation failed.");
    }
    let bundle = null;
    if (acceptedFindings.length > 0 && checkpoint.bundle_sha256) {
      const acceptedBundlePath = join(
        paths.analysisBundles,
        yearFromPeriod(acceptedSummary.period_id),
        `${acceptedSummary.period_id}-${acceptedSummary.input_sha256}.json`,
      );
      bundle = await loadAcceptedBundle({
        stateRoot,
        path: acceptedBundlePath,
        expectedSha256: checkpoint.bundle_sha256,
      });
    }
    await queueAggregates(stateRoot, paths, acceptedSummary, acceptedFindings);
    return {
      status: "not-due",
      period_id: acceptedSummary.period_id,
      input_sha256: acceptedSummary.input_sha256,
      eligible_for_analysis: acceptedFindings.length > 0,
      finding_count: acceptedFindings.length,
      summary: acceptedSummary,
      findings: acceptedFindings,
      ...(options.includePrivateBundle ? { private_bundle: bundle } : {}),
    };
  }

  const bundle = findings.length > 0
    ? boundedBundle(findings, sanitizedEvents, config.analysis.max_events)
    : null;
  await atomicWriteJson(summaryPath, summary);
  await atomicWriteJson(findingsPath, findings);
  if (bundle) {
    await assertSafeUsagePath(stateRoot, bundlePath);
    await atomicWriteJson(bundlePath, bundle);
  }
  await atomicWriteJson(checkpointPath, {
    checkpoint_version: 1,
    period_id: summary.period_id,
    input_sha256: summary.input_sha256,
    summary_sha256: canonicalSha256(summary),
    findings_sha256: canonicalSha256(findings),
    bundle_sha256: bundle ? canonicalSha256(bundle) : null,
  });
  await queueAggregates(stateRoot, paths, summary, findings);
  return {
    status: findings.length > 0 ? "due" : "no-findings",
    period_id: summary.period_id,
    input_sha256: summary.input_sha256,
    eligible_for_analysis: findings.length > 0,
    finding_count: findings.length,
    summary,
    findings,
    ...(options.includePrivateBundle ? { private_bundle: bundle } : {}),
  };
}
