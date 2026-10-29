import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';

async function setup(page: Page) {
  await seedConfiguredApp(page, { theme: 'ultima-atlas', devMode: true });
  await installApiMocks(page);
  await page.route('**/api/v1/statistics?*', (route) => route.fulfill({ json: [{ site: 'onlyfans', snapshot: null, is_building: false, is_current: false, has_snapshot: false }] }));
  await page.route('**/api/v1/statistics/history?*', (route) => route.fulfill({ json: { range: '30d', sites: [], end_date: '2026-09-30', start_date: null } }));
  await page.route('**/api/v1/plugins', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/v1/plugins/metadata', (route) => route.fulfill({ json: { capabilities: [], event_types: [], task_types: [] } }));
  await page.routeWebSocket(/\/ws\//, () => {});
}

async function checkSurface(page: Page, selector: string) {
  const surface = page.locator(selector).first();
  await expect(surface).toBeVisible();
  const geometry = await surface.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    const css = getComputedStyle(node);
    return { left: rect.left, right: rect.right, viewport: innerWidth, radius: parseFloat(css.borderTopLeftRadius), background: css.backgroundImage };
  });
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(geometry.viewport + 1);
  expect(geometry.radius).toBeLessThanOrEqual(3);
  expect(geometry.background).toBe('none');
}

async function capture(page: Page, info: TestInfo, name: string) {
  await page.screenshot({ path: info.outputPath(`atlas-${name}.png`), fullPage: true });
}

test('Atlas renders every operational workspace without page overflow', async ({ page }, info) => {
  test.setTimeout(180_000);
  await setup(page);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const routes = ['jobs', 'jobs/new', 'network', 'auths', 'users', 'users/123', 'favourites', 'subscriptions', 'content', 'media', 'orders', 'chats', 'statistics', 'settings', 'system', 'tools', 'plugins', 'webhooks', 'logs'];
  for (const route of routes) {
    await page.goto(`/${route}`);
    await expect(page.locator('.atlas-main')).toBeVisible();
    await expect(page.locator('.route-loading')).toHaveCount(0);
    await expect(page.locator('.atlas-main')).not.toBeEmpty();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await capture(page, info, route.replaceAll('/', '-'));
  }
  expect(errors).toEqual([]);
});

test('Atlas styles proxy forms, bulk import, and analyzer without losing actions', async ({ page }, info) => {
  await setup(page);
  await page.goto('/network');
  await page.getByRole('button', { name: 'Add Proxy', exact: true }).click();
  await checkSurface(page, '.modal-content');
  await page.getByPlaceholder('http://host:port or socks5://host:port').fill('http://atlas.example:8080');
  await capture(page, info, 'proxy-form');
  await page.getByRole('button', { name: 'Close modal' }).click();
  await page.getByRole('button', { name: 'Bulk Import', exact: true }).click();
  await checkSurface(page, '.wy-bulk-modal');
  await capture(page, info, 'proxy-import');
  await page.locator('.wy-bulk-modal .modal-close').click();
  await page.getByRole('button', { name: 'Analyze baseline' }).click();
  await checkSurface(page, '.route-lab');
  await expect(page.locator('.route-lab-empty__mark')).toBeHidden();
  await expect(page.locator('.route-lab-empty__steps span').first()).toHaveCSS('border-radius', '0px');
  await expect(page.locator('.route-lab-empty__steps strong').first()).toHaveCSS('color', 'rgb(36, 170, 195)');
  await capture(page, info, 'proxy-analysis-ready');
  await page.getByRole('button', { name: /Start Analysis/i }).click();
  await expect(page.getByText(/Analysis complete!/)).toBeVisible();
  await capture(page, info, 'proxy-analysis');
});

test('Atlas confirmation contains focus, restores it, and retains mocked deletion', async ({ page }, info) => {
  await setup(page);
  await page.goto('/orders');
  await page.locator('.orders-row').first().click();
  const opener = page.getByRole('button', { name: 'Delete Order', exact: true });
  await opener.click();
  const dialog = page.getByRole('dialog', { name: 'Delete order?' });
  await checkSurface(page, '.atlas-confirm');
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(dialog.getByRole('button', { name: 'Delete order' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused();
  await capture(page, info, 'confirmation');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await opener.click();
  await dialog.getByRole('button', { name: 'Delete order' }).click();
  await expect(page.getByText('Order deleted')).toBeVisible();
});

test('Atlas keeps identity, content, account, and fleet dialogs usable', async ({ page }, info) => {
  await setup(page);
  await page.goto('/users');
  await page.getByRole('button', { name: /^Filters/ }).click();
  await checkSurface(page, '.content-library-filter-modal');
  await capture(page, info, 'identity-filters');
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await page.goto('/content');
  await page.getByRole('button', { name: /^Filters/ }).click();
  await checkSurface(page, '.content-library-filter-modal');
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await page.goto('/auths');
  await page.getByRole('button', { name: 'Manage', exact: true }).first().click();
  await checkSurface(page, '.manage-auth-modal');
  await capture(page, info, 'account-management');
  await page.locator('.manage-auth-modal .modal-close').click();
  await page.goto('/system');
  await page.getByRole('button', { name: 'Inspect smoke-host', exact: true }).click();
  await checkSurface(page, '.fleet-register-inspect-modal');
  await capture(page, info, 'backend-inspection');
  await page.getByRole('button', { name: 'Close inspection' }).click();
});

test('Atlas setup keeps the same onboarding flow', async ({ page }, info) => {
  await seedConfiguredApp(page, { theme: 'ultima-atlas', configured: false });
  await installApiMocks(page, { configured: false });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Welcome to UltimaScraper' })).toBeVisible();
  await checkSurface(page, '.setup-card');
  await capture(page, info, 'setup');
});

test('Atlas tool surfaces use flat framing and semantic badges', async ({ page }, info) => {
  await setup(page);
  await page.route('**/api/v1/api-requests/methods', (route) => route.fulfill({ json: { methods: {} } }));
  await page.goto('/tools');
  // The MPS tool opens on its ID-space map, which carries its own framing.
  await expect(page.locator('.mps-space-map')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'ID-space map' })).toBeAttached();
  await expect(page.locator('html')).toHaveCSS('color-scheme', 'dark');
  await expect(page.locator('html')).toHaveCSS('scrollbar-color', 'rgb(72, 85, 87) rgb(26, 31, 32)');
  await capture(page, info, 'mps-flat');
  await page.getByRole('button', { name: 'API Requests', exact: true }).click();
  await expect(page.locator('.tools-step')).toHaveCSS('border-radius', '2px');
  await expect(page.locator('.tools-step')).toHaveCSS('color', 'rgb(36, 170, 195)');
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await capture(page, info, 'api-requests');
});

test('Atlas application incidents retain details and recover through reload', async ({ page }, info) => {
  await setup(page);
  const module = /\/src\/themes\/ultima-atlas\/views\/statistics\/StatisticsPage\.tsx(?:\?|$)/;
  await page.route(module, (route) => route.abort());
  await page.goto('/statistics');
  const incident = page.getByRole('alert', { name: 'Application incident' });
  await expect(incident).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Application unavailable' })).toBeVisible();
  await expect(page.locator('.app-incident__status')).toHaveCSS('color', 'rgb(255, 0, 55)');
  await expect(page.locator('.app-incident__details')).not.toHaveAttribute('open');
  await page.getByText('Error details', { exact: true }).click();
  await expect(page.locator('.app-incident__details pre')).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await capture(page, info, 'application-incident');
  await page.unroute(module);
  await page.getByRole('button', { name: 'Reload application' }).click();
  await expect(page.locator('.atlas-main')).toBeVisible();
  await expect(incident).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Statistics', exact: true })).toBeVisible();
});
