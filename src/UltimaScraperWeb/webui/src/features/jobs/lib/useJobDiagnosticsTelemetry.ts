import { useEffect, useMemo, useRef, useState } from 'react';
import type {
  Job,
  JobDetail,
  JobRuntimeSample,
  TaskDetail,
} from '../../../api/types/jobs';
import type { NetworkProxy } from '../../../api/types/network';
import { maskProxyUrl } from './taskProxyUtils';
import {
  analyzeBottleneck,
  buildThroughputDiagnostics,
  calculatePercentiles,
  computeSafetyThresholdLimit,
  getServicePhases,
  jobSetting,
  parseTaskLatency,
  resolveTargetConcurrency,
  summarizeReadyQueueTimeline,
} from './jobDiagnosticsAnalysis';
import type {
  BottleneckAnalysis,
  ErrorVelocityStats,
  FinalReportSummary,
  JobDiagnosticsTelemetry,
  ProxyAnomaly,
  ProxyCapacityStats,
  TelemetryQuality,
  TelemetrySamplingInputs,
  TelemetrySnapshot,
  ThroughputDiagnostics,
  ThroughputStats,
} from './jobDiagnosticsTypes';

// Re-exported so existing importers keep a single entry point.
export type * from './jobDiagnosticsTypes';
export { getServicePhases, summarizeReadyQueueTimeline } from './jobDiagnosticsAnalysis';

const MAX_SNAPSHOTS = 2_048;
const NO_SNAPSHOTS: TelemetrySnapshot[] = [];

interface SampleBaseline {
  timestamp: number;
  completed: number;
  items: number;
  itemsAreAuthoritative: boolean;
  errors: number;
}

const EMPTY_BASELINE: SampleBaseline = {
  timestamp: 0,
  completed: 0,
  items: 0,
  itemsAreAuthoritative: false,
  errors: 0,
};

export function useJobDiagnosticsTelemetry(
  job: Job | JobDetail,
  details: JobDetail | undefined,
  tasks: TaskDetail[] = [],
  proxies: NetworkProxy[] | undefined = undefined,
  isLiveJob: boolean = false,
  workerPoolSize: number = 32,
  taskStatsObservedAtMs?: number,
  jobRuntimeSamples: JobRuntimeSample[] = [],
): JobDiagnosticsTelemetry {
  // History is keyed by job so switching jobs never shows the previous job's samples.
  const [snapshotHistory, setSnapshotHistory] = useState<{
    jobId: string;
    snapshots: TelemetrySnapshot[];
  }>(() => ({ jobId: job.job_id, snapshots: NO_SNAPSHOTS }));
  const snapshots =
    snapshotHistory.jobId === job.job_id ? snapshotHistory.snapshots : NO_SNAPSHOTS;
  const readyTimelineStats = useMemo(
    () => summarizeReadyQueueTimeline(jobRuntimeSamples),
    [jobRuntimeSamples],
  );
  const samplingJobIdRef = useRef(job.job_id);
  const lastStateRef = useRef<SampleBaseline>(EMPTY_BASELINE);
  const hasSampledTelemetryRef = useRef(false);
  const observedAt = taskStatsObservedAtMs ?? details?.task_stats_observed_at_ms ?? 0;
  // Derived windows use the backend observation clock that also stamps
  // snapshots; mount time only covers jobs with no observation yet.
  const [mountedAtMs] = useState(() => Date.now());
  const referenceNowMs = observedAt > 0 ? observedAt : mountedAtMs;

  const enabledProxiesCount = useMemo(() => {
    if (!proxies) return 107; // Default topology baseline
    return proxies.filter((p) => (typeof p === 'string' ? true : p.enabled !== false)).length;
  }, [proxies]);

  const includeDirectConnection = useMemo(() => {
    const fromMeta = jobSetting(job, details, 'metadata', 'include_direct_connection');
    if (fromMeta === false || fromMeta === '0' || fromMeta === 'false') return false;
    if (fromMeta === true || fromMeta === '1' || fromMeta === 'true') return true;
    const fromArgs = jobSetting(job, details, 'args', 'include_direct_connection');
    if (fromArgs === false || fromArgs === '0' || fromArgs === 'false') return false;
    if (fromArgs === true || fromArgs === '1' || fromArgs === 'true') return true;
    const isMpsJob = Boolean(
      job.metadata?.mps_manifest ||
      details?.metadata?.mps_manifest ||
      job.job_type === 'mass_profile_scrape' ||
      details?.job_type === 'mass_profile_scrape' ||
      job.metadata?.job_resource_scope === 'mps' ||
      details?.metadata?.job_resource_scope === 'mps',
    );
    if (isMpsJob) return false;
    return true;
  }, [details, job]);

  const totalProxyCapacity = useMemo(() => {
    // 1. Authoritative job metadata capacity configured by planning layer
    const metaCap =
      details?.metadata?.proxy_capacity ??
      job.metadata?.proxy_capacity ??
      job.args?.proxy_capacity;
    const numericMetaCap = Number(metaCap);
    if (Number.isFinite(numericMetaCap) && numericMetaCap > 0) {
      return numericMetaCap;
    }

    const controls = [...(details?.mps_refill_trace ?? [])].reverse()
      .find((event) => Number(event.controls?.proxy_connection_slots) > 0)?.controls;
    const observedSlots = Number(controls?.proxy_connection_slots);
    if (observedSlots > 0) return observedSlots;

    // 2. Aggregate declared max_connections across configured proxies
    if (Array.isArray(proxies) && proxies.length > 0) {
      const hasMaxConns = proxies.some(
        (p) => typeof p === 'object' && p !== null && typeof p.max_connections === 'number',
      );
      if (hasMaxConns) {
        const slots = proxies
          .filter((p) => (typeof p === 'string' ? true : p.enabled !== false))
          .reduce(
            (acc, p) =>
              acc + (typeof p === 'object' && p?.max_connections ? Number(p.max_connections) : 8),
            0,
          );
        return slots + (includeDirectConnection ? 8 : 0);
      }
    }

    // Proxy count is not connection capacity. Unknown capacity stays unavailable.
    return 0;
  }, [details, includeDirectConnection, job, proxies]);

  // Parse task latencies
  const taskLatencies = useMemo(() => {
    const latencies: number[] = [];
    for (const t of tasks) {
      const lat = parseTaskLatency(t);
      if (lat !== null) latencies.push(lat);
    }
    return latencies;
  }, [tasks]);

  const currentPercentiles = useMemo(
    () => calculatePercentiles(taskLatencies),
    [taskLatencies],
  );

  // The job detail endpoint exposes aggregate task counts but not aggregate
  // item counts. Item throughput is therefore authoritative only when the
  // loaded task set covers the complete job; otherwise report task throughput
  // explicitly instead of presenting a sampled item count as a job total.
  const aggregateTaskStats = details?.task_stats ?? job.task_stats;
  const jobCounters = job as unknown as {
    task_count?: number;
    completed_tasks?: number;
    failed_tasks?: number;
  };
  const totalJobTasks = aggregateTaskStats?.total ?? jobCounters.task_count ?? 0;
  const completedJobTasks = aggregateTaskStats?.completed ?? jobCounters.completed_tasks ?? 0;
  const failedJobTasks = aggregateTaskStats?.failed ?? jobCounters.failed_tasks ?? 0;
  const inflightJobTasks = aggregateTaskStats?.inflight ?? 0;
  const readyJobTasks = aggregateTaskStats?.ready ?? 0;
  const totalJobErrors = details?.error_stats?.total ?? job.error_stats?.total ?? failedJobTasks;
  const runtimeTelemetry = details?.runtime_telemetry ?? null;
  const runtimeTerminalTasks = completedJobTasks + failedJobTasks;
  const runtimeTelemetryComplete = Boolean(
    runtimeTelemetry &&
      runtimeTerminalTasks > 0 &&
      runtimeTelemetry.task_count >= runtimeTerminalTasks,
  );
  const isCompleteTaskSample = totalJobTasks > 0 && tasks.length >= totalJobTasks;
  const throughputUnit: 'items' | 'tasks' = isCompleteTaskSample ? 'items' : 'tasks';
  const taskCoveragePercent =
    totalJobTasks > 0
      ? Number((Math.min(100, (tasks.length / totalJobTasks) * 100)).toFixed(1))
      : 0;
  const telemetryQuality: TelemetryQuality = {
    loadedTaskCount: tasks.length,
    totalTaskCount: totalJobTasks,
    coveragePercent: taskCoveragePercent,
    isCompleteTaskSample,
    throughputUnit,
    peakScope: isCompleteTaskSample ? 'complete_job' : 'loaded_sample',
  };

  // Extract HTTP response distribution and error breakdown
  const { httpDistribution, parsed429Count } =
    useMemo(() => {
      const ok200 = completedJobTasks;
      let rateLimit429 = 0;
      let forbidden403 = 0;
      let notFound404 = 0;
      let serverError5xx = 0;
      let timeoutErrors = 0;
      let otherErrors = 0;

      // Parse error stats groups from backend
      const groups = details?.error_stats?.groups ?? job.error_stats?.groups ?? {};
      for (const [msg, count] of Object.entries(groups)) {
        const numericCount = Number(count);
        if (!Number.isFinite(numericCount) || numericCount <= 0) continue;
        const lower = msg.toLowerCase();
        if (
          lower.includes('429') ||
          lower.includes('rate limit') ||
          lower.includes('too many requests')
        ) {
          rateLimit429 += numericCount;
        } else if (
          lower.includes('403') ||
          lower.includes('forbidden') ||
          lower.includes('ip_mismatch') ||
          lower.includes('route identity')
        ) {
          forbidden403 += numericCount;
        } else if (
          lower.includes('404') ||
          lower.includes('not found') ||
          lower.includes('invalid_user') ||
          lower.includes('content_issues')
        ) {
          notFound404 += numericCount;
        } else if (
          lower.includes('500') ||
          lower.includes('502') ||
          lower.includes('503') ||
          lower.includes('504') ||
          lower.includes('server error') ||
          lower.includes('bad gateway')
        ) {
          serverError5xx += numericCount;
        } else if (
          lower.includes('timeout') ||
          lower.includes('timed out') ||
          lower.includes('connect') ||
          lower.includes('connection reset') ||
          lower.includes('proxy route(s) failed')
        ) {
          timeoutErrors += numericCount;
        } else {
          otherErrors += numericCount;
        }
      }

      // Task pages are also a valid source when aggregate error groups are
      // absent. Do not add them on top of aggregate groups, or the same
      // failures would be counted twice.
      const hasAggregateErrorGroups = Object.keys(groups).length > 0;
      let taskRateLimit429 = 0;
      let taskForbidden403 = 0;
      let taskNotFound404 = 0;
      let taskServerError5xx = 0;
      let taskTimeoutErrors = 0;
      let taskOtherErrors = 0;

      for (const t of tasks) {
        if (t.status === 'failed' && t.error) {
          const errLower = t.error.toLowerCase();
          if (errLower.includes('429') || errLower.includes('rate limit')) taskRateLimit429 += 1;
          else if (errLower.includes('403') || errLower.includes('forbidden')) taskForbidden403 += 1;
          else if (errLower.includes('404') || errLower.includes('not found')) taskNotFound404 += 1;
          else if (/\b5\d{2}\b/.test(errLower) || errLower.includes('server error') || errLower.includes('bad gateway')) {
            taskServerError5xx += 1;
          } else if (
            errLower.includes('timeout') ||
            errLower.includes('timed out') ||
            errLower.includes('connection') ||
            errLower.includes('connect')
          ) {
            taskTimeoutErrors += 1;
          } else {
            taskOtherErrors += 1;
          }
        }
      }

      if (!hasAggregateErrorGroups) {
        rateLimit429 = taskRateLimit429;
        forbidden403 = taskForbidden403;
        notFound404 = taskNotFound404;
        serverError5xx = taskServerError5xx;
        timeoutErrors = taskTimeoutErrors;
        otherErrors = taskOtherErrors;
      } else {
        // Keep aggregate counts authoritative, but preserve a category that
        // only exists in the loaded task evidence.
        if (taskRateLimit429 > 0 && rateLimit429 === 0) rateLimit429 = taskRateLimit429;
        if (taskForbidden403 > 0 && forbidden403 === 0) forbidden403 = taskForbidden403;
        if (taskNotFound404 > 0 && notFound404 === 0) notFound404 = taskNotFound404;
        if (taskServerError5xx > 0 && serverError5xx === 0) serverError5xx = taskServerError5xx;
        if (taskTimeoutErrors > 0 && timeoutErrors === 0) timeoutErrors = taskTimeoutErrors;
        if (taskOtherErrors > 0 && otherErrors === 0) otherErrors = taskOtherErrors;
      }

      const totalObserved =
        ok200 +
        rateLimit429 +
        forbidden403 +
        notFound404 +
        serverError5xx +
        timeoutErrors +
        otherErrors;

      return {
        httpDistribution: {
          ok200,
          rateLimit429,
          forbidden403,
          notFound404,
          serverError5xx,
          timeoutErrors,
          otherErrors,
          totalObserved,
        },
        parsed429Count: rateLimit429,
      };
    }, [completedJobTasks, details, job, tasks]);

  // Aggregate proxy anomalies from proxies list and tasks
  const proxyAnomalies = useMemo(() => {
    const proxyMap = new Map<
      string,
      {
        rawUrl: string;
        displayUrl: string;
        group: string | null;
        country: string | null;
        countryFlag: string | null;
        totalAttempts: number;
        failures: number;
        rateLimits429: number;
        timeouts: number;
        durations: number[];
      }
    >();

    // Seed with known proxies from API
    if (proxies) {
      for (const p of proxies) {
        proxyMap.set(p.url, {
          rawUrl: p.url,
          displayUrl: maskProxyUrl(p.url),
          group: p.group ?? null,
          country: p.geolocation?.country ?? null,
          countryFlag: p.geolocation?.flag?.emoji ?? null,
          totalAttempts: 0,
          failures: 0,
          rateLimits429: 0,
          timeouts: 0,
          durations: [],
        });
      }
    }

    const errorGroups = details?.error_stats?.groups ?? job.error_stats?.groups ?? {};
    const hasAggregateErrorGroups = Object.keys(errorGroups).length > 0;

    // Process tasks
    for (const t of tasks) {
      const payloadParams = (t.payload?.params as Record<string, unknown> | undefined);
      const proxyUrl =
        (t.payload?.guest_proxy_url as string | undefined) ??
        (payloadParams?.guest_proxy_url as string | undefined) ??
        'direct';

      if (!includeDirectConnection && proxyUrl === 'direct') {
        continue;
      }

      let entry = proxyMap.get(proxyUrl);
      if (!entry) {
        entry = {
          rawUrl: proxyUrl,
          displayUrl: maskProxyUrl(proxyUrl),
          group: null,
          country: null,
          countryFlag: null,
          totalAttempts: 0,
          failures: 0,
          rateLimits429: 0,
          timeouts: 0,
          durations: [],
        };
        proxyMap.set(proxyUrl, entry);
      }

      entry.totalAttempts += 1;
      const lat = parseTaskLatency(t);
      if (lat !== null) entry.durations.push(lat);

      if (t.status === 'failed' && !hasAggregateErrorGroups) {
        entry.failures += 1;
        const err = (t.error || '').toLowerCase();
        if (err.includes('429') || err.includes('rate')) entry.rateLimits429 += 1;
        if (err.includes('timeout') || err.includes('timed out') || err.includes('failed to initialize')) {
          entry.timeouts += 1;
        }
      }
    }

    // Inspect error stats groups for proxy mentions
    for (const [msg, count] of Object.entries(errorGroups)) {
      const numericCount = Number(count);
      if (!Number.isFinite(numericCount) || numericCount <= 0) continue;
      for (const [url, entry] of proxyMap.entries()) {
        if (url !== 'direct' && msg.includes(url)) {
          entry.failures += numericCount;
          const lower = msg.toLowerCase();
          if (lower.includes('429')) entry.rateLimits429 += numericCount;
          if (lower.includes('timeout') || lower.includes('failed to initialize')) entry.timeouts += numericCount;
        }
      }
    }

    // Build anomaly list
    const anomalies: ProxyAnomaly[] = [];
    for (const entry of proxyMap.values()) {
      if (!includeDirectConnection && entry.rawUrl === 'direct') {
        continue;
      }

      const avgLatencySec =
        entry.durations.length > 0
          ? Number(
              (
                entry.durations.reduce((a, b) => a + b, 0) /
                entry.durations.length
              ).toFixed(2),
            )
          : 0;

      const failureRatePercent =
        entry.totalAttempts > 0
          ? Number(((entry.failures / entry.totalAttempts) * 100).toFixed(1))
          : entry.failures > 0
            ? 100
            : 0;

      const anomalyScore =
        entry.failures * 3 +
        entry.rateLimits429 * 5 +
        entry.timeouts * 4 +
        (entry.durations.length > 0 && avgLatencySec > 4 ? 10 : 0);

      let status: 'critical' | 'degraded' | 'healthy' = 'healthy';
      let primaryIssue = 'Normal operation';

      if (entry.rateLimits429 >= 3 || entry.failures >= 5 || failureRatePercent > 30) {
        status = 'critical';
        primaryIssue =
          entry.rateLimits429 > 0
            ? `Excessive 429 rate limits (${entry.rateLimits429})`
            : `High error rate (${failureRatePercent}%)`;
      } else if (
        entry.timeouts > 0 ||
        (entry.durations.length > 0 && avgLatencySec > 3.5) ||
        entry.failures > 0
      ) {
        status = 'degraded';
        primaryIssue =
          entry.timeouts > 0
            ? `Connection timeouts (${entry.timeouts})`
            : `Elevated latency (${avgLatencySec}s)`;
      }

      if (anomalyScore > 0 || entry.totalAttempts > 0) {
        anomalies.push({
          proxyUrl: entry.rawUrl,
          displayUrl: entry.displayUrl,
          group: entry.group,
          country: entry.country,
          countryFlag: entry.countryFlag,
          totalAttempts: entry.totalAttempts,
          failures: entry.failures,
          rateLimits429: entry.rateLimits429,
          timeouts: entry.timeouts,
          failureRatePercent,
          avgLatencySec,
          anomalyScore,
          status,
          primaryIssue,
        });
      }
    }

    return anomalies.sort((a, b) => b.anomalyScore - a.anomalyScore || b.failures - a.failures);
  }, [details, includeDirectConnection, job, proxies, tasks]);

  const sampledItemsNow = useMemo(() => {
    const loadedItems = tasks.reduce((total, task) => total + (task.items_processed || 0), 0);
    return isCompleteTaskSample ? loadedItems : completedJobTasks;
  }, [completedJobTasks, isCompleteTaskSample, tasks]);

  // One snapshot represents one fresh backend observation. Throughput is the
  // exact counter delta divided by elapsed time between those observations.
  useEffect(() => {
    if (samplingJobIdRef.current !== job.job_id) {
      samplingJobIdRef.current = job.job_id;
      lastStateRef.current = EMPTY_BASELINE;
      hasSampledTelemetryRef.current = false;
    }
    // Use the timestamp attached to each successful backend response. Sampling a
    // repeated counter on a browser timer can manufacture zeroes and bursts when
    // an API request takes longer than the timer interval.
    const inputs: TelemetrySamplingInputs = {
      observedAt,
      completed: completedJobTasks,
      items: sampledItemsNow,
      itemsAreAuthoritative: isCompleteTaskSample,
      inflight: inflightJobTasks,
      ready: readyJobTasks,
      failed: failedJobTasks,
      errors: totalJobErrors,
      p50Latency: currentPercentiles.p50,
      p95Latency: currentPercentiles.p95,
      totalProxyCapacity,
      isLiveJob,
    };
    if (inputs.observedAt <= 0 || !Number.isFinite(inputs.observedAt)) return;
    if (details?.job_id !== job.job_id) return;

    const now = inputs.observedAt;
    const previous = lastStateRef.current;
    if (previous.timestamp > 0 && now <= previous.timestamp) return;

    const resetBaseline = () => {
      lastStateRef.current = {
        timestamp: now,
        completed: inputs.completed,
        items: inputs.items,
        itemsAreAuthoritative: inputs.itemsAreAuthoritative,
        errors: inputs.errors,
      };
      hasSampledTelemetryRef.current = true;
    };

    if (
      !hasSampledTelemetryRef.current ||
      inputs.itemsAreAuthoritative !== previous.itemsAreAuthoritative ||
      inputs.completed < previous.completed ||
      inputs.items < previous.items
    ) {
      resetBaseline();
      return;
    }

    const elapsedMs = now - previous.timestamp;
    const deltaCompleted = inputs.completed - previous.completed;
    const deltaItems = inputs.items - previous.items;
    const elapsedSeconds = elapsedMs / 1000;
    const taskRate = elapsedSeconds > 0 ? deltaCompleted / elapsedSeconds : 0;
    const itemRate = elapsedSeconds > 0 ? deltaItems / elapsedSeconds : 0;
    const calculatedInflight = inputs.inflight > 0
      ? Math.min(inputs.inflight, inputs.totalProxyCapacity)
      : !inputs.isLiveJob && taskRate > 0
        ? Math.min(
            inputs.totalProxyCapacity,
            Math.round(taskRate * (inputs.p50Latency > 0 ? inputs.p50Latency : 2.1)),
          )
        : 0;

    const newSnapshot: TelemetrySnapshot = {
      timestamp: now,
      intervalStartTimestamp: previous.timestamp,
      completedDelta: deltaCompleted,
      itemsDelta: deltaItems,
      itemsAreAuthoritative: inputs.itemsAreAuthoritative,
      itemsProcessed: inputs.items,
      completedTasks: inputs.completed,
      inflightTasks: calculatedInflight,
      readyTasks: inputs.ready,
      failedTasks: inputs.failed,
      throughputItemsPerSec: Number(itemRate.toFixed(1)),
      throughputTasksPerSec: Number(taskRate.toFixed(1)),
      p50Latency: inputs.p50Latency,
      p95Latency: inputs.p95Latency,
      activeProxies: Math.min(calculatedInflight, inputs.totalProxyCapacity),
      errorCount: inputs.errors,
    };

    const jobId = job.job_id;
    setSnapshotHistory((prev) => ({
      jobId,
      snapshots: [...(prev.jobId === jobId ? prev.snapshots : NO_SNAPSHOTS), newSnapshot].slice(
        -MAX_SNAPSHOTS,
      ),
    }));
    resetBaseline();
  }, [
    completedJobTasks,
    currentPercentiles.p50,
    currentPercentiles.p95,
    details?.job_id,
    failedJobTasks,
    inflightJobTasks,
    isCompleteTaskSample,
    isLiveJob,
    job.job_id,
    observedAt,
    readyJobTasks,
    sampledItemsNow,
    totalJobErrors,
    totalProxyCapacity,
  ]);

  // Compute rolling throughput statistics & trend
  const throughput = useMemo((): ThroughputStats => {
    const startedAt =
      details?.started_at ||
      ('started_at' in job && typeof (job as JobDetail).started_at === 'string'
        ? (job as JobDetail).started_at
        : job.created_at);

    if (snapshots.length === 0) {
      const started = startedAt ? new Date(startedAt).getTime() : 0;
      const finished = details?.completed_at ? new Date(details.completed_at).getTime() : referenceNowMs;
      const elapsedSec = Math.max(1, (finished - started) / 1000);
      const totalCompleted = completedJobTasks;
      const overallRate = Number((totalCompleted / elapsedSec).toFixed(1));

      return {
        currentItemsPerSec: isLiveJob ? 0 : overallRate,
        currentTasksPerSec: isLiveJob ? 0 : overallRate,
        sma1mItemsPerSec: isLiveJob ? 0 : overallRate,
        sma1mTasksPerSec: isLiveJob ? 0 : overallRate,
        sma5mItemsPerSec: isLiveJob ? 0 : overallRate,
        sma5mTasksPerSec: isLiveJob ? 0 : overallRate,
        currentSampleDurationSec: 0,
        sma1mWindowSec: 0,
        trend: 'steady',
        trendDeltaPercent: 0,
        throughputUnit,
      };
    }

    const latest = snapshots[snapshots.length - 1];
    const latestIntervalMs = Math.max(0, latest.timestamp - latest.intervalStartTimestamp);
    const currentItemsPerSec = latest.itemsAreAuthoritative && latestIntervalMs > 0
      ? Number((latest.itemsDelta / (latestIntervalMs / 1000)).toFixed(1))
      : 0;
    const currentTasksPerSec = latestIntervalMs > 0
      ? Number((latest.completedDelta / (latestIntervalMs / 1000)).toFixed(1))
      : 0;

    const observedRate = (windowMs: number | null, unit: 'items' | 'tasks') => {
      const end = latest.timestamp;
      const cutoff = windowMs === null ? Number.NEGATIVE_INFINITY : end - windowMs;
      let itemDelta = 0;
      let coveredMs = 0;
      for (const sample of snapshots) {
        const intervalMs = sample.timestamp - sample.intervalStartTimestamp;
        if (intervalMs <= 0) continue;
        if (unit === 'items' && !sample.itemsAreAuthoritative) continue;
        const overlapMs = Math.max(
          0,
          Math.min(sample.timestamp, end) - Math.max(sample.intervalStartTimestamp, cutoff),
        );
        if (overlapMs <= 0) continue;
        // A measured interval cannot be split into its constituent moments.
        // Keep only whole intervals instead of assuming work was uniform.
        if (overlapMs < intervalMs) continue;
        const delta = unit === 'items' ? sample.itemsDelta : sample.completedDelta;
        itemDelta += delta;
        coveredMs += intervalMs;
      }
      return {
        rate: coveredMs > 0 ? itemDelta / (coveredMs / 1000) : 0,
        coveredSeconds: coveredMs / 1000,
      };
    };

    const avg1mItems = observedRate(60_000, 'items');
    const avg1mTasks = observedRate(60_000, 'tasks');
    const avg5mItems = observedRate(300_000, 'items');
    const avg5mTasks = observedRate(300_000, 'tasks');
    const avgRecent = observedRate(5_000, throughputUnit);
    const avg1m = throughputUnit === 'items' ? avg1mItems : avg1mTasks;

    let trend: 'increasing' | 'decreasing' | 'steady' = 'steady';
    let trendDeltaPercent = 0;

    if (avg1m.rate > 0) {
      trendDeltaPercent = Number((((avgRecent.rate - avg1m.rate) / avg1m.rate) * 100).toFixed(1));
      if (trendDeltaPercent > 5) {
        trend = 'increasing';
      } else if (trendDeltaPercent < -5) {
        trend = 'decreasing';
      }
    }

    return {
      currentItemsPerSec,
      currentTasksPerSec,
      sma1mItemsPerSec: Number(avg1mItems.rate.toFixed(1)),
      sma1mTasksPerSec: Number(avg1mTasks.rate.toFixed(1)),
      sma5mItemsPerSec: Number(avg5mItems.rate.toFixed(1)),
      sma5mTasksPerSec: Number(avg5mTasks.rate.toFixed(1)),
      currentSampleDurationSec: Number((latestIntervalMs / 1000).toFixed(1)),
      sma1mWindowSec: Number(avg1m.coveredSeconds.toFixed(1)),
      trend,
      trendDeltaPercent,
      throughputUnit,
    };
  }, [
    completedJobTasks,
    details?.completed_at,
    details?.started_at,
    isLiveJob,
    job,
    referenceNowMs,
    snapshots,
    throughputUnit,
  ]);

  // Compute error velocity and safety margin
  const errorVelocity = useMemo((): ErrorVelocityStats => {
    const totalErrors = totalJobErrors;

    const now = referenceNowMs;
    const cutoff60s = now - 60000;
    const oldSnapshot = snapshots.find((s) => s.timestamp >= cutoff60s);
    let errorsLast60s = 0;

    if (oldSnapshot && snapshots.length > 0) {
      const latest = snapshots[snapshots.length - 1];
      errorsLast60s = Math.max(0, latest.errorCount - oldSnapshot.errorCount);
    } else if (snapshots.length >= 2) {
      errorsLast60s = Math.max(
        0,
        snapshots[snapshots.length - 1].errorCount - snapshots[0].errorCount,
      );
    }

    const totalTasksCount = totalJobTasks;
    const dynamicSafetyThreshold = computeSafetyThresholdLimit(job, details, totalTasksCount);

    const safetyMarginPercent = Math.min(
      100,
      Number(((errorsLast60s / Math.max(1, dynamicSafetyThreshold)) * 100).toFixed(0)),
    );

    let completedLast60s = 0;
    if (oldSnapshot && snapshots.length > 0) {
      const latest = snapshots[snapshots.length - 1];
      completedLast60s = Math.max(0, latest.completedTasks - oldSnapshot.completedTasks);
    } else if (snapshots.length >= 2) {
      completedLast60s = Math.max(
        0,
        snapshots[snapshots.length - 1].completedTasks - snapshots[0].completedTasks,
      );
    }
    const windowTerminal = completedLast60s + errorsLast60s;
    const windowErrorRate = windowTerminal > 0 ? errorsLast60s / windowTerminal : 0;

    // Check consecutive task failures from recent loaded tasks
    let consecutiveFailures = 0;
    const sortedTerminalTasks = tasks
      .filter((t) => t.status === 'completed' || t.status === 'failed')
      .sort((a, b) => {
        const timeA = a.completed_at ? new Date(a.completed_at).getTime() : 0;
        const timeB = b.completed_at ? new Date(b.completed_at).getTime() : 0;
        return timeB - timeA;
      });
    for (const t of sortedTerminalTasks) {
      if (t.status === 'failed') {
        consecutiveFailures++;
      } else {
        break;
      }
    }

    let trend: 'stable' | 'elevated' | 'critical' = 'stable';
    if (
      safetyMarginPercent >= 80 ||
      errorsLast60s >= Math.max(5, Math.ceil(dynamicSafetyThreshold * 0.8)) ||
      (windowErrorRate >= 0.3 && errorsLast60s >= Math.max(10, Math.ceil(dynamicSafetyThreshold * 0.4)))
    ) {
      trend = 'critical';
    } else if (
      safetyMarginPercent >= 50 ||
      errorsLast60s >= Math.max(3, Math.ceil(dynamicSafetyThreshold * 0.5)) ||
      (windowErrorRate >= 0.1 && errorsLast60s >= Math.max(5, Math.ceil(dynamicSafetyThreshold * 0.2))) ||
      consecutiveFailures >= 5
    ) {
      trend = 'elevated';
    }

    const startedAt =
      details?.started_at ||
      ('started_at' in job && typeof (job as JobDetail).started_at === 'string'
        ? (job as JobDetail).started_at
        : job.created_at);
    const completedAt =
      details?.completed_at ||
      ('completed_at' in job && typeof (job as JobDetail).completed_at === 'string'
        ? (job as JobDetail).completed_at
        : null);
    const jobStartMs = startedAt ? new Date(startedAt).getTime() : NaN;
    const jobEndMs = completedAt ? new Date(completedAt).getTime() : now;
    const jobDurationSec =
      Number.isFinite(jobStartMs) && Number.isFinite(jobEndMs) && jobEndMs > jobStartMs
        ? Math.max(1, (jobEndMs - jobStartMs) / 1000)
        : 1;
    const observedWindowSec =
      snapshots.length >= 2
        ? Math.max(1, (snapshots[snapshots.length - 1].timestamp - snapshots[0].timestamp) / 1000)
        : 0;
    const errorWindowStart = oldSnapshot?.timestamp ?? snapshots[0]?.timestamp ?? now;
    const errorWindowSeconds =
      snapshots.length >= 2
        ? Math.max(1, (snapshots[snapshots.length - 1].timestamp - errorWindowStart) / 1000)
        : 0;
    const hasAggregateErrorGroups = Object.keys(details?.error_stats?.groups ?? job.error_stats?.groups ?? {}).length > 0;
    const rateWindowSec = hasAggregateErrorGroups
      ? jobDurationSec
      : observedWindowSec > 0
        ? observedWindowSec
        : jobDurationSec;
    const rate429PerMin = Number((parsed429Count * (60 / Math.max(1, rateWindowSec))).toFixed(1));

    return {
      totalErrors,
      errorsLast60s,
      safetyThresholdLimit: dynamicSafetyThreshold,
      safetyMarginPercent,
      trend,
      rate429Count: parsed429Count,
      rate429PerMin,
      rate429Scope: hasAggregateErrorGroups || observedWindowSec <= 0 ? 'job_average' : 'observed_window',
      errorWindowScope: snapshots.length >= 2 ? 'observed_window' : 'job_snapshot',
      errorWindowSeconds,
    };
  }, [details, job, parsed429Count, referenceNowMs, snapshots, tasks, totalJobErrors, totalJobTasks]);

  // Proxy capacity stats
  const proxyCapacity = useMemo((): ProxyCapacityStats => {
    const inflight = inflightJobTasks;
    const activeRoutes = Math.min(inflight, totalProxyCapacity);
    const utilizationPercent = Number(
      ((activeRoutes / totalProxyCapacity) * 100).toFixed(1),
    );

    return {
      totalRoutes: totalProxyCapacity,
      enabledProxies: enabledProxiesCount,
      directRoutes: includeDirectConnection ? 1 : 0,
      activeRoutes,
      utilizationPercent,
      isNearCapacity: utilizationPercent >= 85,
      isSaturated: utilizationPercent >= 96,
      capacityUnit: 'connection_slots',
      totalSlots: totalProxyCapacity,
      activeSlots: activeRoutes,
    };
  }, [enabledProxiesCount, includeDirectConnection, inflightJobTasks, totalProxyCapacity]);

  // Reconstruct historical timeline when job is completed or snapshots are sparse
  const effectiveSnapshots = useMemo(() => {
    if (isLiveJob && snapshots.length > 0) {
      return snapshots;
    }

    const completedTasksWithTimes = tasks
      .filter((t) => t.completed_at)
      .map((t) => ({
        task: t,
        completedTime: new Date(t.completed_at!).getTime(),
        latency: parseTaskLatency(t) ?? currentPercentiles.p50,
      }))
      .filter((t) => !isNaN(t.completedTime))
      .sort((a, b) => a.completedTime - b.completedTime);

    // If live snapshots have progression during the run, use them
    const hasLiveProgression =
      snapshots.length >= 5 &&
      snapshots[snapshots.length - 1].completedTasks > snapshots[0].completedTasks;

    if (hasLiveProgression) {
      return snapshots;
    }

    if (completedTasksWithTimes.length < 2) {
      return snapshots;
    }

    const startTime = completedTasksWithTimes[0].completedTime;
    const endTime = completedTasksWithTimes[completedTasksWithTimes.length - 1].completedTime;
    const totalTimeSpan = Math.max(
      endTime - startTime,
      (details?.completed_at ? new Date(details.completed_at).getTime() : endTime) -
        (details?.started_at ? new Date(details.started_at).getTime() : startTime),
    );
    if (totalTimeSpan <= 1000) {
      return snapshots;
    }

    const totalCompleted = completedJobTasks;
    const sampleScale =
      completedTasksWithTimes.length > 0 && totalCompleted > completedTasksWithTimes.length
        ? totalCompleted / completedTasksWithTimes.length
        : 1;

    const bucketCount = Math.min(30, Math.max(10, completedTasksWithTimes.length));
    const bucketDuration = totalTimeSpan / bucketCount;
    const reconstructed: TelemetrySnapshot[] = [];

    let runningCompleted = 0;
    let runningItems = 0;
    let runningErrors = 0;

    for (let i = 0; i < bucketCount; i++) {
      const bStart = startTime + i * bucketDuration;
      const bEnd = bStart + bucketDuration;
      const inBucket = completedTasksWithTimes.filter(
        (item) => item.completedTime >= bStart && item.completedTime < bEnd,
      );

      const rawCompleted = inBucket.length;
      const rawItems = inBucket.reduce(
        (sum, item) => sum + (item.task.items_processed || 1),
        0,
      );
      const rawErrors = inBucket.filter((item) => item.task.status === 'failed').length;

      const bucketCompleted = Math.round(rawCompleted * sampleScale);
      const bucketItems =
        throughputUnit === 'items'
          ? Math.round(rawItems * sampleScale)
          : bucketCompleted;
      const bucketErrors = Math.round(rawErrors * sampleScale);

      runningCompleted += bucketCompleted;
      runningItems += bucketItems;
      runningErrors += bucketErrors;

      // Preserve the actual bucket width. A 0.5s floor would stretch short
      // completed runs and understate their throughput by changing the time
      // denominator; the peak tracker applies the separate burst ceiling.
      const durSec = Math.max(0.05, bucketDuration / 1000);
      const tasksPerSec = Number((bucketCompleted / durSec).toFixed(1));
      const itemsPerSec = Number((bucketItems / durSec).toFixed(1));

      const bucketLatencies = inBucket.map((item) => item.latency);
      const bPercentiles = calculatePercentiles(bucketLatencies);
      const bucketMedianLatency =
        bPercentiles.p50 > 0
          ? bPercentiles.p50
          : currentPercentiles.p50 > 0
            ? currentPercentiles.p50
            : 2.1;

      const bucketInflight = Math.min(
        proxyCapacity.totalRoutes,
        Math.round(tasksPerSec * bucketMedianLatency),
      );

      reconstructed.push({
        timestamp: Math.round(bEnd),
        intervalStartTimestamp: Math.round(bStart),
        completedDelta: bucketCompleted,
        itemsDelta: bucketItems,
        itemsAreAuthoritative: throughputUnit === 'items',
        itemsProcessed: runningItems,
        completedTasks: runningCompleted,
        inflightTasks: bucketInflight,
        readyTasks: Math.max(0, totalJobTasks - runningCompleted),
        failedTasks: runningErrors,
        throughputItemsPerSec: itemsPerSec,
        throughputTasksPerSec: tasksPerSec,
        p50Latency: bucketMedianLatency,
        p95Latency: bPercentiles.p95 || currentPercentiles.p95,
        activeProxies: Math.min(bucketInflight, proxyCapacity.totalRoutes),
        errorCount: runningErrors,
      });
    }

    return reconstructed;
  }, [
    currentPercentiles.p50,
    currentPercentiles.p95,
    details?.completed_at,
    details?.started_at,
    completedJobTasks,
    totalJobTasks,
    isLiveJob,
    proxyCapacity.totalRoutes,
    snapshots,
    tasks,
    throughputUnit,
  ]);

  const finalSummary = useMemo((): FinalReportSummary => {
    const startedAt =
      details?.started_at ||
      ('started_at' in job && typeof (job as JobDetail).started_at === 'string'
        ? (job as JobDetail).started_at
        : job.created_at);

    const completedAt =
      details?.completed_at ||
      ('completed_at' in job && typeof (job as JobDetail).completed_at === 'string'
        ? (job as JobDetail).completed_at
        : null) || (!isLiveJob ? details?.last_activity_at : null);

    const startTimeMs = startedAt ? new Date(startedAt).getTime() : referenceNowMs;
    const endTimeMs = completedAt ? new Date(completedAt).getTime() : referenceNowMs;
    const metadataDurationSec = Math.max(1, (endTimeMs - startTimeMs) / 1000);
    const telemetryActiveWindowSec =
      runtimeTelemetryComplete && runtimeTelemetry?.active_window_ms
        ? runtimeTelemetry.active_window_ms / 1000
        : null;
    // A job window cannot be shorter than the span of its own task executions.
    // Prefer the task aggregate only for that impossible case; a longer job
    // window may legitimately contain materialization or dispatch setup.
    const metadataWindowInvalid = Boolean(
      telemetryActiveWindowSec
      && metadataDurationSec + 1 < telemetryActiveWindowSec * 0.95,
    );
    const totalDurationSec = Math.max(
      1,
      Math.round(
        metadataWindowInvalid && telemetryActiveWindowSec
          ? telemetryActiveWindowSec
          : metadataDurationSec,
      ),
    );
    const durationDiscrepancyPercent = telemetryActiveWindowSec
      ? Number(
          (((metadataDurationSec - telemetryActiveWindowSec) / telemetryActiveWindowSec) * 100)
            .toFixed(1),
        )
      : null;

    const totalCompleted = completedJobTasks;
    const totalFailed = failedJobTasks;

    let itemsProcessedTotal = 0;
    for (const t of tasks) {
      itemsProcessedTotal += t.items_processed || 0;
    }
    if (throughputUnit === 'tasks' || itemsProcessedTotal === 0) {
      // An incomplete task page cannot be extrapolated safely: task mix and
      // items/task are not guaranteed to be uniform. Use the authoritative
      // completed-task counter and label the resulting rate as tasks/s.
      itemsProcessedTotal = totalCompleted;
    }

    const overallAvgTasksPerSec = Number((totalCompleted / totalDurationSec).toFixed(1));
    const overallAvgItemsPerSec = Number((itemsProcessedTotal / totalDurationSec).toFixed(1));

    const measuredMeanLatency =
      runtimeTelemetryComplete && runtimeTelemetry?.mean_task_duration_ms
        ? runtimeTelemetry.mean_task_duration_ms / 1000
        : null;
    const effectiveServiceTime =
      measuredMeanLatency ?? (currentPercentiles.p50 > 0 ? currentPercentiles.p50 : 2.1);
    const measuredMeanRouteActiveDuration =
      runtimeTelemetryComplete
      && runtimeTelemetry
      && runtimeTelemetry.task_count > 0
      && runtimeTelemetry.route_active_sum_ms > 0
        ? runtimeTelemetry.route_active_sum_ms / runtimeTelemetry.task_count / 1000
        : null;
    const measuredMeanRouteAttemptDuration =
      runtimeTelemetryComplete
      && runtimeTelemetry
      && runtimeTelemetry.route_attempts > 0
      && runtimeTelemetry.route_active_sum_ms > 0
        ? runtimeTelemetry.route_active_sum_ms / runtimeTelemetry.route_attempts / 1000
        : null;
    const routeAttemptsPerTask =
      runtimeTelemetryComplete && runtimeTelemetry && runtimeTelemetry.task_count > 0
        ? runtimeTelemetry.route_attempts / runtimeTelemetry.task_count
        : null;
    const effectiveRouteServiceTime = measuredMeanRouteActiveDuration ?? effectiveServiceTime;
    const theoreticalProxyMax = Number(
      (totalProxyCapacity / Math.max(0.05, effectiveRouteServiceTime)).toFixed(1),
    );
    const targetConcurrency = resolveTargetConcurrency(
      job,
      details,
      totalProxyCapacity,
      workerPoolSize,
    );
    const workerConcurrencyDemand = runtimeTelemetryComplete
      && (runtimeTelemetry?.time_weighted_effective_worker_capacity ?? 0) > 0
      ? runtimeTelemetry!.time_weighted_effective_worker_capacity!
      : Math.max(1, workerPoolSize * targetConcurrency);
    const theoreticalWorkerMax = Number(
      (workerConcurrencyDemand / effectiveServiceTime).toFixed(1),
    );
    const governingCapacity = totalProxyCapacity > 0
      ? Math.min(theoreticalProxyMax, theoreticalWorkerMax) : theoreticalWorkerMax;
    const capacityModelBottleneck: FinalReportSummary['capacityModelBottleneck'] =
      totalProxyCapacity > 0 && theoreticalProxyMax <= theoreticalWorkerMax ? 'proxy_routes' : 'worker_slots';

    // Peak tracker: bound short-lived completion bursts by the route-derived rate
    // ceiling. A database writer flush can make a polling delta look arbitrarily
    // large even though the proxy fleet could not have sustained that rate.
    const peakBurstCapItemsPerSec =
      totalProxyCapacity > 0
        ? Number((totalProxyCapacity / Math.min(effectiveRouteServiceTime, 0.5)).toFixed(1))
        : 0;
    let max1sDeltaRate = 0;
    const recordPeakRate = (rate: number) => {
      if (rate <= 0 || peakBurstCapItemsPerSec <= 0) return;
      max1sDeltaRate = Math.max(
        max1sDeltaRate,
        Number(Math.min(rate, peakBurstCapItemsPerSec).toFixed(1)),
      );
    };

    // 1. Scan live snapshots for observed Δtasks / Δt
    for (let i = 1; i < snapshots.length; i++) {
      const dt = (snapshots[i].timestamp - snapshots[i - 1].timestamp) / 1000;
      const dTasks = Math.max(0, snapshots[i].completedTasks - snapshots[i - 1].completedTasks);
      const dItems = Math.max(0, snapshots[i].itemsProcessed - snapshots[i - 1].itemsProcessed);
      if (dt >= 0.4 && dTasks > 0) {
        const rate = (throughputUnit === 'items' ? dItems : dTasks) / dt;
        recordPeakRate(rate);
      }
    }

    // 2. Scan instantaneous snapshot throughputs
    for (const s of snapshots) {
      recordPeakRate(throughputUnit === 'items' ? s.throughputItemsPerSec : s.throughputTasksPerSec);
    }

    // 3. Scan reconstructed buckets
    for (const s of effectiveSnapshots) {
      recordPeakRate(throughputUnit === 'items' ? s.throughputItemsPerSec : s.throughputTasksPerSec);
    }

    // 4. Scan 1-second sliding window across completed tasks
    const completedTasksWithTimes = tasks
      .filter((t) => t.completed_at)
      .map((t) => ({
        task: t,
        completedTime: new Date(t.completed_at!).getTime(),
      }))
      .filter((t) => !isNaN(t.completedTime))
      .sort((a, b) => a.completedTime - b.completedTime);

    if (completedTasksWithTimes.length >= 2) {
      let maxCountIn1s = 0;
      for (let i = 0; i < completedTasksWithTimes.length; i++) {
        const windowEnd = completedTasksWithTimes[i].completedTime + 1000;
        let count = 0;
        for (let j = i; j < completedTasksWithTimes.length; j++) {
          if (completedTasksWithTimes[j].completedTime <= windowEnd) {
            count += throughputUnit === 'items'
              ? (completedTasksWithTimes[j].task.items_processed || 1)
              : 1;
          } else {
            break;
          }
        }
        if (count > maxCountIn1s) maxCountIn1s = count;
      }

      if (maxCountIn1s > 0) {
        // A paginated task sample cannot be expanded into a full-job
        // one-second burst: completion timestamps are not a random sample.
        const burstFrom1s = Number(maxCountIn1s.toFixed(1));
        recordPeakRate(burstFrom1s);
      }
    }

    const peakItemsPerSec = Number(
      Math.min(
        peakBurstCapItemsPerSec,
        Math.max(
          max1sDeltaRate,
          throughputUnit === 'items' ? throughput.currentItemsPerSec : throughput.currentTasksPerSec,
          throughputUnit === 'items' ? overallAvgItemsPerSec : overallAvgTasksPerSec,
        ),
      ).toFixed(1),
    );
    const peakWasCapped = peakBurstCapItemsPerSec > 0 && peakItemsPerSec >= peakBurstCapItemsPerSec;

    const hrs = Math.floor(totalDurationSec / 3600);
    const mins = Math.floor((totalDurationSec % 3600) / 60);
    const secs = totalDurationSec % 60;
    const totalDurationFormatted =
      hrs > 0 ? `${hrs}h ${mins}m ${secs}s` : mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

    const activeWindowThroughput =
      runtimeTelemetryComplete && runtimeTelemetry && runtimeTelemetry.active_window_ms > 0
        ? runtimeTelemetry.task_count / (runtimeTelemetry.active_window_ms / 1000)
        : overallAvgItemsPerSec;
    const efficiencyPercent = Number(
      ((activeWindowThroughput / Math.max(1, governingCapacity)) * 100).toFixed(1),
    );
    const steadyStateThroughput =
      runtimeTelemetryComplete && runtimeTelemetry?.steady_throughput != null
        ? runtimeTelemetry.steady_throughput
        : null;
    const steadyServiceTime =
      runtimeTelemetryComplete && runtimeTelemetry?.steady_mean_task_duration_ms
        ? runtimeTelemetry.steady_mean_task_duration_ms / 1000
        : effectiveServiceTime;
    const steadyProxyCeiling = totalProxyCapacity / Math.max(0.05, effectiveRouteServiceTime);
    const steadyWorkerCeiling = workerConcurrencyDemand / Math.max(0.05, steadyServiceTime);
    const steadyStateCeiling = totalProxyCapacity > 0
      ? Math.min(steadyProxyCeiling, steadyWorkerCeiling) : steadyWorkerCeiling;
    const steadyStateEfficiencyPercent = steadyStateThroughput != null
      ? Number(((steadyStateThroughput / steadyStateCeiling) * 100).toFixed(1))
      : null;
    const telemetryActiveWindowMs = runtimeTelemetry?.active_window_ms ?? 0;
    const rampDrainPercent =
      runtimeTelemetryComplete && runtimeTelemetry && telemetryActiveWindowMs > 0
      && runtimeTelemetry.ramp_window_ms != null && runtimeTelemetry.drain_window_ms != null
      && runtimeTelemetry.ramp_window_ms + runtimeTelemetry.drain_window_ms <= telemetryActiveWindowMs
        ? Number((
            (((runtimeTelemetry.ramp_window_ms ?? 0) + (runtimeTelemetry.drain_window_ms ?? 0))
              / telemetryActiveWindowMs) * 100
          ).toFixed(1))
        : null;
    const workersSeen = runtimeTelemetryComplete ? (runtimeTelemetry?.workers_seen ?? 0) : null;
    const expectedWorkers = runtimeTelemetryComplete
      ? (runtimeTelemetry?.expected_workers ?? workerPoolSize)
      : null;
    const readyNonemptyPercent =
      runtimeTelemetryComplete && runtimeTelemetry?.ready_nonempty_ratio != null
        ? Number((runtimeTelemetry.ready_nonempty_ratio * 100).toFixed(1))
        : null;
    const readyNonemptySamples = runtimeTelemetryComplete
      ? (runtimeTelemetry?.ready_nonempty_samples ?? null)
      : null;
    const readySampleCount = runtimeTelemetryComplete
      ? (runtimeTelemetry?.ready_sample_count ?? null)
      : null;
    const readyTimelineNonemptyPercent = readyTimelineStats.nonemptyPercent;
    const firstStartedMs = Date.parse(runtimeTelemetry?.first_started_at ?? '');
    const lastFinishedMs = Date.parse(runtimeTelemetry?.last_finished_at ?? '');
    const steadyStartMs = firstStartedMs + (runtimeTelemetry?.ramp_window_ms ?? 0);
    const steadyEndMs = lastFinishedMs - (runtimeTelemetry?.drain_window_ms ?? 0);
    const steadyReadyStats = runtimeTelemetryComplete
      && runtimeTelemetry?.ramp_window_ms != null
      && runtimeTelemetry?.drain_window_ms != null
      && Number.isFinite(steadyStartMs) && Number.isFinite(steadyEndMs)
      && steadyEndMs > steadyStartMs
      ? summarizeReadyQueueTimeline(jobRuntimeSamples, { startMs: steadyStartMs, endMs: steadyEndMs })
      : null;
    const steadyReadyPercent = steadyReadyStats?.nonemptyPercent ?? null;
    const readyQueueRecoveryCount = runtimeTelemetryComplete
      ? (runtimeTelemetry?.ready_queue_recovery_count ?? 0)
      : 0;
    const readyQueueRecoveredTasks = runtimeTelemetryComplete
      ? (runtimeTelemetry?.ready_queue_recovered_tasks ?? 0)
      : 0;
    const maxWorkerCompletionGapMs = runtimeTelemetryComplete
      ? (runtimeTelemetry?.max_worker_completion_gap_ms ?? null)
      : null;
    let occupancyGapClassification: FinalReportSummary['occupancyGapClassification'] =
      'insufficient_data';
    let occupancyGapExplanation = 'Steady-state occupancy telemetry is unavailable.';
    if (readyQueueRecoveryCount > 0) {
      occupancyGapClassification = 'routing_stall';
      occupancyGapExplanation = `Backend routing recovery restored ${readyQueueRecoveredTasks} ready task${readyQueueRecoveredTasks === 1 ? '' : 's'} across ${readyQueueRecoveryCount} stalled-queue repair${readyQueueRecoveryCount === 1 ? '' : 's'}; the lifetime gap is a dispatch routing stall, not ordinary ramp/drain.`;
    } else if (steadyStateEfficiencyPercent != null) {
      if (
        steadyStateEfficiencyPercent >= 90
        && steadyStateEfficiencyPercent >= efficiencyPercent + 5
      ) {
        occupancyGapClassification = 'ramp_drain';
        occupancyGapExplanation = `Steady-state efficiency reached ${steadyStateEfficiencyPercent}%, while active-window efficiency was ${efficiencyPercent}%; ramp and drain boundaries account for the remaining lifetime dilution.`;
      } else if (
        expectedWorkers != null
        && expectedWorkers > 0
        && workersSeen != null
        && workersSeen < expectedWorkers
      ) {
        occupancyGapClassification = 'worker_availability';
        occupancyGapExplanation = `Only ${workersSeen} of ${expectedWorkers} expected workers participated in this job.`;
      } else if (
        steadyReadyPercent != null
        && steadyReadyPercent < 10
      ) {
        occupancyGapClassification = 'queue_starvation';
        occupancyGapExplanation = `The ready queue was non-empty during ${steadyReadyPercent}% of ${steadyReadyStats?.coveredSeconds}s of covered steady-state intervals, indicating limited runnable-work supply in that window.`;
      } else if (
        steadyStateEfficiencyPercent < 90
        && steadyReadyPercent != null
        && steadyReadyPercent < 90
      ) {
        occupancyGapClassification = 'intermittent_ready_supply';
        occupancyGapExplanation = `Steady-state efficiency remained ${steadyStateEfficiencyPercent}%, and the ready queue was non-empty during ${steadyReadyPercent}% of covered steady-state intervals. This indicates intermittent runnable-work supply in the same window.`;
      } else if (steadyStateEfficiencyPercent < 90) {
        if (steadyReadyPercent != null) {
          occupancyGapClassification = 'insufficient_data';
          occupancyGapExplanation = `Steady-state efficiency remained ${steadyStateEfficiencyPercent}% while the ready queue was non-empty during ${steadyReadyPercent}% of covered steady-state intervals and ${workersSeen ?? 0}/${expectedWorkers ?? 0} workers participated; work supply was usually present, but the remaining worker-slot or service-phase cause is not isolated by this measure.`;
        } else {
          occupancyGapClassification = 'insufficient_data';
          occupancyGapExplanation = `Steady-state efficiency remained ${steadyStateEfficiencyPercent}%. No ready-queue timeline aligned with the steady-state window is available. Task-completion samples and lifetime intervals cannot distinguish steady-state work-supply gaps from ramp, drain or service-phase waits.`;
        }
      } else {
        occupancyGapClassification = 'steady_state_saturated';
        occupancyGapExplanation = `Steady-state efficiency reached ${steadyStateEfficiencyPercent}% with the expected worker participation.`;
      }
    }

    const proxyBottleneckFactor = Number(
      (Math.min(totalProxyCapacity, workerPoolSize) / Math.max(1, workerPoolSize)).toFixed(2),
    );

    const degradedProxyCount = proxyAnomalies.filter((p) => p.status === 'degraded').length;
    const criticalProxyCount = proxyAnomalies.filter((p) => p.status === 'critical').length;
    const healthyProxyCount = Math.max(0, totalProxyCapacity - degradedProxyCount - criticalProxyCount);

    // In-flight active concurrency:
    // According to Little's Law: Inflight Concurrency = Throughput * Latency (e.g. 39.7 items/s * 1.37s ≈ 54.4 active tasks)
    const littlesLawConcurrency = Number(
      Math.min(totalProxyCapacity, overallAvgTasksPerSec * effectiveServiceTime).toFixed(1),
    );
    const measuredInflight =
      runtimeTelemetryComplete && runtimeTelemetry?.time_weighted_inflight != null
        ? runtimeTelemetry.time_weighted_inflight
        : null;
    const measuredActiveRoutes =
      runtimeTelemetryComplete && runtimeTelemetry?.time_weighted_active_routes != null
        ? runtimeTelemetry.time_weighted_active_routes
        : null;

    // Only average across buckets where completed_tasks > 0 and within the active run window (T_first_task -> T_last_task),
    // to avoid diluting the mean with empty buckets during initialization, teardown, or UI idle intervals
    const activeBuckets = effectiveSnapshots.filter((s) => {
      const hasProgress = s.throughputTasksPerSec > 0 || s.throughputItemsPerSec > 0;
      const hasInflight = s.inflightTasks > 0;
      const isWithinActiveRun = s.completedTasks > 0;
      return isWithinActiveRun && hasProgress && hasInflight;
    });

    let avgActiveConcurrency: number;
    let avgActiveProxyRoutes: number;

    const currentRunning = inflightJobTasks;

    if (!isLiveJob && littlesLawConcurrency > 0) {
      // For completed runs, Little's Law (Throughput * Latency) provides the exact
      // time-weighted average concurrency across the active run window (T_first_task -> T_last_task),
      // immune to idle bucket dilution during initialization, teardown, or UI polling intervals.
      avgActiveConcurrency = measuredInflight ?? littlesLawConcurrency;
      avgActiveProxyRoutes = Math.min(
        totalProxyCapacity,
        Math.round(measuredActiveRoutes ?? avgActiveConcurrency),
      );
    } else if (activeBuckets.length > 0) {
      const observedAvg = Number(
        (activeBuckets.reduce((acc, s) => acc + s.inflightTasks, 0) / activeBuckets.length).toFixed(1),
      );
      // Guard against dilution: if observed bucket average is significantly below Little's Law
      // due to initialization/teardown sliding window buckets, use Little's Law
      avgActiveConcurrency =
        observedAvg >= 0.75 * littlesLawConcurrency && observedAvg > 0
          ? observedAvg
          : littlesLawConcurrency > 0
            ? littlesLawConcurrency
            : observedAvg;
      avgActiveProxyRoutes = Math.min(totalProxyCapacity, Math.round(avgActiveConcurrency));
    } else {
      avgActiveConcurrency =
        littlesLawConcurrency > 0 ? littlesLawConcurrency : isLiveJob ? currentRunning : 0;
      avgActiveProxyRoutes = Math.min(totalProxyCapacity, Math.round(avgActiveConcurrency));
    }

    if (measuredInflight != null) avgActiveConcurrency = measuredInflight;
    if (measuredActiveRoutes != null) {
      avgActiveProxyRoutes = Math.round(measuredActiveRoutes);
    }

    if (avgActiveConcurrency === 0 && !isLiveJob && overallAvgTasksPerSec > 0) {
      avgActiveConcurrency = littlesLawConcurrency;
      avgActiveProxyRoutes = Math.min(totalProxyCapacity, Math.round(avgActiveConcurrency));
    }

    const avgActiveProxyUtilization =
      totalProxyCapacity > 0
        ? Number(((avgActiveProxyRoutes / totalProxyCapacity) * 100).toFixed(1))
        : 0;

    const terminationReason =
      details?.result_error ||
      ('result_error' in job && typeof (job as JobDetail).result_error === 'string'
        ? (job as JobDetail).result_error
        : null) ||
      details?.result_message ||
      ('result_message' in job && typeof (job as JobDetail).result_message === 'string'
        ? (job as JobDetail).result_message
        : null) ||
      (totalFailed > 0 ? `${totalFailed} recorded task failure(s)` : null);

    const recs: string[] = [];
    if (isLiveJob && totalCompleted + totalFailed === 0) {
      recs.push(
        `No tasks have completed after ${totalDurationFormatted}. In-flight tasks may be waiting before upstream execution; claimed task slots alone do not establish proxy saturation or a completion ETA.`,
      );
    }
    if (metadataWindowInvalid && telemetryActiveWindowSec != null) {
      recs.push(
        `Job metadata duration (${metadataDurationSec.toFixed(1)}s) was shorter than the full task-active window (${telemetryActiveWindowSec.toFixed(1)}s). Throughput and displayed duration use the task-active window for this report.`,
      );
    }
    if (totalProxyCapacity < workerPoolSize) {
      const deficit = workerPoolSize - totalProxyCapacity;
      recs.push(
        `Proxy Capacity Headroom: Current proxy pool (${totalProxyCapacity} routes) restricts concurrency below the ${workerPoolSize} worker pool. Adding ${deficit + 10} more proxies will eliminate queue contention and boost peak throughput toward ~${theoreticalWorkerMax}/s.`,
      );
    }
    if (criticalProxyCount > 0) {
      recs.push(
        `Route Health: ${criticalProxyCount} proxy route(s) triggered repeated 429 rate limits or timeouts. Use "Copy Problematic Proxies" to review and rotate these endpoints.`,
      );
    }
    if (totalFailed > 0 && totalFailed <= 1000) {
      recs.push(
        `Selective Retry Scope: ${totalFailed} task(s) failed (${((totalFailed / Math.max(1, totalCompleted + totalFailed)) * 100).toFixed(2)}% error rate). The backend supports selective retries of failed tasks without invalidating the ${totalCompleted.toLocaleString()} completed items.`,
      );
    }
    if (terminationReason && terminationReason.toLowerCase().includes('25/25')) {
      recs.push(
        `Safety Ceiling Tripped: The job halted because the non-fatal failure threshold (25 errors within 60s) was reached. Check proxy route connectivity or rate limits before restarting.`,
      );
    }
    if (!isLiveJob && totalCompleted > 0 && !runtimeTelemetryComplete) {
      recs.push(
        `Runtime telemetry covers ${runtimeTelemetry?.task_count ?? 0}/${runtimeTerminalTasks} terminal tasks. Full-job phase and occupancy measurements are unavailable; capacity estimates use lifetime throughput and sampled task latency and cannot identify a worker-concurrency or claim-batch bottleneck.`,
      );
    }
    if (!isLiveJob && runtimeTelemetryComplete && runtimeTelemetry) {
      if (occupancyGapClassification === 'routing_stall') {
        recs.push(occupancyGapExplanation);
      } else if (
        occupancyGapClassification !== 'steady_state_saturated'
        && occupancyGapClassification !== 'intermittent_ready_supply'
      ) {
        recs.push(occupancyGapExplanation);
      }
      const handlerMs = runtimeTelemetry.mean_handler_ms ?? 0;
      const writerMs = runtimeTelemetry.mean_writer_ms ?? 0;
      const exclusiveHandlerMs =
        runtimeTelemetry.mean_handler_exclusive_ms ?? Math.max(0, handlerMs - writerMs);
      const [dominantPhase, dominantSeconds] = getServicePhases({
        meanSetupSec: (runtimeTelemetry.mean_setup_ms ?? 0) / 1000,
        meanHandlerSec: exclusiveHandlerMs / 1000,
        meanWriterSec: writerMs / 1000,
        meanPostSec: (runtimeTelemetry.mean_post_ms ?? 0) / 1000,
        meanReleaseSec: (runtimeTelemetry.mean_release_ms ?? 0) / 1000,
      }).sort((a, b) => b[1] - a[1])[0];
      if (dominantPhase === 'Terminal State Update' && dominantSeconds > 0) {
        recs.push(`Terminal State Update is the largest measured phase at ${dominantSeconds.toFixed(3)}s per task. Inspect finish-lock waiting, output persistence, and the completion counter transition; compare archive lease duration with worker completion gaps.`);
      } else if (dominantPhase === 'Worker Setup' && dominantSeconds > 0) {
        recs.push(`Worker Setup is the largest measured phase at ${dominantSeconds.toFixed(3)}s per task. Inspect the measured locking, event, claim, and registry subphases before changing upstream routes.`);
      } else if (dominantPhase === 'Release / Publication' && dominantSeconds > 0) {
        recs.push(`Release / Publication is the largest measured phase at ${dominantSeconds.toFixed(3)}s per task. Inspect worker cleanup, lock release, and progress publication.`);
      } else if (writerMs >= exclusiveHandlerMs && writerMs > 0) {
        const writerSubphases = [
          ['admission', runtimeTelemetry.mean_writer_admission_ms ?? 0],
          ['writer queue', runtimeTelemetry.mean_writer_queue_ms ?? 0],
          ['SQL execution', runtimeTelemetry.mean_writer_execution_ms ?? 0],
          ['SQL commit', runtimeTelemetry.mean_writer_commit_ms ?? 0],
          ['co-batch command work', runtimeTelemetry.mean_writer_batch_peer_work_ms ?? 0],
          ['writer overhead', runtimeTelemetry.mean_writer_overhead_ms ?? 0],
          ['result delivery', runtimeTelemetry.mean_writer_delivery_ms ?? 0],
        ] as const;
        const dominantWriter = [...writerSubphases].sort((a, b) => b[1] - a[1])[0];
        const writerInternalSubphases = [
          ['connection checkout', runtimeTelemetry.mean_writer_connection_checkout_ms ?? 0],
          ['receipt lookup', runtimeTelemetry.mean_writer_receipt_lookup_ms ?? 0],
          ['receipt finalization', runtimeTelemetry.mean_writer_receipt_finalize_ms ?? 0],
          ['payload mapping', runtimeTelemetry.mean_writer_payload_ms ?? 0],
          ['user row synchronization', runtimeTelemetry.mean_writer_user_row_ms ?? 0],
          ['alias synchronization', runtimeTelemetry.mean_writer_alias_ms ?? 0],
          ['authority reconciliation', runtimeTelemetry.mean_writer_authority_ms ?? 0],
          ['profile record synchronization', runtimeTelemetry.mean_writer_profile_ms ?? 0],
          ['social synchronization', runtimeTelemetry.mean_writer_social_ms ?? 0],
          ['transaction flush', runtimeTelemetry.mean_writer_flush_ms ?? 0],
        ] as const;
        const dominantInternal = [...writerInternalSubphases].sort((a, b) => b[1] - a[1])[0];
        const configuredWriterConcurrency = runtimeTelemetry.writer_configured_concurrency ?? 0;
        const meanActiveWriterLanes = runtimeTelemetry.mean_writer_active_lanes ?? 0;
        const batchFillPercent = (runtimeTelemetry.mean_writer_batch_fill_ratio ?? 0) * 100;
        const admissionCapacityWait = runtimeTelemetry.mean_writer_admission_capacity_wait_ms ?? 0;
        const ledgerPrepareMs = (runtimeTelemetry.ledger_stats?.writer_prepare?.ms ?? 0)
          / Math.max(1, runtimeTelemetry.task_count);
        recs.push(
          dominantWriter[0] === 'writer queue' && batchFillPercent > 0 && batchFillPercent < 50
            ? `Writer batching is fragmented at ${batchFillPercent.toFixed(1)}% of the configured per-lane target while the queue dominates. Inspect operation/domain distribution and dense-wave refill timing before adding writer lanes.`
            : dominantWriter[0] === 'admission' && ledgerPrepareMs > dominantWriter[1] / 2
            ? `Writer admission includes ${ledgerPrepareMs.toFixed(2)}ms/task of ledger checkpoint wait. Inspect ledger SQL and thread admission; bounded queue-capacity wait is ${admissionCapacityWait.toFixed(2)}ms/task.`
            : dominantWriter[0] === 'admission' && admissionCapacityWait > dominantWriter[1] / 2
            ? `Writer admission is dominated by ${admissionCapacityWait.toFixed(2)}ms/task of bounded queue-capacity wait; reduce the downstream queue before expanding producer concurrency.`
            : dominantWriter[0] === 'writer queue' && configuredWriterConcurrency > 0
            ? `Writer queue dominates with ${meanActiveWriterLanes.toFixed(1)} of ${configuredWriterConcurrency} lanes active on average; the largest measured internal subphase is ${dominantInternal[0]} at ${dominantInternal[1].toFixed(2)}ms per task.`
            : dominantWriter[1] > 0
            ? `Profile and optimize ${dominantWriter[0]}; it is the largest measured writer subphase at ${(dominantWriter[1] / 1000).toFixed(3)}s per task.`
            : 'Writer subphase coverage is unavailable; inspect queue depth, execution, commit latency, and result delivery.',
        );
      } else if (exclusiveHandlerMs > 0) {
        recs.push('Profile upstream request and route-attempt stages inside the handler; handler work is the largest measured phase.');
        const writerQueueMs = runtimeTelemetry.mean_writer_queue_ms ?? 0;
        const writerAdmissionMs = runtimeTelemetry.mean_writer_admission_ms ?? 0;
        const writerSqlMs =
          (runtimeTelemetry.mean_writer_execution_ms ?? 0)
          + (runtimeTelemetry.mean_writer_commit_ms ?? 0);
        const batchFillPercent = (runtimeTelemetry.mean_writer_batch_fill_ratio ?? 0) * 100;
        if (
          writerMs > 0
          && writerQueueMs >= writerAdmissionMs
          && writerQueueMs > writerSqlMs
        ) {
          recs.push(
            batchFillPercent > 0 && batchFillPercent < 50
              ? `Secondary service-time target: writer queue wait is ${(writerQueueMs / 1000).toFixed(3)}s per task while batches average ${batchFillPercent.toFixed(1)}% fill. Improve batch formation and dense-wave refill scheduling before adding writer lanes.`
              : `Secondary service-time target: writer queue wait is ${(writerQueueMs / 1000).toFixed(3)}s per task. Inspect lane scheduling and refill timing before adding writer lanes.`,
          );
        }
      }
      if (occupancyGapClassification === 'intermittent_ready_supply') {
        recs.push(`Occupancy observation: ${occupancyGapExplanation}`);
      }
    }
    if (recs.length === 0) {
      recs.push(runtimeTelemetryComplete
        ? 'No anomalies were identified in the available runtime measurements.'
        : 'Runtime telemetry is incomplete. Verify worker participation, ready work and service-phase timing before assessing throughput.');
    }

    const rawStatus = String(details?.status || job.status || 'unknown').toLowerCase();

    return {
      jobOutcome: rawStatus,
      totalDurationFormatted,
      totalDurationSec,
      metadataDurationSec: Number(metadataDurationSec.toFixed(1)),
      telemetryActiveWindowSec:
        telemetryActiveWindowSec != null
          ? Number(telemetryActiveWindowSec.toFixed(1))
          : null,
      durationDiscrepancyPercent,
      durationSource: metadataWindowInvalid ? 'task_active_window' : 'job_metadata',
      overallAvgItemsPerSec,
      overallAvgTasksPerSec,
      peakItemsPerSec,
      efficiencyPercent,
      proxyBottleneckFactor,
      theoreticalMaxItemsPerSec: governingCapacity,
      theoreticalProxyMaxItemsPerSec: theoreticalProxyMax,
      theoreticalWorkerMaxItemsPerSec: theoreticalWorkerMax,
      capacityModelBottleneck,
      failedTaskCount: totalFailed,
      terminationReason,
      healthyProxyCount,
      degradedProxyCount,
      criticalProxyCount,
      avgActiveConcurrency,
      avgActiveProxyRoutes,
      avgActiveProxyUtilization,
      recommendations: recs,
      throughputUnit,
      peakScope: telemetryQuality.peakScope,
      peakWasCapped,
      runtimeTelemetryComplete,
      meanTaskDurationSec: measuredMeanLatency,
      meanRouteActiveDurationSec: measuredMeanRouteActiveDuration,
      meanRouteAttemptDurationSec: measuredMeanRouteAttemptDuration,
      routeAttemptsPerTask,
      routeLookupStats: runtimeTelemetryComplete && runtimeTelemetry
        ? runtimeTelemetry.route_lookup_stats ?? null
        : null,
      meanHandlerGuestInitMs: runtimeTelemetryComplete ? runtimeTelemetry?.mean_handler_guest_init_ms : null,
      handlerGuestInitCount: runtimeTelemetryComplete ? runtimeTelemetry?.handler_guest_init_count : 0,
      meanHandlerInitialLookupMs: runtimeTelemetryComplete ? runtimeTelemetry?.mean_handler_initial_lookup_ms : null,
      handlerInitialLookupCount: runtimeTelemetryComplete ? runtimeTelemetry?.handler_initial_lookup_count : 0,
      meanHandlerRefreshApiMs: runtimeTelemetryComplete ? runtimeTelemetry?.mean_handler_refresh_api_ms : null,
      handlerRefreshApiCount: runtimeTelemetryComplete ? runtimeTelemetry?.handler_refresh_api_count : 0,
      meanHandlerFallbackRetryMs: runtimeTelemetryComplete ? runtimeTelemetry?.mean_handler_fallback_retry_ms : null,
      handlerFallbackRetryCount: runtimeTelemetryComplete ? runtimeTelemetry?.handler_fallback_retry_count : 0,
      meanHandlerSerializationMs: runtimeTelemetryComplete ? runtimeTelemetry?.mean_handler_serialization_ms : null,
      handlerSerializationCount: runtimeTelemetryComplete ? runtimeTelemetry?.handler_serialization_count : 0,
      meanHandlerResidualMs: runtimeTelemetryComplete && runtimeTelemetry
        ? Math.max(
            0,
            (runtimeTelemetry.mean_handler_exclusive_ms ?? Math.max(
              0,
              (runtimeTelemetry.mean_handler_ms ?? 0) - (runtimeTelemetry.mean_writer_ms ?? 0),
            ))
              - (runtimeTelemetry.mean_handler_guest_init_ms ?? 0)
              - (runtimeTelemetry.mean_handler_initial_lookup_ms ?? 0)
              - (runtimeTelemetry.mean_handler_refresh_api_ms ?? 0)
              - (runtimeTelemetry.mean_handler_fallback_retry_ms ?? 0)
              - (runtimeTelemetry.mean_handler_serialization_ms ?? 0),
          )
        : null,
      dominantHandlerSubphase: runtimeTelemetryComplete && runtimeTelemetry
        ? ([
            ['Guest Initialization', runtimeTelemetry.mean_handler_guest_init_ms ?? 0],
            ['Initial User Lookup', runtimeTelemetry.mean_handler_initial_lookup_ms ?? 0],
            ['Refresh / Auxiliary API', runtimeTelemetry.mean_handler_refresh_api_ms ?? 0],
            ['Fallback / Retry Delay', runtimeTelemetry.mean_handler_fallback_retry_ms ?? 0],
            ['Payload Serialization', runtimeTelemetry.mean_handler_serialization_ms ?? 0],
            ['Other Handler Work', Math.max(
              0,
              (runtimeTelemetry.mean_handler_exclusive_ms ?? Math.max(
                0,
                (runtimeTelemetry.mean_handler_ms ?? 0) - (runtimeTelemetry.mean_writer_ms ?? 0),
              ))
                - (runtimeTelemetry.mean_handler_guest_init_ms ?? 0)
                - (runtimeTelemetry.mean_handler_initial_lookup_ms ?? 0)
                - (runtimeTelemetry.mean_handler_refresh_api_ms ?? 0)
                - (runtimeTelemetry.mean_handler_fallback_retry_ms ?? 0)
                - (runtimeTelemetry.mean_handler_serialization_ms ?? 0),
            )],
          ] as Array<[string, number]>).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
        : null,
      meanQueueWaitSec: runtimeTelemetryComplete && runtimeTelemetry?.mean_queue_wait_ms != null ? runtimeTelemetry.mean_queue_wait_ms / 1000 : null,
      meanSetupSec: runtimeTelemetryComplete && runtimeTelemetry?.mean_setup_ms != null ? runtimeTelemetry.mean_setup_ms / 1000 : null,
      setupSubphases: runtimeTelemetryComplete ? (runtimeTelemetry?.setup_subphases ?? null) : null,
      dominantSetupSubphase: runtimeTelemetryComplete && runtimeTelemetry?.setup_subphases
        ? (Object.entries(runtimeTelemetry.setup_subphases)
            .filter(([name]) => name !== 'residual')
            .sort((a, b) => (b[1]?.mean_ms ?? 0) - (a[1]?.mean_ms ?? 0))[0]?.[0] ?? null)
        : null,
      meanHandlerSec: runtimeTelemetryComplete && runtimeTelemetry
        ? (runtimeTelemetry.mean_handler_exclusive_ms ?? Math.max(
            0,
            (runtimeTelemetry.mean_handler_ms ?? 0) - (runtimeTelemetry.mean_writer_ms ?? 0),
          )) / 1000
        : null,
      meanWriterSec: runtimeTelemetryComplete && runtimeTelemetry?.mean_writer_ms != null ? runtimeTelemetry.mean_writer_ms / 1000 : null,
      meanPostSec: runtimeTelemetryComplete && runtimeTelemetry?.mean_post_ms != null ? runtimeTelemetry.mean_post_ms / 1000 : null,
      meanReleaseSec: runtimeTelemetryComplete && runtimeTelemetry?.mean_release_ms != null ? runtimeTelemetry.mean_release_ms / 1000 : null,
      activeWindowThroughput: runtimeTelemetryComplete ? Number(activeWindowThroughput.toFixed(1)) : null,
      steadyStateThroughput,
      steadyStateCapacityItemsPerSec: runtimeTelemetryComplete
        ? Number(steadyStateCeiling.toFixed(1))
        : null,
      steadyStateEfficiencyPercent,
      rampDrainPercent,
      meanClaimWaitMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_claim_wait_ms ?? null) : null,
      meanWriterAdmissionMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_admission_ms ?? null) : null,
      meanWriterAdmissionSerializationMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_admission_serialization_ms ?? null) : null,
      meanWriterAdmissionCapacityWaitMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_admission_capacity_wait_ms ?? null) : null,
      meanWriterAdmissionRedisMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_admission_redis_ms ?? null) : null,
      meanWriterAdmissionOverheadDetailMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_admission_overhead_detail_ms ?? null) : null,
      meanWriterQueueMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_queue_ms ?? null) : null,
      meanWriterExecutionMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_execution_ms ?? null) : null,
      meanWriterCommitMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_commit_ms ?? null) : null,
      meanWriterOverheadMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_overhead_ms ?? null) : null,
      meanWriterBatchPeerWorkMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_batch_peer_work_ms ?? null) : null,
      meanWriterDeliveryMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_delivery_ms ?? null) : null,
      meanWriterResultPublicationMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_result_publication_ms ?? null) : null,
      meanWriterResultObservationMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_result_observation_ms ?? null) : null,
      meanWriterResultDeliveryResidualMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_result_delivery_residual_ms ?? null) : null,
      writerResultDeliverySplitCoveragePercent:
        runtimeTelemetryComplete && runtimeTelemetry?.writer_result_delivery_split_coverage_ratio != null
          ? Number((runtimeTelemetry.writer_result_delivery_split_coverage_ratio * 100).toFixed(1))
          : null,
      writerTimedSubmits: runtimeTelemetryComplete
        ? (runtimeTelemetry?.writer_timed_submits ?? 0)
        : 0,
      writerSubmitsPerTask:
        runtimeTelemetryComplete && runtimeTelemetry && runtimeTelemetry.task_count > 0
          ? Number((runtimeTelemetry.writer_timed_submits / runtimeTelemetry.task_count).toFixed(3))
          : null,
      writerSubmitsPerSec:
        runtimeTelemetryComplete
        && runtimeTelemetry
        && runtimeTelemetry.active_window_ms > 0
          ? Number(
              (
                runtimeTelemetry.writer_timed_submits
                / (runtimeTelemetry.active_window_ms / 1000)
              ).toFixed(1),
            )
          : null,
      writerResultCacheHits: runtimeTelemetryComplete
        ? (runtimeTelemetry?.writer_result_cache_hits ?? 0)
        : 0,
      writerReceiptFallbacks: runtimeTelemetryComplete
        ? (runtimeTelemetry?.writer_receipt_fallbacks ?? 0)
        : 0,
      writerResultCacheHitPercent:
        runtimeTelemetryComplete && runtimeTelemetry?.writer_result_cache_hit_ratio != null
          ? Number((runtimeTelemetry.writer_result_cache_hit_ratio * 100).toFixed(1))
          : null,
      writerSplitMissingReasons: runtimeTelemetryComplete
        ? (runtimeTelemetry?.writer_split_missing_reasons ?? {})
        : {},
      writerOperationStats: runtimeTelemetryComplete
        ? (runtimeTelemetry?.writer_operation_stats ?? {})
        : {},
      writerDomainStats: runtimeTelemetryComplete
        ? (runtimeTelemetry?.writer_domain_stats ?? {})
        : {},
      writerTimingCoveragePercent:
        runtimeTelemetryComplete && runtimeTelemetry?.writer_timing_coverage_ratio != null
          ? Number((runtimeTelemetry.writer_timing_coverage_ratio * 100).toFixed(1))
          : null,
      dominantWriterSubphase: runtimeTelemetryComplete && runtimeTelemetry
        ? ([
            ['Producer Admission', runtimeTelemetry.mean_writer_admission_ms ?? 0],
            ['Writer Queue', runtimeTelemetry.mean_writer_queue_ms ?? 0],
            ['SQL Execution', runtimeTelemetry.mean_writer_execution_ms ?? 0],
            ['SQL Commit', runtimeTelemetry.mean_writer_commit_ms ?? 0],
            ['Co-batch Command Work', runtimeTelemetry.mean_writer_batch_peer_work_ms ?? 0],
            ['Writer Overhead', runtimeTelemetry.mean_writer_overhead_ms ?? 0],
            ['Result Delivery', runtimeTelemetry.mean_writer_delivery_ms ?? 0],
          ] as Array<[string, number]>).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
        : null,
      meanWriterConnectionCheckoutMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_connection_checkout_ms ?? null) : null,
      meanWriterReceiptLookupMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_receipt_lookup_ms ?? null) : null,
      meanWriterReceiptFinalizeMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_receipt_finalize_ms ?? null) : null,
      meanWriterPayloadMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_payload_ms ?? null) : null,
      meanWriterUserRowMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_user_row_ms ?? null) : null,
      meanWriterAliasMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_alias_ms ?? null) : null,
      meanWriterAuthorityMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_authority_ms ?? null) : null,
      writerAuthorityRowsExamined: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_authority_rows_examined ?? 0) : 0,
      writerAuthorityRowsSkipped: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_authority_rows_skipped ?? 0) : 0,
      writerAuthorityRowsUpserted: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_authority_rows_upserted ?? 0) : 0,
      writerAuthoritySkipPercent:
        runtimeTelemetryComplete && (runtimeTelemetry?.writer_authority_rows_examined ?? 0) > 0
          ? Number((
              ((runtimeTelemetry?.writer_authority_rows_skipped ?? 0)
                / (runtimeTelemetry?.writer_authority_rows_examined ?? 1))
              * 100
            ).toFixed(1))
          : null,
      meanWriterProfileMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_profile_ms ?? null) : null,
      meanWriterSocialMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_social_ms ?? null) : null,
      meanWriterFlushMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_flush_ms ?? null) : null,
      dominantWriterExecutionSubphase: runtimeTelemetryComplete && runtimeTelemetry
        ? ([
            ['Connection Checkout', runtimeTelemetry.mean_writer_connection_checkout_ms ?? 0],
            ['Receipt Lookup', runtimeTelemetry.mean_writer_receipt_lookup_ms ?? 0],
            ['Receipt Finalization', runtimeTelemetry.mean_writer_receipt_finalize_ms ?? 0],
            ['Payload Mapping', runtimeTelemetry.mean_writer_payload_ms ?? 0],
            ['User Row', runtimeTelemetry.mean_writer_user_row_ms ?? 0],
            ['Alias Sync', runtimeTelemetry.mean_writer_alias_ms ?? 0],
            ['Authority Reconciliation', runtimeTelemetry.mean_writer_authority_ms ?? 0],
            ['Profile Records', runtimeTelemetry.mean_writer_profile_ms ?? 0],
            ['Social Sync', runtimeTelemetry.mean_writer_social_ms ?? 0],
            ['Transaction Flush', runtimeTelemetry.mean_writer_flush_ms ?? 0],
          ] as Array<[string, number]>).sort((a, b) => b[1] - a[1])[0]?.[0] ?? null
        : null,
      meanWriterQueueCommandsAtStart: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_queue_commands_at_start ?? null) : null,
      maxWriterQueueCommandsAtStart: runtimeTelemetryComplete ? (runtimeTelemetry?.max_writer_queue_commands_at_start ?? null) : null,
      meanWriterQueueBytesAtStart: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_queue_bytes_at_start ?? null) : null,
      maxWriterQueueBytesAtStart: runtimeTelemetryComplete ? (runtimeTelemetry?.max_writer_queue_bytes_at_start ?? null) : null,
      meanWriterActiveLanes: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_active_lanes ?? null) : null,
      maxWriterActiveLanes: runtimeTelemetryComplete ? (runtimeTelemetry?.max_writer_active_lanes ?? null) : null,
      meanWriterBatchCommands: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_batch_commands ?? null) : null,
      meanWriterBatchFillPercent:
        runtimeTelemetryComplete && runtimeTelemetry?.mean_writer_batch_fill_ratio != null
          ? Number((runtimeTelemetry.mean_writer_batch_fill_ratio * 100).toFixed(1))
          : null,
      meanWriterLaneIdleMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_lane_idle_ms ?? null) : null,
      meanWriterLanePredecessorWaitMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_lane_predecessor_wait_ms ?? null) : null,
      meanWriterRefillWaitMs: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_writer_refill_wait_ms ?? null) : null,
      writerConfiguredConcurrency: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_configured_concurrency ?? null) : null,
      writerConfiguredBatchSize: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_configured_batch_size ?? null) : null,
      writerWindowCommands: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_window_commands ?? null) : null,
      writerQueueMaxCommands: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_queue_max_commands ?? null) : null,
      writerQueueMaxBytes: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_queue_max_bytes ?? null) : null,
      writerRefillMinCommands: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_refill_min_commands ?? null) : null,
      writerRefillMinCommandsPerLane: runtimeTelemetryComplete ? (runtimeTelemetry?.writer_refill_min_commands_per_lane ?? null) : null,
      maxWorkerCompletionGapMs,
      readyQueueRecoveryCount,
      readyQueueRecoveredTasks,
      readyNonemptyPercent,
      readyNonemptySamples,
      readySampleCount,
      readyTimelineNonemptyPercent,
      readyTimelineIntervalCount: readyTimelineStats.intervalCount,
      readyTimelineCoveredSeconds: readyTimelineStats.coveredSeconds,
      steadyReadyTimelineNonemptyPercent: steadyReadyPercent,
      steadyReadyTimelineCoveredSeconds: steadyReadyStats?.coveredSeconds ?? 0,
      meanReadyDepth: runtimeTelemetryComplete ? (runtimeTelemetry?.mean_ready_depth ?? null) : null,
      workersSeen,
      expectedWorkers,
      timeWeightedParticipatingWorkers: runtimeTelemetryComplete
        ? (runtimeTelemetry?.time_weighted_participating_workers ?? null)
        : null,
      timeWeightedEffectiveWorkerCapacity: runtimeTelemetryComplete
        ? (runtimeTelemetry?.time_weighted_effective_worker_capacity ?? null)
        : null,
      occupancyGapClassification,
      occupancyGapExplanation,
    };
  }, [
    completedJobTasks,
    currentPercentiles.p50,
    details,
    failedJobTasks,
    inflightJobTasks,
    runtimeTelemetry,
    runtimeTelemetryComplete,
    readyTimelineStats,
    jobRuntimeSamples,
    runtimeTerminalTasks,
    effectiveSnapshots,
    isLiveJob,
    job,
    proxyAnomalies,
    referenceNowMs,
    tasks,
    throughput.currentItemsPerSec,
    throughput.currentTasksPerSec,
    totalProxyCapacity,
    throughputUnit,
    telemetryQuality.peakScope,
    snapshots,
    workerPoolSize,
  ]);

  const runningTasksCount = inflightJobTasks;
  const readyTasksCount = readyJobTasks;
  const totalTasksCount = totalJobTasks;
  const completedTasksCount = completedJobTasks;

  const bottleneckAnalysis = useMemo<BottleneckAnalysis>(
    () =>
      analyzeBottleneck({
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
      }),
    [
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
    ],
  );

  const throughputDiagnostics = useMemo<ThroughputDiagnostics>(
    () =>
      buildThroughputDiagnostics({
        currentPercentiles,
        details,
        finalSummary,
        httpDistribution,
        job,
        runtimeTelemetry,
        totalProxyCapacity,
        workerPoolSize,
      }),
    [
      currentPercentiles,
      details,
      finalSummary,
      httpDistribution,
      job,
      runtimeTelemetry,
      totalProxyCapacity,
      workerPoolSize,
    ],
  );

  return {
    snapshots: effectiveSnapshots,
    chartSnapshots: snapshots,
    jobRuntimeSamples,
    mpsRefillTrace: details?.mps_refill_trace ?? [],
    guestAuthStats: runtimeTelemetry?.guest_auth_stats ?? {},
    terminalStats: runtimeTelemetry?.terminal_stats ?? {},
    ledgerStats: runtimeTelemetry?.ledger_stats ?? {},
    throughput,
    latencyPercentiles: currentPercentiles,
    proxyCapacity,
    httpDistribution,
    errorVelocity,
    proxyAnomalies,
    finalSummary,
    bottleneckAnalysis,
    throughputDiagnostics,
    durationBreakdown: runtimeTelemetry && runtimeTelemetry.task_count > 0
      ? {
          taskCount: runtimeTelemetry.task_count,
          expectedTaskCount: runtimeTerminalTasks || runtimeTelemetry.task_count,
          meanTaskDurationSec: runtimeTelemetry.mean_task_duration_ms != null
            ? runtimeTelemetry.mean_task_duration_ms / 1000
            : null,
          meanQueueWaitSec: runtimeTelemetry.mean_queue_wait_ms != null
            ? runtimeTelemetry.mean_queue_wait_ms / 1000
            : null,
          meanSetupSec: runtimeTelemetry.mean_setup_ms != null
            ? runtimeTelemetry.mean_setup_ms / 1000
            : null,
          meanHandlerSec: (runtimeTelemetry.mean_handler_exclusive_ms ?? Math.max(
            0,
            (runtimeTelemetry.mean_handler_ms ?? 0) - (runtimeTelemetry.mean_writer_ms ?? 0),
          )) / 1000,
          meanWriterSec: runtimeTelemetry.mean_writer_ms != null
            ? runtimeTelemetry.mean_writer_ms / 1000
            : null,
          meanPostSec: runtimeTelemetry.mean_post_ms != null
            ? runtimeTelemetry.mean_post_ms / 1000
            : null,
          meanReleaseSec: runtimeTelemetry.mean_release_ms != null
            ? runtimeTelemetry.mean_release_ms / 1000
            : null,
        }
      : null,
    runningTasksCount,
    readyTasksCount,
    totalTasksCount,
    completedTasksCount,
    isLive: isLiveJob,
    quality: telemetryQuality,
    lastSampleTime:
      snapshots.length > 0
        ? snapshots[snapshots.length - 1].timestamp
        : observedAt,
  };
}
