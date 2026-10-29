import type {
  Job,
  JobDetail,
  JobRuntimeSample,
  TaskDetail,
} from '../../../api/types/jobs';
import type {
  BottleneckAnalysis,
  BottleneckState,
  ErrorVelocityStats,
  FinalReportSummary,
  HttpStatusBreakdown,
  LatencyPercentiles,
  ProxyAnomaly,
  ProxyCapacityStats,
  ThroughputDiagnostics,
  ThroughputLossFactor,
} from './jobDiagnosticsTypes';

const DEFAULT_SAFETY_THRESHOLD_LIMIT = 25; // Default circuit-breaker ceiling

export function getServicePhases(summary: Pick<FinalReportSummary,
  'meanSetupSec' | 'meanHandlerSec' | 'meanWriterSec' | 'meanPostSec'
  | 'meanReleaseSec' | 'dominantWriterSubphase'
>): Array<[string, number]> {
  const writerBackpressure = (summary.meanWriterSec ?? 0) > (summary.meanHandlerSec ?? 0)
    && (summary.dominantWriterSubphase === 'Writer Queue'
      || summary.dominantWriterSubphase === 'Producer Admission');
  return [
    ['Worker Setup', summary.meanSetupSec ?? 0],
    ['Handler / Upstream Work', summary.meanHandlerSec ?? 0],
    [writerBackpressure ? 'Writer Queue / Admission Backpressure' : 'Durable Writer Wait', summary.meanWriterSec ?? 0],
    ['Terminal State Update', summary.meanPostSec ?? 0],
    ['Release / Publication', summary.meanReleaseSec ?? 0],
  ];
}

export function summarizeReadyQueueTimeline(
  samples: JobRuntimeSample[],
  window?: { startMs: number; endMs: number },
): {
  nonemptyPercent: number | null;
  intervalCount: number;
  coveredSeconds: number;
} {
  let readyMs = 0;
  let coveredMs = 0;
  let intervalCount = 0;
  for (let index = 0; index < samples.length - 1; index += 1) {
    const current = samples[index];
    const next = samples[index + 1];
    const intervalMs = next.timestamp_ms - current.timestamp_ms;
    if (intervalMs <= 0 || intervalMs > 5_000) continue;
    const coveredIntervalMs = window
      ? Math.max(0, Math.min(next.timestamp_ms, window.endMs) - Math.max(current.timestamp_ms, window.startMs))
      : intervalMs;
    if (coveredIntervalMs <= 0) continue;
    coveredMs += coveredIntervalMs;
    intervalCount += 1;
    if (current.ready > 0) readyMs += coveredIntervalMs;
  }
  return {
    nonemptyPercent: coveredMs > 0
      ? Number(((readyMs / coveredMs) * 100).toFixed(1))
      : null,
    intervalCount,
    coveredSeconds: Number((coveredMs / 1_000).toFixed(1)),
  };
}

/** Reads `key` from the job summary first, then its detail payload. */
export function jobSetting(
  job: Job | JobDetail,
  details: JobDetail | undefined,
  bag: 'metadata' | 'args',
  key: string,
): unknown {
  return job[bag]?.[key] ?? details?.[bag]?.[key];
}

export function computeSafetyThresholdLimit(
  job: Job | JobDetail,
  details: JobDetail | undefined,
  totalTasks: number,
): number {
  const metaLimit =
    jobSetting(job, details, 'metadata', 'failure_limit') ??
    jobSetting(job, details, 'metadata', 'continuable_task_failure_maximum') ??
    jobSetting(job, details, 'args', 'failure_limit') ??
    jobSetting(job, details, 'args', 'continuable_task_failure_maximum');

  if (typeof metaLimit === 'number' && metaLimit > 0) {
    return metaLimit;
  }

  // Bounded circuit-breaker limit matching backend Worker._continuable_task_failure_limit:
  // 5% of total tasks (totalTasks / 20), minimum 3, maximum 25 for <= 1000 tasks, scaled up to 2500 for large batches.
  if (totalTasks > 0) {
    const scaledLimit = Math.ceil(totalTasks / 20);
    if (totalTasks > 1000) {
      const effectiveMax = Math.max(25, Math.min(2500, scaledLimit));
      return Math.min(effectiveMax, Math.max(3, scaledLimit));
    }
    return Math.min(25, Math.max(3, scaledLimit));
  }

  return DEFAULT_SAFETY_THRESHOLD_LIMIT;
}

export function resolveTargetConcurrency(
  job: Job | JobDetail,
  details: JobDetail | undefined,
  totalProxyCapacity: number,
  workerPoolSize: number,
): number {
  const configured =
    jobSetting(job, details, 'metadata', 'target_concurrency') ??
    jobSetting(job, details, 'args', 'target_concurrency') ??
    jobSetting(job, details, 'args', 'concurrency');
  const configuredNumber = Number(configured);
  if (Number.isFinite(configuredNumber) && configuredNumber > 0) {
    return Math.max(1, Math.floor(configuredNumber));
  }

  // This matches WorkerPool.compute_dynamic_concurrency when no explicit job
  // override exists: distribute declared proxy slots across worker processes.
  return totalProxyCapacity > 0 && workerPoolSize > 0
    ? Math.max(1, Math.ceil(totalProxyCapacity / workerPoolSize))
    : 16;
}

export function parseTaskLatency(task: TaskDetail): number | null {
  if (typeof task.duration === 'number' && task.duration > 0 && task.duration <= 120) {
    return task.duration;
  }
  if (!task.started_at || !task.completed_at) return null;
  const start = new Date(task.started_at).getTime();
  const end = new Date(task.completed_at).getTime();
  if (isNaN(start) || isNaN(end) || end <= start) return null;
  const durationSec = (end - start) / 1000;
  // Bounded between 0.01s and 120s
  return durationSec >= 0.01 && durationSec <= 120 ? durationSec : null;
}

export function calculatePercentiles(latencies: number[]): LatencyPercentiles {
  if (latencies.length === 0) {
    return { p50: 0, p90: 0, p95: 0, p99: 0, sampleCount: 0 };
  }
  const sorted = [...latencies].sort((a, b) => a - b);
  const getP = (p: number) => {
    const idx = Math.min(
      Math.floor((p / 100) * sorted.length),
      sorted.length - 1,
    );
    return Number((sorted[idx] ?? 0).toFixed(2));
  };
  return {
    p50: getP(50),
    p90: getP(90),
    p95: getP(95),
    p99: getP(99),
    sampleCount: sorted.length,
  };
}

export interface BottleneckInputs {
  completedTasksCount: number;
  failedJobTasks: number;
  details: JobDetail | undefined;
  errorVelocity: ErrorVelocityStats;
  httpDistribution: HttpStatusBreakdown;
  isLiveJob: boolean;
  job: Job | JobDetail;
  proxyAnomalies: ProxyAnomaly[];
  proxyCapacity: ProxyCapacityStats;
  readyTasksCount: number;
  runningTasksCount: number;
  runtimeTelemetry: NonNullable<JobDetail['runtime_telemetry']> | null;
  totalProxyCapacity: number;
  totalTasksCount: number;
  workerPoolSize: number;
  finalSummary: FinalReportSummary;
}

/** Classifies the dominant throughput constraint and explains it. */
export function analyzeBottleneck({
  completedTasksCount,
  failedJobTasks,
  details,
  errorVelocity,
  httpDistribution,
  isLiveJob,
  job,
  proxyAnomalies,
  proxyCapacity,
  readyTasksCount,
  runningTasksCount,
  runtimeTelemetry,
  totalProxyCapacity,
  totalTasksCount,
  workerPoolSize,
  finalSummary,
}: BottleneckInputs): BottleneckAnalysis {
  const rootCauseFindings: string[] = [];
  const observedHttpCount = Math.max(1, httpDistribution.totalObserved);
  const rateLimitPercent = (httpDistribution.rateLimit429 / observedHttpCount) * 100;
  const serverErrorPercent = (httpDistribution.serverError5xx / observedHttpCount) * 100;
  const timeoutPercent = (httpDistribution.timeoutErrors / observedHttpCount) * 100;

  // Analyze HTTP anomalies
  if (httpDistribution.rateLimit429 > 0) {
    const top429Proxy = [...proxyAnomalies]
      .filter((p) => p.rateLimits429 > 0)
      .sort((a, b) => b.rateLimits429 - a.rateLimits429)[0];
    if (top429Proxy) {
      rootCauseFindings.push(
        `Observed rate limiting: ${httpDistribution.rateLimit429} total 429s (${rateLimitPercent.toFixed(2)}% of observed outcomes). Highest contributor is ${top429Proxy.displayUrl} (${top429Proxy.group || 'Default'}) with ${top429Proxy.rateLimits429} rejections.`,
      );
    } else {
      rootCauseFindings.push(
        `Observed rate limiting: ${httpDistribution.rateLimit429} total 429 request(s) (${rateLimitPercent.toFixed(2)}% of observed outcomes); no route attribution was available.`,
      );
    }
  }

  if (httpDistribution.serverError5xx > 0) {
    rootCauseFindings.push(
      `Observed upstream errors: ${httpDistribution.serverError5xx} 5xx response(s) (${serverErrorPercent.toFixed(2)}% of observed outcomes). This count alone does not establish platform degradation.`,
    );
  }

  if (httpDistribution.timeoutErrors > 0) {
    rootCauseFindings.push(
      `Observed timeouts/resets: ${httpDistribution.timeoutErrors} task failure(s) (${timeoutPercent.toFixed(2)}% of observed outcomes). Route responsibility is unknown unless per-route evidence is present.`,
    );
  }

  if (errorVelocity.trend === 'critical') {
    rootCauseFindings.push(
      `Critical error velocity: ${errorVelocity.errorsLast60s} failures in the last 60s (${errorVelocity.safetyMarginPercent}% of threshold: ${errorVelocity.safetyThresholdLimit}). At immediate risk of safety halt.`,
    );
  }

  // Determine primary bottleneck state
  let state: BottleneckState = 'insufficient_data';
  let label = 'No Confirmed Bottleneck';
  let explanation =
    'Current measurements do not establish the cause of unused execution capacity.';

  const targetConcurrency = resolveTargetConcurrency(
    job,
    details,
    totalProxyCapacity,
    workerPoolSize,
  );
  const workerConcurrencyDemand = (runtimeTelemetry?.time_weighted_effective_worker_capacity ?? 0) > 0
    ? runtimeTelemetry!.time_weighted_effective_worker_capacity!
    : workerPoolSize * targetConcurrency;

  const isProxyBottleneck =
    proxyCapacity.isSaturated ||
    (proxyCapacity.utilizationPercent >= 90 && readyTasksCount > 0);

  const isWorkerBottleneck =
    !isProxyBottleneck &&
    runningTasksCount >= workerConcurrencyDemand * 0.9 &&
    readyTasksCount > 0;

  const rawJobStatus = String(details?.status || job.status || '').toLowerCase();
  const isJobActive = isLiveJob && (rawJobStatus === 'running' || rawJobStatus === 'in_progress');
  const remainingTasks = Math.max(0, totalTasksCount - completedTasksCount);
  const isDraining = remainingTasks <= runningTasksCount || remainingTasks === 0;

  const isQueueStarved =
    isJobActive &&
    !isDraining &&
    !isProxyBottleneck &&
    !isWorkerBottleneck &&
    readyTasksCount === 0 &&
    runningTasksCount < Math.max(2, workerConcurrencyDemand * 0.9) &&
    remainingTasks > runningTasksCount;

  const hasCompleteRuntimeTelemetry = Boolean(finalSummary.runtimeTelemetryComplete);
  const meanHandler = finalSummary.meanHandlerSec ?? 0;
  const meanWriter = finalSummary.meanWriterSec ?? 0;
  const exclusiveHandler = meanHandler;
  const [dominantServicePhase, dominantServiceSeconds]: [string, number] =
    hasCompleteRuntimeTelemetry
      ? getServicePhases(finalSummary).sort((a, b) => b[1] - a[1])[0] ?? ['Unavailable', 0]
      : ['Unavailable', 0];

  if (!isJobActive && !hasCompleteRuntimeTelemetry) {
    state = 'insufficient_data';
    label = 'Insufficient Runtime Telemetry';
    explanation =
      'This completed run lacks full-job runtime measurements. Worker participation, ready-queue supply, and service phases are unavailable, so the reported capacity gap cannot identify a concurrency or claim-batch bottleneck.';
  } else if (!isJobActive && hasCompleteRuntimeTelemetry) {
    if (finalSummary.occupancyGapClassification === 'routing_stall') {
      state = 'routing_stall';
      label = 'Ready-Queue Routing Stall';
      explanation = `Backend recovery restored ${finalSummary.readyQueueRecoveredTasks ?? 0} stranded ready tasks across ${finalSummary.readyQueueRecoveryCount ?? 0} repair events.`;
    } else if (dominantServicePhase === 'Terminal State Update' && dominantServiceSeconds > 0) {
      state = 'terminal_constrained';
      label = 'Terminal State Update Dominant';
      explanation = `Tasks spent ${dominantServiceSeconds.toFixed(2)}s on average between handler return and the completion transition. Inspect finish-lock waiting, output persistence, and counter updates; this phase exceeds handler and writer time.`;
    } else if (dominantServicePhase === 'Worker Setup' && dominantServiceSeconds > 0) {
      state = 'setup_constrained';
      label = 'Worker Setup Dominant';
      explanation = `Worker setup averaged ${dominantServiceSeconds.toFixed(2)}s per task, the largest measured service phase. Inspect the locking, event, claim, and registry subphases.`;
    } else if (dominantServicePhase === 'Release / Publication' && dominantServiceSeconds > 0) {
      state = 'release_constrained';
      label = 'Release / Publication Dominant';
      explanation = `Worker cleanup and publication averaged ${dominantServiceSeconds.toFixed(2)}s per task, the largest measured service phase.`;
    } else if (meanWriter > 0 && meanWriter >= exclusiveHandler) {
      state = 'writer_constrained';
      const writerQueueOrAdmissionDominant =
        finalSummary.dominantWriterSubphase === 'Writer Queue'
        || finalSummary.dominantWriterSubphase === 'Producer Admission';
      label = writerQueueOrAdmissionDominant
        ? 'Writer Queue / Admission Backpressure'
        : 'Durable Writer Wait Dominant';
      explanation = writerQueueOrAdmissionDominant
        ? `Tasks spent ${meanWriter.toFixed(2)}s on durable writer waits, dominated by ${finalSummary.dominantWriterSubphase?.toLowerCase()}. Operation execution and commit are measured separately from checkpoint and receipt work.`
        : `Tasks spent ${meanWriter.toFixed(2)}s on average waiting for durable writer operations, more than the non-writer handler work (${exclusiveHandler.toFixed(2)}s).`;
      const writerSubphaseMs = Math.max(
        finalSummary.meanWriterAdmissionMs ?? 0,
        finalSummary.meanWriterQueueMs ?? 0,
        finalSummary.meanWriterExecutionMs ?? 0,
        finalSummary.meanWriterCommitMs ?? 0,
        finalSummary.meanWriterBatchPeerWorkMs ?? 0,
        finalSummary.meanWriterOverheadMs ?? 0,
        finalSummary.meanWriterDeliveryMs ?? 0,
      );
      if (
        finalSummary.dominantWriterSubphase
        && finalSummary.writerTimingCoveragePercent != null
      ) {
        rootCauseFindings.push(
          `Writer profiling covers ${finalSummary.writerTimingCoveragePercent}% of acknowledged writes. The largest measured subphase is ${finalSummary.dominantWriterSubphase} at ${(writerSubphaseMs / 1000).toFixed(3)}s per task.`,
        );
      }
      if (finalSummary.writerConfiguredConcurrency) {
        rootCauseFindings.push(
          `Writer pressure: ${finalSummary.meanWriterActiveLanes?.toFixed(1) ?? 'unknown'} mean active lanes (${finalSummary.maxWriterActiveLanes ?? 'unknown'} max) of ${finalSummary.writerConfiguredConcurrency} configured; queue depth at writer start averaged ${finalSummary.meanWriterQueueCommandsAtStart?.toFixed(1) ?? 'unknown'} commands and peaked at ${finalSummary.maxWriterQueueCommandsAtStart ?? 'unknown'} of ${finalSummary.writerQueueMaxCommands ?? 'unknown'}.`,
        );
      }
      if (finalSummary.meanWriterBatchFillPercent != null) {
        rootCauseFindings.push(
          `Writer batch fill averaged ${finalSummary.meanWriterBatchFillPercent}% (${finalSummary.meanWriterBatchCommands?.toFixed(1) ?? 'unknown'} of ${finalSummary.writerConfiguredBatchSize ?? 'unknown'} commands per lane); the admitted working window was ${finalSummary.writerWindowCommands ?? 'unknown'} commands and the effective refill threshold was ${finalSummary.writerRefillMinCommands ?? 'unknown'}.`,
        );
      }
      if (finalSummary.writerSubmitsPerTask != null) {
        rootCauseFindings.push(
          `Writer demand: ${(finalSummary.writerTimedSubmits ?? 0).toLocaleString()} acknowledged submits, ${finalSummary.writerSubmitsPerTask.toFixed(3)} submits per task, and ${(finalSummary.writerSubmitsPerSec ?? 0).toFixed(1)} submits/s across the task-active window.`,
        );
      }
      if (finalSummary.writerResultCacheHitPercent != null) {
        rootCauseFindings.push(
          `Writer result delivery: ${(finalSummary.writerResultCacheHits ?? 0).toLocaleString()} result-cache hits and ${(finalSummary.writerReceiptFallbacks ?? 0).toLocaleString()} PostgreSQL receipt fallbacks (${finalSummary.writerResultCacheHitPercent}% cache hit rate).`,
        );
      }
      if (finalSummary.meanWriterAdmissionCapacityWaitMs != null) {
        rootCauseFindings.push(
          `Producer admission split: ${finalSummary.meanWriterAdmissionCapacityWaitMs.toFixed(2)}ms queue-capacity wait, ${(finalSummary.meanWriterAdmissionRedisMs ?? 0).toFixed(2)}ms Redis admission, ${(finalSummary.meanWriterAdmissionSerializationMs ?? 0).toFixed(2)}ms serialization, and ${(finalSummary.meanWriterAdmissionOverheadDetailMs ?? 0).toFixed(2)}ms other overhead per task.`,
        );
      }
      const ledgerPrepare = runtimeTelemetry?.ledger_stats?.writer_prepare;
      if (ledgerPrepare && (runtimeTelemetry?.task_count ?? 0) > 0) {
        const count = runtimeTelemetry!.task_count;
        rootCauseFindings.push(
          `Writer admission includes ${(ledgerPrepare.ms / count).toFixed(2)}ms/task of ledger checkpoint wait: ${((runtimeTelemetry?.ledger_stats?.writer_prepare_execution?.ms ?? 0) / count).toFixed(2)}ms SQL call and ${((runtimeTelemetry?.ledger_stats?.writer_prepare_admission?.ms ?? 0) / count).toFixed(2)}ms thread admission and dispatch. These spans are nested inside writer admission.`,
        );
      }
      if (
        finalSummary.meanWriterResultPublicationMs != null
        || finalSummary.meanWriterResultObservationMs != null
      ) {
        rootCauseFindings.push(
          `Result delivery split: ${(finalSummary.meanWriterResultPublicationMs ?? 0).toFixed(2)}ms writer publication, ${(finalSummary.meanWriterResultObservationMs ?? 0).toFixed(2)}ms producer observation, and ${(finalSummary.meanWriterResultDeliveryResidualMs ?? 0).toFixed(2)}ms fallback/unclassified delivery per task (${finalSummary.writerResultDeliverySplitCoveragePercent ?? 0}% split coverage).`,
        );
      }
      if (finalSummary.dominantWriterExecutionSubphase) {
        rootCauseFindings.push(
          `Within writer SQL/user-sync work, the largest measured internal subphase is ${finalSummary.dominantWriterExecutionSubphase}.`,
        );
      }
      if ((finalSummary.writerAuthorityRowsExamined ?? 0) > 0) {
        rootCauseFindings.push(
          `Authority observation filtering examined ${(finalSummary.writerAuthorityRowsExamined ?? 0).toLocaleString()} rows, skipped ${(finalSummary.writerAuthorityRowsSkipped ?? 0).toLocaleString()} unchanged rows (${finalSummary.writerAuthoritySkipPercent ?? 0}%), and submitted ${(finalSummary.writerAuthorityRowsUpserted ?? 0).toLocaleString()} rows to the conflict upsert.`,
        );
      }
    } else if (finalSummary.avgActiveProxyUtilization >= 90) {
      state = 'route_constrained';
      label = 'Active Route Capacity Reached';
      explanation = `Measured time-weighted route occupancy reached ${finalSummary.avgActiveProxyUtilization}% of declared route-slot capacity.`;
    } else {
      state = 'handler_constrained';
      label = 'Handler / Upstream Time Dominant';
      explanation = `Measured task service time is dominated by handler and upstream work (${exclusiveHandler.toFixed(2)}s exclusive of writer wait).`;
    }
    const writerServiceDominant = meanWriter > exclusiveHandler;
    const writerPhaseLabel =
      writerServiceDominant
      && (finalSummary.dominantWriterSubphase === 'Writer Queue'
        || finalSummary.dominantWriterSubphase === 'Producer Admission')
        ? 'Writer Queue / Admission Backpressure'
        : 'Durable Writer Wait';
    // Subphases only exist for the phases that actually break down further.
    const dominantServiceSubphase = dominantServicePhase === 'Worker Setup'
      ? finalSummary.dominantSetupSubphase
      : dominantServicePhase === writerPhaseLabel
        ? finalSummary.dominantWriterSubphase
        : dominantServicePhase === 'Handler / Upstream Work'
          ? finalSummary.dominantHandlerSubphase
          : null;
    if (hasCompleteRuntimeTelemetry) {
      rootCauseFindings.push(
        `Dominant task service phase: ${dominantServicePhase} at ${dominantServiceSeconds.toFixed(2)}s per task${dominantServiceSubphase ? `; primary measured subphase: ${dominantServiceSubphase}` : ''}.`,
      );
    }
    rootCauseFindings.unshift(
      `Full-job telemetry covers ${runtimeTelemetry?.task_count ?? 0} task attempts with ${finalSummary.avgActiveConcurrency.toFixed(1)} time-weighted in-flight tasks and ${finalSummary.avgActiveProxyRoutes} time-weighted active routes.`,
    );
    if ((finalSummary.meanQueueWaitSec ?? 0) > 0) {
      rootCauseFindings.push(
        `Mean pre-service queue age was ${finalSummary.meanQueueWaitSec?.toFixed(2)}s. It indicates backlog/admission delay, but is not part of task service time and is not ranked as an additive throughput bottleneck.`,
      );
    }
    if (finalSummary.occupancyGapExplanation) {
      rootCauseFindings.push(finalSummary.occupancyGapExplanation);
    }
  } else if (isJobActive && completedTasksCount + failedJobTasks === 0 && !hasCompleteRuntimeTelemetry) {
    state = 'insufficient_data';
    label = 'Awaiting First Completion';
    explanation = `${runningTasksCount.toLocaleString()} tasks are in flight, but none have completed. Claimed task slots do not establish active upstream requests or proxy saturation.`;
    rootCauseFindings.push('Check execution waits before interpreting route capacity or estimating completion time.');
  } else if (isProxyBottleneck) {
    state = 'proxy_saturated';
    label = 'Proxy Route Saturated';
    explanation = `Task execution is constrained by ${proxyCapacity.totalRoutes} proxy routes. Inflight concurrency (${runningTasksCount}) has reached proxy capacity while ${readyTasksCount.toLocaleString()} ready tasks await route allocation.`;
    if (workerConcurrencyDemand > proxyCapacity.totalRoutes) {
      rootCauseFindings.unshift(
        `Proxy ceiling bound: total worker concurrency demand (${workerPoolSize} workers × ${targetConcurrency} = ${workerConcurrencyDemand}) exceeds proxy capacity (${proxyCapacity.totalRoutes} routes). Adding proxy routes will directly increase throughput.`,
      );
    } else {
      rootCauseFindings.unshift(
        `Proxy ceiling bound: active route utilization reached capacity (${proxyCapacity.totalRoutes} routes). Adding proxy routes will directly increase throughput.`,
      );
    }
  } else if (isWorkerBottleneck) {
    state = 'worker_constrained';
    label = 'Worker Pool Capacity Reached';
    explanation = `Worker capacity (${workerConcurrencyDemand} task slots across ${workerPoolSize} workers) is fully engaged with ${readyTasksCount.toLocaleString()} queued tasks pending execution. Expanding the worker pool will scale throughput.`;
  } else if (isQueueStarved) {
    state = 'queue_starved';
    label = 'Pipeline Queue Starvation';
    explanation = `Workers are idling (${runningTasksCount} active of ${workerConcurrencyDemand} task slots) because the upstream task generator has not filled the ready queue.`;
  } else if (hasCompleteRuntimeTelemetry && meanHandler > 0) {
    state = 'handler_constrained';
    label = 'Handler / Upstream Time Dominant';
    explanation = `Handler and upstream work averaged ${meanHandler.toFixed(2)}s per task; refill-stage timing is needed to explain intermittent empty ready queues.`;
  }

  if (rootCauseFindings.length === 0) {
    rootCauseFindings.push(
      state === 'insufficient_data'
        ? 'Full-job runtime telemetry is incomplete. Worker participation, ready-queue supply, and service phases are unavailable, so throughput constraints cannot be established from this run.'
        : 'Telemetry indicates healthy operational equilibrium across proxy routes and worker execution.',
    );
  }

  return {
    state,
    label,
    explanation,
    rootCauseFindings,
  };
}

export interface ThroughputDiagnosticsInputs {
  currentPercentiles: LatencyPercentiles;
  details: JobDetail | undefined;
  finalSummary: FinalReportSummary;
  httpDistribution: HttpStatusBreakdown;
  job: Job | JobDetail;
  runtimeTelemetry: NonNullable<JobDetail['runtime_telemetry']> | null;
  totalProxyCapacity: number;
  workerPoolSize: number;
}

/** Decomposes the gap between achieved and modelled throughput into loss factors. */
export function buildThroughputDiagnostics({
  currentPercentiles,
  details,
  finalSummary,
  httpDistribution,
  job,
  runtimeTelemetry,
  totalProxyCapacity,
  workerPoolSize,
}: ThroughputDiagnosticsInputs): ThroughputDiagnostics {
  const effectiveMedianLatency = currentPercentiles.p50 > 0 ? currentPercentiles.p50 : 2.1;
  const effectiveServiceTime =
    finalSummary.runtimeTelemetryComplete && finalSummary.meanTaskDurationSec
      ? finalSummary.meanTaskDurationSec
      : effectiveMedianLatency;
  const effectiveRouteServiceTime =
    finalSummary.runtimeTelemetryComplete && finalSummary.meanRouteActiveDurationSec
      ? finalSummary.meanRouteActiveDurationSec
      : effectiveServiceTime;
  const p95Latency = currentPercentiles.p95 > 0 ? currentPercentiles.p95 : effectiveMedianLatency;

  const targetConcurrency = resolveTargetConcurrency(
    job,
    details,
    totalProxyCapacity,
    workerPoolSize,
  );

  const workerConcurrencyDemand = (runtimeTelemetry?.time_weighted_effective_worker_capacity ?? 0) > 0
    ? runtimeTelemetry!.time_weighted_effective_worker_capacity!
    : Math.max(1, workerPoolSize * targetConcurrency);
  const theoreticalProxyMax = finalSummary.theoreticalProxyMaxItemsPerSec
    ?? Number((totalProxyCapacity / Math.max(0.05, effectiveRouteServiceTime)).toFixed(1));
  const theoreticalWorkerMax = finalSummary.theoreticalWorkerMaxItemsPerSec
    ?? Number((workerConcurrencyDemand / Math.max(0.05, effectiveServiceTime)).toFixed(1));
  const governingCeiling = totalProxyCapacity > 0
    ? Math.min(theoreticalProxyMax, theoreticalWorkerMax) : theoreticalWorkerMax;
  const governingBottleneck: 'proxy_capacity' | 'worker_concurrency' | 'upstream_latency' =
    totalProxyCapacity > 0 && theoreticalProxyMax <= theoreticalWorkerMax ? 'proxy_capacity' : 'worker_concurrency';

  const activeConcurrency = finalSummary.avgActiveConcurrency;
  const activeRoutes = finalSummary.avgActiveProxyRoutes;
  const idleProxyRoutes = Math.max(0, totalProxyCapacity - Math.round(activeRoutes));
  const idleProxyPercent =
    totalProxyCapacity > 0
      ? Number(((idleProxyRoutes / totalProxyCapacity) * 100).toFixed(1))
      : 0;

  const proxyUtilizationPercent =
    totalProxyCapacity > 0
      ? Number(((activeRoutes / totalProxyCapacity) * 100).toFixed(1))
      : 0;

  const workerUtilizationPercent = Math.min(
    100,
    Number(((activeConcurrency / Math.max(1, workerConcurrencyDemand)) * 100).toFixed(1)),
  );

  const latencySpreadRatio = Number((p95Latency / Math.max(0.1, effectiveMedianLatency)).toFixed(2));
  const tailLatencyDragPercent =
    p95Latency > effectiveMedianLatency
      ? Math.min(
          60,
          Number(
            (
              ((p95Latency - effectiveMedianLatency) /
                (p95Latency + effectiveMedianLatency)) *
              100
            ).toFixed(1),
          ),
        )
      : 0;

  const peakToAvgRatio =
    finalSummary.peakWasCapped
      ? 1
      : finalSummary.overallAvgItemsPerSec > 0
      ? Number(
          (finalSummary.peakItemsPerSec / finalSummary.overallAvgItemsPerSec).toFixed(2),
        )
      : 1;

  const lossFactors: ThroughputLossFactor[] = [];

  if (finalSummary.runtimeTelemetryComplete) {
    const remedies: Record<string, string> = {
      'Worker Setup': 'Inspect the measured locking, event, claim, and registry subphases.',
      'Handler / Upstream Work': 'Profile upstream request stages and route-attempt latency inside the task handler.',
      'Writer Queue / Admission Backpressure': 'Improve writer batch formation and queue/refill scheduling before adding writer lanes.',
      'Durable Writer Wait': 'Inspect writer execution and commit latency before raising writer concurrency.',
      'Terminal State Update': 'Inspect finish-lock waiting, output persistence, counter updates, and archive lease duration.',
      'Release / Publication': 'Inspect worker cleanup, lock release, and progress publication.',
    };
    const phases = getServicePhases(finalSummary)
      .map(([factor, seconds]) => ({ factor, seconds, remedy: remedies[factor] }))
      .sort((a, b) => b.seconds - a.seconds);
    if (phases[0].seconds > 0) {
      lossFactors.push({
        factor: phases[0].factor,
        severity: 'high',
        estimatedLossItemsPerSec: 0,
        description: `${phases[0].factor} is the largest measured phase at ${phases[0].seconds.toFixed(2)}s per task on average. This is a measured time attribution, not an additive throughput-loss estimate.`,
        remedy: phases[0].remedy,
      });
    }
  }

  if (!finalSummary.runtimeTelemetryComplete) {
    lossFactors.push({
      factor: 'Insufficient Runtime Telemetry',
      severity: 'moderate',
      estimatedLossItemsPerSec: 0,
      description: 'Worker participation, ready-queue supply, and full-job phase measurements are unavailable. Capacity and occupancy estimates derived from lifetime throughput and sampled latency cannot establish that concurrency or claim batching is limiting.',
      remedy: 'Use a telemetry-complete run before changing worker concurrency, claim-batch size, or proxy capacity.',
    });
  }

  // 3. HTTP 429 Rate Limiting
  if (httpDistribution.rateLimit429 > 0) {
    const incidencePercent =
      (httpDistribution.rateLimit429 / Math.max(1, httpDistribution.totalObserved)) * 100;
    lossFactors.push({
      factor: 'Upstream Rate Limiting (HTTP 429)',
      severity: incidencePercent >= 5 ? 'critical' : incidencePercent >= 1 ? 'high' : incidencePercent >= 0.1 ? 'moderate' : 'low',
      estimatedLossItemsPerSec: 0,
      description: `${httpDistribution.rateLimit429} request(s) rejected by upstream API rate limiters (${incidencePercent.toFixed(2)}% observed incidence). No additive throughput loss is inferred from the count alone.`,
      remedy: 'Inspect per-route attribution first; rotate or redistribute only routes that account for the observed 429 responses.',
    });
  }

  // 4. Connection Timeouts & Resets
  if (httpDistribution.timeoutErrors > 0) {
    const incidencePercent =
      (httpDistribution.timeoutErrors / Math.max(1, httpDistribution.totalObserved)) * 100;
    lossFactors.push({
      factor: 'Connection Timeouts & Network Resets',
      severity: incidencePercent >= 5 ? 'critical' : incidencePercent >= 1 ? 'high' : incidencePercent >= 0.1 ? 'moderate' : 'low',
      estimatedLossItemsPerSec: 0,
      description: `${httpDistribution.timeoutErrors} task connection abort(s)/timeout(s) (${incidencePercent.toFixed(2)}% observed incidence). No additive throughput loss is inferred without measured occupied time.`,
      remedy: 'Capture per-route timeout attribution and upstream timing before pruning routes; inspect the handler stage identified by the evidence.',
    });
  }

  return {
    theoreticalProxyMaxItemsPerSec: theoreticalProxyMax,
    theoreticalWorkerMaxItemsPerSec: theoreticalWorkerMax,
    governingCeilingItemsPerSec: governingCeiling,
    governingBottleneck,
    activeConcurrency,
    idleProxyRoutes,
    idleProxyPercent,
    proxyUtilizationPercent,
    workerUtilizationPercent,
    workerPoolSize,
    workerConcurrencyDemand,
    targetConcurrency,
    latencySpreadRatio,
    tailLatencyDragPercent,
    peakToAvgRatio,
    lossFactors,
  };
}
