import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, type Page } from '@playwright/test';
import { installApiMocks, seedConfiguredApp, seedSetupApp } from '../smoke/helpers';
import { installDemoMocks, installDemoSetupMocks } from './demoData';

// Writes docs/assets/screenshots/*.png. SCREENSHOT_DIR writes elsewhere, e.g.
// to review a capture before replacing the committed images.
const OUT_DIR = process.env.SCREENSHOT_DIR ?? fileURLToPath(new URL('../../../../../docs/assets/screenshots', import.meta.url));

async function capture(page: Page, name: string, settleMs = 1500) {
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(settleMs);
  await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`) });
}

const PAGES: Array<{ name: string; url: string; settleMs?: number }> = [
  // The dashboard measures throughput between polls, so give it a few.
  { name: 'dashboard', url: '/', settleMs: 12_000 },
  { name: 'jobs', url: '/jobs' },
  { name: 'statistics', url: '/statistics', settleMs: 4_000 },
  { name: 'users', url: '/users' },
  { name: 'system', url: '/system' },
];

for (const { name, url, settleMs } of PAGES) {
  test(name, async ({ page }) => {
    test.setTimeout(60_000);
    await seedConfiguredApp(page);
    await installApiMocks(page);
    await installDemoMocks(page);
    await page.goto(url);
    await capture(page, name, settleMs);
  });
}

test('setup', async ({ page }) => {
  await seedSetupApp(page);
  await installApiMocks(page, { configured: false });
  await installDemoSetupMocks(page);
  await page.goto('/setup');
  await capture(page, 'setup');

  // A new cluster on this machine takes the recommended components and goes
  // straight to the review, with its architecture diagram.
  await page.getByText('Create a cluster', { exact: true }).click();
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByText('Local', { exact: true }).click();
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.setViewportSize({ width: 1440, height: 1240 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await capture(page, 'setup-review');
});
