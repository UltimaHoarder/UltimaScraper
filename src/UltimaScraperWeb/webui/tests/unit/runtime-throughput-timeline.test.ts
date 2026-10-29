import { expect, it } from 'vitest';
import type { JobRuntimeSample } from '../../src/api/types/jobs';
import {
  bucketRuntimeThroughputTimeline,
  buildRuntimeThroughputTimeline,
  chooseRuntimeBucketMs,
  formatBucketDuration,
  rollingRuntimeThroughput,
} from '../../src/features/jobs/lib/diagnosticsChartUtils';

const sample = (timestamp_ms: number, completed: number): JobRuntimeSample => ({
  cursor: `${timestamp_ms}-0`,
  timestamp_ms,
  total: 10_000,
  ready: 0,
  inflight: 8,
  completed,
  failed: 0,
});

it('folds a sub-tick sample into the next interval instead of plotting a burst', () => {
  // A late-stamped sample 19ms after the previous one carried ~1s of completions.
  const timeline = buildRuntimeThroughputTimeline([
    sample(1_000, 0),
    sample(2_364, 473),
    sample(2_383, 1_078),
    sample(4_182, 1_614),
  ]);

  expect(timeline.map((point) => point.timestamp)).toEqual([1_000, 2_364, 4_182]);
  expect(timeline[2]).toMatchObject({
    intervalStartTimestamp: 2_364,
    intervalMs: 1_818,
    completedDelta: 1_141,
    throughput: 627.6,
  });
  expect(Math.max(...timeline.map((point) => point.throughput ?? 0))).toBeLessThan(700);
});

it('drops out-of-order samples without counting a negative delta', () => {
  const timeline = buildRuntimeThroughputTimeline([
    sample(1_000, 100),
    sample(2_000, 700),
    sample(1_977, 650),
    sample(3_000, 1_300),
  ]);

  expect(timeline.map((point) => point.throughput)).toEqual([null, 600, 600]);
});

it('scales the lifecycle bucket with job duration', () => {
  expect(chooseRuntimeBucketMs(90_000)).toBe(1_000);
  expect(chooseRuntimeBucketMs(10 * 60_000)).toBe(5_000);
  expect(chooseRuntimeBucketMs(82 * 60_000 + 7_000)).toBe(60_000);
  expect(chooseRuntimeBucketMs(8 * 3_600_000)).toBe(300_000);
  expect([1_000, 60_000, 300_000].map(formatBucketDuration)).toEqual(['1s', '1m', '5m']);
});

it('buckets per-second intervals by covered time, skipping gaps', () => {
  const samples = Array.from({ length: 121 }, (_, index) => sample(index * 1_000, index * 10))
    // A 10s outage inside the second minute must not dilute its rate.
    .filter((_, index) => index <= 70 || index >= 80);
  const timeline = buildRuntimeThroughputTimeline(samples);
  const buckets = bucketRuntimeThroughputTimeline(timeline, 60_000);

  expect(buckets.map((point) => point.throughput)).toEqual([10, 10, 10]);
  expect(buckets[1]).toMatchObject({ intervalStartTimestamp: 60_000, intervalMs: 50_000 });
  expect(buckets.map((point) => point.inflight)).toEqual([8, 8, 8]);
  expect(bucketRuntimeThroughputTimeline(timeline, 1_000)).toBe(timeline);
});

it('averages only intervals wholly inside the rolling window', () => {
  const timeline = buildRuntimeThroughputTimeline(
    [0, 10, 30, 60].map((completed, index) => sample(index * 1_000, completed)),
  );

  expect(rollingRuntimeThroughput(timeline, 2_000)).toEqual([null, 10, 15, 25]);
});
