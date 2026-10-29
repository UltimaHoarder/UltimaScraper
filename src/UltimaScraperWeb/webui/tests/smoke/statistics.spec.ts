import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';
import { makeSiteStatistics, makeStatisticsSnapshot } from '../fixtures/statistics';
import { advanceActivityBucket } from '../../src/themes/ultima-atlas/views/statistics/statisticsActivityModel';
import type { StatisticsActivityInterval } from '../../src/api/types/statistics';

const executablePath = [process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, '/usr/bin/chromium', '/usr/bin/google-chrome-stable'].find((candidate) => candidate && fs.existsSync(candidate));
test.use({ launchOptions: { executablePath, args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } });

test('statistics charts render, filter, and fit the viewport', async ({ page }, info) => {
  test.setTimeout(60000);
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);
  await page.routeWebSocket(/\/ws\//, () => {});
  const onlyfans = makeStatisticsSnapshot({
    total_media_count: 1_240_000, downloaded_media_count: 1_050_000,
    image_media_count: 840_000, video_media_count: 360_000, audio_media_count: 30_000, other_media_count: 10_000,
    sized_media_count: 1_100_000, image_sized_count: 750_000, video_sized_count: 320_000, audio_sized_count: 25_000, other_sized_count: 5_000,
    user_record_count: 92_400, performer_profile_count: 8_200, active_user_count: 74_800, archived_content_count: 640_000,
    post_count: 390_000, message_count: 165_000, story_count: 52_000, mass_message_count: 33_000,
    total_known_bytes: 48_000_000_000_000, avg_image_size_bytes: 3_000_000, avg_video_size_bytes: 140_000_000, avg_audio_size_bytes: 24_000_000,
    size_coverage_ratio: 1_100_000 / 1_240_000,
  });
  const fansly = makeStatisticsSnapshot({
    site: 'fansly', total_media_count: 240_000, downloaded_media_count: 168_000,
    image_media_count: 180_000, video_media_count: 50_000, audio_media_count: 8_000, other_media_count: 2_000,
    sized_media_count: 180_000, image_sized_count: 140_000, video_sized_count: 34_000, audio_sized_count: 5_000, other_sized_count: 1_000,
    user_record_count: 18_400, performer_profile_count: 2_100, active_user_count: 14_200, archived_content_count: 140_000,
    post_count: 88_000, message_count: 34_000, story_count: 11_000, mass_message_count: 7_000,
    total_known_bytes: 6_000_000_000_000, avg_image_size_bytes: 2_000_000, avg_video_size_bytes: 160_000_000, avg_audio_size_bytes: 24_000_000,
    size_coverage_ratio: 0.75,
  });
  await page.route('**/api/v1/statistics?*', (route) => route.fulfill({ json: [makeSiteStatistics(onlyfans), makeSiteStatistics(fansly)] }));
  await page.route('**/api/v1/statistics/activity?*', (route) => {
    const params = new URL(route.request().url()).searchParams;
    const interval = params.get('interval') as StatisticsActivityInterval;
    if ((params.get('metric') === 'posts' && params.get('range') === 'all' && interval === 'hour') || params.get('range') === 'custom') {
      const first = Date.parse(params.get('range') === 'custom' ? `${params.get('start_date')}T00:00:00Z` : '2016-07-15T14:00:00Z');
      const end = params.get('range') === 'custom' ? Date.parse(`${params.get('end_date')}T00:00:00Z`) + 86400000 : Date.parse('2026-10-11T10:00:00Z');
      const bucketCount = Math.ceil((end - first) / { minute: 60000, hour: 3600000, day: 86400000, month: 2628000000, year: 31536000000 }[interval]);
      const offset = Math.min(Number(params.get('bucket_offset') ?? Math.max(0, bucketCount - 2000)), Math.max(0, bucketCount - 2000));
      const windowStart = new Date(first);
      let windowTimestamp = first;
      for (let i = 0; i < offset; i++) windowTimestamp = advanceActivityBucket(windowTimestamp, interval);
      windowStart.setTime(windowTimestamp);
      const dates = Array.from({ length: Math.min(2000, bucketCount - offset) }, () => { const bucket = windowTimestamp; windowTimestamp = advanceActivityBucket(windowTimestamp, interval); return bucket; });
      const count = (i: number) => i % 7 === 3 ? 0 : 10 + i % 17;
      const total = Array.from({ length: bucketCount }, (_, i) => count(i)).reduce((sum, value) => sum + value, 0);
      const prefix = Array.from({ length: offset }, (_, i) => count(i)).reduce((sum, value) => sum + value, 0);
      const sites = ['onlyfans', 'fansly'].filter((site) => !params.get('site') || params.get('site') === site);
      return route.fulfill({ json: {
        metric: 'posts', interval, range: params.get('range'), date_field: 'created_at',
        start_at: new Date(first).toISOString(), end_at: new Date(end).toISOString(), calculated_at: '2026-10-11T09:30:00Z',
        window_start_at: windowStart.toISOString(), window_end_at: new Date(windowTimestamp).toISOString(), bucket_count: bucketCount, bucket_offset: offset, completed_bucket_count: bucketCount - 1,
        sites: sites.map((site) => ({ site, available: true, availability_error: null, undated_count: 8, total_count: total, completed_count: total, before_window_count: prefix, points: dates.map((bucket, index) => ({ bucket_started_at: new Date(bucket).toISOString(), count: count(offset + index) })).filter((point) => point.count > 0) })),
      } });
    }
    const start = Date.parse({ minute: '2026-10-11T08:31:00Z', hour: '2026-10-10T10:00:00Z', day: '2026-09-12T00:00:00Z', month: '2025-11-01T00:00:00Z', year: '2018-01-01T00:00:00Z' }[interval]);
    const length = { minute: 60, hour: 24, day: 30, month: 12, year: 9 }[interval];
    const dates: number[] = [];
    for (let bucket = start; dates.length < length; bucket = advanceActivityBucket(bucket, interval)) dates.push(bucket);
    const metric = params.get('metric');
    const sites = ['onlyfans', 'fansly'].filter((site) => !params.get('site') || params.get('site') === site);
    return route.fulfill({ json: {
      metric, interval, range: params.get('range'), date_field: metric === 'accounts' ? params.get('account_date') : 'created_at',
      start_at: new Date(start).toISOString(), end_at: new Date(advanceActivityBucket(dates[dates.length - 1], interval)).toISOString(), calculated_at: '2026-10-11T09:30:00Z',
      sites: sites.map((site, siteIndex) => ({ site, available: true, availability_error: null, undated_count: metric === 'accounts' ? 248 * (siteIndex + 1) : 0,
        points: dates.filter((_, index) => index % 7 !== 3).map((bucket, index) => ({ bucket_started_at: new Date(bucket).toISOString(), count: Math.round((metric === 'accounts' ? 90 : 2400) * (1 + Math.sin(index * 0.7) * 0.6) / (siteIndex + 1)) })),
      })),
    } });
  });
  await page.route('**/api/v1/statistics/seasonality?*', (route) => {
    const params = new URL(route.request().url()).searchParams;
    const cycle = params.get('cycle') ?? 'weekday';
    const bins = { hour: 24, weekday: 7, monthday: 31, month: 12 }[cycle as 'hour' | 'weekday' | 'monthday' | 'month'];
    return route.fulfill({ json: { metric: params.get('metric'), cycle, date_field: 'created_at', start_date: '2025-10-11', end_date: '2026-10-10', calculated_at: '2026-10-11T09:30:00Z', exposures: Array(bins).fill(cycle === 'hour' ? 365 : cycle === 'weekday' ? 52 : cycle === 'monthday' ? 12 : 1), sites: ['onlyfans', 'fansly'].filter((site) => !params.get('site') || params.get('site') === site).map((site, j) => ({ site, available: true, availability_error: null, counts: Array.from({ length: bins }, (_, i) => Math.round((10000 + Math.sin(i * 0.6) * 6000) / (j + 1))) })) } });
  });
  await page.route('**/api/v1/statistics/history?*', (route) => route.fulfill({ json: {
    range: '30d', start_date: '2026-09-12', end_date: '2026-10-11',
    sites: [onlyfans, fansly].map((snapshot) => ({ site: snapshot.site, available: true, availability_error: null,
      points: Array.from({ length: 30 }, (_, index) => {
        const bucket = new Date(Date.UTC(2026, 8, 12 + index)).toISOString().slice(0, 10);
        return { ...snapshot, bucket_date: bucket, total_media_count: snapshot.total_media_count - (29 - index) * 1700,
          downloaded_media_count: snapshot.downloaded_media_count - (29 - index) * 1200 };
      }).filter((_, index) => index !== 8),
    })),
  } }));
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/statistics');
  await expect(page.getByRole('heading', { name: 'Media composition' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Users vs performers' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Active vs inactive users' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Content types' })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Daily net change bars' })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Accounts per month bar graph' })).toBeVisible();
  await expect(page.getByRole('img', { name: 'Posts per month bar graph' })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('statistics-overview.png'), fullPage: true });
  const accounts = page.getByRole('region', { name: 'Account creation', exact: true });
  const posts = page.getByRole('region', { name: 'Post publication', exact: true });
  const grid = page.locator('.statistics-visualizations');
  const gridRect = (await grid.boundingBox())!;
  const compactRect = (await accounts.boundingBox())!;
  const postsRect = (await posts.boundingBox())!;
  if (gridRect.width > 880) {
    expect(Math.abs(compactRect.y - postsRect.y)).toBeLessThan(2);
    expect(postsRect.x).toBeGreaterThan(compactRect.x + compactRect.width);
  } else {
    expect(postsRect.y).toBeGreaterThan(compactRect.y + compactRect.height);
  }
  await expect(page.getByRole('button', { name: /^Expand / })).toHaveCount(12);
  await expect(accounts.getByRole('combobox', { name: 'Group accounts by' })).toHaveCount(0);
  await expect(accounts.locator('.statistics-three__stage').getByRole('toolbar')).toBeVisible();
  expect(await accounts.getByRole('button', { name: 'Account creation settings' }).evaluate((button) => !!button.closest('.statistics-three__stage'))).toBe(true);
  expect(await accounts.locator('.statistics-three').evaluate((chart) => !!(chart.compareDocumentPosition(chart.parentElement!.querySelector('.statistics-growth-summary')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
  await expect(page.getByRole('table')).toHaveCount(0);
  await expect(page.getByText('View data table', { exact: true })).toHaveCount(0);
  await accounts.screenshot({ path: info.outputPath('statistics-account-days.png') });
  await posts.screenshot({ path: info.outputPath('statistics-post-hours.png') });
  await expect(accounts.locator('canvas')).toHaveCount(1);
  await expect(accounts.locator('.statistics-three__fallback')).toHaveCount(0);
  expect(await accounts.locator('canvas').evaluate((canvas) => !(canvas as HTMLCanvasElement).getContext('webgl2')?.isContextLost())).toBe(true);
  const plot = accounts.getByRole('img', { name: 'Accounts per month bar graph' });
  await plot.scrollIntoViewIfNeeded();
  const before = await accounts.locator('.statistics-three__readout').innerText();
  const rect = (await plot.boundingBox())!;
  await page.mouse.move(rect.x + rect.width * 0.25, rect.y + rect.height * 0.5);
  await expect(accounts.locator('.statistics-three__readout')).not.toHaveText(before);
  await plot.dispatchEvent('wheel', { deltaY: -100 });
  await expect(accounts.getByRole('button', { name: 'Show all' })).toBeVisible();
  await accounts.getByRole('button', { name: 'Expand Account creation', exact: true }).click();
  await expect(accounts.getByRole('button', { name: 'Collapse Account creation', exact: true })).toHaveAttribute('aria-expanded', 'true');
  await expect(posts).toBeHidden();
  await expect.poll(async () => (await accounts.boundingBox())!.width).toBeCloseTo(gridRect.width, 0);
  await expect(accounts.getByRole('button', { name: 'Show all' })).toBeVisible();
  await expect.poll(() => accounts.locator('canvas').evaluate((canvas) => {
    const rect = canvas.getBoundingClientRect();
    return Math.abs((canvas as HTMLCanvasElement).width - rect.width * Math.min(devicePixelRatio, 1.5)) < 3;
  })).toBe(true);
  await accounts.screenshot({ path: info.outputPath('statistics-account-expanded.png') });
  await accounts.getByRole('button', { name: 'Collapse Account creation', exact: true }).click();
  await expect(accounts.getByRole('button', { name: 'Expand Account creation', exact: true })).toHaveAttribute('aria-expanded', 'false');
  await expect.poll(async () => (await accounts.boundingBox())!.width).toBeCloseTo(compactRect.width, 0);
  await expect(posts).toBeVisible();
  // The second member replaces its own row too, without moving its partner.
  await posts.getByRole('button', { name: 'Expand Post publication', exact: true }).click();
  await expect(accounts).toBeHidden();
  await expect.poll(async () => (await posts.boundingBox())!.width).toBeCloseTo(gridRect.width, 0);
  expect(await posts.evaluate((element) => element.parentElement?.classList.contains('statistics-visualization-row'))).toBe(true);
  await posts.getByRole('button', { name: 'Collapse Post publication', exact: true }).click();
  await expect(accounts).toBeVisible();
  await expect(accounts.getByRole('button', { name: 'Show all' })).toBeVisible();
  await accounts.getByRole('button', { name: 'Show all' }).click();
  await accounts.getByRole('button', { name: 'Depth', exact: true }).click();
  await expect(accounts.getByRole('button', { name: 'Depth', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await accounts.locator('.statistics-chart__legend').getByRole('button', { name: 'Onlyfans', exact: true }).click();
  await expect(accounts.locator('.statistics-chart__legend').getByRole('button', { name: 'Onlyfans', exact: true })).toHaveAttribute('aria-pressed', 'false');
  await accounts.locator('.statistics-chart__legend').getByRole('button', { name: 'Onlyfans', exact: true }).click();
  await accounts.getByRole('button', { name: 'Account creation settings' }).click();
  const settingsRect = (await accounts.getByRole('region', { name: 'Account creation settings' }).boundingBox())!;
  expect(settingsRect.x).toBeGreaterThanOrEqual(0);
  expect(settingsRect.x + settingsRect.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  await accounts.screenshot({ path: info.outputPath('statistics-account-settings.png') });
  await accounts.getByRole('combobox', { name: 'Group accounts by' }).selectOption('day');
  await expect(accounts.getByRole('img', { name: 'Accounts per day bar graph' })).toBeVisible();
  await accounts.getByRole('combobox', { name: 'Group accounts by' }).selectOption('year');
  await expect(accounts.getByRole('img', { name: 'Accounts per year bar graph' })).toBeVisible();
  await expect(accounts.getByRole('combobox', { name: 'Accounts time range' })).toHaveValue('all');
  await expect(accounts.getByRole('combobox', { name: 'Account date' })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(accounts.getByRole('combobox', { name: 'Group accounts by' })).toHaveCount(0);
  await expect(accounts.getByRole('button', { name: 'Account creation settings' })).toBeFocused();
  await posts.getByRole('button', { name: 'Post publication settings' }).click();
  await expect(posts.getByRole('combobox', { name: 'Posts time range' })).toHaveValue('all');
  await posts.getByRole('combobox', { name: 'Group posts by' }).selectOption('minute');
  await expect(posts.getByRole('img', { name: 'Posts per minute bar graph' })).toBeVisible();
  await posts.getByRole('combobox', { name: 'Group posts by' }).selectOption('day');
  await expect(posts.getByRole('img', { name: 'Posts per day bar graph' })).toBeVisible();
  await posts.getByRole('combobox', { name: 'Posts time range' }).selectOption('custom');
  await posts.getByLabel('Posts from', { exact: true }).fill('2020-01-15');
  await posts.getByLabel('Posts through', { exact: true }).fill('2026-10-10');
  await posts.getByRole('button', { name: 'Apply dates' }).click();
  await expect(posts.getByRole('img', { name: 'Posts per day bar graph' })).toBeVisible();
  await expect(posts.getByText(/Showing month buckets/)).toHaveCount(0);
  await posts.getByRole('combobox', { name: 'Posts view' }).selectOption('cumulative');
  await expect(posts.getByRole('combobox', { name: 'Posts trendline' })).toBeDisabled();
  const seasonal = page.getByRole('region', { name: 'Seasonality', exact: true });
  await seasonal.getByRole('button', { name: 'Seasonality settings' }).click();
  await expect(posts.getByRole('combobox', { name: 'Posts view' })).toHaveCount(0);
  await seasonal.getByRole('combobox', { name: 'Seasonality cycle' }).selectOption('hour');
  await expect(seasonal.locator('.statistics-three__toolbar')).toContainText('24 points');
  await seasonal.getByRole('combobox', { name: 'Seasonality cycle' }).selectOption('monthday');
  await expect(seasonal.locator('.statistics-three__toolbar')).toContainText('31 points');
  await seasonal.getByRole('combobox', { name: 'Seasonality cycle' }).selectOption('month');
  await expect(seasonal.locator('.statistics-three__toolbar')).toContainText('12 points');
  await page.keyboard.press('Escape');
  await seasonal.screenshot({ path: info.outputPath('statistics-seasonality.png') });
  await page.getByRole('button', { name: 'Focus Fansly' }).click();
  await expect(page.getByRole('region', { name: 'Archive totals' })).toContainText('240,000');
  await expect(page.getByRole('region', { name: 'Download coverage' })).toContainText('70.0%');
  await expect(accounts.locator('.statistics-chart__legend')).not.toContainText('Onlyfans');
  await expect(posts.locator('.statistics-chart__legend')).not.toContainText('Onlyfans');
  await page.getByRole('button', { name: 'Archive trends settings' }).click();
  await page.getByRole('combobox', { name: 'Metric', exact: true }).selectOption('downloads');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('img', { name: 'Daily Downloaded vs pending trend' })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('statistics-filtered.png'), fullPage: true });
  expect(errors).toEqual([]);
});
