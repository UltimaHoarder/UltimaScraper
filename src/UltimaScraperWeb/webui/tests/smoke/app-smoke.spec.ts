import { expect, test, type Page } from '@playwright/test';

import { installApiMocks, seedConfiguredApp, seedSetupApp } from './helpers';

async function expectSystemPulseGeometry(page: Page) {
  const geometry = await page.locator('.system-pulse').evaluate((dashboard) => {
    const dashboardBounds = dashboard.getBoundingClientRect();
    const rect = (selector: string) => {
      const bounds = dashboard.querySelector(selector)?.getBoundingClientRect();
      return bounds
        ? { top: bounds.top, bottom: bounds.bottom, height: bounds.height }
        : null;
    };
    const kpis = dashboard.querySelector('.system-pulse__kpis');
    const grid = dashboard.querySelector('.system-pulse__grid');
    const rootFontSize = Number.parseFloat(
      window.getComputedStyle(document.documentElement).fontSize,
    );
    return {
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      rootFontSize,
      dashboard: {
        top: dashboardBounds.top,
        bottom: dashboardBounds.bottom,
        height: dashboardBounds.height,
      },
      topbar: rect('.system-pulse__topbar'),
      throughput: rect('.system-pulse__throughput'),
      chart: rect('.system-pulse__chart'),
      kpiHeight: rect('.system-pulse__kpis article')?.height ?? 0,
      kpiColumns: kpis
        ? window.getComputedStyle(kpis).gridTemplateColumns.split(' ').length
        : 0,
      // Narrow layouts switch the panel grid to a flex column; a non-grid
      // container still reports its declared template, so count it as one.
      gridColumns: grid
        ? window.getComputedStyle(grid).display === 'grid'
          ? window.getComputedStyle(grid).gridTemplateColumns.split(' ').length
          : 1
        : 0,
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    };
  });

  // Breakpoints and card heights follow the Atlas dashboard stylesheet.
  const narrow = geometry.viewportWidth <= 760;
  const expectedColumns = narrow ? 2 : geometry.viewportWidth <= 1279 ? 3 : 6;
  const expectedGridColumns = narrow ? 1 : 2;
  expect(geometry.kpiColumns).toBe(expectedColumns);
  expect(geometry.gridColumns).toBe(expectedGridColumns);
  expect(Math.abs(geometry.kpiHeight - (narrow ? 110 : 116))).toBeLessThan(1.5);
  expect(geometry.chart?.bottom ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(
    geometry.throughput?.bottom ?? Number.NEGATIVE_INFINITY,
  );
  if (geometry.viewportWidth > 820) {
    expect(geometry.topbar?.height ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(
      geometry.rootFontSize * 4.8,
    );
  }
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth + 1);
  expect(geometry.dashboard?.bottom ?? Number.NEGATIVE_INFINITY).toBeGreaterThanOrEqual(
    geometry.viewportHeight - 64,
  );
}

test.describe('webui smoke flows', () => {
  test('loads the setup wizard when setup is incomplete', async ({ page }) => {
    await seedSetupApp(page);
    await installApiMocks(page, { configured: false });

    await page.goto('/setup');

    await expect(page.getByRole('heading', { name: 'Set up UltimaScraper' })).toBeVisible();
    await expect(page.getByText('Install and configure your environment in one flow')).toBeVisible();
  });

  test('loads the dashboard and system surfaces', async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'System telemetry' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Active jobs' })).toBeVisible();
    await expectSystemPulseGeometry(page);

    await page.goto('/system');
    await expect(page.getByRole('heading', { name: 'Resource register' })).toBeVisible();
  });

  test('renders key surfaces under the registered theme', async ({ page }, testInfo) => {
    await seedConfiguredApp(page, { theme: 'ultima-atlas' });
    await installApiMocks(page);

    await page.goto('/');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'ultima-atlas');
    await expectSystemPulseGeometry(page);
    if (process.env.CAPTURE_THEME_SHOTS === '1') {
      await page.screenshot({ path: testInfo.outputPath('atlas-dashboard.png'), fullPage: true });
    }

    await page.goto('/users/123?site=onlyfans');
    await expect(page.getByRole('heading', { name: 'Alice Example' })).toBeVisible();
    await expect(page.getByText('Subject record')).toBeVisible();
    if (process.env.CAPTURE_THEME_SHOTS === '1') {
      await page.screenshot({ path: testInfo.outputPath('ultimur-user-profile.png'), fullPage: true });

      await page.getByRole('button', { name: 'Content', exact: true }).click();
      await expect(page.getByPlaceholder('Search content...')).toBeVisible();
      await page.screenshot({
        path: testInfo.outputPath('ultimur-user-profile-content.png'),
        fullPage: true,
      });

      await page
        .locator('.ultimur-profile-tabs')
        .getByRole('button', { name: /Paid/ })
        .click();
      await expect(page.getByPlaceholder('Search paid content...')).toBeVisible();
      await page.screenshot({
        path: testInfo.outputPath('ultimur-user-profile-paid.png'),
        fullPage: true,
      });
    }

    await page.goto('/jobs');
    await expect(page.getByRole('heading', { name: 'Operations ledger' })).toBeVisible();
    await expect(page.getByRole('table', { name: 'Jobs operations ledger' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Saved views' })).toBeVisible();
    await expect(page.getByRole('button', { name: /New job/i })).toBeVisible();
    const ledger = page.locator('.jobs-ledger');
    const firstLedgerRow = page.locator('.jobs-ledger-table tbody tr').first();
    const ledgerViewport = page.locator('.jobs-ledger-table-viewport');
    const ledgerWidth = await ledger.evaluate((element) => element.getBoundingClientRect().width);
    const rootFontSize = await page.evaluate(() =>
      Number.parseFloat(window.getComputedStyle(document.documentElement).fontSize),
    );

    await expect(firstLedgerRow).toHaveCSS(
      'display',
      ledgerWidth <= 45 * rootFontSize ? 'flex' : 'table-row',
    );
    const ledgerOverflow = await ledgerViewport.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(ledgerOverflow.scrollWidth).toBeLessThanOrEqual(ledgerOverflow.clientWidth + 1);

    const statusOverflow = await page.locator('.jobs-ledger-statuses').evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(statusOverflow.scrollWidth).toBeLessThanOrEqual(statusOverflow.clientWidth + 1);

    const pageOverflow = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(pageOverflow.scrollWidth).toBeLessThanOrEqual(pageOverflow.clientWidth + 1);
    if (process.env.CAPTURE_THEME_SHOTS === '1') {
      await page.screenshot({ path: testInfo.outputPath('ultimur-jobs.png'), fullPage: true });
    }

    await page.goto('/users');
    await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible();
    if (process.env.CAPTURE_THEME_SHOTS === '1') {
      await page.screenshot({ path: testInfo.outputPath('ultimur-users.png'), fullPage: true });
    }

    await page.goto('/chats');
    await expect(page.getByRole('heading', { name: 'Chats' })).toBeVisible();
    if (process.env.CAPTURE_THEME_SHOTS === '1') {
      await page.screenshot({ path: testInfo.outputPath('ultimur-chats.png'), fullPage: true });
    }

    await page.goto('/system');
    await expect(page.getByRole('heading', { name: 'Resource register' })).toBeVisible();
    if (process.env.CAPTURE_THEME_SHOTS === '1') {
      await page.screenshot({ path: testInfo.outputPath('ultimur-system.png'), fullPage: true });
    }
  });

  test('keeps the operations ledger dense at constrained desktop width', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop', 'One exact constrained-desktop regression is sufficient.');

    await page.setViewportSize({ width: 1240, height: 900 });
    await seedConfiguredApp(page, { theme: 'ultima-atlas' });
    await installApiMocks(page);
    await page.goto('/jobs');

    const ledger = page.locator('.jobs-ledger');
    const ledgerWidth = await ledger.evaluate((element) => element.getBoundingClientRect().width);
    const rootFontSize = await page.evaluate(() =>
      Number.parseFloat(window.getComputedStyle(document.documentElement).fontSize),
    );
    expect(ledgerWidth).toBeGreaterThan(45 * rootFontSize);
    expect(ledgerWidth).toBeLessThanOrEqual(88 * rootFontSize);

    await expect(page.locator('.jobs-ledger-table tbody tr').first()).toHaveCSS('display', 'table-row');
    await expect(page.locator('.jobs-ledger-table thead .jobs-ledger-cell-target')).toHaveCSS('display', 'table-cell');
    await expect(page.locator('.jobs-ledger-table thead .jobs-ledger-cell-owner')).toHaveCSS('display', 'none');

    const overflow = await page.locator('.jobs-ledger-table-viewport').evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);

    if (process.env.CAPTURE_THEME_SHOTS === '1') {
      await page.screenshot({ path: testInfo.outputPath('ultimur-jobs-constrained.png'), fullPage: true });
    }
  });

  test('reports the registered theme in settings appearance', async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/settings');
    await page.getByRole('button', { name: 'Appearance' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'ultima-atlas');
    await expect(page.getByLabel('Active theme')).toHaveCount(0);
    await expect(page.locator('.theme-static-value')).toHaveText('Ultima Atlas');
    await expect(
      page.getByText('The current theme is registered and active.', { exact: false }),
    ).toBeVisible();
  });

  test('creates, retries, and cancels jobs from the workspace', async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/jobs');
    await expect(page.getByRole('heading', { name: 'Operations ledger' })).toBeVisible();

    await page.getByRole('button', { name: /New job/i }).click();
    await page.getByPlaceholder('Enter a descriptive name for this job').fill('Creator Smoke');
    await page.getByPlaceholder('target-user').fill('charlie');
    await page.getByRole('button', { name: 'Add Task to Queue' }).click();
    await page.getByRole('button', { name: /Create Job/i }).last().click();

    await expect(page.getByText('Creator Smoke')).toBeVisible();

    await page.getByRole('checkbox', { name: 'Select Failed Smoke Job' }).check();
    await page.getByRole('button', { name: 'Retry failed (1)' }).click();
    await expect(page.getByText('1 retry queued.')).toBeVisible();

    await page.getByRole('checkbox', { name: 'Select Running Smoke Job' }).check();
    await page.getByRole('button', { name: 'Cancel jobs (1)' }).click();
    await page.locator('.confirm-dialog').getByRole('button', { name: 'Cancel job' }).click();
    await expect(page.getByText('Cancellation requested for 1 job.')).toBeVisible();
  });

  test('navigates from users into a user profile', async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/users');
    await expect(page.getByRole('heading', { name: 'Users' })).toBeVisible();
    await page.getByPlaceholder('Search by identifier…').fill('alice');
    await expect(page).toHaveURL(/identifier=alice/);
    await page.locator('button[title="Table view"]').click();
    await page.locator('table .username-link').click();

    await expect(page).toHaveURL(/\/users\/123\?/);
    await expect(page.getByText('@alice')).toBeVisible();
    await page.getByRole('button', { name: /Back/i }).click();
    await expect(page).toHaveURL(/\/users\?/);
    await expect(page).toHaveURL(/identifier=alice/);
  });

  test('filters subscriptions and preserves profile return context', async ({ page }) => {
    await seedConfiguredApp(page);
    await installApiMocks(page);

    await page.goto('/subscriptions');
    await expect(page.getByRole('heading', { name: 'Subscriptions' })).toBeVisible();

    await page.getByPlaceholder('Search by identifier…').fill('alice');
    await expect(page).toHaveURL(/identifier=alice/);
    await expect(page.getByText('@alice')).toBeVisible();

    await page.goto(
      '/users/123?site=onlyfans&source=subscriptions&return_to=%2Fsubscriptions%3Factive_only%3Dtrue%26hide_free%3Dfalse%26sort_by%3Did%26sort_order%3Ddesc%26identifier%3Dalice',
    );
    await page.getByRole('button', { name: /Back/i }).click();
    await expect(page).toHaveURL(/\/subscriptions\?/);
    await expect(page).toHaveURL(/identifier=alice/);
  });
});
