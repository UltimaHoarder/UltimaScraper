import { describe, expect, it } from 'vitest';

import {
  getNonOverlappingRefetchInterval,
  isJobLifecycleRefreshEvent,
} from '../../src/features/jobs/lib/jobLiveRefresh';

describe('job live refresh policy', () => {
  it('refreshes on bounded job lifecycle transitions only', () => {
    expect(isJobLifecycleRefreshEvent('job_created')).toBe(true);
    expect(isJobLifecycleRefreshEvent('job_materialized')).toBe(true);
    expect(isJobLifecycleRefreshEvent('job_completed')).toBe(true);

    expect(isJobLifecycleRefreshEvent('task_started')).toBe(false);
    expect(isJobLifecycleRefreshEvent('task_progress')).toBe(false);
    expect(isJobLifecycleRefreshEvent('task_completed')).toBe(false);
    expect(isJobLifecycleRefreshEvent('job_progress')).toBe(false);
    expect(isJobLifecycleRefreshEvent('download_progress')).toBe(false);
  });

  it('does not schedule another poll while a request is active or paused', () => {
    expect(
      getNonOverlappingRefetchInterval(
        { state: { fetchStatus: 'idle' } },
        3_000,
      ),
    ).toBe(3_000);
    expect(
      getNonOverlappingRefetchInterval(
        { state: { fetchStatus: 'fetching' } },
        3_000,
      ),
    ).toBe(false);
    expect(
      getNonOverlappingRefetchInterval(
        { state: { fetchStatus: 'paused' } },
        3_000,
      ),
    ).toBe(false);
    expect(
      getNonOverlappingRefetchInterval(
        { state: { fetchStatus: 'idle' } },
        3_000,
        false,
      ),
    ).toBe(false);
  });
});

describe('resolveEffectiveJobStatus', () => {
  it('does not mark a completed run as overall FAILED when tasks hit terminal threshold with low failure rate', async () => {
    const { resolveEffectiveJobStatus } = await import('../../src/features/jobs/lib/jobUtils');

    // 1 dropped connection out of 10,600 requests at 100% progress
    const effectiveStatus = resolveEffectiveJobStatus(
      'failed',
      { total: 10600, completed: 10599, failed: 1, ready: 0, inflight: 0, blocked: 0, deferred: 0 },
      100,
    );

    expect(effectiveStatus).toBe('completed');
  });

  it('preserves overall FAILED if job genuinely failed without completing all tasks', async () => {
    const { resolveEffectiveJobStatus } = await import('../../src/features/jobs/lib/jobUtils');

    const effectiveStatus = resolveEffectiveJobStatus(
      'failed',
      { total: 10600, completed: 500, failed: 200, ready: 9900, inflight: 0, blocked: 0, deferred: 0 },
      7,
    );

    expect(effectiveStatus).toBe('failed');
  });

  it('preserves overall FAILED if 100% of tasks failed', async () => {
    const { resolveEffectiveJobStatus } = await import('../../src/features/jobs/lib/jobUtils');

    const effectiveStatus = resolveEffectiveJobStatus(
      'failed',
      { total: 100, completed: 0, failed: 100, ready: 0, inflight: 0, blocked: 0, deferred: 0 },
      100,
    );

    expect(effectiveStatus).toBe('failed');
  });
});
