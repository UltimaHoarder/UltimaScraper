import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { installApiMocks, seedConfiguredApp } from './helpers';

// firstVisit: no migration check is recorded, so the startup gate shows.
async function setup(page: Page, firstVisit = false, theme = 'ultima-atlas') {
  await seedConfiguredApp(page);
  await page.addInitScript(({ theme, firstVisit }) => {
    localStorage.setItem('usr_theme', theme);
    if (firstVisit) {
      for (const key of Object.keys(localStorage)) {
        if (key.startsWith('usr_migration_done_startup_id')) localStorage.removeItem(key);
      }
    }
  }, { theme, firstVisit });
  await installApiMocks(page);
  await page.routeWebSocket(/\/ws\//, () => {});
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

async function capture(page: Page, info: TestInfo, name: string) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true });
}

const upToDate = { status: 'no_changes', message: 'Database schema is up to date', output: [] };

const review = {
  status: 'ready', preview_id: 'preview-test', revision: 'atlas-revision',
  filename: 'add_inventory_metrics_to_daily_statistics.py', diff: '+ inventory_metrics\n- legacy_column',
  message: 'Schema changes require review', has_changes: true, can_apply: true, output: ['Backend connected'],
};

test('Atlas startup handles slow connections and reduced motion', async ({ page }, info) => {
  await setup(page, true);
  await page.route('**/api/v1/setup/migrations/preview', (route) => route.fulfill({ json: upToDate }));
  const gate = deferred();
  await page.route('**/api/v1/system/bootstrap', async (route) => {
    // Hold only the app's bootstrap query (XHR); anything else passes.
    if (route.request().resourceType() !== 'xhr') return route.fallback();
    await gate.promise;
    await route.fallback();
  });
  await page.clock.install();
  await page.goto('/tools');
  await expect(page.locator('.startup-atlas-mark')).toBeVisible();
  await expect(page.locator('.startup-container')).toHaveAttribute('data-state', 'connecting');
  await expect(page.locator('.startup-status-text')).toHaveCSS('color', 'rgb(36, 170, 195)');
  await expect(page.locator('.startup-glow')).toBeHidden();
  await expect(page.locator('.startup-container')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await capture(page, info, 'startup-connecting');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect(await page.locator('.startup-pulse').evaluate((node) => getComputedStyle(node, '::after').animationName)).toBe('none');
  await page.clock.fastForward(10_100);
  await expect(page.getByText('Still connecting.', { exact: true })).toBeVisible();
  await expect(page.locator('.startup-status-text')).toHaveCSS('color', 'rgb(255, 211, 3)');
  await expect(page.getByRole('button', { name: 'Retrying…' })).toBeDisabled();
  await capture(page, info, 'startup-slow');
  gate.resolve();
  await expect(page.locator('.atlas-main')).toBeVisible();
});

test('Atlas backend failure retains the retry action', async ({ page }, info) => {
  await setup(page, true);
  await page.route('**/api/v1/setup/migrations/preview', (route) => route.fulfill({ json: upToDate }));
  let recover = false;
  await page.route('**/api/v1/system/bootstrap', (route) => recover || route.request().resourceType() !== 'xhr' ? route.fallback() : route.fulfill({ status: 503, json: { detail: 'Backend unavailable' } }));
  await page.goto('/tools');
  await expect(page.getByRole('status')).toContainText('Backend unavailable', { timeout: 15_000 });
  await expect(page.locator('.startup-status-text')).toHaveCSS('color', 'rgb(255, 0, 55)');
  await expect(page.getByRole('button', { name: 'Retry connection' })).toBeEnabled();
  await capture(page, info, 'startup-error');
  recover = true;
  await page.getByRole('button', { name: 'Retry connection' }).click();
  await expect(page.locator('.atlas-main')).toBeVisible();
});

test('Atlas migration review stays gated and applies only the approved preview', async ({ page }, info) => {
  await setup(page, true);
  const applied: unknown[] = [];
  await page.route('**/api/v1/setup/migrations/preview', (route) => route.fulfill({ json: review }));
  await page.route('**/api/v1/setup/migrations/apply', (route) => {
    applied.push(route.request().postDataJSON());
    return route.fulfill({ json: { success: true, message: 'Migration applied', output: [] } });
  });
  await page.goto('/tools');
  const apply = page.getByRole('button', { name: 'Apply migration' });
  await expect(apply).toBeFocused();
  await expect(page.locator('.startup-status-text')).toHaveCSS('color', 'rgb(255, 211, 3)');
  await expect(page.locator('.startup-terminal')).toHaveCSS('box-shadow', 'none');
  await expect(page.locator('.startup-review-panel')).toHaveCSS('background-image', 'none');
  expect(applied).toEqual([]);
  await capture(page, info, 'startup-review');
  await apply.click();
  await expect(page.locator('.atlas-main')).toBeVisible();
  expect(applied).toEqual([{ preview_id: 'preview-test' }]);
});

test('Atlas migration review preserves regeneration and skip actions', async ({ page }, info) => {
  await setup(page, true);
  let discarded = false;
  await page.route('**/api/v1/setup/migrations/preview', (route) => route.fulfill({ json: review }));
  await page.route('**/api/v1/setup/migrations/regenerate', (route) => route.fulfill({ json: { ...review, preview_id: 'preview-regenerated', revision: 'atlas-revised' } }));
  await page.route('**/api/v1/setup/migrations/discard', (route) => {
    discarded = true;
    return route.fulfill({ json: { success: true, message: 'Skipped', output: [] } });
  });
  await page.goto('/tools');
  await page.getByRole('button', { name: 'Generate preview again' }).click();
  await expect(page.getByText('Revision: atlas-revised')).toBeVisible();
  await capture(page, info, 'startup-regenerated');
  await page.getByRole('button', { name: 'Skip for this startup' }).click();
  await expect(page.locator('.atlas-main')).toBeVisible();
  expect(discarded).toBe(true);
});

test('Atlas lazy routes announce loading with a static reduced-motion rail', async ({ page }, info) => {
  await setup(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const gate = deferred();
  // Hold the Tools view's module, so its loading screen stays up until released.
  await page.route(/\/src\/themes\/ultima-atlas\/views\/tools\/ToolsPage\.tsx(?:\?|$)/, async (route) => { await gate.promise; await route.continue(); });
  await page.goto('/tools');
  await expect(page.getByRole('status')).toContainText('Loading workspace...');
  await expect(page.locator('.route-loading')).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('.startup-atlas-mark')).toBeVisible();
  expect(await page.locator('.route-loading__pulse').evaluate((node) => getComputedStyle(node, '::after').animationName)).toBe('none');
  await capture(page, info, 'route-loading');
  gate.resolve();
  await expect(page.locator('.atlas-main')).toBeVisible();
});

test('Atlas skeletons and inline media loaders remain readable', async ({ page }, info) => {
  await setup(page);
  await page.route('**/api/v1/search-loadouts/?*', (route) => route.fulfill({ json: { success: true, loadouts: [], default_name: null } }));
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const content = deferred();
  await page.route('**/api/v1/database/content?*', async (route) => { await content.promise; await route.fallback(); });
  await page.goto('/content');
  await expect(page.getByRole('status', { name: 'Loading content' })).toBeVisible();
  await expect(page.locator('.skeleton').first()).toHaveCSS('animation-name', 'none');
  await expect(page.locator('.content-card-skeleton').first()).toHaveCSS('border-radius', '0px');
  await capture(page, info, 'content-loading');
  content.resolve();
  await expect(page.locator('.skeleton')).toHaveCount(0);
  const media = deferred();
  await page.route('**/api/v1/database/media?*', async (route) => { await media.promise; await route.fallback(); });
  await page.goto('/media');
  await expect(page.getByRole('status')).toContainText('Loading media');
  await expect(page.locator('.ops-state-spinner')).toHaveCSS('height', '4px');
  await expect(page.locator('.ops-state-spinner')).toHaveCSS('border-radius', '0px');
  await capture(page, info, 'media-loading');
  media.resolve();
  await expect(page.locator('.ops-state-spinner')).toHaveCount(0);
});


test('Atlas job-details loading text stays outside the indeterminate rail', async ({ page }, info) => {
  await setup(page);
  const details = deferred();
  await page.route(/\/api\/v1\/jobs\/job-failed-1(?:\?|$)/, async (route) => { await details.promise; await route.fallback(); });
  await page.goto('/jobs');
  await page.getByRole('button', { name: /Failed Smoke Job job-failed-1/ }).click();
  const status = page.locator('.jdm-loading');
  await expect(status).toHaveText('Loading job details...');
  await expect(status.locator('.loading-spinner')).toHaveCSS('height', '4px');
  await expect(status.locator('.loading-spinner')).toHaveText('');
  await capture(page, info, 'job-details-loading');
  details.resolve();
  await expect(status).toHaveCount(0);
});
