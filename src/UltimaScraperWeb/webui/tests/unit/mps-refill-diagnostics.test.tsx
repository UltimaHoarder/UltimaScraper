import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { JobDiagnosticsReport } from '../../src/features/jobs/components/JobDiagnosticsReport';
import { useJobDiagnosticsTelemetry } from '../../src/features/jobs/lib/useJobDiagnosticsTelemetry';
import type { Job, JobDetail } from '../../src/api/types/jobs';

const job = {
  job_id: 'refill-regression', status: 'running',
  metadata: { proxy_capacity: 1656, target_concurrency: 207 },
  task_stats: { total: 12058000, completed: 510630, failed: 0, inflight: 271, ready: 0 },
} as unknown as Job;

it.each([false, true])('attributes ledger admission wait with thread split=%s', async (hasThreadSplit) => {
  const completed = { ...job, status: 'completed',
    task_stats: { total: 32320, completed: 32320, failed: 0, inflight: 0, ready: 0 },
  } as unknown as Job;
  const details = { ...completed, runtime_telemetry: {
    scope: 'full_job_aggregate', task_count: 32320, active_window_ms: 149400,
    mean_task_duration_ms: 4705, mean_route_active_ms: 730,
    mean_handler_ms: 3706, mean_handler_exclusive_ms: 1084,
    mean_writer_ms: 2622, mean_post_ms: 843,
    mean_writer_admission_ms: 918.31, mean_writer_queue_ms: 900.61,
    mean_writer_batch_commands: 31.56, mean_writer_batch_fill_ratio: 0.3156,
    mean_writer_admission_capacity_wait_ms: 0.06,
    mean_writer_overhead_ms: 519, workers_seen: 7, expected_workers: 7,
    time_weighted_inflight: 1018, time_weighted_active_routes: 158,
    time_weighted_effective_worker_capacity: 1412.5,
    ledger_stats: {
      writer_prepare: { count: 32320, ms: 869.93 * 32320 },
      writer_prepare_execution: { count: 32320, ms: 466.32 * 32320 },
      writer_prepare_admission: { count: 32320, ms: 403.60 * 32320 },
      ...(hasThreadSplit ? {
        writer_prepare_thread_wait_admission: { count: 32320, ms: 303 * 32320 },
        writer_prepare_resume_admission: { count: 32320, ms: 100.60 * 32320 },
      } : {}),
    },
  } } as unknown as JobDetail;
  const { result } = renderHook(() => useJobDiagnosticsTelemetry(completed, details, [], undefined, false, 8));
  const recommendations = result.current.finalSummary.recommendations.join(' ');
  expect(recommendations).toContain('869.93ms/task of ledger checkpoint wait');
  expect(recommendations).not.toContain('dominated by 0.06ms/task');
  expect(result.current.bottleneckAnalysis.rootCauseFindings.join(' ')).toContain('466.32ms SQL call');
  expect(result.current.bottleneckAnalysis.explanation).not.toContain('SQL execution and commit were not');
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  render(<JobDiagnosticsReport telemetry={result.current} isLiveJob={false} jobId="writer-ledger" />);
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Copy Markdown Report to clipboard' })));
  const report = writeText.mock.calls[0][0] as string;
  expect(report).toContain('Writer Batch Overhead');
  expect(report).toContain('receipt/fence work');
  expect(report).toContain('31.56 commands, command-weighted mean');
  expect(report).toContain('Count committed transactions to measure mean commands per transaction.');
  expect(report).toContain('Mean thread wait | Mean event-loop resume');
  expect(report).toContain(hasThreadSplit ? '| 303.00ms | 100.60ms |' : '| Unavailable | Unavailable |');
  expect(report).not.toContain('| writer_prepare_thread_wait_admission |');
});

it('detects an empty ready queue against task slots rather than eight processes', () => {
  const { result } = renderHook(() => useJobDiagnosticsTelemetry(job, undefined, [], undefined, true, 8));
  expect(result.current.bottleneckAnalysis.state).toBe('queue_starved');
  expect(result.current.bottleneckAnalysis.explanation).toContain('1656 task slots');
});

it('uses measured route occupancy for running jobs and omits invalid drain percentages', () => {
  const details = {
    ...job, runtime_telemetry: {
      scope: 'full_job_aggregate', task_count: 510630, active_window_ms: 2263600,
      mean_task_duration_ms: 4220, mean_route_active_ms: 1720,
      time_weighted_inflight: 951, time_weighted_active_routes: 388,
      ramp_window_ms: 1000, drain_window_ms: 1760000000000,
    },
  } as unknown as JobDetail;
  const { result } = renderHook(() => useJobDiagnosticsTelemetry(job, details, [], undefined, true, 8));
  expect(result.current.finalSummary.runtimeTelemetryComplete).toBe(true);
  expect(result.current.finalSummary.avgActiveConcurrency).toBe(951);
  expect(result.current.finalSummary.avgActiveProxyRoutes).toBe(388);
  expect(result.current.finalSummary.rampDrainPercent).toBeNull();
});


it('uses connection slots and measured worker capacity instead of proxy count', () => {
  const historical = { ...job, metadata: {}, status: 'completed' } as unknown as Job;
  const details = {
    ...historical,
    mps_refill_trace: [{ stage: 'runtime_controls', controls: { proxy_connection_slots: 1656 } }],
    runtime_telemetry: {
      scope: 'full_job_aggregate', task_count: 510630, active_window_ms: 2263600,
      mean_task_duration_ms: 3860, mean_route_active_ms: 2140,
      time_weighted_inflight: 809, time_weighted_active_routes: 449,
      time_weighted_effective_worker_capacity: 1564.6,
    },
  } as unknown as JobDetail;
  const { result } = renderHook(() => useJobDiagnosticsTelemetry(historical, details, [], undefined, false, 8));
  expect(result.current.proxyCapacity.totalRoutes).toBe(1656);
  expect(result.current.throughputDiagnostics?.workerConcurrencyDemand).toBe(1564.6);
  expect(result.current.finalSummary.theoreticalWorkerMaxItemsPerSec).toBeCloseTo(405.3, 0);
  expect(result.current.finalSummary.avgActiveProxyRoutes).toBe(449);
  expect(result.current.bottleneckAnalysis.state).not.toBe('route_constrained');
});


it('does not turn opaque proxy count into connection slots when capacity evidence is missing', () => {
  const historical = { ...job, metadata: {}, status: 'completed' } as unknown as Job;
  const details = {
    ...historical,
    runtime_telemetry: {
      scope: 'full_job_aggregate', task_count: 510630, active_window_ms: 2263600,
      mean_task_duration_ms: 3860, mean_route_active_ms: 2140,
      time_weighted_inflight: 809, time_weighted_active_routes: 449,
      time_weighted_effective_worker_capacity: 1564.6,
    },
  } as unknown as JobDetail;
  const { result } = renderHook(() => useJobDiagnosticsTelemetry(historical, details, [], undefined, false, 8));
  expect(result.current.proxyCapacity.totalRoutes).toBe(0);
  expect(result.current.finalSummary.avgActiveProxyRoutes).toBe(449);
  expect(result.current.throughputDiagnostics?.governingBottleneck).toBe('worker_concurrency');
  expect(result.current.bottleneckAnalysis.state).not.toBe('route_constrained');
});


it('retains guest auth initialization counters and nested spans for reports', () => {
  const details = { ...job, runtime_telemetry: {
    guest_auth_stats: { cache_hit: { count: 100, ms: 0 }, lock_wait: { count: 5, ms: 120 }, login_timeout: { count: 2, ms: 0 } },
  } } as unknown as JobDetail;
  const { result } = renderHook(() => useJobDiagnosticsTelemetry(job, details, [], undefined, true, 8));
  expect(result.current.guestAuthStats?.lock_wait).toEqual({ count: 5, ms: 120 });
  expect(result.current.guestAuthStats?.login_timeout.count).toBe(2);
});

it('uses wall-clock elapsed time and avoids a proxy verdict before the first completion', () => {
  const startedAt = new Date(Date.now() - 240_000).toISOString();
  const waitingJob = {
    ...job,
    created_at: startedAt,
    task_stats: { total: 31_920, completed: 0, failed: 0, inflight: 1_656, ready: 343 },
  } as unknown as Job;
  const details = {
    ...waitingJob,
    started_at: startedAt,
    last_activity_at: new Date(new Date(startedAt).getTime() + 1_000).toISOString(),
  } as unknown as JobDetail;
  const { result } = renderHook(() => useJobDiagnosticsTelemetry(waitingJob, details, [], undefined, true, 8));

  expect(result.current.finalSummary.totalDurationSec).toBeGreaterThanOrEqual(240);
  expect(result.current.bottleneckAnalysis.state).toBe('insufficient_data');
  expect(result.current.bottleneckAnalysis.label).toBe('Awaiting First Completion');
  expect(result.current.bottleneckAnalysis.rootCauseFindings.join(' ')).not.toContain('Adding proxy routes');
  expect(result.current.finalSummary.recommendations.join(' ')).toContain('No tasks have completed');
  expect(result.current.finalSummary.recommendations.join(' ')).not.toContain('No anomalies detected');
});

it.each([
  ['Worker Setup', 'setup_constrained', { mean_setup_ms: 4570 }],
  ['Terminal State Update', 'terminal_constrained', { mean_post_ms: 4570 }],
  ['Release / Publication', 'release_constrained', { mean_release_ms: 4570 }],
] as const)('uses %s consistently when it is the largest service phase', async (phase, state, dominant) => {
  const completedJob = {
    ...job, status: 'completed',
    started_at: '2026-10-03T01:34:41.000Z', completed_at: '2026-10-03T01:37:25.000Z',
    task_stats: { total: 31930, completed: 31930, failed: 0, inflight: 0, ready: 0 },
  } as unknown as Job;
  const details = {
    ...completedJob,
    runtime_telemetry: {
      scope: 'full_job_aggregate', task_count: 31930, active_window_ms: 164000,
      mean_task_duration_ms: 7114, mean_route_active_ms: 890,
      mean_setup_ms: 414, mean_handler_ms: 2130, mean_handler_exclusive_ms: 1473,
      mean_writer_ms: 657, mean_post_ms: 500, mean_release_ms: 434,
      time_weighted_inflight: 1382, time_weighted_active_routes: 174,
      time_weighted_effective_worker_capacity: 1632.5,
      ...dominant,
    },
  } as unknown as JobDetail;
  const { result } = renderHook(() => useJobDiagnosticsTelemetry(completedJob, details, [], undefined, false, 8));
  expect(result.current.bottleneckAnalysis.state).toBe(state);
  expect(result.current.bottleneckAnalysis.label).toBe(`${phase} Dominant`);
  expect(result.current.bottleneckAnalysis.explanation).toContain('4.57s');
  expect(result.current.finalSummary.recommendations.join(' ')).toContain(phase);
  expect(result.current.finalSummary.recommendations.join(' ')).not.toContain('handler work is the largest');
  expect(result.current.throughputDiagnostics?.lossFactors[0].factor).toBe(phase);
  expect(result.current.throughputDiagnostics?.lossFactors[0].description).toContain('4.57s');
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  render(<JobDiagnosticsReport telemetry={result.current} isLiveJob={false} jobId="phase-regression" />);
  // The report no longer has a bottleneck card; its classification is in the copied Markdown.
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Copy Markdown Report to clipboard' })));
  const report = writeText.mock.calls[0][0] as string;
  expect(report).toContain(`**Bottleneck Classification:** ${phase} Dominant`);
  expect(report).toContain(`**Dominant Task Service Phase:** ${phase} (4.570s/task)`);
  expect(report).toContain(`${phase} is the largest measured phase`);
  expect(report).not.toContain('Handler / Upstream Work is the largest measured phase');
});
