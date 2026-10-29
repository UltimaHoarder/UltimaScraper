import { QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PluginRecord } from '../../src/api/types/plugins';
import { PluginSplitWorkspace } from '../../src/features/plugins/components/PluginSplitWorkspace';
import { usePluginsPageController } from '../../src/features/plugins/hooks/usePluginsPageController';
import { createTestQueryClient } from './testUtils';

const api = vi.hoisted(() => ({
  listPlugins: vi.fn(), getPluginMetadata: vi.fn(), getPluginManifest: vi.fn(), listPluginSecrets: vi.fn(),
  getPluginSettings: vi.fn(), setPluginConfiguration: vi.fn(), testPluginConnection: vi.fn(),
  updatePluginManifest: vi.fn(), enablePlugin: vi.fn(), disablePlugin: vi.fn(), approvePluginCapabilities: vi.fn(),
}));
vi.mock('../../src/api/plugins', async (original) => ({ ...await original<typeof import('../../src/api/plugins')>(), ...api }));

const alpha: PluginRecord = {
  plugin_id: 'alpha', display_name: 'Alpha', plugin_version: '1.0.0', status: 'enabled', capabilities: ['events.read'],
  loaded_at: '', enabled_at: null, disabled_at: null, last_error: null, revision: 1, has_settings: true,
};
const beta: PluginRecord = { ...alpha, plugin_id: 'beta', display_name: 'Beta', status: 'disabled', pending_capabilities: ['events.read'] };
function Harness() {
  const controller = usePluginsPageController();
  return <><PluginSplitWorkspace controller={controller} />{controller.setupTarget && <output>{JSON.stringify(controller.setupTarget)}</output>}</>;
}
function show(records = [alpha, beta]) {
  api.listPlugins.mockResolvedValue(records);
  const client = createTestQueryClient();
  client.setQueryData(['plugins'], records);
  const result = render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);
  return { ...result, client };
}
const tab = (name: string) => screen.getByRole('tab', { name });
const picker = (name: string) => within(screen.getByRole('complementary', { name: 'Plugin list' })).getByRole('button', { name: new RegExp(name) });

beforeEach(() => {
  vi.resetAllMocks();
  api.getPluginMetadata.mockResolvedValue({ manifest_schema_version: 2, capabilities: ['events.read'], event_families: [] });
  api.listPluginSecrets.mockResolvedValue([]);
  api.getPluginManifest.mockImplementation(async (id: string) => ({ plugin_id: id, manifest_yaml: `plugin_id: ${id}`, revision: 1, status: 'enabled' }));
  api.getPluginSettings.mockImplementation(async (id: string) => ({ schema: { type: 'object', properties: { url: { type: 'string', title: 'Service URL' } } }, values: { url: `https://${id}.example` }, connections: [] }));
  api.setPluginConfiguration.mockResolvedValue(alpha);
  api.updatePluginManifest.mockResolvedValue(beta);
  api.disablePlugin.mockResolvedValue(beta);
  api.enablePlugin.mockResolvedValue(beta);
  api.approvePluginCapabilities.mockResolvedValue(beta);
});
afterEach(cleanup);

describe('Plugin split workspace', () => {
  it('keeps selection through polling reorder and filtering, and falls back when removed', async () => {
    const { client } = show();
    await waitFor(() => expect(api.listPlugins).toHaveBeenCalled());
    act(() => client.setQueryData(['plugins'], [beta, { ...alpha, revision: 2 }]));
    await waitFor(() => expect(client.getQueryData(['plugins'])).toEqual([beta, { ...alpha, revision: 2 }]));
    expect(screen.getByRole('heading', { name: 'Alpha' })).toBeVisible();
    fireEvent.click(picker('Beta'));
    fireEvent.change(screen.getByRole('textbox', { name: 'Search plugins' }), { target: { value: 'alpha' } });
    expect(screen.getByRole('heading', { name: 'Beta' })).toBeVisible();
    expect(picker('Alpha')).toHaveAttribute('aria-pressed', 'false');
    fireEvent.change(screen.getByRole('textbox', { name: 'Search plugins' }), { target: { value: 'no-match' } });
    expect(screen.getByText('No plugins match.')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    act(() => client.setQueryData(['plugins'], [alpha]));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Alpha' })).toBeVisible());
    expect(picker('Alpha')).toHaveAttribute('aria-pressed', 'true');
  });

  it('loads settings on demand and keeps the draft across tabs and record refreshes', async () => {
    const { client } = show();
    expect(api.getPluginSettings).not.toHaveBeenCalled();
    fireEvent.click(tab('settings'));
    const field = await screen.findByLabelText('Service URL');
    await waitFor(() => expect(field).toHaveValue('https://alpha.example'));
    fireEvent.change(field, { target: { value: 'https://draft.example' } });
    fireEvent.click(tab('overview'));
    expect(field).not.toBeVisible();
    await waitFor(() => expect(api.listPlugins).toHaveBeenCalled());
    act(() => client.setQueryData(['plugins'], [{ ...alpha, revision: 2 }, beta]));
    fireEvent.click(tab('settings'));
    expect(field).toHaveValue('https://draft.example');
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(api.setPluginConfiguration).toHaveBeenCalledWith('alpha', { url: 'https://draft.example' }));
    fireEvent.click(picker('Beta'));
    fireEvent.click(tab('settings'));
    await waitFor(() => expect(screen.getByLabelText('Service URL')).toHaveValue('https://beta.example'));
  });

  it('supports keyboard tab navigation with one visible panel and moving focus', () => {
    show();
    fireEvent.keyDown(tab('overview'), { key: 'ArrowRight' });
    expect(tab('settings')).toHaveFocus();
    expect(tab('settings')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByRole('tabpanel')).toHaveLength(1);
    fireEvent.keyDown(tab('settings'), { key: 'End' });
    expect(tab('manifest')).toHaveFocus();
    fireEvent.keyDown(tab('manifest'), { key: 'Home' });
    expect(tab('overview')).toHaveFocus();
  });

  it('routes manifest saves and setup to the selected plugin and keeps Access read-only', async () => {
    show();
    fireEvent.click(picker('Beta'));
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    const field = await screen.findByRole('textbox', { name: 'Manifest YAML' });
    expect(field).toHaveValue('plugin_id: beta');
    fireEvent.change(field, { target: { value: 'plugin_id: beta\nplugin_version: 2.0.0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Manifest' }));
    await waitFor(() => expect(api.updatePluginManifest).toHaveBeenCalledWith('beta', { manifest_yaml: 'plugin_id: beta\nplugin_version: 2.0.0' }));
    fireEvent.click(tab('access'));
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Purge data' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Uninstall' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Enable' }));
    expect(screen.getByRole('status')).toHaveTextContent('"pluginId":"beta","enable":true');
    expect(api.enablePlugin).not.toHaveBeenCalled();
  });

  it('opens setup for an unconfigured selected plugin without enabling it', () => {
    show([alpha, { ...beta, setup_required: true, setup_ready: false }]);
    fireEvent.click(picker('Beta'));
    fireEvent.click(screen.getByRole('button', { name: 'Enable' }));
    expect(screen.getByRole('status')).toHaveTextContent('"pluginId":"beta","enable":true');
    expect(api.enablePlugin).not.toHaveBeenCalled();
  });
});
