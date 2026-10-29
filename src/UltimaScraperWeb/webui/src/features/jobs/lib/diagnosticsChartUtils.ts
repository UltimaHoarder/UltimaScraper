import type { JobRuntimeSample, MPSRefillTraceEvent } from '../../../api/types/jobs';

export interface ChartSeries {
  name: string;
  values: Array<number | null>;
  color: string;
  strokeWidth?: number;
  isDashed?: boolean;
}

export interface ChartMarker {
  timestamp: number;
  label: string;
  color: string;
}

export const MAX_CHART_LINE_GAP_MS = 5_000;
// The backend samples once per second. A much shorter gap means a sample was
// stamped late or out of order, and dividing ~1s of completions by it would
// plot a fake burst, so such samples are folded into the next interval.
export const MIN_RUNTIME_SAMPLE_INTERVAL_MS = 500;

export interface RuntimeThroughputPoint {
  timestamp: number;
  intervalStartTimestamp: number;
  intervalMs: number;
  completedDelta: number;
  throughput: number | null;
  inflight: number;
}

export function buildRuntimeThroughputTimeline(
  samples: JobRuntimeSample[],
): RuntimeThroughputPoint[] {
  const timeline: RuntimeThroughputPoint[] = [];
  let previous: JobRuntimeSample | undefined;
  for (const sample of samples) {
    const intervalMs = previous ? sample.timestamp_ms - previous.timestamp_ms : 0;
    if (previous && intervalMs < MIN_RUNTIME_SAMPLE_INTERVAL_MS) continue;
    const completedDelta = previous
      ? Math.max(
          0,
          sample.completed + sample.failed - previous.completed - previous.failed,
        )
      : 0;
    timeline.push({
      timestamp: sample.timestamp_ms,
      intervalStartTimestamp: previous?.timestamp_ms ?? sample.timestamp_ms,
      intervalMs,
      completedDelta,
      throughput: previous && intervalMs <= MAX_CHART_LINE_GAP_MS
        ? Number((completedDelta / (intervalMs / 1_000)).toFixed(1))
        : null,
      inflight: sample.inflight,
    });
    previous = sample;
  }
  return timeline;
}

const RUNTIME_CHART_TARGET_POINTS = 120;
const RUNTIME_BUCKET_STEPS_MS = [
  1_000, 5_000, 10_000, 15_000, 30_000, 60_000, 120_000, 300_000, 600_000,
  900_000, 1_800_000, 3_600_000,
];

/** Smallest round bucket that keeps a lifecycle chart near the point target. */
export function chooseRuntimeBucketMs(spanMs: number): number {
  return RUNTIME_BUCKET_STEPS_MS.find(
    (step) => spanMs / step <= RUNTIME_CHART_TARGET_POINTS,
  ) ?? RUNTIME_BUCKET_STEPS_MS[RUNTIME_BUCKET_STEPS_MS.length - 1];
}

export function formatBucketDuration(ms: number): string {
  if (ms >= 3_600_000 && ms % 3_600_000 === 0) return `${ms / 3_600_000}h`;
  if (ms >= 60_000 && ms % 60_000 === 0) return `${ms / 60_000}m`;
  return `${Math.round(ms / 1_000)}s`;
}

/**
 * Merge per-second intervals into fixed time buckets. Each bucket's rate is
 * its completions over the time its valid intervals cover, so blank stretches
 * inside a bucket do not dilute it; in-flight is the mean of its samples.
 */
export function bucketRuntimeThroughputTimeline(
  points: RuntimeThroughputPoint[],
  bucketMs: number,
): RuntimeThroughputPoint[] {
  if (bucketMs <= 1_000 || points.length === 0) return points;
  const origin = points[0].intervalStartTimestamp;
  const grouped = new Map<number, RuntimeThroughputPoint[]>();
  for (const point of points) {
    const index = Math.floor((point.timestamp - origin) / bucketMs);
    const members = grouped.get(index);
    if (members) members.push(point);
    else grouped.set(index, [point]);
  }
  return [...grouped].map(([index, members]) => {
    const measured = members.filter((point) => point.throughput != null);
    const intervalMs = measured.reduce((sum, point) => sum + point.intervalMs, 0);
    const completedDelta = measured.reduce((sum, point) => sum + point.completedDelta, 0);
    return {
      timestamp: members[members.length - 1].timestamp,
      intervalStartTimestamp: origin + index * bucketMs,
      intervalMs,
      completedDelta,
      throughput: intervalMs > 0
        ? Number((completedDelta / (intervalMs / 1_000)).toFixed(1))
        : null,
      inflight: Math.round(
        members.reduce((sum, point) => sum + point.inflight, 0) / members.length,
      ),
    };
  });
}

/** Rate over the trailing window, using only intervals wholly inside it. */
export function rollingRuntimeThroughput(
  points: RuntimeThroughputPoint[],
  windowMs: number,
): Array<number | null> {
  return points.map((point, index) => {
    if (point.throughput == null) return null;
    const cutoff = point.timestamp - windowMs;
    let completed = 0;
    let coveredMs = 0;
    for (let previous = index; previous >= 0; previous -= 1) {
      const interval = points[previous];
      if (interval.timestamp <= cutoff) break;
      if (interval.throughput == null || interval.intervalStartTimestamp < cutoff) continue;
      completed += interval.completedDelta;
      coveredMs += interval.intervalMs;
    }
    return coveredMs > 0
      ? Number((completed / (coveredMs / 1_000)).toFixed(1))
      : null;
  });
}

export function formatChartClock(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function refillStageLabel(stage: string): string {
  const labels: Record<string, string> = {
    queued: 'Refill queued',
    materializer_dequeued: 'Materializer dequeued',
    materializer_started: 'Materializer started',
    archive_started: 'Archive started',
    archive_finished: 'Archive finished',
    tasks_published: 'Ready tasks published',
    tasks_activated: 'Tasks activated',
    runtime_controls: 'Effective refill controls',
    cleanup_started: 'Cleanup started',
    cleanup_finished: 'Cleanup finished',
    manifest_read_started: 'Manifest read started',
    manifest_read_finished: 'Manifest read finished',
    publication_started: 'Publication started',
    refill_stopped: 'Refill stopped',
  };
  return labels[stage] ?? stage.replaceAll('_', ' ');
}

export function formatElapsedMs(value: number): string {
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

export function refillBatchLabel(event: MPSRefillTraceEvent): string {
  if (event.ready_added != null) return `${event.ready_added.toLocaleString()} ready`;
  if (event.task_count == null) return '—';
  if (event.stage === 'archive_started') return `${event.task_count.toLocaleString()} to archive`;
  if (event.stage === 'archive_finished') return `${event.task_count.toLocaleString()} archived`;
  return `${event.task_count.toLocaleString()} tasks`;
}
