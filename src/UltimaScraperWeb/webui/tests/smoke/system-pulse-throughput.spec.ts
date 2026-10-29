import { expect, test } from '@playwright/test';

import { installApiMocks, seedConfiguredApp } from './helpers';

test('shows MPS completion throughput while active profile counters stay zero', async ({ page }, testInfo) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas' });
  await installApiMocks(page);
  await page.routeWebSocket('**/ws/**', () => {});

  let firstSample: number | undefined;
  let taskSnapshot = 0;
  await page.route('**/api/v1/jobs?*', async (route) => {
    firstSample ??= Date.now();
    await route.fulfill({ json: {
      jobs: [{
        job_id: 'job-mps-throughput',
        job_name: 'MPS profile checks',
        created_by: 'webui_mps',
        status: 'running',
        task_count: 674439,
        completed_tasks: 243775 + Math.floor((Date.now() - firstSample) * 28 / 1000),
        failed_tasks: 0,
        created_at: '2026-09-05T00:00:00Z',
        updated_at: null,
      }],
      total: 1, page: 1, page_size: 200,
    } });
  });
  await page.route('**/api/v1/jobs/active-tasks?*', async (route) => {
    taskSnapshot += 1;
    await route.fulfill({ json: {
      tasks: [{
        job_id: 'job-mps-throughput',
        task_id: `profile-${taskSnapshot}`,
        task_type: 'scrape',
        content_type: 'Profile',
        status: 'running',
        items_processed: 0,
        items_scraped: 0,
        items_saved: 0,
      }],
      total: 1,
    } });
  });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'System telemetry' })).toBeVisible();
  const itemMetric = page.locator('article').filter({
    has: page.getByText('Items / sec', { exact: true }),
  });
  await expect.poll(
    async () => Number(await itemMetric.locator('strong').innerText()),
    { timeout: 15000 },
  ).toBeGreaterThan(25);
  expect(Number(await itemMetric.locator('strong').innerText())).toBeLessThan(31);
  expect(taskSnapshot).toBeGreaterThan(1);
  const writeMetric = page.locator('article').filter({
    has: page.getByText('Write throughput', { exact: true }),
  });
  await expect(writeMetric.getByText('2.00 MB/s')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('mps-throughput.png'), fullPage: true });
});
