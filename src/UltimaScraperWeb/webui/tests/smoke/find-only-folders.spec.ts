import { expect, test } from '@playwright/test';

import { installApiMocks, seedConfiguredApp } from './helpers';

test('marks an alternate site folder as find-only from the mounts tab', async ({ page }, testInfo) => {
  await seedConfiguredApp(page);
  await installApiMocks(page);

  await page.goto('/system');
  await page.getByRole('button', { name: /^mounts/i }).click();
  await expect(page.getByRole('heading', { name: 'Find-only site folders' })).toBeVisible();

  await page.getByRole('checkbox', { name: 'OnlyFansImages' }).check();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);

  if (process.env.CAPTURE_THEME_SHOTS === '1') {
    await page
      .getByRole('region', { name: 'Find-only site folders' })
      .screenshot({ path: testInfo.outputPath('find-only-folders.png') });
  }

  const saved = page.waitForRequest(
    (request) => request.method() === 'PUT' && new URL(request.url()).pathname.replace(/\/$/, '') === '/api/v1/settings',
  );
  await page.getByRole('button', { name: 'Save find-only folders' }).click();
  const payload = (await saved).postDataJSON() as {
    download_setup: { find_only_site_directories: Record<string, string[]> };
  };

  expect(payload.download_setup.find_only_site_directories).toEqual({ onlyfans: ['OnlyFansImages'] });
  await expect(page.getByRole('status').filter({ hasText: 'Find-only folders saved' })).toBeVisible();
});
