import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { JobDetail } from '../../src/api/types/jobs';
import { useJobDiagnosticsTelemetry } from '../../src/features/jobs/lib/useJobDiagnosticsTelemetry';

const start = Date.parse('2026-10-05T01:00:00Z');

function liveDetails(jobId: string, completed: number, observedAt: number, errors = 0): JobDetail {
  return {
    job_id: jobId,
    name: jobId,
    status: 'running',
    created_at: new Date(start).toISOString(),
    started_at: new Date(start).toISOString(),
    task_stats: { total: 1000, completed, failed: errors, inflight: 4, ready: 10 },
    task_stats_observed_at_ms: observedAt,
  } as unknown as JobDetail;
}

function renderTelemetry(initial: JobDetail) {
  return renderHook(
    ({ details }: { details: JobDetail }) =>
      useJobDiagnosticsTelemetry(details, details, [], undefined, true, 10, details.task_stats_observed_at_ms ?? undefined),
    { initialProps: { details: initial } },
  );
}

describe('job telemetry sampling', () => {
  it('records one snapshot per fresh backend observation', () => {
    const { result, rerender } = renderTelemetry(liveDetails('job-a', 0, start + 1_000));
    rerender({ details: liveDetails('job-a', 20, start + 3_000) });
    rerender({ details: liveDetails('job-a', 20, start + 3_000) });
    rerender({ details: liveDetails('job-a', 50, start + 6_000) });

    expect(result.current.chartSnapshots.map((snapshot) => snapshot.timestamp)).toEqual([
      start + 3_000,
      start + 6_000,
    ]);
    expect(result.current.chartSnapshots[1].throughputTasksPerSec).toBe(10);
  });

  it('drops the previous job history as soon as the job changes', () => {
    const { result, rerender } = renderTelemetry(liveDetails('job-a', 0, start + 1_000));
    rerender({ details: liveDetails('job-a', 20, start + 3_000) });
    expect(result.current.chartSnapshots).toHaveLength(1);

    rerender({ details: liveDetails('job-b', 500, start + 4_000) });
    expect(result.current.chartSnapshots).toHaveLength(0);

    rerender({ details: liveDetails('job-b', 530, start + 7_000) });
    expect(result.current.chartSnapshots).toHaveLength(1);
    expect(result.current.chartSnapshots[0].completedDelta).toBe(30);
  });

  it('measures the error window on the backend observation clock', () => {
    // The fixture observations are far from the browser clock; a browser-clock
    // window would treat every snapshot as stale.
    const { result, rerender } = renderTelemetry(liveDetails('job-a', 0, start + 1_000));
    rerender({ details: liveDetails('job-a', 10, start + 11_000, 0) });
    rerender({ details: liveDetails('job-a', 20, start + 100_000, 2) });
    rerender({ details: liveDetails('job-a', 30, start + 130_000, 6) });

    // Only the +100s and +130s observations fall inside the last 60 seconds.
    expect(result.current.errorVelocity.errorsLast60s).toBe(4);
  });
});
