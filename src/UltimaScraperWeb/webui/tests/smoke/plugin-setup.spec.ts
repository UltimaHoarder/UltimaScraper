import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp, backendPath } from './helpers';

test('Webshare setup approves access, enables sync and preserves saved keys', async ({ page }, testInfo) => {
  await seedConfiguredApp(page, { devMode: true });
  await installApiMocks(page);
  let enabled = false;
  let configured = false;
  let approved = false;
  let interval = 3600;
  let runs = 0;
  const submissions: { configuration: { sync_interval_seconds: number }; credentials: Record<string, string>; enable: boolean }[] = [];
  const record = () => ({ plugin_id: 'webshare-proxy', display_name: 'WebshareProxy', plugin_version: '1.0.0', status: enabled ? 'enabled' : 'disabled', capabilities: ['http.request', 'proxies.sync', 'jobs.schedule'], pending_capabilities: approved ? [] : ['http.request', 'proxies.sync', 'jobs.schedule'], pending_scopes: approved ? [] : ['http_services:proxy-list'], loaded_at: '', enabled_at: null, disabled_at: null, last_error: null, revision: 1, manifest_schema_version: 2, setup_required: true, setup_ready: configured, has_settings: true, schedules: [{ schedule_id: 'sync', task_type: 'webshare-proxy.sync', next_at: '2026-10-12T23:00:00Z', last_result: { status: 'completed', added: 10, adopted: 5, deleted: 1, retained_assigned: 2 } }] });
  await page.route('**/api/v1/plugins**', async (route) => {
    const path = backendPath(route.request().url());
    const headers = { 'content-type': 'application/json', 'access-control-allow-origin': 'http://127.0.0.1:4173', 'access-control-allow-headers': '*' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (path.endsWith('/active-webui')) return route.fulfill({ headers, json: [] });
    if (path.endsWith('/metadata')) return route.fulfill({ headers, json: { manifest_schema_version: 2, capabilities: [], event_families: [] } });
    if (path.endsWith('/capabilities/approve')) { approved = true; return route.fulfill({ headers, json: record() }); }
    if (path.endsWith('/setup')) {
      if (route.request().method() === 'POST') {
        const payload = route.request().postDataJSON();
        submissions.push(payload);
        interval = payload.configuration.sync_interval_seconds;
        configured = true;
        if (payload.enable) enabled = true;
        return route.fulfill({ headers, json: record() });
      }
      return route.fulfill({ headers, json: { required: true, ready: configured, schema: { type: 'object', properties: { sync_interval_seconds: { type: 'integer', title: 'Sync interval (seconds)', description: 'Automatically sync while the plugin supervisor is running.', minimum: 60, maximum: 604800, default: 3600 } }, required: ['sync_interval_seconds'] }, values: { sync_interval_seconds: interval }, credentials: [{ name: 'api-key', title: 'Webshare API key', description: 'Stored as a managed credential.', required: true, configured }] } });
    }
    if (path.endsWith('/schedules/sync/run')) { runs++; return route.fulfill({ headers, json: { job_id: 'plugin-smoke-sync' } }); }
    return route.fulfill({ headers, json: [record()] });
  });
  await page.goto('/plugins');
  await page.getByRole('button', { name: 'Enable', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'WebshareProxy setup' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Validate and enable' })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Approve permissions' }).click();
  await expect(dialog.getByRole('button', { name: 'Validate and enable' })).toBeEnabled();
  const key = dialog.getByLabel('Webshare API key');
  await key.fill('smoke-only-webshare-key');
  await dialog.getByLabel('Sync interval (seconds)').fill('900');
  await dialog.getByRole('button', { name: 'Cancel' }).focus();
  await page.keyboard.press('Tab');
  await expect(key).toBeFocused();
  await page.screenshot({ path: testInfo.outputPath('webshare-setup.png') });
  await dialog.getByRole('button', { name: 'Validate and enable' }).click();
  await expect(dialog).not.toBeVisible();
  expect(submissions).toEqual([{ configuration: { sync_interval_seconds: 900 }, credentials: { 'api-key': 'smoke-only-webshare-key' }, enable: true }]);
  await page.getByRole('button', { name: 'Setup', exact: true }).click();
  await expect(dialog.getByLabel('Webshare API key')).toHaveValue('');
  await expect(dialog.getByText(/Leave blank to keep/)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Setup', exact: true })).toBeFocused();
  await page.getByText('Runtime details', { exact: true }).click();
  await expect(page.getByText(/Last sync: completed/)).toContainText('2 retained assigned');
  await page.getByRole('button', { name: 'Sync now', exact: true }).click();
  await expect.poll(() => runs).toBe(1);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain('smoke-only-webshare-key');
});
