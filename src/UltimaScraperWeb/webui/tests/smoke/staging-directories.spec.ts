import { expect, test } from '@playwright/test';

import { installApiMocks, seedConfiguredApp } from './helpers';

test('edits the global staging directories from the mounts tab', async ({ page }, testInfo) => {
  await seedConfiguredApp(page);
  await installApiMocks(page);

  await page.goto('/system');
  await page.getByRole('button', { name: /^mounts/i }).click();
  await expect(page.getByRole('heading', { name: 'Staging directories' })).toBeVisible();

  await page.getByRole('button', { name: '+ Add staging directory' }).click();
  await page.getByLabel('Path', { exact: true }).fill('/dev/shm/staging');

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  if (process.env.CAPTURE_THEME_SHOTS === '1') {
    await page.locator('.fleet-staging').screenshot({ path: testInfo.outputPath('staging-directories.png') });
  }

  const saved = page.waitForRequest(
    (request) => request.method() === 'PUT' && new URL(request.url()).pathname.replace(/\/$/, '') === '/api/v1/settings',
  );
  await page.getByRole('button', { name: 'Save staging directories' }).click();
  const payload = (await saved).postDataJSON() as {
    download_setup: { staging_directories: Array<{ path: string; usage: string[] }> };
  };

  expect(payload.download_setup.staging_directories).toEqual([
    expect.objectContaining({ path: '/dev/shm/staging', usage: ['downloads', 'merge', 'drm'] }),
  ]);
  await expect(page.getByRole('status').filter({ hasText: 'Staging directories saved' })).toBeVisible();
});
