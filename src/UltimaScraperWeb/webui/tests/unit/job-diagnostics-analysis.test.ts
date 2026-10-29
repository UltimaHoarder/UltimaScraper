import { describe, expect, it } from 'vitest';

import type { Job } from '../../src/api/types/jobs';
import {
  analyzeBottleneck,
  type BottleneckInputs,
} from '../../src/features/jobs/lib/jobDiagnosticsAnalysis';
import type { FinalReportSummary } from '../../src/features/jobs/lib/jobDiagnosticsTypes';

function inputs(overrides: Partial<BottleneckInputs> = {}): BottleneckInputs {
  return {
    completedTasksCount: 100,
    failedJobTasks: 0,
    details: undefined,
    errorVelocity: {
      totalErrors: 0,
      errorsLast60s: 0,
      safetyThresholdLimit: 25,
      safetyMarginPercent: 0,
      trend: 'stable',
      rate429Count: 0,
      rate429PerMin: 0,
    },
    httpDistribution: {
      ok200: 100,
      rateLimit429: 0,
      forbidden403: 0,
      notFound404: 0,
      serverError5xx: 0,
      timeoutErrors: 0,
      otherErrors: 0,
      totalObserved: 100,
    },
    isLiveJob: true,
    job: { job_id: 'job-1', status: 'running' } as Job,
    proxyAnomalies: [],
    proxyCapacity: {
      totalRoutes: 16,
      enabledProxies: 16,
      directRoutes: 0,
      activeRoutes: 4,
      utilizationPercent: 25,
      isNearCapacity: false,
      isSaturated: false,
    },
    readyTasksCount: 0,
    runningTasksCount: 4,
    runtimeTelemetry: null,
    totalProxyCapacity: 16,
    totalTasksCount: 1000,
    workerPoolSize: 32,
    finalSummary: {} as FinalReportSummary,
    ...overrides,
  };
}

describe('analyzeBottleneck', () => {
  it('reports proxy saturation when routes are full and work is waiting', () => {
    const result = analyzeBottleneck(inputs({
      proxyCapacity: { ...inputs().proxyCapacity, activeRoutes: 16, utilizationPercent: 100, isSaturated: true },
      runningTasksCount: 16,
      readyTasksCount: 500,
    }));

    expect(result.state).toBe('proxy_saturated');
    expect(result.label).toBe('Proxy Route Saturated');
  });

  it('refuses to diagnose a finished run without full-job runtime telemetry', () => {
    const result = analyzeBottleneck(inputs({
      isLiveJob: false,
      job: { job_id: 'job-1', status: 'completed' } as Job,
      completedTasksCount: 1000,
      runningTasksCount: 0,
    }));

    expect(result.state).toBe('insufficient_data');
    expect(result.label).toBe('Insufficient Runtime Telemetry');
  });

  it('does not report queue starvation while the last tasks drain', () => {
    const result = analyzeBottleneck(inputs({
      completedTasksCount: 998,
      runningTasksCount: 2,
      readyTasksCount: 0,
    }));

    expect(result.state).not.toBe('queue_starved');
  });

  it('reports queue starvation when idle workers have nothing ready', () => {
    const result = analyzeBottleneck(inputs({
      completedTasksCount: 100,
      runningTasksCount: 1,
      readyTasksCount: 0,
    }));

    expect(result.state).toBe('queue_starved');
  });
});
