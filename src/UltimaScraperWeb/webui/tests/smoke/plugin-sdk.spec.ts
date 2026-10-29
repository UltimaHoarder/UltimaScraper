import { expect, test } from '@playwright/test';
import { installApiMocks, seedConfiguredApp, backendPath } from './helpers';

test('plugin settings validate fields, test drafts and persist saved values', async ({ page }) => {
  await seedConfiguredApp(page, { devMode: true });
  await installApiMocks(page);
  let values = { service_url: 'http://localhost:8086' };
  let saves = 0;
  const probes: unknown[] = [];
  const record = { plugin_id: 'usweb-remote', display_name: 'USWeb', plugin_version: '1.0.0', status: 'disabled', capabilities: [], loaded_at: '', enabled_at: null, disabled_at: null, last_error: null, revision: 1, manifest_schema_version: 1, has_settings: true };
  await page.route('**/api/v1/plugins**', async (route) => {
    const path = backendPath(route.request().url());
    const headers = { 'content-type': 'application/json', 'access-control-allow-origin': 'http://127.0.0.1:4173', 'access-control-allow-headers': '*' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (path.endsWith('/active-webui')) return route.fulfill({ headers, json: [] });
    if (path.endsWith('/metadata')) return route.fulfill({ headers, json: { manifest_schema_version: 2, capabilities: [], event_families: [] } });
    if (path.endsWith('/settings/test')) {
      probes.push(route.request().postDataJSON());
      return route.fulfill({ headers, json: { reachable: true, status_code: 401, message: 'Reached service (HTTP 401); authentication and task execution were not tested.' } });
    }
    if (path.endsWith('/settings')) return route.fulfill({ headers, json: { schema: { type: 'object', properties: { service_url: { type: 'string', title: 'USWeb service URL', description: 'Remote job service address.', format: 'uri', pattern: '^https?://', default: 'http://localhost:8086' } }, required: ['service_url'] }, values, connections: [{ name: 'remote-service', label: 'Remote service' }] } });
    if (path.endsWith('/configuration')) {
      values = route.request().postDataJSON(); saves++;
      // The WebUI server adds the backend's token; the page sends none.
      expect(route.request().headers()['x-usr-admin-token']).toBeUndefined();
      return route.fulfill({ headers, json: record });
    }
    return route.fulfill({ headers, json: [record] });
  });
  await page.goto('/plugins');
  const settingsTab = page.getByRole('tab', { name: 'settings', exact: true });
  await settingsTab.click();
  const field = page.getByLabel('USWeb service URL');
  await expect(field).toHaveValue('http://localhost:8086');
  await field.fill('invalid-url');
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  expect(saves).toBe(0);
  await field.fill('http://localhost:9090');
  await page.getByRole('button', { name: 'Test connection', exact: true }).click();
  await expect(page.getByText(/Reached service \(HTTP 401\)/)).toBeVisible();
  expect(probes).toEqual([{ target: 'remote-service', configuration: { service_url: 'http://localhost:9090' } }]);
  expect(saves).toBe(0);
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await expect(page.getByText('Settings saved.', { exact: true })).toBeVisible();
  expect(saves).toBe(1);
  await page.getByRole('tab', { name: 'overview', exact: true }).click();
  await settingsTab.click();
  await expect(field).toHaveValue('http://localhost:9090');
});

test('declarative plugin pages invoke through a scoped token', async ({ page }) => {
  await seedConfiguredApp(page, { devMode: true });
  await installApiMocks(page);
  const requests: string[] = [];
  await page.route('**/api/v1/plugins**', async (route) => {
    const path = backendPath(route.request().url());
    const headers = { 'content-type': 'application/json', 'access-control-allow-origin': 'http://127.0.0.1:4173', 'access-control-allow-headers': '*' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (path.endsWith('/active-webui')) return route.fulfill({ headers, json: [{
      plugin_id: 'sdk-smoke', display_name: 'SDK Smoke', plugin_version: '1', package_digest: 'v1',
      entry: '', styles: [], mode: 'declarative',
      access: { profile_fields: [], task_types: ['sdk-smoke.preview'], outbound_domains: [], propose_profile_changes: false },
      contributions: [{ contribution_id: 'tools', slot: 'navigation.pages', kind: 'page', title: 'SDK preview', text: 'Plugin page', order: 0, task_type: 'sdk-smoke.preview' }],
    }] });
    if (path.endsWith('/token')) return route.fulfill({ headers, json: { token: 'scoped-test-token', expires_in: 300 } });
    if (path.endsWith('/runtime/invoke')) {
      requests.push(route.request().headers().authorization);
      return route.fulfill({ headers, json: { value: 'Scoped result' } });
    }
    return route.fulfill({ headers, json: [] });
  });
  await page.goto('/plugins/sdk-smoke/tools');
  await expect(page.getByText('Plugin page', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'SDK preview', exact: true }).click();
  await expect(page.getByText(/Scoped result/)).toBeVisible();
  expect(requests).toEqual(['Bearer scoped-test-token']);
});

test('authenticated native assets are removed when disabled', async ({ page }) => {
  await seedConfiguredApp(page, { devMode: true });
  await installApiMocks(page);
  let enabled = true;
  let assetAuthorization = '';
  const record = () => ({ plugin_id: 'sdk-smoke', display_name: 'SDK Smoke', plugin_version: '1.0.0', status: enabled ? 'enabled' : 'disabled', capabilities: ['webui.extend', 'webui.native'], loaded_at: '', enabled_at: null, disabled_at: null, last_error: null, revision: 1 });
  await page.route('**/api/v1/plugins**', async (route) => {
    const path = backendPath(route.request().url());
    const headers = { 'content-type': 'application/json', 'access-control-allow-origin': 'http://127.0.0.1:4173', 'access-control-allow-headers': '*' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (path.endsWith('/active-webui')) return route.fulfill({ headers, json: enabled ? [{ plugin_id: 'sdk-smoke', display_name: 'SDK Smoke', plugin_version: '1.0.0', package_digest: 'v1', entry: '/api/v1/plugins/sdk-smoke/assets/webui.js?package=v1', styles: [], mode: 'native', contributions: [] }] : [] });
    if (path.endsWith('/webui.js')) {
      assetAuthorization = route.request().headers()['x-usr-admin-token'] ?? '';
      return route.fulfill({ headers: { ...headers, 'content-type': 'text/javascript' }, body: `(function() { const api = window.USR.forPlugin('sdk-smoke'); api.registerSlot('navigation.pages', function() { return api.React.createElement('p', null, 'Native SDK page'); }, { id: 'tools' }); })();` });
    }
    if (path.endsWith('/disable')) { enabled = false; return route.fulfill({ headers, json: record() }); }
    if (path.endsWith('/metadata')) return route.fulfill({ headers, json: { manifest_schema_version: 2, capabilities: [], event_families: [] } });
    return route.fulfill({ headers, json: [record()] });
  });
  await page.goto('/plugins/sdk-smoke/tools');
  await expect(page.getByText('Native SDK page')).toBeVisible();
  // Native assets load through the WebUI server, which adds the token itself.
  expect(assetAuthorization).toBe('');
  await page.goto('/plugins');
  await page.getByRole('button', { name: 'Disable', exact: true }).click();
  await expect(page.locator('script[data-usr-plugin="sdk-smoke"]')).toHaveCount(0);
});

test('sandbox UI receives a private channel and cannot read application storage', async ({ page }) => {
  await seedConfiguredApp(page, { devMode: true });
  await installApiMocks(page);
  await page.route('**/api/v1/plugins**', async (route) => {
    const path = backendPath(route.request().url());
    const headers = { 'content-type': 'application/json', 'access-control-allow-origin': 'http://127.0.0.1:4173', 'access-control-allow-headers': '*' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (path.endsWith('/active-webui')) return route.fulfill({ headers, json: [{ plugin_id: 'sdk-smoke', display_name: 'SDK Sandbox', plugin_version: '1', package_digest: 'v1', entry: '/api/v1/plugins/sdk-smoke/assets/page.html', styles: [], mode: 'sandbox', access: { profile_fields: [], task_types: [], outbound_domains: [], propose_profile_changes: false }, contributions: [{ contribution_id: 'tools', slot: 'navigation.pages', kind: 'page', title: 'Sandbox page', text: '', order: 0, task_type: null }] }] });
    if (path.endsWith('/page.html')) return route.fulfill({ headers: { ...headers, 'content-type': 'text/html' }, body: `<p id="status">Connecting</p><script>window.addEventListener('message', function(event) { if (event.data.type !== 'usr.plugin.connect') return; let isolated = false; try { localStorage.getItem('usr_admin_token'); } catch { isolated = true; } document.getElementById('status').textContent = isolated && event.ports.length === 1 ? 'Isolated channel connected' : 'Isolation failed'; });</script>` });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto('/plugins/sdk-smoke/tools');
  await expect(page.frameLocator('iframe[title="SDK Sandbox"]').getByText('Isolated channel connected')).toBeVisible();
  await expect(page.locator('iframe')).toHaveAttribute('sandbox', 'allow-scripts');
});
