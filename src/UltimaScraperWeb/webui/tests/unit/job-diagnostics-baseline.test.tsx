import { fireEvent, render, renderHook, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Job, JobDetail } from '../../src/api/types/jobs';
import { JobDiagnosticsReport } from '../../src/features/jobs/components/JobDiagnosticsReport';
import { useJobDiagnosticsTelemetry } from '../../src/features/jobs/lib/useJobDiagnosticsTelemetry';

const currentJob = {
  job_id: 'job-current',
  job_name: 'Current run',
  status: 'completed',
  site: 'OnlyFans',
  created_at: '2026-10-01T12:00:00.000Z',
  started_at: '2026-10-01T12:00:00.000Z',
  completed_at: '2026-10-01T12:01:40.000Z',
  task_stats: { total: 100, completed: 100, failed: 0, ready: 0, inflight: 0 },
} as unknown as JobDetail;

function historicalJob(jobId: string, site: string, taskCount: number): Job {
  return {
    job_id: jobId,
    job_name: jobId,
    status: 'completed',
    site,
    created_at: '2026-09-01T12:00:00.000Z',
    started_at: '2026-09-01T12:00:00.000Z',
    completed_at: '2026-09-01T12:01:40.000Z',
    task_count: taskCount,
    completed_tasks: taskCount,
    failed_tasks: 0,
  } as unknown as Job;
}

const historicalJobs = [
  historicalJob('job-fansly', 'Fansly', 102),
  historicalJob('job-onlyfans', 'OnlyFans', 98),
  historicalJob('job-large', 'OnlyFans', 130),
];

function renderReport() {
  const { result } = renderHook(() => useJobDiagnosticsTelemetry(currentJob, currentJob));
  const onBaselineJobChange = vi.fn();
  render(
    <JobDiagnosticsReport
      telemetry={result.current}
      isLiveJob={false}
      jobId="job-current"
      jobName="Current run"
      site="OnlyFans"
      currentJob={currentJob}
      historicalJobs={historicalJobs}
      defaultTaskCountTolerancePercent={10}
      onBaselineJobChange={onBaselineJobChange}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
  return {
    baseline: () => screen.getByTestId('baseline-select') as HTMLSelectElement,
    tolerance: () => screen.getByTestId('tolerance-select') as HTMLSelectElement,
    onBaselineJobChange,
  };
}

describe('JobDiagnosticsReport baseline selection', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('automatically compares against a comparable run from the same site', () => {
    const { baseline, onBaselineJobChange } = renderReport();

    expect(baseline().value).toBe('job-onlyfans');
    expect(onBaselineJobChange).toHaveBeenLastCalledWith('job-onlyfans');
  });

  it('keeps comparison disabled until the tolerance changes', () => {
    const { baseline, tolerance, onBaselineJobChange } = renderReport();

    fireEvent.change(baseline(), { target: { value: '' } });
    expect(baseline().value).toBe('');
    expect(onBaselineJobChange).toHaveBeenLastCalledWith(null);

    fireEvent.change(tolerance(), { target: { value: '50' } });
    expect(baseline().value).toBe('job-onlyfans');
  });

  it('falls back to automatic selection when an explicit choice stops matching', () => {
    const { baseline, tolerance } = renderReport();

    fireEvent.change(tolerance(), { target: { value: '50' } });
    fireEvent.change(baseline(), { target: { value: 'job-large' } });
    expect(baseline().value).toBe('job-large');

    fireEvent.change(tolerance(), { target: { value: '10' } });
    expect(baseline().value).toBe('job-onlyfans');
  });
});
