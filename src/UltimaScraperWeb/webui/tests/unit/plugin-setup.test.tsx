import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PluginSetupModal } from '../../src/features/plugins/components/PluginSetupModal';
import type { PluginRecord } from '../../src/api/types/plugins';

const api = vi.hoisted(() => ({ getPluginSetup: vi.fn(), savePluginSetup: vi.fn(), approvePluginCapabilities: vi.fn() }));
vi.mock('../../src/api/plugins', () => api);
const plugin: PluginRecord = { plugin_id: 'webshare-proxy', display_name: 'WebshareProxy', plugin_version: '1.0.0', status: 'disabled', capabilities: ['http.request'], loaded_at: '', enabled_at: null, disabled_at: null, last_error: null, revision: 1, setup_required: true, setup_ready: false };
const setup = (configured = false) => ({ required: true, ready: configured, schema: { type: 'object', properties: { sync_interval_seconds: { type: 'integer', title: 'Sync interval (seconds)', minimum: 60, maximum: 604800, default: 3600 } }, required: ['sync_interval_seconds'] }, values: { sync_interval_seconds: 3600 }, credentials: [{ name: 'api-key', title: 'Webshare API key', description: 'Stored securely.', required: true, configured }] });
function show(options: { configured?: boolean; enable?: boolean; pending?: boolean } = {}) {
  api.getPluginSetup.mockResolvedValue(setup(options.configured));
  const onClose = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><PluginSetupModal plugin={{ ...plugin, pending_capabilities: options.pending ? ['http.request'] : [] }} enable={options.enable ?? true} onClose={onClose} /></QueryClientProvider>);
  return { ...view, onClose, client };
}
beforeEach(() => {
  vi.resetAllMocks();
  api.savePluginSetup.mockResolvedValue({ ...plugin, status: 'enabled', setup_ready: true });
  api.approvePluginCapabilities.mockResolvedValue(plugin);
});
afterEach(cleanup);

describe('Plugin setup', () => {
  it('collects credentials separately from settings and enables after validation', async () => {
    const { onClose, client } = show();
    const key = await screen.findByLabelText('Webshare API key');
    expect(key).toHaveAttribute('type', 'password');
    fireEvent.change(key, { target: { value: 'private-test-key' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: /Sync interval/ }), { target: { value: '900' } });
    fireEvent.click(screen.getByRole('button', { name: 'Validate and enable' }));
    await waitFor(() => expect(api.savePluginSetup).toHaveBeenCalledWith('webshare-proxy', { configuration: { sync_interval_seconds: 900 }, credentials: { 'api-key': 'private-test-key' }, enable: true }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(JSON.stringify(client.getQueryCache().getAll().map((query) => query.state.data))).not.toContain('private-test-key');
    expect(client.getMutationCache().getAll()).toHaveLength(0);
  });

  it('preserves configured keys when the replacement is empty', async () => {
    show({ configured: true, enable: false });
    const key = await screen.findByLabelText('Webshare API key');
    expect(key).not.toBeRequired();
    expect(screen.getByText(/Leave blank to keep/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Validate and save' }));
    await waitFor(() => expect(api.savePluginSetup).toHaveBeenCalledWith('webshare-proxy', { configuration: { sync_interval_seconds: 3600 }, credentials: {}, enable: false }));
  });

  it('requires explicit permission approval before validation', async () => {
    show({ pending: true });
    await screen.findByLabelText('Webshare API key');
    expect(screen.getByRole('button', { name: 'Validate and enable' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Approve permissions' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Validate and enable' })).toBeEnabled());
    expect(api.approvePluginCapabilities).toHaveBeenCalledWith('webshare-proxy');
    expect(api.savePluginSetup).not.toHaveBeenCalled();
  });

  it('clears the candidate key after validation fails and keeps the modal open', async () => {
    api.savePluginSetup.mockRejectedValue({ response: { data: { detail: 'Plugin service returned HTTP 401' } } });
    const { onClose } = show();
    const key = await screen.findByLabelText('Webshare API key');
    fireEvent.change(key, { target: { value: 'private-test-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Validate and enable' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 401');
    expect(key).toHaveValue('');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('cancels without saving and restores focus to the opener', async () => {
    const opener = document.createElement('button');
    document.body.append(opener); opener.focus();
    const { onClose, unmount } = show();
    await screen.findByLabelText('Webshare API key');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
    expect(api.savePluginSetup).not.toHaveBeenCalled();
    unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it('wraps keyboard focus within the modal', async () => {
    show();
    const key = await screen.findByLabelText('Webshare API key');
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    cancel.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(key).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(cancel).toHaveFocus();
  });
});
