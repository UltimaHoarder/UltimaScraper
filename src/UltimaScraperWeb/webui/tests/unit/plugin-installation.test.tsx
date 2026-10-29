import { QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PluginInstallModal } from '../../src/features/plugins/components/PluginInstallModal';
import { PluginUninstallModal } from '../../src/features/plugins/components/PluginUninstallModal';
import { PluginsPage } from '../../src/themes/ultima-atlas/views/plugins/PluginsPage';
import { createTestQueryClient } from './testUtils';
import { ThemeProvider } from '../../src/app/theme/ThemeProvider';
import type { PluginRecord } from '../../src/api/types/plugins';

const api = vi.hoisted(() => ({
  listPluginSources: vi.fn(), preparePluginInstall: vi.fn(), confirmPluginInstall: vi.fn(), cancelPluginInstall: vi.fn(), uninstallPlugin: vi.fn(),
  listPlugins: vi.fn(), getPluginMetadata: vi.fn(), getPluginSetup: vi.fn(), savePluginSetup: vi.fn(), approvePluginCapabilities: vi.fn(),
}));
const jobs = vi.hoisted(() => ({ getTaskTypes: vi.fn() }));
vi.mock('../../src/api/plugins', async (original) => ({ ...await original<typeof import('../../src/api/plugins')>(), ...api }));
vi.mock('../../src/api/jobs', () => jobs);
const plugin: PluginRecord = { plugin_id: 'sample-plugin', display_name: 'Sample Plugin', plugin_version: '1.0.0', status: 'disabled', capabilities: ['events.read'], requested_capabilities: ['events.read'], pending_capabilities: ['events.read'], enabled_at: null, disabled_at: null, loaded_at: '', revision: 1, last_error: null, setup_required: true, setup_ready: false };
const preview = { plugin_id: plugin.plugin_id, display_name: plugin.display_name, plugin_version: plugin.plugin_version, preview_token: 'a'.repeat(32), package_digest: 'b'.repeat(64), requested_capabilities: ['events.read'], requested_scopes: {}, source: { kind: 'local', source_id: 'SamplePlugin', revision: 'c'.repeat(40), dirty: false } };
const setup = { required: true, ready: true, schema: null, values: {}, credentials: [] };
function show(element: React.ReactElement) {
  const client = createTestQueryClient();
  return { ...render(<QueryClientProvider client={client}>{element}</QueryClientProvider>), client };
}
beforeEach(() => {
  vi.resetAllMocks();
  jobs.getTaskTypes.mockResolvedValue([]);
  api.listPluginSources.mockResolvedValue([{ source_id: 'SamplePlugin', plugin_id: plugin.plugin_id, display_name: plugin.display_name, plugin_version: '1.0.0', revision: 'c'.repeat(40), installed: false, data_retained: true }]);
  api.preparePluginInstall.mockResolvedValue(preview);
  api.confirmPluginInstall.mockResolvedValue(plugin);
  api.cancelPluginInstall.mockResolvedValue(undefined);
  api.uninstallPlugin.mockResolvedValue({ plugin_id: plugin.plugin_id, data_retained: true });
  api.listPlugins.mockResolvedValue([]);
  api.getPluginMetadata.mockResolvedValue({ manifest_schema_version: 2, capabilities: ['events.read'], event_families: [] });
  api.getPluginSetup.mockResolvedValue(setup);
  api.approvePluginCapabilities.mockResolvedValue({ ...plugin, pending_capabilities: [] });
  api.savePluginSetup.mockResolvedValue({ ...plugin, status: 'enabled' });
});
afterEach(cleanup);

describe('Plugin installation UI', () => {
  it('reviews a local package and confirms that exact receipt', async () => {
    const onInstalled = vi.fn();
    show(<PluginInstallModal onClose={vi.fn()} onInstalled={onInstalled} />);
    await screen.findByRole('option', { name: /Sample Plugin.*Data retained/ });
    fireEvent.change(screen.getByLabelText('Source folder'), { target: { value: 'SamplePlugin' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review package' }));
    await screen.findByText(preview.package_digest);
    expect(api.preparePluginInstall).toHaveBeenCalledWith({ kind: 'local', source_id: 'SamplePlugin' });
    fireEvent.click(screen.getByRole('button', { name: 'Install and set up' }));
    await waitFor(() => expect(api.confirmPluginInstall).toHaveBeenCalledWith(preview));
    expect(onInstalled).toHaveBeenCalledWith(plugin);
  });

  it('submits a Git URL and revision and keeps errors reviewable', async () => {
    api.preparePluginInstall.mockRejectedValue({ response: { data: { detail: 'Git operation failed' } } });
    show(<PluginInstallModal onClose={vi.fn()} onInstalled={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Git repository' }));
    fireEvent.change(screen.getByLabelText('Git URL'), { target: { value: 'https://plugins.example/sample.git' } });
    fireEvent.change(screen.getByLabelText('Revision'), { target: { value: 'v1.0.0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review package' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Git operation failed');
    expect(api.preparePluginInstall).toHaveBeenCalledWith({ kind: 'git', url: 'https://plugins.example/sample.git', revision: 'v1.0.0' });
    expect(screen.getByLabelText('Revision')).toHaveValue('v1.0.0');
  });

  it('cancels a prepared package and restores keyboard focus', async () => {
    const opener = document.createElement('button'); document.body.append(opener); opener.focus();
    const onClose = vi.fn();
    const { unmount } = show(<PluginInstallModal onClose={onClose} onInstalled={vi.fn()} />);
    await screen.findByRole('option', { name: /Sample Plugin/ });
    fireEvent.change(screen.getByLabelText('Source folder'), { target: { value: 'SamplePlugin' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review package' }));
    await screen.findByText(preview.package_digest);
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(api.cancelPluginInstall).toHaveBeenCalledWith(preview));
    expect(onClose).toHaveBeenCalled();
    unmount(); expect(opener).toHaveFocus(); opener.remove();
  });

  it('uninstalls while keeping data by default', async () => {
    const onUninstalled = vi.fn();
    show(<PluginUninstallModal plugin={plugin} onClose={vi.fn()} onUninstalled={onUninstalled} />);
    expect(screen.getByRole('checkbox', { name: 'Delete retained data' })).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Uninstall' }));
    await waitFor(() => expect(api.uninstallPlugin).toHaveBeenCalledWith(plugin.plugin_id, false, ''));
    expect(onUninstalled).toHaveBeenCalledWith(plugin.plugin_id);
  });

  it('requires the exact ID for deletion and keeps the dialog open on failure', async () => {
    api.uninstallPlugin.mockRejectedValue(new Error('Uninstall unavailable'));
    const onUninstalled = vi.fn();
    show(<PluginUninstallModal plugin={plugin} onClose={vi.fn()} onUninstalled={onUninstalled} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Delete retained data' }));
    const remove = screen.getByRole('button', { name: 'Uninstall and delete data' });
    expect(remove).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Type sample-plugin/), { target: { value: plugin.plugin_id } });
    fireEvent.click(remove);
    expect(await screen.findByRole('alert')).toHaveTextContent('Uninstall unavailable');
    expect(api.uninstallPlugin).toHaveBeenCalledWith(plugin.plugin_id, true, plugin.plugin_id);
    expect(onUninstalled).not.toHaveBeenCalled();
  });

  it('selects the installed plugin, opens Setup, and approves before enabling', async () => {
    show(<ThemeProvider><PluginsPage /></ThemeProvider>);
    fireEvent.click(screen.getByRole('button', { name: '+ Install plugin' }));
    await screen.findByRole('option', { name: /Sample Plugin/ });
    fireEvent.change(screen.getByLabelText('Source folder'), { target: { value: 'SamplePlugin' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review package' }));
    await screen.findByText(preview.package_digest);
    api.listPlugins.mockResolvedValue([plugin]);
    fireEvent.click(screen.getByRole('button', { name: 'Install and set up' }));
    await screen.findByRole('dialog', { name: 'Sample Plugin setup' });
    expect(screen.getByRole('heading', { name: 'Sample Plugin' })).toBeVisible();
    expect(await screen.findByRole('button', { name: 'Validate and enable' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Approve permissions' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Validate and enable' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Validate and enable' }));
    await waitFor(() => expect(api.savePluginSetup).toHaveBeenCalledWith(plugin.plugin_id, { configuration: {}, credentials: {}, enable: true }));
    expect(api.approvePluginCapabilities).toHaveBeenCalledWith(plugin.plugin_id);
  });
});
