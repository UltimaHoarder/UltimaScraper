import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';

for (const theme of ['ultima-atlas'] as const) {
  test(`${theme} diagnostics and recovery retain their workflows`, async ({ page }, info) => {
    await seedConfiguredApp(page, { theme });
    await installApiMocks(page);
    await page.routeWebSocket(/\/ws\//, () => {});
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'clipboard', { value: { writeText: async () => {} } });
    });
    const started = '2026-03-08T00:00:00Z';
    const completed = '2026-03-08T00:01:00Z';
    const task = {
      task_id: 'task-download-failed', task_type: 'download_media', status: 'failed',
      site: 'onlyfans', username: 'bravo', content_type: 'Posts', payload: { auth_id: 2 },
      started_at: started, completed_at: completed, progress: 0.5,
      items_processed: 1, items_total: 2, error: 'Transfer stopped after media errors.',
      result: { output: {
        failure_breakdown: { url_expired: 1, disk_full: 1 },
        download_results: [
          { content_id: 8801, media_id: 9001, status: 'failed',
            url: 'https://media.example.test/9001', path: '/archive/bravo/posts/9001.jpg',
            errors: [{ reason: 'url_expired', message: 'The source URL expired before transfer started.' }] },
          { content_id: 8802, media_id: 9002, status: 'failed', path: '/archive/bravo/posts/9002.mp4',
            errors: [{ reason: 'disk_full', message: 'The selected destination has insufficient capacity.' }] },
        ],
      } },
    };
    await page.route(/\/api\/v1\/jobs\/job-failed-1(?:\?|$)/, (route) => route.fulfill({ json: {
      job_id: 'job-failed-1', job_name: 'Failed Smoke Job', job_type: 'scrape', status: 'failed',
      site: 'onlyfans', priority: 0, worker_id: 'worker-1', retries: 0, max_retries: 3,
      created_at: started, started_at: started, completed_at: completed,
      result_success: false, result_message: null, result_error: 'Transfer failed', args: {},
      tasks: [task], task_stats: { total: 1, ready: 0, blocked: 0, inflight: 0,
        deferred: 0, completed: 0, failed: 1, task_type_counts: { download_media: 1 } },
    } }));
    await page.route(/\/api\/v1\/jobs\/job-failed-1\/tasks(?:\?|$)/, (route) => route.fulfill({ json: {
      tasks: [task], next_cursor: null, has_more: false, scanned_count: 1, offset: 0, limit: 100,
    } }));
    await page.route(/\/api\/v1\/jobs\/job-failed-1\/runtime-samples(?:\?|$)/, (route) => route.fulfill({ json: {
      samples: Array.from({ length: 61 }, (_, seconds) => ({
        cursor: `sample-${seconds}`, timestamp_ms: Date.parse(started) + seconds * 1_000,
        total: 1, ready: 0, inflight: seconds === 60 ? 0 : 1, completed: 0, failed: seconds === 60 ? 1 : 0,
      })), next_after_id: null, has_more: false,
    } }));
    await page.goto('/jobs');
    await page.getByRole('button', { name: /Failed Smoke Job job-failed-1/ }).click();
    const modal = page.locator('.jdm-modal');
    await modal.getByRole('tab', { name: 'Diagnostics', exact: true }).click();
    await expect(modal.locator('.jdr-container')).toBeVisible();
    await expect(modal.locator('.jdr-chart-card').first()).toBeVisible();
    await modal.getByRole('button', { name: /Copy Markdown Report/ }).click();
    await expect(modal.getByRole('button', { name: 'Markdown Report copied to clipboard' })).toBeVisible();
    if (theme === 'ultima-atlas') {
      await expect(modal.locator('.jdr-view-btn.active')).toHaveCSS('border-top-color', 'rgb(36, 170, 195)');
      await expect(modal.locator('.jdr-chart-card').first()).toHaveCSS('border-radius', '2px');
      // Charts draw on an ECharts canvas; each series' colour shows in its legend dot.
      await expect(modal.locator('.jdr-chart-card .jdr-echart-canvas').first()).toBeAttached();
      const traces = modal.locator('.jdr-chart-card .jdr-legend-dot');
      await expect(traces.first()).toBeAttached();
      const colors = await traces.evaluateAll((nodes) => nodes.map((node) => getComputedStyle(node).backgroundColor));
      expect(colors).toContain('rgb(36, 170, 195)');
      expect(colors.every((color) => ['rgb(36, 170, 195)', 'rgb(244, 244, 242)', 'rgb(255, 211, 3)', 'rgb(255, 0, 55)', 'rgb(190, 200, 201)', 'rgb(52, 58, 59)'].includes(color))).toBe(true);
      expect(await modal.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
      await page.screenshot({ path: info.outputPath('atlas-diagnostics.png') });
    } else {
      expect(await modal.evaluate((node) => getComputedStyle(node).getPropertyValue('--jdm-runbook-accent').trim())).toBe('#efb768');
    }
    await modal.getByRole('button', { name: /Compare/, exact: false }).click();
    await expect(modal.locator('#jdr-baseline-select')).toBeVisible();
    await modal.getByRole('tab', { name: /Errors/ }).click();
    await expect(modal.getByRole('heading', { name: 'Recovery console' })).toBeVisible();
    await modal.getByRole('button', { name: 'Copy summary', exact: true }).click();
    await expect(modal.getByRole('button', { name: 'Summary copied' })).toBeVisible();
    await modal.getByRole('tab', { name: /Signed URL expired/ }).click();
    await modal.getByRole('button', { name: /Inspect Posts 8801 media 9001 evidence/i }).click();
    const evidence = modal.getByRole('region', { name: 'Selected affected evidence' });
    await expect(evidence).toBeVisible();
    await evidence.getByText('Raw evidence record', { exact: true }).click();
    await expect(evidence.locator('pre')).toContainText('9001');
    if (theme === 'ultima-atlas') {
      await expect(modal.locator('.jdm-error-badge').first()).toHaveCSS('color', 'rgb(255, 0, 55)');
      await expect(modal.locator('.jdm-recovery-posture')).toHaveCSS('border-radius', '0px');
      await expect(modal.locator('.jdm-recovery-heading')).toHaveCSS('background-image', 'none');
      expect(await modal.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
      await page.screenshot({ path: info.outputPath('atlas-recovery-evidence.png') });
    }
    await evidence.getByRole('button', { name: 'Close affected evidence' }).click();
    const retry = page.waitForRequest((request) => request.url().includes('/jobs/job-failed-1/retry') && request.method() === 'POST');
    await modal.getByRole('button', { name: 'Create retry job', exact: true }).click();
    await retry;
    await expect(modal).not.toBeVisible();
  });
}
