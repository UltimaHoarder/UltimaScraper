import type { SiteStatistics, SiteStatisticsHistory, SiteStatisticsSnapshot } from '../../../../api/types/statistics';
import { formatBytes } from '../../../../shared/lib/format';

export { formatBytes };

export type CountField =
  | 'user_record_count' | 'performer_profile_count' | 'active_user_count' | 'archived_content_count'
  | 'post_count' | 'message_count' | 'story_count' | 'mass_message_count'
  | 'downloaded_media_count' | 'total_media_count' | 'sized_media_count'
  | 'total_known_bytes' | 'image_media_count' | 'video_media_count'
  | 'audio_media_count' | 'other_media_count';
export type TrendMetric = Exclude<
  CountField,
  | 'downloaded_media_count'
  | 'sized_media_count'
  | 'active_user_count'
  | 'post_count'
  | 'message_count'
  | 'story_count'
  | 'mass_message_count'
> | 'downloads';
export interface MetricTotal { value: number | null; partial: boolean }
export interface TrendSeries { label: string; color: string; values: Array<number | null> }
export interface TrendData { dates: string[]; series: TrendSeries[] }

export const TREND_OPTIONS: Array<{ value: TrendMetric; label: string }> = [
  { value: 'user_record_count', label: 'User records' },
  { value: 'performer_profile_count', label: 'Performer profiles' },
  { value: 'archived_content_count', label: 'Content items' },
  { value: 'total_media_count', label: 'Media records' },
  { value: 'downloads', label: 'Downloaded vs pending' },
  { value: 'total_known_bytes', label: 'Known source size' },
  { value: 'image_media_count', label: 'Images' },
  { value: 'video_media_count', label: 'Videos' },
  { value: 'audio_media_count', label: 'Audio' },
  { value: 'other_media_count', label: 'Other media' },
];

const MEDIA_TYPES = [
  { label: 'Images', count: 'image_media_count', sized: 'image_sized_count', average: 'avg_image_size_bytes', color: 'var(--color-accent-primary, #24aac3)' },
  { label: 'Videos', count: 'video_media_count', sized: 'video_sized_count', average: 'avg_video_size_bytes', color: '#9b8fea' },
  { label: 'Audio', count: 'audio_media_count', sized: 'audio_sized_count', average: 'avg_audio_size_bytes', color: 'var(--color-warning, #ffd303)' },
  { label: 'Other', count: 'other_media_count', sized: 'other_sized_count', average: 'avg_other_size_bytes', color: 'var(--color-text-secondary, #9aa69f)' },
] as const;

const CONTENT_TYPES = [
  { label: 'Posts', count: 'post_count' as const, color: 'var(--color-accent-primary, #24aac3)' },
  { label: 'Messages', count: 'message_count' as const, color: '#9b8fea' },
  { label: 'Stories', count: 'story_count' as const, color: 'var(--color-warning, #ffd303)' },
  { label: 'Mass messages', count: 'mass_message_count' as const, color: 'var(--color-success, #82d6b2)' },
] as const;

export function formatCount(value: number): string { return value.toLocaleString(); }
export function formatPercent(value: number): string { return `${(value * 100).toFixed(1)}%`; }
export function formatDate(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
  });
}
export function formatSiteLabel(site: string): string { return site.charAt(0).toUpperCase() + site.slice(1); }
export function formatMetric(value: number, metric: TrendMetric): string {
  return metric === 'total_known_bytes' ? formatBytes(value) : formatCount(value);
}

function availableSnapshots(statistics: SiteStatistics[]): SiteStatisticsSnapshot[] {
  return statistics.flatMap((item) => item.snapshot && !item.availability_error ? [item.snapshot] : []);
}

export function sumMetric(statistics: SiteStatistics[], field: CountField): MetricTotal {
  const snapshots = availableSnapshots(statistics);
  const values = snapshots.map((snapshot) => snapshot[field]);
  const unknown = values.some((value) => value == null);
  return {
    value: snapshots.length === 0 || unknown ? null : values.reduce<number>((total, value) => total + (value ?? 0), 0),
    partial: snapshots.length !== statistics.length || unknown,
  };
}

export function getPendingCount(snapshot: SiteStatisticsSnapshot | null): number | null {
  if (!snapshot || snapshot.downloaded_media_count == null) return null;
  return Math.max(0, snapshot.total_media_count - snapshot.downloaded_media_count);
}

export function buildMediaBreakdown(statistics: SiteStatistics[]) {
  const snapshots = availableSnapshots(statistics);
  return MEDIA_TYPES.map((type) => {
    const count = sumMetric(statistics, type.count).value;
    const sized = snapshots.reduce((total, snapshot) => total + snapshot[type.sized], 0);
    // Snapshot averages are rounded by the API. Weight by sized records, never by site count.
    const weightedBytes = snapshots.reduce((total, snapshot) => total + snapshot[type.average] * snapshot[type.sized], 0);
    return { ...type, value: count, sized: snapshots.length > 0 ? sized : null, average: sized > 0 ? weightedBytes / sized : null, totalBytes: snapshots.length > 0 ? weightedBytes : null };
  });
}

export function buildUserRoleBreakdown(statistics: SiteStatistics[]) {
  const snapshots = availableSnapshots(statistics).filter(
    (s) => s.user_record_count != null && s.performer_profile_count != null,
  );
  const totalUsers = snapshots.length > 0 ? snapshots.reduce((sum, s) => sum + (s.user_record_count ?? 0), 0) : null;
  const performers = snapshots.length > 0 ? snapshots.reduce((sum, s) => sum + (s.performer_profile_count ?? 0), 0) : null;
  const regularUsers =
    totalUsers !== null && performers !== null
      ? Math.max(0, totalUsers - performers)
      : null;
  return {
    total: totalUsers,
    partial: snapshots.length !== statistics.length,
    slices: [
      { label: 'Users', value: regularUsers, color: 'var(--color-accent-primary, #24aac3)' },
      { label: 'Performers', value: performers, color: '#9b8fea' },
    ],
  };
}

export function buildUserActivityBreakdown(statistics: SiteStatistics[]) {
  const snapshots = availableSnapshots(statistics).filter(
    (s) => s.user_record_count != null && s.active_user_count != null,
  );
  const totalUsers = snapshots.length > 0 ? snapshots.reduce((sum, s) => sum + (s.user_record_count ?? 0), 0) : null;
  const activeUsers = snapshots.length > 0 ? snapshots.reduce((sum, s) => sum + (s.active_user_count ?? 0), 0) : null;
  const inactiveUsers =
    totalUsers !== null && activeUsers !== null
      ? Math.max(0, totalUsers - activeUsers)
      : null;
  return {
    total: totalUsers,
    active: activeUsers,
    inactive: inactiveUsers,
    partial: snapshots.length !== statistics.length,
    slices: [
      { label: 'Active', value: activeUsers, color: 'var(--color-success, #82d6b2)' },
      { label: 'Inactive', value: inactiveUsers, color: 'var(--color-warning, #ffd303)' },
    ],
  };
}

export function buildContentBreakdown(statistics: SiteStatistics[]) {
  const totalContent = sumMetric(statistics, 'archived_content_count');
  const snapshots = availableSnapshots(statistics);
  const items = CONTENT_TYPES.map((type) => {
    const known = snapshots
      .map((s) => s[type.count])
      .filter((v): v is number => v != null);
    return {
      label: type.label,
      color: type.color,
      value: known.length > 0 ? known.reduce((sum, v) => sum + v, 0) : null,
    };
  });
  const hasPartialTypeBreakdown = snapshots.some((s) =>
    CONTENT_TYPES.some((type) => s[type.count] == null),
  );
  const hasTypeBreakdown = items.some((item) => item.value !== null && item.value > 0) || items.every((item) => item.value !== null);
  const typedTotal = items.reduce((sum, item) => sum + (item.value ?? 0), 0);
  return {
    total: hasTypeBreakdown && typedTotal > 0 ? typedTotal : totalContent.value,
    hasTypeBreakdown,
    partial: totalContent.partial || hasPartialTypeBreakdown,
    items,
  };
}

export function buildTrendData(
  sites: SiteStatisticsHistory[], siteScope: string, metric: TrendMetric,
  startDate?: string | null, endDate?: string,
): TrendData {
  const selected = sites.filter((site) => site.available && (siteScope === 'all' || site.site === siteScope));
  const recordedDates = [...new Set(selected.flatMap((site) => site.points.map((point) => point.bucket_date)))].sort();
  if (recordedDates.length === 0) return { dates: [], series: [] };
  const start = startDate ?? recordedDates[0];
  const end = endDate ?? recordedDates[recordedDates.length - 1];
  const dates: string[] = [];
  // A calendar axis prevents a missing day from becoming a fabricated one-day change.
  for (let day = Date.parse(`${start}T00:00:00Z`); day <= Date.parse(`${end}T00:00:00Z`); day += 86_400_000) {
    dates.push(new Date(day).toISOString().slice(0, 10));
  }
  const bySite = selected.map((site) => new Map(site.points.map((point) => [point.bucket_date, point])));
  const definitions = metric === 'downloads'
    ? [{ key: 'downloaded', label: 'Downloaded', color: 'var(--color-success, #82d6b2)' },
      { key: 'pending', label: 'Pending', color: 'var(--color-warning, #ffd303)' }]
    : [{ key: 'value', label: TREND_OPTIONS.find((option) => option.value === metric)?.label ?? 'Total', color: 'var(--color-accent-primary, #24aac3)' }];
  return {
    dates,
    series: definitions.map((definition) => ({
      label: definition.label, color: definition.color,
      values: dates.map((date) => {
        const values = bySite.map((points) => {
          const snapshot = points.get(date);
          if (!snapshot) return null;
          if (definition.key === 'pending') return getPendingCount(snapshot);
          return metric === 'downloads' ? snapshot.downloaded_media_count : snapshot[metric];
        });
        return values.some((value) => value == null) ? null : values.reduce<number>((total, value) => total + (value ?? 0), 0);
      }),
    })),
  };
}

export function dailyChanges(values: Array<number | null>): Array<number | null> {
  return values.map((value, index) => {
    const previous = index > 0 ? values[index - 1] : null;
    return value === null || previous === null ? null : value - previous;
  });
}

export function summarizeTrend(dates: string[], values: Array<number | null>) {
  const known = values.flatMap((value, index) => value === null ? [] : [{ value, date: dates[index] }]);
  const first = known[0];
  const last = known[known.length - 1];
  const changes = dailyChanges(values).filter((value): value is number => value !== null);
  const net = known.length >= 2 ? last.value - first.value : null;
  return {
    first, last, net,
    percent: net !== null && first.value > 0 ? net / first.value : null,
    averageDaily: changes.length ? changes.reduce((total, value) => total + value, 0) / changes.length : null,
    comparedDays: changes.length,
    recordedDays: known.length,
  };
}
