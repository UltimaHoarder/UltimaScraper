import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { JobDetail, JobRuntimeSample } from '../../src/api/types/jobs';
import { summarizeReadyQueueTimeline, useJobDiagnosticsTelemetry } from '../../src/features/jobs/lib/useJobDiagnosticsTelemetry';

const start = Date.parse('2026-10-05T01:00:00Z');
const samples = Array.from({ length: 11 }, (_, index) => ({
  timestamp_ms: start + index * 1000,
  ready: index >= 2 && index < 8 ? 100 : 0,
}) as JobRuntimeSample);

describe('ready supply in the steady throughput window', () => {
  it('excludes empty ramp and drain intervals and clips boundary intervals', () => {
    expect(summarizeReadyQueueTimeline(samples).nonemptyPercent).toBe(60);
    expect(summarizeReadyQueueTimeline(samples, { startMs: start + 2500, endMs: start + 7500 })).toEqual({
      nonemptyPercent: 100, intervalCount: 6, coveredSeconds: 5,
    });
    expect(summarizeReadyQueueTimeline(samples, { startMs: start + 20000, endMs: start + 22000 }).nonemptyPercent).toBeNull();
  });

  it('does not classify finite-job drain as intermittent steady-state supply', () => {
    const details = {
      job_id: 'job-finite', name: 'Finite MPS', status: 'completed',
      created_at: new Date(start).toISOString(), started_at: new Date(start).toISOString(),
      completed_at: new Date(start + 10000).toISOString(),
      task_stats: { total: 100, completed: 100, failed: 0, inflight: 0, ready: 0 },
      metadata: { target_concurrency: 10 },
      runtime_telemetry: {
        task_count: 100, active_window_ms: 10000,
        first_started_at: new Date(start).toISOString(), last_finished_at: new Date(start + 10000).toISOString(),
        mean_task_duration_ms: 1000, mean_route_active_ms: 300,
        steady_throughput: 12, steady_mean_task_duration_ms: 1000,
        ramp_window_ms: 2000, drain_window_ms: 2000,
        time_weighted_effective_worker_capacity: 100,
        workers_seen: 10, expected_workers: 10,
      },
    } as unknown as JobDetail;
    const { result } = renderHook(() => useJobDiagnosticsTelemetry(details, details, [], undefined, false, 10, undefined, samples));
    expect(result.current.finalSummary.readyTimelineNonemptyPercent).toBe(60);
    expect(result.current.finalSummary.steadyReadyTimelineNonemptyPercent).toBe(100);
    expect(result.current.finalSummary.occupancyGapClassification).not.toBe('intermittent_ready_supply');
    expect(result.current.finalSummary.occupancyGapClassification).not.toBe('queue_starvation');
  });
});
