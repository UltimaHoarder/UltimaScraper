import { describe, expect, it } from 'vitest';
import {
  buildContentBreakdown,
  buildMediaBreakdown,
  buildTrendData,
  buildUserActivityBreakdown,
  buildUserRoleBreakdown,
  dailyChanges,
  formatBytes,
  summarizeTrend,
  sumMetric,
} from '../../src/themes/ultima-atlas/views/statistics/statisticsModel';
import { makeSiteStatistics, makeStatisticsSnapshot } from '../fixtures/statistics';

describe('statistics analytics', () => {
  it('weights average type sizes by sized records instead of averaging site averages', () => {
    const sites = [
      makeSiteStatistics(makeStatisticsSnapshot({ image_sized_count: 90, avg_image_size_bytes: 10 })),
      makeSiteStatistics(makeStatisticsSnapshot({ site: 'fansly', image_sized_count: 10, avg_image_size_bytes: 110 })),
    ];
    expect(buildMediaBreakdown(sites)[0].average).toBe(20);
    expect(buildMediaBreakdown([makeSiteStatistics(makeStatisticsSnapshot({ image_sized_count: 0 }))])[0].average).toBeNull();
  });

  it('builds user role, user activity, and content type breakdowns across sites', () => {
    const sites = [
      makeSiteStatistics(
        makeStatisticsSnapshot({
          user_record_count: 240,
          performer_profile_count: 20,
          active_user_count: 180,
          archived_content_count: 50,
          post_count: 25,
          message_count: 15,
          story_count: 6,
          mass_message_count: 4,
        }),
      ),
      makeSiteStatistics(
        makeStatisticsSnapshot({
          site: 'fansly',
          user_record_count: 100,
          performer_profile_count: 10,
          active_user_count: 70,
          archived_content_count: 30,
          post_count: 18,
          message_count: 8,
          story_count: 3,
          mass_message_count: 1,
        }),
      ),
    ];

    const roles = buildUserRoleBreakdown(sites);
    expect(roles.total).toBe(340);
    expect(roles.slices.map((s) => ({ label: s.label, value: s.value }))).toEqual([
      { label: 'Users', value: 310 },
      { label: 'Performers', value: 30 },
    ]);

    const activity = buildUserActivityBreakdown(sites);
    expect(activity.total).toBe(340);
    expect(activity.active).toBe(250);
    expect(activity.inactive).toBe(90);
    expect(activity.slices.map((s) => ({ label: s.label, value: s.value }))).toEqual([
      { label: 'Active', value: 250 },
      { label: 'Inactive', value: 90 },
    ]);

    const content = buildContentBreakdown(sites);
    expect(content.total).toBe(80);
    expect(content.hasTypeBreakdown).toBe(true);
    expect(content.items.map((i) => ({ label: i.label, value: i.value }))).toEqual([
      { label: 'Posts', value: 43 },
      { label: 'Messages', value: 23 },
      { label: 'Stories', value: 9 },
      { label: 'Mass messages', value: 5 },
    ]);
  });

  it('keeps unknown legacy counts unknown and excludes unavailable site snapshots', () => {
    const sites = [makeSiteStatistics(), makeSiteStatistics(makeStatisticsSnapshot({ site: 'fansly', downloaded_media_count: null }))];
    expect(sumMetric(sites, 'downloaded_media_count')).toEqual({ value: null, partial: true });
    sites[1].availability_error = 'offline';
    expect(sumMetric(sites, 'total_media_count')).toEqual({ value: 100, partial: true });
    expect(sumMetric([makeSiteStatistics(null)], 'total_media_count').value).toBeNull();
    expect(buildMediaBreakdown([makeSiteStatistics(null)])[0]).toMatchObject({ value: null, sized: null, average: null });

    const mixedBreakdownSites = [
      makeSiteStatistics(makeStatisticsSnapshot({ site: 'fansly', user_record_count: 20, active_user_count: 15, post_count: 10, message_count: 5, story_count: 2, mass_message_count: 1 })),
      makeSiteStatistics(makeStatisticsSnapshot({ site: 'onlyfans', user_record_count: 100, active_user_count: null, post_count: null, message_count: null, story_count: null, mass_message_count: null })),
    ];
    const activity = buildUserActivityBreakdown(mixedBreakdownSites);
    expect(activity.total).toBe(20);
    expect(activity.active).toBe(15);
    expect(activity.inactive).toBe(5);
    expect(activity.partial).toBe(true);

    const content = buildContentBreakdown(mixedBreakdownSites);
    expect(content.hasTypeBreakdown).toBe(true);
    expect(content.partial).toBe(true);
    expect(content.items.map((i) => ({ label: i.label, value: i.value }))).toEqual([
      { label: 'Posts', value: 10 },
      { label: 'Messages', value: 5 },
      { label: 'Stories', value: 2 },
      { label: 'Mass messages', value: 1 },
    ]);
  });

  it('inserts calendar gaps and never reports growth across missing or unknown days', () => {
    const history = [{ site: 'onlyfans', available: true, availability_error: null, points: [
      makeStatisticsSnapshot({ bucket_date: '2026-10-07', total_media_count: 100 }),
      makeStatisticsSnapshot({ bucket_date: '2026-10-09', total_media_count: 140 }),
      makeStatisticsSnapshot({ bucket_date: '2026-10-10', total_media_count: 130 }),
    ] }];
    const trend = buildTrendData(history, 'all', 'total_media_count', '2026-10-07', '2026-10-11');
    expect(trend.dates).toEqual(['2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10', '2026-10-11']);
    expect(trend.series[0].values).toEqual([100, null, 140, 130, null]);
    expect(dailyChanges(trend.series[0].values)).toEqual([null, null, null, -10, null]);
    expect(summarizeTrend(trend.dates, trend.series[0].values)).toMatchObject({ net: 30, averageDaily: -10, comparedDays: 1, recordedDays: 3 });
  });

  it('requires every available site on a date for an all-site total', () => {
    const history = [
      { site: 'onlyfans', available: true, availability_error: null, points: [makeStatisticsSnapshot()] },
      { site: 'fansly', available: true, availability_error: null, points: [] },
    ];
    expect(buildTrendData(history, 'all', 'total_media_count').series[0].values).toEqual([null]);
    expect(buildTrendData(history, 'onlyfans', 'total_media_count').series[0].values).toEqual([100]);
  });

  it('preserves unknown downloads and negative net changes without fabricating zero totals', () => {
    const points = [makeStatisticsSnapshot({ bucket_date: '2026-10-10', downloaded_media_count: null }), makeStatisticsSnapshot()];
    const trend = buildTrendData([{ site: 'onlyfans', available: true, availability_error: null, points }], 'all', 'downloads');
    expect(trend.series.map((series) => series.values)).toEqual([[null, 75], [null, 25]]);
    expect(dailyChanges([30, 20, null, 10])).toEqual([null, -10, null, null]);
    expect(formatBytes(-2048)).toBe('-2.0 KB');
    expect(summarizeTrend(['2026-10-11'], [0]).net).toBeNull();
  });
});

