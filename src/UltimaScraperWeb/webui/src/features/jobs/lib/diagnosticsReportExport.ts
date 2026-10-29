import type { JobRouteLookupStat } from '../../../api/types/jobs';
import type { HistoricalComparisonResult } from './historicalComparison';
import { formatMPSRefillReport } from './mpsRefillReport';
import { getServicePhases, type JobDiagnosticsTelemetry } from './useJobDiagnosticsTelemetry';

export const ROUTE_LOOKUP_DISPLAY_LIMIT = 20;

export function getRouteLookupRows(
  stats: Record<string, JobRouteLookupStat> | null | undefined,
): Array<[string, JobRouteLookupStat]> {
  return Object.entries(stats ?? {})
    .filter(([, route]) => route.route_attempts > 0)
    .sort(([, left], [, right]) =>
      (right.mean_lookup_ms ?? -1) - (left.mean_lookup_ms ?? -1),
    );
}

export function formatRouteLookupOutcomes(route: JobRouteLookupStat): string {
  const rawCounts = [
    route.lookup_found_count,
    route.lookup_not_found_count,
    route.lookup_error_count,
    route.lookup_timeout_count,
    route.lookup_cancelled_count,
    route.guest_init_failure_count,
    route.guest_init_cancelled_count,
  ];
  if (rawCounts.every((count) => count == null)) return 'Unavailable';

  const counts = rawCounts.map((count) => Math.max(0, count ?? 0));
  const outcomeCount = counts.reduce((sum, count) => sum + count, 0);
  const coverage = outcomeCount === route.route_attempts
    ? outcomeCount.toLocaleString()
    : `${outcomeCount.toLocaleString()}/${route.route_attempts.toLocaleString()}`;
  return `${coverage}; ${counts.map((count) => count.toLocaleString()).join('/')}`;
}

export function generateMarkdownReport(
  telemetry: JobDiagnosticsTelemetry,
  jobName: string,
  jobId: string,
  site: string,
  comparison?: HistoricalComparisonResult | null,
): string {
  const {
    finalSummary,
    latencyPercentiles,
    proxyCapacity,
    httpDistribution,
    proxyAnomalies,
    bottleneckAnalysis,
  } = telemetry;
  const routeSlotsLabel = proxyCapacity.totalRoutes > 0
    ? proxyCapacity.totalRoutes : 'Unavailable';
  const throughputUnit =
    telemetry.quality?.throughputUnit ??
    finalSummary.throughputUnit ??
    telemetry.throughput.throughputUnit ??
    'items';
  const throughputLabel = throughputUnit === 'items' ? 'items/s' : 'tasks/s';
  const sampleNoticeParts: string[] = [];
  if (telemetry.quality && telemetry.quality.totalTaskCount > 0 && !telemetry.quality.isCompleteTaskSample) {
    sampleNoticeParts.push(
      `Loaded ${telemetry.quality.loadedTaskCount.toLocaleString()} of ${telemetry.quality.totalTaskCount.toLocaleString()} task details; percentile, peak, error-category, and proxy route-outlier values are sample-scoped.`,
    );
  }
  if (finalSummary.runtimeTelemetryComplete) {
    sampleNoticeParts.push(
      'Mean duration, phase timing, concurrency, route occupancy, and per-route user lookup timing use the full-job aggregate.',
    );
  } else {
    sampleNoticeParts.push(
      'Runtime telemetry is incomplete; occupancy and efficiency are model estimates from lifetime throughput and sampled latency, not measured time-weighted values.',
    );
  }
  const sampleNotice = sampleNoticeParts.join(' ');
  const badProxies = proxyAnomalies.filter((p) => p.status !== 'healthy');
  const routeLookupRows = getRouteLookupRows(finalSummary.routeLookupStats);
  const observedProxies = proxyAnomalies.filter((p) => p.totalAttempts > 0);
  const observedProxiesWithoutFailures = observedProxies.filter(
    (p) => p.failures === 0 && p.rateLimits429 === 0 && p.timeouts === 0,
  );
  const proxiesWithLatency = proxyAnomalies.filter((p) => p.avgLatencySec > 0);
  const averageProxyLatencySec = proxiesWithLatency.length > 0
    ? Number(
        (
          proxiesWithLatency.reduce((total, proxy) => total + proxy.avgLatencySec, 0) /
          proxiesWithLatency.length
        ).toFixed(2),
      )
    : null;

  const diag = telemetry.throughputDiagnostics ?? {
    theoreticalProxyMaxItemsPerSec:
      finalSummary.theoreticalProxyMaxItemsPerSec ?? finalSummary.theoreticalMaxItemsPerSec,
    theoreticalWorkerMaxItemsPerSec:
      finalSummary.theoreticalWorkerMaxItemsPerSec ?? finalSummary.theoreticalMaxItemsPerSec,
    governingCeilingItemsPerSec: finalSummary.theoreticalMaxItemsPerSec,
    governingBottleneck: 'proxy_capacity' as const,
    activeConcurrency: finalSummary.avgActiveConcurrency,
    idleProxyRoutes: Math.max(0, proxyCapacity.totalRoutes - Math.round(finalSummary.avgActiveConcurrency)),
    idleProxyPercent:
      proxyCapacity.totalRoutes > 0
        ? Number(
            (
              (Math.max(0, proxyCapacity.totalRoutes - Math.round(finalSummary.avgActiveConcurrency)) /
                proxyCapacity.totalRoutes) *
              100
            ).toFixed(1),
          )
        : 0,
    proxyUtilizationPercent: finalSummary.avgActiveProxyUtilization,
    workerUtilizationPercent: 100,
    workerPoolSize: 8,
    workerConcurrencyDemand: proxyCapacity.totalRoutes > 0 ? proxyCapacity.totalRoutes : 8 * 16,
    targetConcurrency: proxyCapacity.totalRoutes > 0 ? Math.ceil(proxyCapacity.totalRoutes / 8) : 16,
    latencySpreadRatio:
      latencyPercentiles.p50 > 0
        ? Number((latencyPercentiles.p95 / latencyPercentiles.p50).toFixed(2))
        : 1.0,
    tailLatencyDragPercent: 0,
    peakToAvgRatio:
      finalSummary.overallAvgItemsPerSec > 0
        ? Number(
            (finalSummary.peakItemsPerSec / finalSummary.overallAvgItemsPerSec).toFixed(2),
          )
        : 1.0,
    lossFactors: [],
  };
  const normalizedOutcome = finalSummary.jobOutcome.toLowerCase();
  const completedOutcome = ['completed', 'complete', 'succeeded', 'success'].includes(
    normalizedOutcome,
  );
  const failedTaskCount = finalSummary.failedTaskCount ?? telemetry.errorVelocity.totalErrors;
  const terminalTaskCount = Math.min(
    telemetry.totalTasksCount,
    telemetry.completedTasksCount + failedTaskCount,
  );
  const successPercent = (
    (telemetry.completedTasksCount / Math.max(1, telemetry.totalTasksCount)) * 100
  ).toFixed(1);
  const terminalPercent = (
    (terminalTaskCount / Math.max(1, telemetry.totalTasksCount)) * 100
  ).toFixed(1);
  const failureSummary = completedOutcome
    ? `${failedTaskCount.toLocaleString()} task failure(s); job completed`
    : finalSummary.terminationReason
      ? `Halted: ${finalSummary.terminationReason}`
      : `${failedTaskCount.toLocaleString()} task failure(s)`;
  const writerServiceDominant =
    (finalSummary.meanWriterSec ?? 0) > (finalSummary.meanHandlerSec ?? 0);
  const fmtSetup = (name: string): string => {
    const entry = finalSummary.setupSubphases?.[name];
    return entry?.mean_ms != null ? `${entry.mean_ms.toFixed(2)}ms` : 'Unavailable';
  };
  const fmtSetupCount = (name: string): string =>
    (finalSummary.setupSubphases?.[name]?.count ?? 0).toLocaleString();
  const fmtSetupObs = (name: string): string => {
    const value = finalSummary.setupSubphases?.[name]?.mean_ms_per_observation;
    return value != null ? `${value.toFixed(2)}ms` : 'Unavailable';
  };
  const writerPhaseLabel =
    writerServiceDominant
    && (finalSummary.dominantWriterSubphase === 'Writer Queue'
      || finalSummary.dominantWriterSubphase === 'Producer Admission')
      ? 'Writer Queue / Admission Backpressure'
      : 'Durable Writer Wait';
  const servicePhases = getServicePhases(finalSummary);
  const [dominantServicePhase, dominantServiceSeconds]: [string, number] = finalSummary.runtimeTelemetryComplete
    ? servicePhases.sort((a, b) => b[1] - a[1])[0] ?? ['Unavailable', 0]
    : ['Unavailable', 0];
  // Subphases only exist for the phases that actually break down further.
  const dominantServiceSubphase = dominantServicePhase === 'Worker Setup'
    ? finalSummary.dominantSetupSubphase
    : dominantServicePhase === writerPhaseLabel
      ? finalSummary.dominantWriterSubphase
      : dominantServicePhase === 'Handler / Upstream Work'
        ? finalSummary.dominantHandlerSubphase
        : null;
  const governingCapacityLabel =
    diag.governingBottleneck === 'proxy_capacity' ? 'proxy-route capacity' : 'worker-slot capacity';

  const totalHttp = Math.max(1, httpDistribution.totalObserved);
  const pct200 = ((httpDistribution.ok200 / totalHttp) * 100).toFixed(1);
  const pct429 = ((httpDistribution.rateLimit429 / totalHttp) * 100).toFixed(1);
  const pct403 = ((httpDistribution.forbidden403 / totalHttp) * 100).toFixed(1);
  const pct404 = ((httpDistribution.notFound404 / totalHttp) * 100).toFixed(1);
  const pct5xx = ((httpDistribution.serverError5xx / totalHttp) * 100).toFixed(1);
  const pctTimeout = ((httpDistribution.timeoutErrors / totalHttp) * 100).toFixed(1);
  let historicalSection = '';
  if (comparison?.hasBaseline && comparison.baselineJob) {
    historicalSection = `
## 6. Historical Performance Regression Comparison (vs Baseline: ${comparison.baselineJob.jobName} - \`${comparison.baselineJob.jobId}\`)
- **Baseline Executed:** ${comparison.baselineJob.createdAt} | **Baseline Status:** ${comparison.baselineJob.status.toUpperCase()}
- **Throughput Delta:** ${comparison.throughputComparable === false ? 'Unavailable (item/task units differ)' : `${comparison.currentRun.avgItemsPerSec} ${throughputLabel} vs ${comparison.baselineJob.avgItemsPerSec} ${throughputLabel} (${comparison.deltas.throughputDeltaPercent >= 0 ? '+' : ''}${comparison.deltas.throughputDeltaPercent}%)`}
- **Duration Delta:** ${comparison.currentRun.isProjectedDuration ? `~${comparison.currentRun.durationFormatted} (projected)` : comparison.currentRun.durationFormatted} vs ${comparison.baselineJob.durationFormatted} (${comparison.deltas.durationComparable === false ? 'In progress' : `${comparison.deltas.durationDeltaPercent >= 0 ? '+' : ''}${comparison.deltas.durationDeltaPercent}%`})
- **Failure Rate Delta:** ${comparison.currentRun.failureRatePercent}% vs ${comparison.baselineJob.failureRatePercent}% (${comparison.deltas.failureRateDeltaPercent >= 0 ? '+' : ''}${comparison.deltas.failureRateDeltaPercent}%)
- **Regression Classification:** ${comparison.deltas.status.toUpperCase()} - ${comparison.deltas.verdictTitle}
- **Analysis:** ${comparison.deltas.verdictMessage}
${comparison.deltas.keyDifferences.map((d) => `- ${d}`).join('\n')}

### Baseline vs Current Run Comparison Table:
| Performance Vector | Current Run (\`${jobId}\`) | Baseline Run (\`${comparison.baselineJob.jobId}\`) | Delta | Classification |
| :--- | :--- | :--- | :--- | :--- |
| **Average Throughput** | ${comparison.throughputComparable === false ? 'Unavailable' : `${comparison.currentRun.avgItemsPerSec} ${throughputLabel}`} | ${comparison.throughputComparable === false ? 'Incompatible unit' : `${comparison.baselineJob.avgItemsPerSec} ${throughputLabel}`} | ${comparison.throughputComparable === false ? '-' : `${comparison.deltas.throughputDeltaPercent >= 0 ? '+' : ''}${comparison.deltas.throughputDeltaPercent}%`} | \`${comparison.deltas.status.toUpperCase()}\` |
| **Total Duration** | ${comparison.currentRun.isProjectedDuration ? `~${comparison.currentRun.durationFormatted} (est.)` : comparison.currentRun.durationFormatted} | ${comparison.baselineJob.durationFormatted} | ${comparison.deltas.durationComparable === false ? 'In progress' : `${comparison.deltas.durationDeltaPercent >= 0 ? '+' : ''}${comparison.deltas.durationDeltaPercent}%`} | - |
| **Task Failure Rate** | ${comparison.currentRun.failureRatePercent}% | ${comparison.baselineJob.failureRatePercent}% | ${comparison.deltas.failureRateDeltaPercent >= 0 ? '+' : ''}${comparison.deltas.failureRateDeltaPercent}% | - |
| **Completed Tasks** | ${comparison.currentRun.completedTasks.toLocaleString()} | ${comparison.baselineJob.completedTasks.toLocaleString()} | ${comparison.deltas.completedTasksDelta >= 0 ? '+' : ''}${comparison.deltas.completedTasksDelta.toLocaleString()} tasks | - |
`;
  }

  return `# Diagnostic Final Report: ${jobName}
**Job ID:** \`${jobId}\` | **Site:** ${site} | **Outcome:** ${finalSummary.jobOutcome.toUpperCase()}
**Runtime Duration:** ${finalSummary.totalDurationFormatted} | **Throughput Avg:** ${finalSummary.overallAvgItemsPerSec} ${throughputLabel} (Peak observed completion-publication burst: ${finalSummary.peakItemsPerSec} ${throughputLabel})
**Duration Authority:** ${finalSummary.durationSource === 'task_active_window' ? `Full task-active window (${finalSummary.telemetryActiveWindowSec?.toFixed(1)}s); job metadata reported ${finalSummary.metadataDurationSec?.toFixed(1)}s` : `Job metadata${finalSummary.telemetryActiveWindowSec != null ? ` (${finalSummary.metadataDurationSec?.toFixed(1)}s metadata vs ${finalSummary.telemetryActiveWindowSec.toFixed(1)}s task-active window)` : ''}`}
**Governing Capacity Model:** ${diag.governingCeilingItemsPerSec} ${throughputLabel} (${governingCapacityLabel}) | **${finalSummary.runtimeTelemetryComplete ? 'Active-Window Efficiency' : 'Estimated Model Efficiency (whole-job rate)'}:** ${finalSummary.efficiencyPercent}%
${sampleNotice ? `**Data Quality:** ${sampleNotice}\n` : ''}

## 1. Executive Performance Metrics
- **Successful Tasks:** ${telemetry.completedTasksCount.toLocaleString()} / ${telemetry.totalTasksCount.toLocaleString()} (${successPercent}%)
- **Failures:** ${failureSummary}
- **Terminalized Tasks:** ${terminalTaskCount.toLocaleString()} / ${telemetry.totalTasksCount.toLocaleString()} (${terminalPercent}%)
- **${finalSummary.runtimeTelemetryComplete ? 'Time-Weighted In-Flight Concurrency' : 'Estimated In-Flight Concurrency (Little’s Law)'}:** ${finalSummary.avgActiveConcurrency} active tasks avg (${telemetry.runningTasksCount} at close)
- **${finalSummary.runtimeTelemetryComplete ? 'Measured Active-Route Occupancy' : 'Estimated Active-Route Occupancy'}:** ${finalSummary.avgActiveProxyRoutes} / ${routeSlotsLabel} route slots (${finalSummary.avgActiveProxyUtilization}% ${finalSummary.runtimeTelemetryComplete ? 'measured' : 'estimated'} utilization)
- **Full-Job Mean Task Duration:** ${finalSummary.meanTaskDurationSec != null ? `${finalSummary.meanTaskDurationSec.toFixed(2)}s` : 'Unavailable (sample fallback in use)'}
- **Mean Route-Active Duration per Task:** ${finalSummary.meanRouteActiveDurationSec != null ? `${finalSummary.meanRouteActiveDurationSec.toFixed(2)}s` : 'Unavailable (task-duration fallback in use)'}
- **Mean Route Attempt Duration:** ${finalSummary.meanRouteAttemptDurationSec != null ? `${finalSummary.meanRouteAttemptDurationSec.toFixed(2)}s` : 'Unavailable'} (${finalSummary.routeAttemptsPerTask != null ? `${finalSummary.routeAttemptsPerTask.toFixed(2)} attempts/task` : 'attempt density unavailable'})
- **Latency Percentiles:** p50: ${latencyPercentiles.p50}s | p90: ${latencyPercentiles.p90}s | p95: ${latencyPercentiles.p95}s | p99: ${latencyPercentiles.p99}s
- **${finalSummary.runtimeTelemetryComplete ? 'Active-Window Efficiency' : 'Estimated Model Efficiency (whole-job rate)'}:** ${finalSummary.efficiencyPercent}% of the governing ${governingCapacityLabel} model (${finalSummary.theoreticalMaxItemsPerSec} ${throughputLabel})

### Full-Job Execution Phase Timing:

| Phase | Mean per Task | Measurement Boundary |
| :--- | :--- | :--- |
| **Queue / Dispatch Wait** | ${finalSummary.meanQueueWaitSec != null ? `${finalSummary.meanQueueWaitSec.toFixed(3)}s` : 'Unavailable'} | Task creation/admission to worker execution |
| **Worker Setup** | ${finalSummary.meanSetupSec != null ? `${finalSummary.meanSetupSec.toFixed(3)}s` : 'Unavailable'} | Locking, dedupe, state, auth, and context setup |
| **Handler / Upstream Work** | ${finalSummary.meanHandlerSec != null ? `${finalSummary.meanHandlerSec.toFixed(3)}s` : 'Unavailable'} | Task handler wall time excluding durable writer waits |
| **Durable Writer Wait** | ${finalSummary.meanWriterSec != null ? `${finalSummary.meanWriterSec.toFixed(3)}s` : 'Unavailable'} | Writer admission plus acknowledged commit waits inside the handler |
| **Terminal State Update** | ${finalSummary.meanPostSec != null ? `${finalSummary.meanPostSec.toFixed(3)}s` : 'Unavailable'} | Handler return through task completion state transition |
| **Release / Publication** | ${finalSummary.meanReleaseSec != null ? `${finalSummary.meanReleaseSec.toFixed(3)}s` : 'Unavailable'} | Completion transition through worker cleanup/publication |

### Worker Setup Timing Breakdown:

| Setup Subphase | Mean per Task | Per Observation | Observations | Boundary |
| :--- | :--- | :--- | :--- | :--- |
| **Task Lock** | ${fmtSetup('task_lock')} | ${fmtSetupObs('task_lock')} | ${fmtSetupCount('task_lock')} | Redis execution-lock acquisition |
| **Dedup Reservation** | ${fmtSetup('dedup')} | ${fmtSetupObs('dedup')} | ${fmtSetupCount('dedup')} | Deduplicate-key reservation |
| **Claim / Start Transition** | ${fmtSetup('mark_started')} | ${fmtSetupObs('mark_started')} | ${fmtSetupCount('mark_started')} | Ready-set to running state transition |
| **Claimed Event** | ${fmtSetup('event_claimed')} | ${fmtSetupObs('event_claimed')} | ${fmtSetupCount('event_claimed')} | TASK_CLAIMED event append |
| **Job Started Event** | ${fmtSetup('event_job_started')} | ${fmtSetupObs('event_job_started')} | ${fmtSetupCount('event_job_started')} | JOB_STARTED event append (first task) |
| **Job Persist** | ${fmtSetup('persist_job')} | ${fmtSetupObs('persist_job')} | ${fmtSetupCount('persist_job')} | Job blob persist on PENDING to RUNNING |
| **Task Started Event** | ${fmtSetup('event_task_started')} | ${fmtSetupObs('event_task_started')} | ${fmtSetupCount('event_task_started')} | TASK_STARTED event append |
| **Registry Start** | ${fmtSetup('registry_start')} | ${fmtSetupObs('registry_start')} | ${fmtSetupCount('registry_start')} | Worker registry task registration |
| **Status Enqueue** | ${fmtSetup('status_enqueue')} | ${fmtSetupObs('status_enqueue')} | ${fmtSetupCount('status_enqueue')} | RUNNING status durable-writer enqueue |
| **Dependencies** | ${fmtSetup('dependencies')} | ${fmtSetupObs('dependencies')} | ${fmtSetupCount('dependencies')} | Upstream task output resolution |
| **Config Refresh** | ${fmtSetup('config_refresh')} | ${fmtSetupObs('config_refresh')} | ${fmtSetupCount('config_refresh')} | Storage config signature check and reload |
| **Auth Load** | ${fmtSetup('auth_load')} | ${fmtSetupObs('auth_load')} | ${fmtSetupCount('auth_load')} | Lazy cookie-auth load and verification |
| **Context / Log** | ${fmtSetup('context_and_log')} | ${fmtSetupObs('context_and_log')} | ${fmtSetupCount('context_and_log')} | Worker context build and execution log |
| **Lock Renewal Register** | ${fmtSetup('lock_renewal_register')} | ${fmtSetupObs('lock_renewal_register')} | ${fmtSetupCount('lock_renewal_register')} | Background lock-renewal registration |
| **Uninstrumented Residual** | ${fmtSetup('residual')} | ${fmtSetupObs('residual')} | ${fmtSetupCount('residual')} | Setup time not covered by an instrumented span |

- **Dominant Setup Subphase:** ${finalSummary.dominantSetupSubphase ?? 'Unavailable'}

### Handler / Upstream Timing Breakdown:

| Handler Subphase | Mean per Task | Observations | Boundary |
| :--- | :--- | :--- | :--- |
| **Guest Initialization / Login** | ${finalSummary.meanHandlerGuestInitMs != null ? `${finalSummary.meanHandlerGuestInitMs.toFixed(2)}ms` : 'Unavailable'} | ${(finalSummary.handlerGuestInitCount ?? 0).toLocaleString()} | Guest auth construction and initialization |
| **Initial User Lookup** | ${finalSummary.meanHandlerInitialLookupMs != null ? `${finalSummary.meanHandlerInitialLookupMs.toFixed(2)}ms` : 'Unavailable'} | ${(finalSummary.handlerInitialLookupCount ?? 0).toLocaleString()} | Initial ID, username, and chat fallback lookup |
| **Refresh / Auxiliary API** | ${finalSummary.meanHandlerRefreshApiMs != null ? `${finalSummary.meanHandlerRefreshApiMs.toFixed(2)}ms` : 'Unavailable'} | ${(finalSummary.handlerRefreshApiCount ?? 0).toLocaleString()} | Explicit profile refresh and auxiliary profile API calls |
| **Fallback / Retry Delay** | ${finalSummary.meanHandlerFallbackRetryMs != null ? `${finalSummary.meanHandlerFallbackRetryMs.toFixed(2)}ms` : 'Unavailable'} | ${(finalSummary.handlerFallbackRetryCount ?? 0).toLocaleString()} | Geo-fallback transitions and retry backoff |
| **Payload Serialization** | ${finalSummary.meanHandlerSerializationMs != null ? `${finalSummary.meanHandlerSerializationMs.toFixed(2)}ms` : 'Unavailable'} | ${(finalSummary.handlerSerializationCount ?? 0).toLocaleString()} | Profile object to durable writer payload |
| **Other Handler Work** | ${finalSummary.meanHandlerResidualMs != null ? `${finalSummary.meanHandlerResidualMs.toFixed(2)}ms` : 'Unavailable'} | - | Exclusive handler time not covered by an instrumented subphase |

- **Dominant Handler Subphase:** ${finalSummary.dominantHandlerSubphase ?? 'Unavailable'}

### Guest Auth Initialization Detail:

| Observation | Count | Total time | Mean per observation |
| :--- | ---: | ---: | ---: |
${Object.entries(telemetry.guestAuthStats ?? {}).map(([name, stats]) =>
  `| ${name} | ${stats.count} | ${stats.ms.toFixed(2)} ms | ${(stats.count > 0 ? stats.ms / stats.count : 0).toFixed(2)} ms |`).join('\n') || '| Unavailable | — | — | — |'}

Cache observations and failure categories are counters. Lock and login spans are nested inside guest initialization; do not add them to handler phase totals.

### Terminal State Timing Detail:

| Stage | Count | Mean per observation |
| :--- | ---: | ---: |
${Object.entries(telemetry.terminalStats ?? {}).map(([name, stats]) => `| ${name} | ${stats.count} | ${(stats.ms / Math.max(1, stats.count)).toFixed(2)}ms |`).join('\n') || '| Unavailable | — | — |'}

Before counter and Counter transition subdivide Terminal State Update. Finish-lock wait and Output persistence, when available, are nested within Before counter; do not add them to phase totals.

### Ledger Checkpoint Timing:

| Stage | Calls | Mean total wait | Mean SQL call | Mean admission and dispatch | Mean batch queue wait | Mean thread wait | Mean event-loop resume |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
${Object.entries(telemetry.ledgerStats ?? {}).filter(([name]) => !name.endsWith('_execution') && !name.endsWith('_admission')).map(([name, stats]) => {
    const count = Math.max(1, stats.count);
    const threadWait = telemetry.ledgerStats?.[`${name}_thread_wait_admission`];
    const batchWait = telemetry.ledgerStats?.[`${name}_batch_wait_admission`];
    const resume = telemetry.ledgerStats?.[`${name}_resume_admission`];
    return `| ${name} | ${stats.count} | ${(stats.ms / count).toFixed(2)}ms | ${((telemetry.ledgerStats?.[`${name}_execution`]?.ms ?? 0) / count).toFixed(2)}ms | ${((telemetry.ledgerStats?.[`${name}_admission`]?.ms ?? 0) / count).toFixed(2)}ms | ${batchWait ? `${(batchWait.ms / count).toFixed(2)}ms` : 'Unavailable'} | ${threadWait ? `${(threadWait.ms / count).toFixed(2)}ms` : 'Unavailable'} | ${resume ? `${(resume.ms / count).toFixed(2)}ms` : 'Unavailable'} |`;
  }).join('\n') || '| Unavailable | — | — | — | — | — | — | — |'}

SQL call time includes connection checkout, statements and commit. Batch queue wait measures request admission through submission of its batch. Thread wait measures batch submission through worker-thread start; event-loop resume measures worker-thread return through coroutine resumption. All three are nested inside admission and dispatch. Progress is inside handler time; writer preparation is inside writer admission; finish is inside terminal time. These spans are nested, not additional task phases.

### Per-Route User Lookup Timing:

${finalSummary.routeLookupStats == null
    ? 'Unavailable for this run or backend version.'
    : routeLookupRows.length === 0
      ? 'No route-level lookup observations were recorded.'
      : `Showing the ${Math.min(ROUTE_LOOKUP_DISPLAY_LIMIT, routeLookupRows.length)} slowest of ${routeLookupRows.length.toLocaleString()} observed routes, sorted by mean lookup time. Route IDs are opaque labels; proxy hosts and credentials are omitted.

| Route ID | Primary / hedge / fallback | Deferred / healthy / retry | Route Attempts | Lookups | Outcomes (n; found/no match/error/timeout/lookup canceled/init fail/init canceled) | Mean Guest Init | Mean User Lookup | Mean Route Active |
| :--- | :--- | :--- | ---: | ---: | :--- | ---: | ---: | ---: |
${routeLookupRows.slice(0, ROUTE_LOOKUP_DISPLAY_LIMIT).map(([routeId, route]) => `| \`${routeId}\` | ${[route.primary_selected_count, route.hedge_selected_count, route.fallback_selected_count].map(value => value ?? "Unavailable").join(" / ")} | ${[route.deferred_selected_count, route.healthy_selected_count, route.retry_selected_count].map(value => value ?? "Unavailable").join(" / ")} | ${route.route_attempts.toLocaleString()} | ${route.lookup_observations.toLocaleString()} | ${formatRouteLookupOutcomes(route)} | ${route.mean_guest_init_ms.toFixed(2)}ms | ${route.mean_lookup_ms != null ? `${route.mean_lookup_ms.toFixed(2)}ms` : 'Unavailable'} | ${route.mean_route_active_ms.toFixed(2)}ms |`).join('\n')}`}

### Durable Writer Timing Breakdown:

| Writer Subphase | Mean per Task | Boundary |
| :--- | :--- | :--- |
| **Producer Admission** | ${finalSummary.meanWriterAdmissionMs != null ? `${finalSummary.meanWriterAdmissionMs.toFixed(2)}ms` : 'Unavailable'} | Writer preparation (including ledger checkpoints), serialization, and bounded Redis queue admission |
| **Writer Queue / Lane Wait** | ${finalSummary.meanWriterQueueMs != null ? `${finalSummary.meanWriterQueueMs.toFixed(2)}ms` : 'Unavailable'} | Redis stream admission through writer batch execution start |
| **SQL Operation Execution** | ${finalSummary.meanWriterExecutionMs != null ? `${finalSummary.meanWriterExecutionMs.toFixed(2)}ms` : 'Unavailable'} | UPSERT_USER processing before transaction commit |
| **SQL Commit** | ${finalSummary.meanWriterCommitMs != null ? `${finalSummary.meanWriterCommitMs.toFixed(2)}ms` : 'Unavailable'} | PostgreSQL transaction commit including durable receipt |
| **Co-batch Command Work** | ${finalSummary.meanWriterBatchPeerWorkMs != null ? `${finalSummary.meanWriterBatchPeerWorkMs.toFixed(2)}ms` : 'Unavailable'} | Time spent completing other commands in the same transaction batch |
| **Writer Batch Overhead** | ${finalSummary.meanWriterOverheadMs != null ? `${finalSummary.meanWriterOverheadMs.toFixed(2)}ms` : 'Unavailable'} | Batch wall time outside command execution, commit, and peer work; includes receipt/fence work, connection checkout, and scheduling |
| **Result Delivery / Acknowledgement** | ${finalSummary.meanWriterDeliveryMs != null ? `${finalSummary.meanWriterDeliveryMs.toFixed(2)}ms` : 'Unavailable'} | Redis-clock publication start through producer observation |

| Delivery Subphase | Mean per Task | Boundary |
| :--- | :--- | :--- |
| **Writer Result Publication** | ${finalSummary.meanWriterResultPublicationMs != null ? `${finalSummary.meanWriterResultPublicationMs.toFixed(2)}ms` : 'Unavailable'} | Redis-clock publication start through result-cache availability |
| **Producer Result Observation** | ${finalSummary.meanWriterResultObservationMs != null ? `${finalSummary.meanWriterResultObservationMs.toFixed(2)}ms` : 'Unavailable'} | Result-cache availability through producer polling observation |
| **Fallback / Unclassified Delivery** | ${finalSummary.meanWriterResultDeliveryResidualMs != null ? `${finalSummary.meanWriterResultDeliveryResidualMs.toFixed(2)}ms` : 'Unavailable'} | Delivery observations without a complete same-clock split |

- **Dominant Writer Subphase:** ${finalSummary.dominantWriterSubphase ?? 'Unavailable'}
- **Writer Timing Coverage:** ${finalSummary.writerTimingCoveragePercent != null ? `${finalSummary.writerTimingCoveragePercent}%` : 'Unavailable'}
- **Delivery Split Coverage:** ${finalSummary.writerResultDeliverySplitCoveragePercent != null ? `${finalSummary.writerResultDeliverySplitCoveragePercent}%` : 'Unavailable'}

### Producer Admission Breakdown:

| Admission Subphase | Mean per Task | Boundary |
| :--- | :--- | :--- |
| **Payload Serialization** | ${finalSummary.meanWriterAdmissionSerializationMs != null ? `${finalSummary.meanWriterAdmissionSerializationMs.toFixed(2)}ms` : 'Unavailable'} | Durable command envelope construction and JSON encoding |
| **Queue-Capacity Wait** | ${finalSummary.meanWriterAdmissionCapacityWaitMs != null ? `${finalSummary.meanWriterAdmissionCapacityWaitMs.toFixed(2)}ms` : 'Unavailable'} | Backoff while the bounded writer stream is full |
| **Redis Admission Calls** | ${finalSummary.meanWriterAdmissionRedisMs != null ? `${finalSummary.meanWriterAdmissionRedisMs.toFixed(2)}ms` : 'Unavailable'} | Atomic queue-capacity checks and stream insertion |
| **Admission Overhead** | ${finalSummary.meanWriterAdmissionOverheadDetailMs != null ? `${finalSummary.meanWriterAdmissionOverheadDetailMs.toFixed(2)}ms` : 'Unavailable'} | Result lookup and producer-side work outside the measured stages |

### Writer SQL / User-Sync Detail:

| Internal Subphase | Mean per Task | Boundary |
| :--- | :--- | :--- |
| **Connection Checkout** | ${finalSummary.meanWriterConnectionCheckoutMs != null ? `${finalSummary.meanWriterConnectionCheckoutMs.toFixed(2)}ms` : 'Unavailable'} | SQLAlchemy writer-pool checkout before transaction work |
| **Durable Receipt Lookup** | ${finalSummary.meanWriterReceiptLookupMs != null ? `${finalSummary.meanWriterReceiptLookupMs.toFixed(2)}ms` : 'Unavailable'} | Advisory lock, receipt read, and attempt ownership fence |
| **Payload Mapping** | ${finalSummary.meanWriterPayloadMs != null ? `${finalSummary.meanWriterPayloadMs.toFixed(2)}ms` : 'Unavailable'} | Queued API payload normalization |
| **User Row** | ${finalSummary.meanWriterUserRowMs != null ? `${finalSummary.meanWriterUserRowMs.toFixed(2)}ms` : 'Unavailable'} | User lookup, insert, or core-field update |
| **Alias Synchronization** | ${finalSummary.meanWriterAliasMs != null ? `${finalSummary.meanWriterAliasMs.toFixed(2)}ms` : 'Unavailable'} | Previous and observed username alias persistence |
| **Authority Reconciliation** | ${finalSummary.meanWriterAuthorityMs != null ? `${finalSummary.meanWriterAuthorityMs.toFixed(2)}ms` : 'Unavailable'} | Existing-performer collision reconciliation |
| **Profile Records** | ${finalSummary.meanWriterProfileMs != null ? `${finalSummary.meanWriterProfileMs.toFixed(2)}ms` : 'Unavailable'} | User info, history, media, and website synchronization |
| **Social Records** | ${finalSummary.meanWriterSocialMs != null ? `${finalSummary.meanWriterSocialMs.toFixed(2)}ms` : 'Unavailable'} | Optional social-record synchronization |
| **Transaction Flush** | ${finalSummary.meanWriterFlushMs != null ? `${finalSummary.meanWriterFlushMs.toFixed(2)}ms` : 'Unavailable'} | ORM flushes before receipt finalization |
| **Durable Receipt Finalization** | ${finalSummary.meanWriterReceiptFinalizeMs != null ? `${finalSummary.meanWriterReceiptFinalizeMs.toFixed(2)}ms` : 'Unavailable'} | Receipt serialization and insert before commit |

- **Dominant Internal Subphase:** ${finalSummary.dominantWriterExecutionSubphase ?? 'Unavailable'}
- **Authority Observation Rows:** ${finalSummary.writerAuthorityRowsExamined?.toLocaleString() ?? 0} examined; ${finalSummary.writerAuthorityRowsSkipped?.toLocaleString() ?? 0} unchanged skipped; ${finalSummary.writerAuthorityRowsUpserted?.toLocaleString() ?? 0} upserted${finalSummary.writerAuthoritySkipPercent != null ? ` (${finalSummary.writerAuthoritySkipPercent}% skipped)` : ''}

### Writer Configuration & Pressure:

| Metric | Observed | Configured Limit |
| :--- | :--- | :--- |
| **Writer Lanes** | ${finalSummary.meanWriterActiveLanes != null ? `${finalSummary.meanWriterActiveLanes.toFixed(2)} mean per write observation / ${finalSummary.maxWriterActiveLanes ?? 'N/A'} max` : 'Unavailable'} | ${finalSummary.writerConfiguredConcurrency ?? 'Unavailable'} concurrent lanes |
| **Writer Batch** | ${finalSummary.meanWriterBatchCommands != null ? `${finalSummary.meanWriterBatchCommands.toFixed(2)} commands, command-weighted mean (${finalSummary.meanWriterBatchFillPercent ?? 'N/A'}% weighted fill)` : 'Unavailable'} | ${finalSummary.writerConfiguredBatchSize ?? 'Unavailable'} commands per lane |
| **Writer Submit Demand** | ${finalSummary.writerTimedSubmits?.toLocaleString() ?? 'Unavailable'} submits; ${finalSummary.writerSubmitsPerTask ?? 'N/A'} per task | ${finalSummary.writerSubmitsPerSec ?? 'N/A'} submits/s across the task-active window |
| **Result Delivery Source** | ${finalSummary.writerResultCacheHits?.toLocaleString() ?? 0} cache hits / ${finalSummary.writerReceiptFallbacks?.toLocaleString() ?? 0} receipt fallbacks | ${finalSummary.writerResultCacheHitPercent ?? 'N/A'}% result-cache hit rate |
| **Working Window** | ${finalSummary.writerWindowCommands ?? 'Unavailable'} commands | Batch target × writer lanes |
| **Rolling Refill Trigger** | ${finalSummary.writerRefillMinCommandsPerLane ?? 'Unavailable'} free commands/lane | ${finalSummary.writerRefillMinCommands ?? 'Unavailable'} free commands across the working window |
| **Lane Scheduling Delay** | ${finalSummary.meanWriterLaneIdleMs != null ? `${finalSummary.meanWriterLaneIdleMs.toFixed(2)}ms idle; ${(finalSummary.meanWriterLanePredecessorWaitMs ?? 0).toFixed(2)}ms predecessor; ${(finalSummary.meanWriterRefillWaitMs ?? 0).toFixed(2)}ms refill` : 'Unavailable'} | Per acknowledged write observation |
| **Queue Commands at Writer Start** | ${finalSummary.meanWriterQueueCommandsAtStart != null ? `${finalSummary.meanWriterQueueCommandsAtStart.toFixed(1)} mean / ${finalSummary.maxWriterQueueCommandsAtStart ?? 'N/A'} max` : 'Unavailable'} | ${finalSummary.writerQueueMaxCommands ?? 'Unavailable'} commands |
| **Queue Bytes at Writer Start** | ${finalSummary.meanWriterQueueBytesAtStart != null ? `${(finalSummary.meanWriterQueueBytesAtStart / 1048576).toFixed(2)} MiB mean / ${((finalSummary.maxWriterQueueBytesAtStart ?? 0) / 1048576).toFixed(2)} MiB max` : 'Unavailable'} | ${finalSummary.writerQueueMaxBytes != null ? `${(finalSummary.writerQueueMaxBytes / 1048576).toFixed(2)} MiB` : 'Unavailable'} |

Batch averages weight each acknowledged command's batch equally, so large transactions contribute more observations. Count committed transactions to measure mean commands per transaction. Lane activity is sampled at write observations; time-weighted SQL occupancy requires transaction intervals.

### Writer Batch Distribution by Operation:

| Operation | Timed Commands | Command-Weighted Batch Commands | Command-Weighted Batch Wall |
| :--- | ---: | ---: | ---: |
${Object.entries(finalSummary.writerOperationStats ?? {}).sort(([, a], [, b]) => b.count - a.count).map(([name, stats]) => `| \`${name}\` | ${stats.count.toLocaleString()} | ${stats.mean_batch_commands.toFixed(2)} | ${stats.mean_batch_wall_ms.toFixed(2)}ms |`).join('\n') || '| Unavailable | 0 | - | - |'}

### Writer Batch Distribution by Ordering Domain:

| Domain | Timed Commands | Command-Weighted Batch Commands | Command-Weighted Batch Wall |
| :--- | ---: | ---: | ---: |
${Object.entries(finalSummary.writerDomainStats ?? {}).sort(([, a], [, b]) => b.count - a.count).map(([name, stats]) => `| \`${name}\` | ${stats.count.toLocaleString()} | ${stats.mean_batch_commands.toFixed(2)} | ${stats.mean_batch_wall_ms.toFixed(2)}ms |`).join('\n') || '| Unavailable | 0 | - | - |'}

### Receipt Lock and Recovery Read Timings:

| Operation | Measured Commands | Lock Share / Command | Receipt Read Share / Command | Attempt Fence Share / Command |
| :--- | ---: | ---: | ---: | ---: |
${Object.entries(finalSummary.writerOperationStats ?? {}).sort(([, a], [, b]) => b.count - a.count).map(([name, stats]) => `| \`${name}\` | ${(stats.receipt_phases_count ?? 0).toLocaleString()} | ${stats.mean_receipt_lock_ms != null ? `${stats.mean_receipt_lock_ms.toFixed(2)}ms` : 'Unavailable'} | ${stats.mean_receipt_read_ms != null ? `${stats.mean_receipt_read_ms.toFixed(2)}ms` : 'Unavailable'} | ${stats.mean_write_fence_ms != null ? `${stats.mean_write_fence_ms.toFixed(2)}ms` : 'Unavailable'} |`).join('\n') || '| Unavailable | 0 | Unavailable | Unavailable | Unavailable |'}

These subdivide the receipt lookup stage. Each batch cost is shared across its measured commands; coverage counts identify runs with the new instrumentation.

### Result Delivery Split Gaps:

${Object.entries(finalSummary.writerSplitMissingReasons ?? {}).sort(([, a], [, b]) => b - a).map(([reason, count]) => `- **${reason}:** ${count.toLocaleString()}`).join('\n') || '- No missing delivery-split observations recorded.'}

### Performance & Capacity Utilization Summary:
| Metric | Measured Value | Target / Ceiling | Utilization / Status |
| :--- | :--- | :--- | :--- |
| **Lifetime Avg Throughput** | ${finalSummary.overallAvgItemsPerSec} ${throughputLabel} | ${diag.governingCeilingItemsPerSec} ${throughputLabel} | Whole-job wall-clock rate; governing model: ${governingCapacityLabel} |
| **Active-Window Throughput** | ${finalSummary.activeWindowThroughput ?? 'Unavailable'} ${throughputLabel} | ${diag.governingCeilingItemsPerSec} ${throughputLabel} | ${finalSummary.efficiencyPercent}% of modeled capacity |
| **Steady-State Throughput (10–90%)** | ${finalSummary.steadyStateThroughput ?? 'Unavailable'} ${throughputLabel} | ${finalSummary.steadyStateCapacityItemsPerSec ?? 'Unavailable'} ${throughputLabel} | ${finalSummary.steadyStateEfficiencyPercent != null ? `${finalSummary.steadyStateEfficiencyPercent}% efficiency (not clamped)` : 'Unavailable'} |
| **Proxy-Route Capacity Model** | ${proxyCapacity.totalRoutes > 0 ? `${diag.theoreticalProxyMaxItemsPerSec} ${throughputLabel}` : 'Unavailable'} | ${routeSlotsLabel} route slots | ${finalSummary.runtimeTelemetryComplete ? 'Uses full-job route-active time per completed task; retries consume additional route capacity' : 'Estimated using sampled task latency because full-job route-active timing is unavailable'} |
| **Worker-Slot Capacity Model** | ${diag.theoreticalWorkerMaxItemsPerSec} ${throughputLabel} | ${diag.workerConcurrencyDemand} worker slots | ${finalSummary.runtimeTelemetryComplete ? 'Uses full-job mean task duration' : 'Estimated using sampled task latency because full-job task duration is unavailable'} |
| **Peak Completion-Publication Burst** | ${finalSummary.peakItemsPerSec} ${throughputLabel} | Not a service-rate ceiling | Counter/task-completion timestamps may arrive in batches |
| **${finalSummary.runtimeTelemetryComplete ? 'Time-Weighted Task Concurrency' : 'Estimated Task Concurrency (Little’s Law)'}** | ${finalSummary.avgActiveConcurrency} active tasks avg | ${diag.workerConcurrencyDemand} worker slots | ${diag.workerUtilizationPercent}% ${finalSummary.runtimeTelemetryComplete ? 'measured' : 'estimated'} worker occupancy |
| **${finalSummary.runtimeTelemetryComplete ? 'Active Route Occupancy' : 'Estimated Active Route Slots'}** | ${finalSummary.avgActiveProxyRoutes} active routes avg | ${routeSlotsLabel} route slots | ${finalSummary.avgActiveProxyUtilization}% ${finalSummary.runtimeTelemetryComplete ? 'measured' : 'estimated'} route occupancy |
| **${finalSummary.runtimeTelemetryComplete ? 'Idle / Unutilized Routes' : 'Estimated Idle Route Slots'}** | ${diag.idleProxyRoutes} routes | 0 routes | ${diag.idleProxyPercent}% ${finalSummary.runtimeTelemetryComplete ? 'measured' : 'estimated'} idle capacity |
| **Modeled Worker Concurrency Demand** | ${diag.workerConcurrencyDemand} slots | ${routeSlotsLabel} route capacity | ${diag.workerUtilizationPercent}% ${finalSummary.runtimeTelemetryComplete ? 'measured' : 'estimated'} worker utilization |
| **Worker Participation** | ${finalSummary.workersSeen ?? 'Unavailable'} workers seen | ${finalSummary.expectedWorkers ?? 'Unavailable'} expected | ${finalSummary.timeWeightedParticipatingWorkers != null ? `${finalSummary.timeWeightedParticipatingWorkers.toFixed(1)} time-weighted participating` : 'Unavailable'} |
| **Effective Participating Capacity** | ${finalSummary.timeWeightedEffectiveWorkerCapacity != null ? `${finalSummary.timeWeightedEffectiveWorkerCapacity.toFixed(1)} slots` : 'Unavailable'} | ${diag.workerConcurrencyDemand} configured slots | Participation spans × effective per-worker limits |
| **Ready Queue Availability (time-sampled)** | ${finalSummary.readyTimelineNonemptyPercent != null ? `${finalSummary.readyTimelineNonemptyPercent}% of covered time` : 'Unavailable'} | Sampled Redis task-state intervals | ${finalSummary.readyTimelineIntervalCount?.toLocaleString() ?? 0} intervals across ${finalSummary.readyTimelineCoveredSeconds?.toFixed(1) ?? '0.0'}s; gaps over 5s excluded |
| **Steady-State Ready Availability** | ${finalSummary.steadyReadyTimelineNonemptyPercent != null ? `${finalSummary.steadyReadyTimelineNonemptyPercent}% of covered steady-state time` : 'Unavailable'} | Same 10–90% window as steady throughput | ${finalSummary.steadyReadyTimelineCoveredSeconds?.toFixed(1) ?? '0.0'}s covered; excludes ramp and drain |
| **Ready Queue at Task Completion** | ${finalSummary.readyNonemptySamples != null && finalSummary.readySampleCount != null ? `${finalSummary.readyNonemptySamples.toLocaleString()}/${finalSummary.readySampleCount.toLocaleString()} samples (${finalSummary.readyNonemptyPercent ?? 0}%)` : finalSummary.readyNonemptyPercent != null ? `${finalSummary.readyNonemptyPercent}% (sample count unavailable)` : 'Unavailable'} | Descriptive completion samples | Mean depth at completion sample: ${finalSummary.meanReadyDepth != null ? finalSummary.meanReadyDepth.toFixed(1) : 'Unavailable'} |
| **Successful Claim Latency** | ${finalSummary.meanClaimWaitMs != null ? `${finalSummary.meanClaimWaitMs.toFixed(2)}ms/task` : 'Unavailable'} | Redis dispatch round trip | Excludes empty-queue blocking claims |
| **Largest Per-Worker Completion Gap** | ${finalSummary.maxWorkerCompletionGapMs != null ? `${(finalSummary.maxWorkerCompletionGapMs / 1000).toFixed(2)}s` : 'Unavailable'} | Continuous worker progress | Highlights long idle/stall intervals between completions |
| **Ready-Queue Recovery** | ${finalSummary.readyQueueRecoveredTasks ?? 0} tasks | 0 expected | ${(finalSummary.readyQueueRecoveryCount ?? 0)} stalled-queue repair event(s) |
| **Ramp + Drain Share** | ${finalSummary.rampDrainPercent != null ? `${finalSummary.rampDrainPercent}%` : 'Unavailable'} | Active execution window | Completion-decile boundary share |
| **Task Success Rate** | ${telemetry.completedTasksCount.toLocaleString()} / ${telemetry.totalTasksCount.toLocaleString()} | 100% success | ${successPercent}% succeeded |
| **Task Terminalization Rate** | ${terminalTaskCount.toLocaleString()} / ${telemetry.totalTasksCount.toLocaleString()} | 100% terminal | ${terminalPercent}% terminalized |

### Occupancy Gap Classification:
- **Classification:** ${(finalSummary.occupancyGapClassification ?? 'insufficient_data').replaceAll('_', ' ')}
- **Evidence:** ${finalSummary.occupancyGapExplanation ?? 'Steady-state occupancy telemetry is unavailable.'}

## 2. System Bottleneck Diagnosis
- **Bottleneck Classification:** ${bottleneckAnalysis?.label || (finalSummary.runtimeTelemetryComplete ? 'Optimal Concurrency' : 'Insufficient Runtime Telemetry')}
- **Diagnosis:** ${bottleneckAnalysis?.explanation || (finalSummary.runtimeTelemetryComplete ? 'No contention observed.' : 'This completed run lacks full-job measurements needed to classify its bottleneck.')}
- **Dominant Task Service Phase:** ${dominantServicePhase}${dominantServiceSeconds > 0 ? ` (${dominantServiceSeconds.toFixed(3)}s/task)` : ''}
- **Primary Measured Service Subphase:** ${dominantServiceSubphase ?? 'Unavailable'}
${
  bottleneckAnalysis?.rootCauseFindings && bottleneckAnalysis.rootCauseFindings.length > 0
    ? `\n### Root Cause Findings:\n` +
      bottleneckAnalysis.rootCauseFindings.map((f) => `- ${f}`).join('\n')
    : ''
}

### Throughput Gap & Efficiency Loss Decomposition:
*${finalSummary.runtimeTelemetryComplete ? 'Measured phase attribution' : 'Capacity model comparison (whole-job throughput; occupancy is estimated)'} against the governing ${governingCapacityLabel} model: ${diag.governingCeilingItemsPerSec} ${throughputLabel} vs ${finalSummary.runtimeTelemetryComplete ? 'active-window' : 'whole-job'} ${finalSummary.activeWindowThroughput ?? finalSummary.overallAvgItemsPerSec} ${throughputLabel}:*

| Limiting Factor | Severity | Impact on Throughput | Root Cause & Diagnostics |
| :--- | :--- | :--- | :--- |
${
  diag.lossFactors.length > 0
    ? diag.lossFactors
        .map(
          (lf) =>
            `| **${lf.factor}** | \`${lf.severity.toUpperCase()}\` | ${lf.estimatedLossItemsPerSec > 0 ? `-${lf.estimatedLossItemsPerSec} ${throughputLabel}` : lf.factor.includes('Insufficient Runtime Telemetry') ? 'Unavailable (telemetry gap)' : lf.factor.includes('429') || lf.factor.includes('Timeout') ? 'Observed incidence' : 'Measured phase'} | ${lf.description} |`,
        )
        .join('\n')
    : `| **Nominal Flow** | \`NOMINAL\` | 0.0 ${throughputLabel} | Telemetry indicates balanced execution near target capacity. |`
}

### Proxy Latency Summary:
- ${averageProxyLatencySec != null ? `${proxiesWithLatency.length} observed proxies had an average latency of ${averageProxyLatencySec}s.` : 'No proxy transport-latency observations were available; per-route user-lookup timings are reported separately.'}

## 3. HTTP Response Code Distribution
- **200 OK:** ${httpDistribution.ok200.toLocaleString()}
- **429 Rate Limits:** ${httpDistribution.rateLimit429.toLocaleString()}
- **403 Forbidden / Route Mismatch:** ${httpDistribution.forbidden403.toLocaleString()}
- **404 Not Found / Inactive:** ${httpDistribution.notFound404.toLocaleString()}
- **5xx Server Errors:** ${httpDistribution.serverError5xx.toLocaleString()}
- **Timeouts / Aborts:** ${httpDistribution.timeoutErrors.toLocaleString()}

### HTTP Response Breakdown Table:
| Response Status / Category | Count | Percentage | Operational Diagnosis |
| :--- | :--- | :--- | :--- |
| **200 OK** | ${httpDistribution.ok200.toLocaleString()} | ${pct200}% | Nominal task completion |
| **429 Rate Limits** | ${httpDistribution.rateLimit429.toLocaleString()} | ${pct429}% | Observed upstream rate-limit responses (${telemetry.errorVelocity.rate429PerMin}/min) |
| **403 Forbidden** | ${httpDistribution.forbidden403.toLocaleString()} | ${pct403}% | Route identity or session mismatch |
| **404 Not Found** | ${httpDistribution.notFound404.toLocaleString()} | ${pct404}% | Inactive, deleted, or missing creator resource |
| **5xx Server Errors** | ${httpDistribution.serverError5xx.toLocaleString()} | ${pct5xx}% | Observed upstream errors; count alone does not establish platform degradation |
| **Timeouts / Aborts** | ${httpDistribution.timeoutErrors.toLocaleString()} | ${pctTimeout}% | Timeout/reset outcomes; route attribution is required before assigning proxy responsibility |

## 4. Proxy Route Audit
- **Configured Route Slots:** ${routeSlotsLabel}
- **Routes With Sampled Health Observations:** ${observedProxies.length}
- **Opaque Routes With Full-Job Lookup Timing:** ${routeLookupRows.length}
- **Observed Routes Without an Attributed Failure:** ${observedProxiesWithoutFailures.length} / ${observedProxies.length}
- **Observed Degraded Routes:** ${observedProxies.filter((p) => p.status === 'degraded').length}
- **Observed Critical / Rate-Limited Routes:** ${observedProxies.filter((p) => p.status === 'critical').length}

${
  badProxies.length > 0
    ? `### Problematic Routes Identified:\n` +
      badProxies
        .map(
          (p) =>
            `- \`${p.displayUrl}\` (${p.group || 'Default'}): ${p.failures} fails, ${p.rateLimits429} rate limits, ${p.timeouts} timeouts (Issue: ${p.primaryIssue})`,
        )
        .join('\n')
    : observedProxies.length > 0
      ? `No failures were attributed to the ${observedProxies.length} sampled route(s); unobserved routes were not classified. Full-job lookup timing covers ${routeLookupRows.length} opaque route ID(s).`
      : routeLookupRows.length > 0
        ? `Full-job lookup timing covers ${routeLookupRows.length} opaque route ID(s), but sampled per-route failure/health observations were unavailable. No route-health conclusion can be made from aggregate failures.`
        : `Per-route failure and lookup attribution were unavailable, so no route-health conclusion can be made from aggregate failures.`
}

${
  badProxies.length > 0
    ? `\n### Problematic Proxy Outlier Table:\n` +
      `| Proxy Route | Group / Region | Requests | Fails | 429s | Timeouts | Issue & Health Status |\n` +
      `| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n` +
      badProxies
        .slice(0, 25)
        .map(
          (p) =>
            `| \`${p.displayUrl}\` | ${p.countryFlag ? `${p.countryFlag} ` : ''}${p.group || p.country || 'Default'} | ${p.totalAttempts.toLocaleString()} | ${p.failures} | ${p.rateLimits429} | ${p.timeouts} | \`${p.status.toUpperCase()}\`: ${p.primaryIssue} |`,
        )
        .join('\n')
    : ''
}

${formatMPSRefillReport(telemetry.mpsRefillTrace)}

## 5. Operator Recommendations
${finalSummary.recommendations.map((r, idx) => `${idx + 1}. ${r}`).join('\n')}

### Environment Tuning Guardrail:
No concurrency or claim-batch override is emitted automatically. ${finalSummary.runtimeTelemetryComplete ? 'Apply an environment change only when the measured dominant phase and supporting queue/database telemetry justify it.' : 'Runtime telemetry is incomplete; this report cannot establish that worker concurrency or claim batching is limiting.'}
${historicalSection}`;
}

export function generateDiagnosticJsonBundle(
  telemetry: JobDiagnosticsTelemetry,
  jobName: string,
  jobId: string,
  site: string,
  comparison?: HistoricalComparisonResult | null,
): string {
  const bundle = {
    meta: {
      reportType: 'UltimaScraper Diagnostic Bundle',
      version: '1.0.0',
      jobName,
      jobId,
      site,
      exportedAt: new Date().toISOString(),
    },
    bottleneckAnalysis: telemetry.bottleneckAnalysis,
    finalSummary: telemetry.finalSummary,
    throughputDiagnostics: telemetry.throughputDiagnostics,
    counts: {
      completedTasks: telemetry.completedTasksCount,
      readyTasks: telemetry.readyTasksCount,
      runningTasks: telemetry.runningTasksCount,
      totalTasks: telemetry.totalTasksCount,
    },
    throughput: telemetry.throughput,
    latencyPercentiles: telemetry.latencyPercentiles,
    proxyCapacity: telemetry.proxyCapacity,
    httpDistribution: telemetry.httpDistribution,
    errorVelocity: telemetry.errorVelocity,
    proxyAnomalies: telemetry.proxyAnomalies,
    snapshots: telemetry.snapshots,
    historicalComparison: comparison?.hasBaseline
      ? {
          hasBaseline: true,
          baselineJobId: comparison.baselineJob?.jobId,
          baselineJobName: comparison.baselineJob?.jobName,
          baselineStatus: comparison.baselineJob?.status,
          deltas: comparison.deltas,
        }
      : { hasBaseline: false },
  };
  return JSON.stringify(bundle, null, 2);
}

export function downloadTextFile(
  filename: string,
  content: string,
  mimeType: string = 'text/markdown;charset=utf-8;',
) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
