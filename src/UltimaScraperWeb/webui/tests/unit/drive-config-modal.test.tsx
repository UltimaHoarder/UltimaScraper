import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { getDirectoryConfig } from '../../src/api/system';
import type { SettingsResponse } from '../../src/api/types/settings';
import type {
  DirectoryConfigInfo,
  DriveInfo,
  StorageConfigPropagation,
} from '../../src/api/types/system';
import { DriveConfigModal } from '../../src/features/system/components/DriveConfigModal';
import { renderWithProviders } from './testUtils';

vi.mock('../../src/api/system', () => ({
  getDirectoryConfig: vi.fn(),
}));

const driveFixture: DriveInfo = {
  path: '/mnt/storage-pool',
  device: '/dev/sdz1',
  total_bytes: 1024,
  used_bytes: 256,
  free_bytes: 768,
  percent_used: 25,
  is_configured: true,
  directory_count: 1,
  configured_directories: ['/mnt/storage-pool/downloads'],
};

const settingsFixture: SettingsResponse = {
  hostname: 'cluster-node',
  job_execution: {
    window_max_tasks: null,
    refill_ready_threshold: null,
    event_retention_hours: 168,
    task_history_retention_days: 3,
    receipt_retention_minutes: 60,
    terminal_reconcile_interval_seconds: 60,
    terminal_reconcile_min_age_seconds: 300,
    terminal_reconcile_batch_size: 100,
    completed_job_retention_seconds: 86400,
    completed_job_retention_batch_size: 100,
  },
  worker_pool: {
    enabled: true,
    size: 10,
    sites: ['onlyfans'],
    max_claimed_jobs: 4,
  },
  backend: {
    backend_id: 'backend-1',
    execution_mode: 'distributed',
  },
  redis: {
    host: 'localhost',
    port: 6379,
    db: 0,
    password: null,
    enabled: true,
  },
  network: {
    guest_route_rate_limit: 0,
    guest_session_pool: false,
    max_connections: 32,
    proxies: [],
    proxy_fallback: false,
    downloads: {
      max_concurrency: 8,
      per_domain_concurrency: 4,
      head_concurrency: 2,
      buffer_size_bytes: 1024,
    },
  },
  download_setup: {
    drives: [
      {
        minimum_space: 0,
        store: true,
        scan_existing: true,
        overflow: true,
        directories: ['/mnt/storage-pool/downloads'],
      },
    ],
    alt_directory_formats: [],
    staging_directories: [],
    directory_format: '{site_name}/{user_username}',
    filename_format: '{filename}',
    text_length: 255,
    date_format: '%Y-%m-%d',
    overwrite_files: true,
  },
  metadata_setup: {
    drives: [],
    directory_format: '{site_name}/{user_username}',
  },
  previews_directory: null,
  subtitles_directory: null,
  drm: {
    device_client_blob_filepath: null,
    device_private_key_filepath: null,
  },
  sites: {
    onlyfans: { blacklists: [] },
    fansly: { blacklists: [] },
  },
  config_path: '/tmp/config.json',
  config_version: 7,
  is_configured: true,
};

const acknowledgedPropagation: StorageConfigPropagation = {
  status: 'acknowledged',
  target_backend_id: 'backend-1',
  settings_scope: 'backend-1',
  config_version: 8,
  revision: 'revision-1',
  request_id: 'request-1',
  expected_workers: ['worker-1'],
  acknowledged_workers: ['worker-1'],
  failed_workers: [],
  message: 'Applied by all 1 registered worker(s).',
};

function savedSettingsResponse(
  propagation: StorageConfigPropagation | null,
): SettingsResponse {
  return {
    ...settingsFixture,
    config_version: 8,
    storage_propagation: propagation,
  };
}

describe('DriveConfigModal', () => {
  it('saves the scan_existing flag for download directories', async () => {
    const configFixture: DirectoryConfigInfo = {
      path: '/mnt/storage-pool/downloads',
      setup_type: 'download',
      minimum_space: 0,
      store: true,
      scan_existing: true,
      overflow: true,
    };
    vi.mocked(getDirectoryConfig).mockResolvedValue({
      success: true,
      message: 'ok',
      config: configFixture,
    });

    const onUpdateDirectoryConfig = vi.fn().mockResolvedValue({
      success: true,
      message: 'updated',
      config: { ...configFixture, scan_existing: false },
      propagation: acknowledgedPropagation,
    });

    renderWithProviders(
      <DriveConfigModal
        drive={driveFixture}
        backendId="backend-1"
        settings={settingsFixture}
        onClose={() => {}}
        onAddDirectory={vi.fn().mockResolvedValue(null)}
        onRemoveDirectory={vi.fn().mockResolvedValue(null)}
        onUpdateDirectoryConfig={onUpdateDirectoryConfig}
        onSaveSettings={vi.fn().mockResolvedValue(savedSettingsResponse(null))}
        onRefreshDrive={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit/i }));

    await waitFor(() => {
      expect(getDirectoryConfig).toHaveBeenCalledWith(
        '/mnt/storage-pool/downloads',
        'download',
        'backend-1',
      );
    });

    const scanExistingCheckbox = await screen.findByLabelText(
      /reuse performer folders already on this drive/i,
    );

    fireEvent.click(scanExistingCheckbox);
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }));

    await waitFor(() => {
      expect(onUpdateDirectoryConfig).toHaveBeenCalledWith({
        directory_path: '/mnt/storage-pool/downloads',
        setup_type: 'download',
        minimum_space: 0,
        store: true,
        scan_existing: false,
        overflow: true,
      });
    });
    expect(
      await screen.findByText(
        /directory settings saved on backend-1; applied by all 1 registered worker/i,
      ),
    ).toHaveClass('success');
  });

  it('shows the backend conflict detail for a directory settings save', async () => {
    vi.mocked(getDirectoryConfig).mockResolvedValue({
      success: true,
      message: 'ok',
      config: {
        path: '/mnt/storage-pool/downloads',
        setup_type: 'download',
        minimum_space: 0,
        store: true,
        scan_existing: true,
        overflow: true,
      },
    });
    const onUpdateDirectoryConfig = vi.fn().mockRejectedValue({
      response: {
        data: {
          detail: {
            message: 'Configuration version conflict.',
            current_version: 9,
          },
        },
      },
    });

    renderWithProviders(
      <DriveConfigModal
        drive={driveFixture}
        backendId="backend-1"
        settings={settingsFixture}
        onClose={() => {}}
        onAddDirectory={vi.fn()}
        onRemoveDirectory={vi.fn()}
        onUpdateDirectoryConfig={onUpdateDirectoryConfig}
        onSaveSettings={vi.fn().mockResolvedValue(savedSettingsResponse(null))}
        onRefreshDrive={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit/i }));
    await screen.findByRole('button', { name: /save changes/i });
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }));

    expect(
      await screen.findByText(/configuration version conflict\. current version: 9\./i),
    ).toHaveClass('error');
  });

  it('keeps an unavailable mount editable while blocking directory creation', async () => {
    renderWithProviders(
      <DriveConfigModal
        backendId="backend-1"
        drive={{
          ...driveFixture,
          path: '/mnt/offline',
          configured_directories: ['/mnt/offline/downloads'],
          is_available: false,
        }}
        settings={{
          ...settingsFixture,
          download_setup: {
            ...settingsFixture.download_setup,
            drives: [
              {
                ...settingsFixture.download_setup.drives[0],
                directories: ['/mnt/offline/downloads'],
              },
            ],
          },
        }}
        onClose={() => {}}
        onAddDirectory={vi.fn().mockResolvedValue(null)}
        onRemoveDirectory={vi.fn().mockResolvedValue(null)}
        onUpdateDirectoryConfig={vi.fn().mockResolvedValue(null)}
        onSaveSettings={vi.fn().mockResolvedValue(savedSettingsResponse(null))}
        onRefreshDrive={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/existing directory assignments and download or metadata settings can still be edited here/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add directory/i })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /download settings/i }));
    expect(screen.getByRole('button', { name: /save download settings/i })).toBeEnabled();
  });

  it('reports an acknowledged global download settings save as applied', async () => {
    const onSaveSettings = vi
      .fn()
      .mockResolvedValue(savedSettingsResponse(acknowledgedPropagation));

    renderWithProviders(
      <DriveConfigModal
        drive={driveFixture}
        backendId="backend-1"
        settings={settingsFixture}
        onClose={() => {}}
        onAddDirectory={vi.fn()}
        onRemoveDirectory={vi.fn()}
        onUpdateDirectoryConfig={vi.fn()}
        onSaveSettings={onSaveSettings}
        onRefreshDrive={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /download settings/i }));
    fireEvent.click(screen.getByRole('button', { name: /save download settings/i }));

    const message = await screen.findByText(
      /download settings saved on backend-1; applied by all 1 registered worker/i,
    );
    expect(message).toHaveClass('success');
    expect(onSaveSettings).toHaveBeenCalledWith(
      expect.objectContaining({ download_setup: expect.any(Object) }),
    );
  });

  it('leaves staging directories to the global section', async () => {
    const stagingDirectories = [
      { path: '/dev/shm/staging', usage: ['drm'], policy: ['prefer'], min_free_bytes: 1024 },
    ] as SettingsResponse['download_setup']['staging_directories'];
    const onSaveSettings = vi
      .fn()
      .mockResolvedValue(savedSettingsResponse(acknowledgedPropagation));

    renderWithProviders(
      <DriveConfigModal
        drive={driveFixture}
        backendId="backend-1"
        settings={{
          ...settingsFixture,
          download_setup: { ...settingsFixture.download_setup, staging_directories: stagingDirectories },
        }}
        onClose={() => {}}
        onAddDirectory={vi.fn()}
        onRemoveDirectory={vi.fn()}
        onUpdateDirectoryConfig={vi.fn()}
        onSaveSettings={onSaveSettings}
        onRefreshDrive={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /download settings/i }));

    expect(screen.queryByText(/staging director/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /save download settings/i }));

    await waitFor(() => expect(onSaveSettings).toHaveBeenCalledTimes(1));
    expect(onSaveSettings.mock.calls[0][0].download_setup.staging_directories).toEqual(stagingDirectories);
  });

  it('reports a pending global metadata settings save as saved but not applied', async () => {
    const onSaveSettings = vi.fn().mockResolvedValue(
      savedSettingsResponse({
        ...acknowledgedPropagation,
        status: 'pending',
        acknowledged_workers: [],
        message: 'Saved, but no worker acknowledged this revision before the timeout.',
      }),
    );

    renderWithProviders(
      <DriveConfigModal
        drive={driveFixture}
        backendId="backend-1"
        settings={settingsFixture}
        onClose={() => {}}
        onAddDirectory={vi.fn()}
        onRemoveDirectory={vi.fn()}
        onUpdateDirectoryConfig={vi.fn()}
        onSaveSettings={onSaveSettings}
        onRefreshDrive={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /metadata settings/i }));
    fireEvent.click(screen.getByRole('button', { name: /save metadata settings/i }));

    const message = await screen.findByText(
      /metadata settings saved on backend-1; saved, but no worker acknowledged/i,
    );
    expect(message).toHaveClass('warning');
    expect(message).not.toHaveClass('success');
  });

  it('shows the backend conflict detail for a failed global storage save', async () => {
    const onSaveSettings = vi.fn().mockRejectedValue({
      response: {
        data: {
          detail: {
            message: 'Settings have changed since you loaded them.',
            current_version: 9,
          },
        },
      },
    });

    renderWithProviders(
      <DriveConfigModal
        drive={driveFixture}
        backendId="backend-1"
        settings={settingsFixture}
        onClose={() => {}}
        onAddDirectory={vi.fn()}
        onRemoveDirectory={vi.fn()}
        onUpdateDirectoryConfig={vi.fn()}
        onSaveSettings={onSaveSettings}
        onRefreshDrive={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /download settings/i }));
    fireEvent.click(screen.getByRole('button', { name: /save download settings/i }));

    expect(
      await screen.findByText(
        /settings have changed since you loaded them\. current version: 9\./i,
      ),
    ).toHaveClass('error');
  });
});
