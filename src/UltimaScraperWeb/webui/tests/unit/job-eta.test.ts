import { describe, expect, it } from 'vitest';

import { calculateJobEta } from '../../src/features/jobs/lib/jobEta';

describe('calculateJobEta', () => {
  const baseTime = new Date('2026-09-05T12:00:00Z').getTime();

  it('returns pending when job has no startedAt timestamp', () => {
    const result = calculateJobEta({
      status: 'pending',
      startedAt: null,
      currentTime: baseTime,
    });
    expect(result.status).toBe('pending');
    expect(result.formattedRemaining).toBe('Queued');
    expect(result.elapsedSeconds).toBeNull();
  });

  it('returns completed when job has completedAt timestamp', () => {
    const startedAt = new Date(baseTime - 120_000).toISOString();
    const completedAt = new Date(baseTime).toISOString();
    const result = calculateJobEta({
      status: 'completed',
      startedAt,
      completedAt,
      currentTime: baseTime,
    });
    expect(result.status).toBe('completed');
    expect(result.elapsedSeconds).toBe(120);
    expect(result.formattedElapsed).toBe('2m');
    expect(result.formattedRemaining).toBe('Done');
  });

  it('calculates remaining time based on progress percentage', () => {
    // 60 seconds elapsed, 40% progress -> remaining should be 60 * 60 / 40 = 90 seconds (1m 30s)
    const startedAt = new Date(baseTime - 60_000).toISOString();
    const result = calculateJobEta({
      status: 'running',
      startedAt,
      progressPercent: 40,
      currentTime: baseTime,
    });
    expect(result.status).toBe('running');
    expect(result.elapsedSeconds).toBe(60);
    expect(result.remainingSeconds).toBe(90);
    expect(result.formattedRemaining).toBe('1m 30s');
    expect(result.completionDate).not.toBeNull();
  });

  it('calculates remaining time based on items processed when progress is 0', () => {
    // 30 seconds elapsed, 10 items processed of 50 total -> remaining items: 40, rate: 10/30 = 1/3 item/s -> 120s
    const startedAt = new Date(baseTime - 30_000).toISOString();
    const result = calculateJobEta({
      status: 'running',
      startedAt,
      progressPercent: 0,
      itemsProcessed: 10,
      itemsTotal: 50,
      currentTime: baseTime,
    });
    expect(result.status).toBe('running');
    expect(result.remainingSeconds).toBe(120);
    expect(result.formattedRemaining).toBe('2m');
  });

  it('returns wrapping up when progress is 100%', () => {
    const startedAt = new Date(baseTime - 90_000).toISOString();
    const result = calculateJobEta({
      status: 'running',
      startedAt,
      progressPercent: 100,
      currentTime: baseTime,
    });
    expect(result.status).toBe('wrapping_up');
    expect(result.formattedRemaining).toBe('< 5s');
  });

  it('returns estimating when no progress or items have been reported yet', () => {
    const startedAt = new Date(baseTime - 5_000).toISOString();
    const result = calculateJobEta({
      status: 'running',
      startedAt,
      progressPercent: 0,
      itemsProcessed: 0,
      itemsTotal: 0,
      currentTime: baseTime,
    });
    expect(result.status).toBe('running');
    expect(result.formattedRemaining).toBe('Estimating...');
    expect(result.remainingSeconds).toBeNull();
  });

  it('honors smoothed target timestamp countdown', () => {
    const startedAt = new Date(baseTime - 50_000).toISOString();
    const smoothedTargetMs = baseTime + 25_000; // 25s remaining
    const result = calculateJobEta({
      status: 'running',
      startedAt,
      progressPercent: 50,
      currentTime: baseTime,
      smoothedTargetMs,
    });
    expect(result.remainingSeconds).toBe(25);
    expect(result.formattedRemaining).toBe('25s');
  });

  it('returns estimating when running job has no startedAt timestamp', () => {
    const result = calculateJobEta({
      status: 'running',
      startedAt: null,
      currentTime: baseTime,
    });
    expect(result.status).toBe('running');
    expect(result.formattedRemaining).toBe('Estimating...');
  });

  it('returns Queued when job status is queued', () => {
    const result = calculateJobEta({
      status: 'queued',
      startedAt: null,
      currentTime: baseTime,
    });
    expect(result.status).toBe('pending');
    expect(result.formattedRemaining).toBe('Queued');
  });

  it('returns Starting... when job status is claimed', () => {
    const result = calculateJobEta({
      status: 'claimed',
      startedAt: null,
      currentTime: baseTime,
    });
    expect(result.status).toBe('pending');
    expect(result.formattedRemaining).toBe('Starting...');
  });

  it('returns stopped when job status is failed or cancelled', () => {
    const startedAt = new Date(baseTime - 30_000).toISOString();
    const failedResult = calculateJobEta({
      status: 'failed',
      startedAt,
      currentTime: baseTime,
    });
    expect(failedResult.status).toBe('stopped');
    expect(failedResult.formattedRemaining).toBe('Failed');
    expect(failedResult.elapsedSeconds).toBe(30);

    const cancelledResult = calculateJobEta({
      status: 'cancelled',
      startedAt,
      currentTime: baseTime,
    });
    expect(cancelledResult.status).toBe('stopped');
    expect(cancelledResult.formattedRemaining).toBe('Cancelled');
  });
});

