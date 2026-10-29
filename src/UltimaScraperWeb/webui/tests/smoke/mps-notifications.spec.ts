import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';

for (const theme of ['ultima-atlas'] as const) {
  test(`${theme} shows MPS acceptance as a dismissible notification`, async ({ page }, info) => {
    await seedConfiguredApp(page, { theme });
    await installApiMocks(page);
    await page.routeWebSocket(/\/ws\//, () => {});
    await page.route('**/api/v1/mps/create-job', (route) => route.fulfill({ json: {
      job: { job_id: 'job-notification-test', materialization_status: 'queued' },
      selected_profiles: 200, remaining_candidate_count: 1_800,
      candidate_offset: 0, next_candidate_offset: 200, next_batch_size: 200,
      has_next_batch: true,
    } }));
    await page.goto('/tools');
    await expect(page.getByRole('heading', { name: 'ID-space map', exact: true })).toBeVisible();
    const create = page.getByRole('button', { name: 'Create Job', exact: true });
    await expect(create).toBeVisible();
    await expect(page.locator('.mps-design')).toBeVisible();
    await expect(page.locator('.mps-id-map-plot')).toBeVisible();
    await expect(create).toBeEnabled();
    if (info.project.name === 'desktop') {
      // The map is read-only; a bounded range is entered through the ID boundaries.
      const analysisRequest = page.waitForRequest((request) => request.url().endsWith('/mps/analyze') && request.postDataJSON().start_id === 2501);
      await page.getByText('ID boundaries', { exact: true }).click();
      await page.getByLabel('First profile ID (optional)').fill('2501');
      await page.getByLabel('Last profile ID (optional)').fill('7500');
      const bounded = (await analysisRequest).postDataJSON();
      expect(bounded.bounded).toBe(true);
      expect(bounded.end_id).toBe(7500);
      await expect(create).toBeEnabled();
      await page.getByLabel('First profile ID (optional)').fill('');
      await page.getByLabel('Last profile ID (optional)').fill('');
      await expect(create).toBeEnabled();
    }
    await page.screenshot({ path: info.outputPath('mps-id-space-map.png'), fullPage: true });
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: 'Configure lookup routes' }).click();
    await expect(page.getByRole('dialog', { name: 'Lookup routes', exact: true })).toBeVisible();
    await expect(page.getByText('http://proxy1.example:8080', { exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByText('Candidate IDs (Preview)', { exact: true })).toHaveCount(0);
    await page.clock.install();
    await create.click();
    const notification = page.locator('.toast-container').getByRole('status');
    await expect(notification).toContainText('Job job-notification-test accepted. Materializing 200 profile tasks');
    await expect(page.locator('.tools-alert.success')).toHaveCount(0);
    await expect(page.getByText('Materializing', { exact: true })).toBeVisible();
    const geometry = await notification.evaluate((node) => {
      const rect = node.getBoundingClientRect();
      return { withinViewport: rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight };
    });
    expect(geometry.withinViewport).toBe(true);
    await page.screenshot({ path: info.outputPath(`${theme}-mps-notification.png`) });
    await page.getByRole('button', { name: 'Close notification' }).click();
    await expect(notification).toHaveCount(0);
    await expect(page.getByText('Materializing', { exact: true })).toBeVisible();
    await create.click();
    await expect(notification).toBeVisible();
    await page.clock.fastForward(8_000);
    await expect(notification).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Queue Next Batch' })).toBeVisible();
  });
}
