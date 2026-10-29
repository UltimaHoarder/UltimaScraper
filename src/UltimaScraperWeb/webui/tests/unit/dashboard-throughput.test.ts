import { describe, expect, it } from 'vitest';

import type { Job } from '../../src/api/types/jobs';
import { chartPath } from '../../src/features/dashboard/lib/dashboardChartUtils';
import { buildJobCompletionSamples } from '../../src/features/dashboard/lib/dashboardUtils';

const job: Job = {
  job_id: 'job-mps',
  job_name: 'Profile checks',
  created_by: 'webui_mps',
  status: 'running',
  created_at: '2026-09-05T00:00:00Z',
  updated_at: null,
  task_count: 674439,
  completed_tasks: 243775,
  failed_tasks: 0,
};

describe('job completion throughput', () => {
  it('measures completed profile checks without active task samples', () => {
    const first = buildJobCompletionSamples([job], 1000, {});
    expect(first[job.job_id].rate).toBe(0);

    const next = buildJobCompletionSamples(
      [{ ...job, completed_tasks: job.completed_tasks + 112 }],
      5000,
      first,
    );
    expect(next[job.job_id].rate).toBe(28);
  });

  it('does not lose completions when events refresh faster than the sample interval', () => {
    const first = buildJobCompletionSamples([job], 1000, {});
    const fast = buildJobCompletionSamples(
      [{ ...job, completed_tasks: job.completed_tasks + 14 }], 1500, first,
    );
    const next = buildJobCompletionSamples(
      [{ ...job, completed_tasks: job.completed_tasks + 28 }], 2000, fast,
    );
    expect(next[job.job_id].rate).toBe(28);
  });

  it('handles new jobs, disappearing rows and counter resets without spikes', () => {
    const first = buildJobCompletionSamples([job], 1000, {});
    const replacement = { ...job, job_id: 'job-new', completed_tasks: 500000 };
    const next = buildJobCompletionSamples(
      [{ ...job, completed_tasks: 10 }, replacement], 5000, first,
    );
    expect(next[job.job_id].rate).toBe(0);
    expect(next[replacement.job_id].rate).toBe(0);
    expect(buildJobCompletionSamples([], 9000, next)).toEqual({});
  });

  it('resets recurring jobs and returns to zero after their last completion', () => {
    const first = buildJobCompletionSamples([job], 1000, {});
    const rerun = { ...job, run_count: 1, completed_tasks: job.completed_tasks + 100 };
    const reset = buildJobCompletionSamples([rerun], 5000, first);
    expect(reset[job.job_id].rate).toBe(0);

    const finished: Job = { ...rerun, status: 'completed', completed_tasks: rerun.completed_tasks + 4 };
    const terminal = buildJobCompletionSamples([finished], 9000, reset);
    expect(terminal[job.job_id].rate).toBe(1);
    expect(buildJobCompletionSamples([finished], 13000, terminal)[job.job_id].rate).toBe(0);
  });

  it('does not count failed tasks as successful profile completions', () => {
    const first = buildJobCompletionSamples([job], 1000, {});
    const next = buildJobCompletionSamples([{ ...job, failed_tasks: 112 }], 5000, first);
    expect(next[job.job_id].rate).toBe(0);
  });
});

describe('dashboard chart coordinates', () => {
  it('positions samples by elapsed time instead of sample count', () => {
    const path = chartPath(
      [
        { timestamp: 0, value: 0 },
        { timestamp: 1_000, value: 10 },
      ],
      640,
      180,
      10,
      0,
      10_000,
    );

    expect(path).toBe('M0.0 168.0 L64.0 12.0');
  });

  it('supports a visible-data y-axis minimum', () => {
    const path = chartPath(
      [{ timestamp: 5_000, value: 50 }],
      640,
      180,
      60,
      0,
      10_000,
      40,
    );

    expect(path).toBe('M319.0 90.0 L321.0 90.0');
  });
});
