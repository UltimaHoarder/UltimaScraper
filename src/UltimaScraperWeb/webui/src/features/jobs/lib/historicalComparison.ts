import type { Job, JobDetail } from '../../../api/types/jobs';
import { computeJobDurationSeconds, formatDuration, isJobRunningStatus } from './jobUtils';
import type { JobDiagnosticsTelemetry } from './useJobDiagnosticsTelemetry';
import type { JobEtaResult } from './jobEta';

export const DEFAULT_TASK_COUNT_TOLERANCE_PERCENT = 10;
const DEFAULT_TASK_COUNT_BOUNDARY = DEFAULT_TASK_COUNT_TOLERANCE_PERCENT / 100;
const TASK_COUNT_TOLERANCE_PRESETS = [5, 10, 15, 20, 25, 50, 100] as const;

export function isTaskCountTolerancePreset(percent: number): boolean {
  return (TASK_COUNT_TOLERANCE_PRESETS as readonly number[]).includes(percent);
}

export function comparableTaskCount(job?: Job | JobDetail | null): number | null {
  if (!job) return null;
  const candidate = job as Job & { task_count?: number; task_stats?: Job['task_stats'] };
  const directCount = candidate.task_count ?? candidate.task_stats?.total;
  if (typeof directCount === 'number' && Number.isFinite(directCount)) return directCount;

  const completed = candidate.completed_tasks ?? candidate.task_stats?.completed ?? 0;
  const failed = candidate.failed_tasks ?? candidate.task_stats?.failed ?? 0;
  const derivedCount = completed + failed;
  return derivedCount > 0 ? derivedCount : null;
}

export function isSimilarTaskCount(
  currentCount: number,
  candidateCount: number | null,
  toleranceBoundary: number = DEFAULT_TASK_COUNT_BOUNDARY,
): boolean {
  if (candidateCount === null || !Number.isFinite(currentCount) || currentCount < 0) return false;
  if (!Number.isFinite(candidateCount) || candidateCount < 0) return false;
  if (toleranceBoundary === Infinity || toleranceBoundary >= 1000) return true;
  if (currentCount === 0) return candidateCount === 0;
  return Math.abs(candidateCount - currentCount) / currentCount <= toleranceBoundary;
}

export interface HistoricalComparisonResult {
  hasBaseline: boolean;
  baselineJob?: {
    jobId: string;
    jobName: string;
    status: string;
    site?: string | null;
    createdAt: string;
    startedAt?: string | null;
    completedAt?: string | null;
    durationSec: number;
    durationFormatted: string;
    completedTasks: number;
    failedTasks: number;
    totalTasks: number;
    avgItemsPerSec: number;
    failureRatePercent: number;
  };
  currentRun: {
    jobId: string;
    jobName: string;
    status: string;
    startedAt?: string | null;
    completedAt?: string | null;
    durationSec: number;
    durationFormatted: string;
    elapsedSec?: number;
    elapsedFormatted?: string;
    remainingSec?: number | null;
    remainingFormatted?: string | null;
    isProjectedDuration?: boolean;
    completedTasks: number;
    failedTasks: number;
    totalTasks: number;
    avgItemsPerSec: number;
    failureRatePercent: number;
  };
  deltas: {
    throughputDeltaPercent: number;
    durationDeltaSec: number;
    durationDeltaPercent: number;
    durationComparable?: boolean;
    failureRateDeltaPercent: number;
    completedTasksDelta: number;
    status: 'regression' | 'improvement' | 'parity';
    verdictTitle: string;
    verdictMessage: string;
    keyDifferences: string[];
  };
  throughputComparable?: boolean;
}

export function computeHistoricalComparison(
  telemetry: JobDiagnosticsTelemetry,
  currentJobId: string,
  currentJobName: string,
  currentSite: string,
  isLiveJob: boolean,
  baselineJob?: Job | JobDetail | null,
  currentJob?: Job | JobDetail | null,
  toleranceBoundary: number = DEFAULT_TASK_COUNT_BOUNDARY,
  jobEta?: JobEtaResult | null,
): HistoricalComparisonResult | null {
  if (!baselineJob || isJobRunningStatus(baselineJob.status)) return null;
  void currentSite;

  const elapsedSec = telemetry.finalSummary.totalDurationSec || 1;
  const elapsedFormatted =
    telemetry.finalSummary.totalDurationFormatted || formatDuration(elapsedSec);
  const currentJobCounters = currentJob as (Job & {
    completed_tasks?: number;
    failed_tasks?: number;
    task_count?: number;
  }) | null | undefined;
  const currentCompleted = telemetry.completedTasksCount || currentJobCounters?.completed_tasks || 0;
  const currentFailed = telemetry.errorVelocity.totalErrors || currentJobCounters?.failed_tasks || 0;
  const currentTotal =
    telemetry.totalTasksCount ||
    currentJobCounters?.task_count ||
    currentJobCounters?.task_stats?.total ||
    (currentCompleted + currentFailed);
  const currentThroughput =
    telemetry.finalSummary.overallAvgItemsPerSec ||
    telemetry.throughput.currentItemsPerSec ||
    (elapsedSec > 0 ? Number((currentCompleted / elapsedSec).toFixed(1)) : 0);
  const currentFailureRate =
    currentTotal > 0 ? Number(((currentFailed / currentTotal) * 100).toFixed(1)) : 0;
  const currentThroughputUnit =
    telemetry.quality?.throughputUnit ?? telemetry.throughput.throughputUnit ?? 'items';
  const comparisonRateLabel = currentThroughputUnit === 'tasks' ? 'tasks/s' : 'items/s';
  // Historical list responses expose task counters, not aggregate item
  // counters. Only compare rates when the current run is also task-based.
  const throughputComparable = (
    (!telemetry.quality || currentThroughputUnit === 'tasks')
    && telemetry.finalSummary.durationSource !== 'task_active_window'
  );

  // Determine remaining ETA and projected duration for ongoing jobs
  let remainingSec: number | null = null;
  let isProjectedDuration = false;
  let durationComparable = true;

  if (isLiveJob) {
    if (typeof jobEta?.remainingSeconds === 'number' && Number.isFinite(jobEta.remainingSeconds)) {
      remainingSec = Math.max(0, Math.round(jobEta.remainingSeconds));
      isProjectedDuration = true;
    } else {
      const knownTotalTasks =
        telemetry.totalTasksCount ||
        currentJobCounters?.task_count ||
        currentJobCounters?.task_stats?.total ||
        0;

      if (knownTotalTasks > 0) {
        const remainingTasks = Math.max(0, knownTotalTasks - (currentCompleted + currentFailed));
        if (remainingTasks === 0) {
          remainingSec = 0;
          isProjectedDuration = true;
        } else if (currentCompleted > 0 && elapsedSec > 0) {
          remainingSec = Math.max(0, Math.round((elapsedSec * remainingTasks) / currentCompleted));
          isProjectedDuration = true;
        } else if (currentThroughput > 0) {
          remainingSec = Math.max(0, Math.round(remainingTasks / currentThroughput));
          isProjectedDuration = true;
        }
      }
    }

    if (!isProjectedDuration) {
      // Live job without a known total task count or valid ETA cannot compare elapsed time to full baseline runtime
      durationComparable = false;
    }
  }

  const currentDurationSec = isProjectedDuration && remainingSec !== null
    ? elapsedSec + remainingSec
    : elapsedSec;
  const currentDurationFormatted = formatDuration(currentDurationSec);
  const remainingFormatted = remainingSec !== null ? formatDuration(remainingSec) : null;

  // Baseline timing & stats: compute active execution duration (started_at to completed_at)
  // falling back to created_at only when started_at is omitted.
  const baselineStarted = baselineJob.started_at || baselineJob.created_at || null;
  const baselineDurationSec = computeJobDurationSeconds(baselineJob);
  const baselineDurationFormatted = formatDuration(baselineDurationSec);
  const baselineFinished =
    baselineJob.completed_at ||
    baselineJob.last_ran_at ||
    baselineJob.last_activity_at ||
    baselineJob.updated_at ||
    null;

  const baselineJobCounters = baselineJob as (Job & {
    completed_tasks?: number;
    failed_tasks?: number;
    task_count?: number;
  });
  const baselineCompleted =
    baselineJobCounters.completed_tasks ?? baselineJob.task_stats?.completed ?? 0;
  const baselineFailed = baselineJobCounters.failed_tasks ?? baselineJob.task_stats?.failed ?? 0;
  const baselineTotal =
    baselineJobCounters.task_count ??
    baselineJob.task_stats?.total ??
    (baselineCompleted + baselineFailed);

  const baselineThroughput =
    baselineDurationSec > 0 && baselineCompleted > 0
      ? Number((baselineCompleted / baselineDurationSec).toFixed(1))
      : 0;
  const baselineFailureRate =
    baselineTotal > 0 ? Number(((baselineFailed / baselineTotal) * 100).toFixed(1)) : 0;

  const throughputDeltaPercent =
    throughputComparable && baselineThroughput > 0
      ? Number((((currentThroughput - baselineThroughput) / baselineThroughput) * 100).toFixed(1))
      : 0;
  const durationDeltaSec = durationComparable ? currentDurationSec - baselineDurationSec : 0;
  const durationDeltaPercent =
    durationComparable && baselineDurationSec > 0
      ? Number((((currentDurationSec - baselineDurationSec) / baselineDurationSec) * 100).toFixed(1))
      : 0;
  const failureRateDeltaPercent = Number((currentFailureRate - baselineFailureRate).toFixed(1));
  const completedTasksDelta = currentCompleted - baselineCompleted;

  let status: 'regression' | 'improvement' | 'parity' = 'parity';
  let verdictTitle = 'Performance Parity (Nominal)';
  let verdictMessage = `Performance metrics are within normal variance compared to baseline run (${baselineJob.job_id}).`;

  const workloadComparable =
    baselineTotal > 0 && isSimilarTaskCount(currentTotal, baselineTotal, toleranceBoundary);

  if (
    (throughputComparable && throughputDeltaPercent <= -10) ||
    failureRateDeltaPercent >= 3.0 ||
    (durationComparable && durationDeltaPercent >= 25 && workloadComparable)
  ) {
    status = 'regression';
    if (throughputComparable && throughputDeltaPercent <= -10 && failureRateDeltaPercent >= 3.0) {
      verdictTitle = `Performance Regression: Throughput Drop (${throughputDeltaPercent}%) & Error Spike (+${failureRateDeltaPercent}%)`;
      verdictMessage = `Throughput dropped from ${baselineThroughput} to ${currentThroughput} ${comparisonRateLabel} while error rate spiked from ${baselineFailureRate}% to ${currentFailureRate}%. Check route degradation or upstream rate limiting.`;
    } else if (throughputComparable && throughputDeltaPercent <= -10) {
      verdictTitle = `Performance Regression: ${Math.abs(throughputDeltaPercent)}% Throughput Degradation`;
      verdictMessage = `Throughput decreased from ${baselineThroughput} ${comparisonRateLabel} in baseline to ${currentThroughput} ${comparisonRateLabel} (-${Math.abs(throughputDeltaPercent)}%). Current-run diagnosis: ${telemetry.bottleneckAnalysis.label}.`;
    } else if (failureRateDeltaPercent >= 3.0) {
      verdictTitle = `Reliability Regression: +${failureRateDeltaPercent}% Failure Rate Spike`;
      verdictMessage = `Task failure rate jumped from ${baselineFailureRate}% in baseline to ${currentFailureRate}%. Check API error distribution and blocked proxies.`;
    } else {
      verdictTitle = `Duration Regression: +${durationDeltaPercent}% Runtime Drift`;
      verdictMessage = `Job took ${formatDuration(Math.abs(durationDeltaSec))} longer to complete than baseline despite comparable task volumes.`;
    }
  } else if (throughputComparable && throughputDeltaPercent >= 10 && failureRateDeltaPercent <= 0.5) {
    status = 'improvement';
    verdictTitle = `Performance Improvement: +${throughputDeltaPercent}% Throughput Gain`;
    verdictMessage = `Current run achieved ${currentThroughput} ${comparisonRateLabel} vs baseline ${baselineThroughput} ${comparisonRateLabel} (+${throughputDeltaPercent}%) with stable reliability.`;
  }

  if (!throughputComparable) {
    verdictTitle = 'Throughput Comparison Unavailable';
    verdictMessage = 'The current run reports item throughput, but the selected historical summary only exposes task counts. Compare runs after loading a compatible item-level baseline.';
  }

  const keyDifferences: string[] = [];
  if (throughputDeltaPercent !== 0) {
    keyDifferences.push(
      throughputDeltaPercent < 0
        ? `Throughput regressed by ${Math.abs(throughputDeltaPercent)}% (${currentThroughput} ${comparisonRateLabel} vs baseline ${baselineThroughput} ${comparisonRateLabel})`
        : `Throughput improved by +${throughputDeltaPercent}% (${currentThroughput} ${comparisonRateLabel} vs baseline ${baselineThroughput} ${comparisonRateLabel})`,
    );
  }
  if (durationComparable && Math.abs(durationDeltaSec) >= 5) {
    keyDifferences.push(
      isProjectedDuration
        ? durationDeltaSec > 0
          ? `Projected runtime duration increased by ${formatDuration(durationDeltaSec)} (~${currentDurationFormatted} vs baseline ${baselineDurationFormatted})`
          : `Projected runtime duration reduced by ${formatDuration(Math.abs(durationDeltaSec))} (~${currentDurationFormatted} vs baseline ${baselineDurationFormatted})`
        : durationDeltaSec > 0
          ? `Runtime duration increased by ${formatDuration(durationDeltaSec)} (${currentDurationFormatted} vs baseline ${baselineDurationFormatted})`
          : `Runtime duration reduced by ${formatDuration(Math.abs(durationDeltaSec))} (${currentDurationFormatted} vs baseline ${baselineDurationFormatted})`,
    );
  } else if (!durationComparable && isLiveJob) {
    keyDifferences.push(
      `Job is in progress (${elapsedFormatted} elapsed); final duration delta will be calculated once completed or once task count is known.`,
    );
  }
  if (Math.abs(failureRateDeltaPercent) >= 0.1) {
    keyDifferences.push(
      failureRateDeltaPercent > 0
        ? `Failure rate increased by +${failureRateDeltaPercent}% (${currentFailureRate}% vs baseline ${baselineFailureRate}%)`
        : `Failure rate decreased by ${Math.abs(failureRateDeltaPercent)}% (${currentFailureRate}% vs baseline ${baselineFailureRate}%)`,
    );
  }
  if (completedTasksDelta !== 0) {
    keyDifferences.push(
      `Workload scale: ${currentCompleted.toLocaleString()} completed tasks vs baseline ${baselineCompleted.toLocaleString()} tasks (${completedTasksDelta > 0 ? '+' : ''}${completedTasksDelta.toLocaleString()})`,
    );
  }
  if (!throughputComparable) {
    keyDifferences.unshift(
      'Throughput delta unavailable: current item rate cannot be compared with the baseline task rate.',
    );
  }

  return {
    hasBaseline: true,
    baselineJob: {
      jobId: baselineJob.job_id,
      jobName: baselineJob.job_name ?? baselineJob.job_id,
      status: baselineJob.status,
      site: baselineJob.site,
      createdAt: baselineJob.created_at ?? '',
      startedAt: baselineStarted,
      completedAt: baselineFinished || null,
      durationSec: baselineDurationSec,
      durationFormatted: baselineDurationFormatted,
      completedTasks: baselineCompleted,
      failedTasks: baselineFailed,
      totalTasks: baselineTotal,
      avgItemsPerSec: baselineThroughput,
      failureRatePercent: baselineFailureRate,
    },
    currentRun: {
      jobId: currentJobId,
      jobName: currentJobName,
      status: isLiveJob
        ? 'running'
        : (telemetry.finalSummary.jobOutcome || currentJob?.status || 'completed'),
      startedAt:
        typeof currentJob?.started_at === 'string'
          ? currentJob.started_at || null
          : currentJob?.created_at || null,
      completedAt: currentJob?.completed_at || null,
      durationSec: currentDurationSec,
      durationFormatted: currentDurationFormatted,
      elapsedSec,
      elapsedFormatted,
      remainingSec,
      remainingFormatted,
      isProjectedDuration,
      completedTasks: currentCompleted,
      failedTasks: currentFailed,
      totalTasks: currentTotal,
      avgItemsPerSec: currentThroughput,
      failureRatePercent: currentFailureRate,
    },
    deltas: {
      throughputDeltaPercent,
      durationDeltaSec,
      durationDeltaPercent,
      durationComparable,
      failureRateDeltaPercent,
      completedTasksDelta,
      status,
      verdictTitle,
      verdictMessage,
      keyDifferences,
    },
    throughputComparable,
  };
}
