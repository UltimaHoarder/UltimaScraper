import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PluginSettingsPanel } from '../../src/features/plugins/components/PluginSettingsPanel';
import type { PluginRecord } from '../../src/api/types/plugins';

const api = vi.hoisted(() => ({ getPluginSettings: vi.fn(), setPluginConfiguration: vi.fn(), testPluginConnection: vi.fn() }));
vi.mock('../../src/api/plugins', () => api);
const plugin: PluginRecord = { plugin_id: 'ultima-ai', display_name: 'UltimaAI', plugin_version: '1.0.0', status: 'enabled', capabilities: [], loaded_at: '', enabled_at: null, disabled_at: null, last_error: null, revision: 1, has_settings: true };
const settings = () => ({ schema: { type: 'object', properties: { service_url: { type: 'string', title: 'Service URL', description: 'Classification server address.', format: 'uri', default: 'http://localhost:8029' } }, required: ['service_url'] }, values: { service_url: 'http://localhost:8029' }, connections: [{ name: 'classification', label: 'Classification' }] });
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><PluginSettingsPanel plugin={plugin} onClose={vi.fn()} onManageCredentials={vi.fn()} /></QueryClientProvider>);
}
beforeEach(() => {
  vi.resetAllMocks();
  api.getPluginSettings.mockResolvedValue(settings());
  api.setPluginConfiguration.mockResolvedValue(plugin);
  api.testPluginConnection.mockResolvedValue({ reachable: true, status_code: 200, message: 'Reached service (HTTP 200).' });
});
afterEach(cleanup);

describe('Plugin settings', () => {
  it('renders declared labels and defaults and saves the edited values', async () => {
    show();
    const field = await screen.findByLabelText(/Service URL/);
    await waitFor(() => expect(field).toHaveValue('http://localhost:8029'));
    expect(screen.getByText('Classification server address.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled();
    fireEvent.change(field, { target: { value: 'http://localhost:8030' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(api.setPluginConfiguration).toHaveBeenCalledWith('ultima-ai', { service_url: 'http://localhost:8030' }));
    expect(await screen.findByText('Settings saved.')).toBeVisible();
  });

  it('tests unsaved settings without saving and reports the result', async () => {
    show();
    const field = await screen.findByLabelText(/Service URL/);
    fireEvent.change(field, { target: { value: 'http://localhost:8030' } });
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }));
    await waitFor(() => expect(api.testPluginConnection).toHaveBeenCalledWith('ultima-ai', 'classification', { service_url: 'http://localhost:8030' }));
    expect(api.setPluginConfiguration).not.toHaveBeenCalled();
    expect(await screen.findByText('Reached service (HTTP 200).')).toBeVisible();
  });

  it('uses typed controls for booleans, numbers, enums and nested fields', async () => {
    api.getPluginSettings.mockResolvedValue({ schema: { type: 'object', properties: {
      enabled: { type: 'boolean', title: 'Enabled' }, retries: { type: 'integer', title: 'Retries', minimum: 0, maximum: 5 },
      mode: { type: 'string', enum: ['fast', 'accurate'], title: 'Mode' },
      nested: { type: 'object', title: 'Advanced', properties: { name: { type: 'string', title: 'Worker name' } } },
    } }, values: { enabled: true, retries: 3, mode: 'fast', nested: { name: 'original' } }, connections: [] });
    show();
    const enabled = await screen.findByRole('checkbox', { name: 'Enabled' });
    await waitFor(() => expect(enabled).toBeChecked());
    fireEvent.click(enabled);
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Retries' }), { target: { value: '4' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Mode' }), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('Worker name'), { target: { value: 'changed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(api.setPluginConfiguration).toHaveBeenCalledWith('ultima-ai', { enabled: false, retries: 4, mode: 'accurate', nested: { name: 'changed' } }));
  });

  it('restores defaults as an unsaved draft', async () => {
    api.getPluginSettings.mockResolvedValue({ ...settings(), values: { service_url: 'http://localhost:8030' } });
    show();
    const field = await screen.findByLabelText(/Service URL/);
    await waitFor(() => expect(field).toHaveValue('http://localhost:8030'));
    fireEvent.click(screen.getByRole('button', { name: 'Use defaults' }));
    expect(screen.getByLabelText(/Service URL/)).toHaveValue('http://localhost:8029');
    expect(api.setPluginConfiguration).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Save settings' })).toBeEnabled();
  });

  it('keeps the draft when the server rejects a setting', async () => {
    api.setPluginConfiguration.mockRejectedValue({ response: { data: { detail: 'Invalid configuration.service_url: disallowed value' } } });
    show();
    const field = await screen.findByLabelText(/Service URL/);
    fireEvent.change(field, { target: { value: 'http://localhost:8030' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid configuration.service_url: disallowed value');
    expect(field).toHaveValue('http://localhost:8030');
  });

  it('does not offer an empty save when loading fails', async () => {
    api.getPluginSettings.mockRejectedValue(new Error('Settings unavailable'));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('Settings unavailable');
    expect(screen.queryByRole('button', { name: 'Save settings' })).not.toBeInTheDocument();
  });
});
