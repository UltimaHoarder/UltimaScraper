import type { ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { usePluginsPageController } from '../../src/features/plugins/hooks/usePluginsPageController';
import { createTestQueryClient } from './testUtils';

const mockListPlugins = vi.fn();
const mockGetPluginMetadata = vi.fn();
const mockPurgePluginData = vi.fn();
const mockGetPluginManifest = vi.fn();
const mockListPluginSecrets = vi.fn();

vi.mock('../../src/api/plugins', () => ({
  approvePluginCapabilities: vi.fn(),
  createPlugin: vi.fn(),
  disablePlugin: vi.fn(),
  enablePlugin: vi.fn(),
  getPluginManifest: (...args: unknown[]) => mockGetPluginManifest(...args),
  getPluginMetadata: (...args: unknown[]) => mockGetPluginMetadata(...args),
  listPluginSecrets: (...args: unknown[]) => mockListPluginSecrets(...args),
  listPlugins: (...args: unknown[]) => mockListPlugins(...args),
  purgePluginData: (...args: unknown[]) => mockPurgePluginData(...args),
  reloadPlugin: vi.fn(),
  setPluginSecret: vi.fn(),
  updatePluginManifest: vi.fn(),
}));

function createWrapper() {
  const queryClient = createTestQueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('usePluginsPageController', () => {
  it('opens setup for first-time Enable without enabling the plugin', async () => {
    mockListPlugins.mockResolvedValue([{ plugin_id: 'webshare-proxy', display_name: 'WebshareProxy', status: 'disabled', setup_required: true, setup_ready: false }]);
    const { result } = renderHook(() => usePluginsPageController(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.plugins).toHaveLength(1));
    act(() => result.current.handleEnable('webshare-proxy'));
    expect(result.current.setupTarget).toEqual({ pluginId: 'webshare-proxy', enable: true });
  });
  beforeEach(() => {
    vi.clearAllMocks();
    mockListPlugins.mockResolvedValue([]);
    mockListPluginSecrets.mockResolvedValue([]);
    mockGetPluginMetadata.mockResolvedValue({
      manifest_schema_version: 1,
      capabilities: ['auth.credentials.export', 'events.read'],
      event_families: ['job.lifecycle'],
    });
  });

  it('uses backend metadata and counts quarantined plugins', async () => {
    mockListPlugins.mockResolvedValue([
      {
        plugin_id: 'missing-plugin',
        display_name: 'Missing Plugin',
        plugin_version: 'unknown',
        status: 'missing',
        capabilities: [],
        loaded_at: '2026-08-23T00:00:00Z',
        enabled_at: null,
        disabled_at: null,
        last_error: 'Manifest missing',
        revision: 1,
      },
    ]);

    const { result } = renderHook(() => usePluginsPageController(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.plugins).toHaveLength(1));
    expect(result.current.capabilityOptions).toEqual([
      'auth.credentials.export',
      'events.read',
    ]);
    expect(result.current.eventFamilyOptions).toEqual(['job.lifecycle']);
    expect(result.current.statusCounts.missing).toBe(1);
    expect(result.current.isMetadataFallback).toBe(false);
  });

  it('requires exact UI confirmation before purging retained data', async () => {
    mockPurgePluginData.mockResolvedValue({
      plugin_id: 'disabled-plugin',
      status: 'purged',
      deleted_records: 4,
      deleted_by_store: {},
      manifest_retained: true,
    });
    vi.spyOn(window, 'prompt').mockReturnValue('PURGE disabled-plugin');

    const { result } = renderHook(() => usePluginsPageController(), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(mockGetPluginMetadata).toHaveBeenCalled());

    act(() => result.current.handlePurge('disabled-plugin'));

    await waitFor(() =>
      expect(mockPurgePluginData).toHaveBeenCalledWith(
        'disabled-plugin',
        'PURGE disabled-plugin',
      ),
    );
  });

  it('ignores a canceled manifest read that finishes after a newer selection', async () => {
    let finishOld!: (value: unknown) => void;
    mockGetPluginManifest.mockImplementation((id: string) => id === 'old'
      ? new Promise((resolve) => { finishOld = resolve; })
      : Promise.resolve({ plugin_id: id, manifest_yaml: 'plugin_id: current' }));
    const { result } = renderHook(() => usePluginsPageController(), { wrapper: createWrapper() });
    act(() => result.current.handleEdit('old'));
    await waitFor(() => expect(mockGetPluginManifest).toHaveBeenCalledWith('old'));
    act(() => result.current.cancelEdit());
    expect(result.current.isLoadingManifest).toBe(false);
    act(() => result.current.handleEdit('current'));
    await waitFor(() => expect(result.current.editingPluginId).toBe('current'));
    await act(async () => { finishOld({ plugin_id: 'old', manifest_yaml: 'stale YAML' }); });
    expect(result.current.editingPluginId).toBe('current');
    expect(result.current.editingManifestYaml).toBe('plugin_id: current');
  });
});
