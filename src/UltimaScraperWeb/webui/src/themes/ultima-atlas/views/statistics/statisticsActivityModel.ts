import type { StatisticsActivityInterval, StatisticsActivityRange, StatisticsActivityResponse } from '../../../../api/types/statistics';

export const ACTIVITY_RANGES: Record<StatisticsActivityInterval, StatisticsActivityRange[]> = {
  minute: ['all', '1h', '24h'], hour: ['all', '24h', '7d', '30d'], day: ['all', '7d', '30d', '90d', '1y'], month: ['all', '1y'], year: ['all'],
};
export const ACTIVITY_RANGE_LABELS: Record<StatisticsActivityRange, string> = {
  '1h': 'Past hour', '24h': 'Past 24 hours', '7d': 'Past 7 days', '30d': 'Past 30 days',
  '90d': 'Past 90 days', '1y': 'Past year', all: 'Start to now', custom: 'Custom dates',
};

export function advanceActivityBucket(start: number, interval: StatisticsActivityInterval): number {
  const date = new Date(start);
  if (interval === 'year') date.setUTCFullYear(date.getUTCFullYear() + 1);
  else if (interval === 'month') date.setUTCMonth(date.getUTCMonth() + 1);
  else return start + { minute: 60_000, hour: 3_600_000, day: 86_400_000 }[interval];
  return date.getTime();
}

export function formatActivityDate(timestamp: number, interval: StatisticsActivityInterval): string {
  return new Date(timestamp).toLocaleString('en-GB', {
    timeZone: 'UTC',
    ...(interval === 'year' ? { year: 'numeric' }
      : interval === 'month' ? { month: 'short', year: 'numeric' }
        : interval === 'day' ? { day: 'numeric', month: 'short', year: 'numeric' }
          : { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }),
  });
}

export function buildActivityBuckets(data: StatisticsActivityResponse) {
  const sites = data.sites.filter((site) => site.available);
  const maps = sites.map((site) => new Map(site.points.map((point) => [Date.parse(point.bucket_started_at), point.count])));
  const end = Date.parse(data.window_end_at ?? data.end_at);
  const buckets: Array<{ start: number; count: number | null; counts: number[]; partial: boolean }> = [];
  for (let start = Date.parse(data.window_start_at ?? data.start_at); start < end; start = advanceActivityBucket(start, data.interval)) {
    if (buckets.length >= 2000) throw new Error('Activity window exceeds the chart limit.');
    const counts = maps.map((points) => points.get(start) ?? 0);
    buckets.push({ start, counts, count: sites.length ? counts.reduce((total, count) => total + count, 0) : null,
      partial: start < Date.parse(data.coverage_start_at ?? data.start_at) || advanceActivityBucket(start, data.interval) > Date.parse(data.coverage_end_at ?? data.calculated_at) });
  }
  const complete = buckets.filter((bucket) => !bucket.partial && bucket.count !== null);
  const hasValues = sites.length > 0;
  const fullTotals = sites.length > 0 && sites.every((site) => site.total_count != null);
  const fullCompleted = sites.length > 0 && sites.every((site) => site.completed_count != null);
  return {
    sites, buckets,
    partialSites: sites.length !== data.sites.length,
    undated: hasValues ? sites.reduce((total, site) => total + (site.undated_count ?? 0), 0) : null,
    total: fullTotals ? sites.reduce((total, site) => total + site.total_count!, 0) : hasValues ? buckets.reduce((total, bucket) => total + (bucket.count ?? 0), 0) : null,
    average: fullCompleted ? data.completed_bucket_count ? sites.reduce((total, site) => total + site.completed_count!, 0) / data.completed_bucket_count : null : complete.length ? complete.reduce((total, bucket) => total + (bucket.count ?? 0), 0) / complete.length : null,
    peak: hasValues ? buckets.reduce((max, bucket) => Math.max(max, bucket.count ?? 0), 0) : null,
  };
}

export function analyzeActivity(values: Array<number | null>, windowSize = 7) {
  const rolling = values.map((value, index) => {
    const window = values.slice(Math.max(0, index - windowSize + 1), index + 1);
    return value === null || window.length < windowSize || window.some((v) => v === null) ? null : window.reduce<number>((sum, v) => sum + (v ?? 0), 0) / window.length;
  });
  // Equal adjacent windows, excluding partial buckets represented by nulls.
  const complete = values.filter((v): v is number => v !== null);
  const n = Math.min(windowSize, Math.floor(complete.length / 2));
  const previous = n ? complete.slice(-2 * n, -n).reduce((a, b) => a + b, 0) / n : null;
  const recent = n ? complete.slice(-n).reduce((a, b) => a + b, 0) / n : null;
  const change = previous && recent !== null ? (recent - previous) / previous : null;
  const signal = n < 3 ? 'More history needed' : change === null ? 'No baseline rate' : change > 0.2 ? 'Accelerating' : change < -0.2 ? 'Slowing down' : 'Steady rate';
  const points = values.map((value, x) => ({ x, value })).filter((p): p is { x: number; value: number } => p.value !== null);
  const fit = (exponential: boolean) => {
    if (points.length < 6 || (exponential && points.some((p) => p.value <= 0))) return null;
    const meanX = points.reduce((sum, p) => sum + p.x, 0) / points.length;
    const meanY = points.reduce((sum, p) => sum + (exponential ? Math.log(p.value) : p.value), 0) / points.length;
    const varianceX = points.reduce((sum, p) => sum + (p.x - meanX) ** 2, 0);
    if (!varianceX) return null;
    const slope = points.reduce((sum, p) => sum + (p.x - meanX) * ((exponential ? Math.log(p.value) : p.value) - meanY), 0) / varianceX;
    const predict = (x: number) => meanY + slope * (x - meanX);
    const sse = points.reduce((sum, p) => sum + ((exponential ? Math.log(p.value) : p.value) - predict(p.x)) ** 2, 0);
    const sst = points.reduce((sum, p) => sum + ((exponential ? Math.log(p.value) : p.value) - meanY) ** 2, 0);
    const fitted = values.map((_, x) => exponential ? Math.exp(predict(x)) : Math.max(0, predict(x)));
    if (fitted.some((v) => !Number.isFinite(v))) return null;
    return { values: fitted, r2: sst === 0 ? 1 : Math.max(0, 1 - sse / sst), rate: Math.expm1(slope) };
  };
  let sum = 0;
  const cumulative = values.map((v) => v === null ? null : (sum += v));
  return { rolling, previous, recent, change, n, signal, cumulative, linear: fit(false), exponential: fit(true) };
}

export const CHART_COLORS = ['#24aac3', '#9b8fea', '#ffd303', '#82d6b2', '#ff738f'];
