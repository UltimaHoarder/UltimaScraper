import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getRemoteSettings,
  syncSettingsToAll,
  updateRemoteSettings,
} from '../../src/api/settings';
import type { SettingsResponse } from '../../src/api/types/settings';
import { RemoteConfigModal } from '../../src/features/system/components/RemoteConfigModal';

vi.mock('../../src/api/settings', () => ({
  getRemoteSettings: vi.fn(),
  updateRemoteSettings: vi.fn(),
  syncSettingsToAll: vi.fn(),
}));

const mockGetRemoteSettings = vi.mocked(getRemoteSettings);
const mockUpdateRemoteSettings = vi.mocked(updateRemoteSettings);
const mockSyncSettingsToAll = vi.mocked(syncSettingsToAll);

const fixtureSettings: SettingsResponse = {
  hostname: 'alpha-worker-01',
  config_version: 3,
  worker_pool: {
    enabled: true,
    size: 8,
    max_claimed_jobs: 6,
    sites: ['onlyfans', 'fansly'],
  },
  backend: {
    backend_id: 'alpha-worker-01',
    execution_mode: 'distributed',
  },
  redis: {
    host: 'redis.internal',
    port: 6380,
    db: 1,
    password: 'secret-password',
    enabled: true,
  },
  download_setup: {
    directory_format: '{site_name}/{username}',
    alt_directory_formats: ['archive/{username}'],
    filename_format: '{media_id}_{filename}',
    text_length: 200,
    date_format: '%Y%m%d',
    overwrite_files: false,
    drives: [],
    staging_directories: [],
  },
  metadata_setup: {
    directory_format: '{site_name}/{username}/.metadata',
    drives: [],
  },
  previews_directory: '/mnt/storage/previews',
  subtitles_directory: '/mnt/storage/subtitles',
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
  drm: {
    device_client_blob_filepath: null,
    device_private_key_filepath: null,
  },
  sites: {
    onlyfans: { blacklists: [] },
    fansly: { blacklists: [] },
  },
  config_path: '/tmp/config.json',
  is_configured: true,
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
};

describe('RemoteConfigModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetRemoteSettings.mockResolvedValue({
      backend_id: 'alpha-worker-01',
      settings: fixtureSettings,
      error: null,
    });
    mockUpdateRemoteSettings.mockResolvedValue({
      backend_id: 'alpha-worker-01',
      success: true,
      message: 'Node settings updated successfully',
    });
    mockSyncSettingsToAll.mockResolvedValue({
      success: true,
      backends_updated: ['alpha-worker-01', 'alpha-worker-02'],
      backends_failed: [],
      message: 'Synchronized shared options to cluster',
    });
  });

  it('renders loading state initially and then populates node details', async () => {
    const onClose = vi.fn();
    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={onClose} />);

    expect(screen.getByText(/Reading remote node configuration/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByText(/Reading remote node configuration/i)).not.toBeInTheDocument();
    });

    expect(screen.getByRole('heading', { name: /Node Configuration/i })).toBeInTheDocument();
    expect(screen.getAllByText('alpha-worker-01').length).toBeGreaterThan(0);
    expect(screen.getByText(/Config version: v3/i)).toBeInTheDocument();

    // Check General tab fields
    const hostnameInput = screen.getByLabelText(/Hostname/i) as HTMLInputElement;
    expect(hostnameInput.value).toBe('alpha-worker-01');

    const workerSizeInput = screen.getByLabelText(/Worker Pool Size/i) as HTMLInputElement;
    expect(workerSizeInput.value).toBe('8');

    const claimedJobsInput = screen.getByLabelText(/Max Claimed Jobs/i) as HTMLInputElement;
    expect(claimedJobsInput.value).toBe('6');
  });

  it('navigates between configuration tabs and displays appropriate inputs', async () => {
    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Hostname/i)).toBeInTheDocument();
    });

    // Switch to Redis & Broker tab
    fireEvent.click(screen.getByRole('button', { name: /Redis & Broker/i }));
    expect(screen.getByLabelText(/Broker Host/i)).toBeInTheDocument();
    const redisHostInput = screen.getByLabelText(/Broker Host/i) as HTMLInputElement;
    expect(redisHostInput.value).toBe('redis.internal');

    const redisPortInput = screen.getByLabelText(/Port/i) as HTMLInputElement;
    expect(redisPortInput.value).toBe('6380');

    // Switch to Storage & Formats tab
    fireEvent.click(screen.getByRole('button', { name: /Storage & Formats/i }));
    expect(screen.getByLabelText(/Download Directory Format/i)).toBeInTheDocument();
    const dirFormatInput = screen.getByLabelText(/Download Directory Format/i) as HTMLInputElement;
    expect(dirFormatInput.value).toBe('{site_name}/{username}');

    const fileFormatInput = screen.getByLabelText(/Filename Format/i) as HTMLInputElement;
    expect(fileFormatInput.value).toBe('{media_id}_{filename}');

    const previewsInput = screen.getByLabelText(/Previews Directory/i) as HTMLInputElement;
    expect(previewsInput.value).toBe('/mnt/storage/previews');

    // Switch back to General tab
    fireEvent.click(screen.getByRole('button', { name: /General/i }));
    expect(screen.getByLabelText(/Hostname/i)).toBeInTheDocument();
  });

  it('toggles the cluster synchronization master switch', async () => {
    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/Sync to other backends: ON/i)).toBeInTheDocument();
    });

    const saveButton = screen.getByRole('button', { name: /Save & Sync to Cluster/i });
    expect(saveButton).toBeInTheDocument();
    expect(screen.getByText(/Auto-sync: Cluster broadcast enabled/i)).toBeInTheDocument();

    // Toggle switch to OFF
    const syncCheckbox = screen.getByRole('checkbox', { name: /Sync to other backends: ON/i });
    fireEvent.click(syncCheckbox);

    expect(screen.getByText(/Sync to other backends: OFF/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Save Configuration/i })).toBeInTheDocument();
    expect(screen.getByText(/Auto-sync: Local save only/i)).toBeInTheDocument();
  });

  it('saves configuration and broadcasts shared options across cluster when sync is enabled', async () => {
    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Hostname/i)).toBeInTheDocument();
    });

    // Modify hostname
    const hostnameInput = screen.getByLabelText(/Hostname/i);
    fireEvent.change(hostnameInput, { target: { value: 'alpha-worker-renamed' } });

    // Save with sync ON (default)
    const saveButton = screen.getByRole('button', { name: /Save & Sync to Cluster/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockUpdateRemoteSettings).toHaveBeenCalledWith(
        'alpha-worker-01',
        expect.objectContaining({
          hostname: 'alpha-worker-renamed',
          expected_version: 3,
        }),
      );
    });

    await waitFor(() => {
      expect(mockSyncSettingsToAll).toHaveBeenCalledWith(
        expect.objectContaining({
          download_setup: expect.objectContaining({
            directory_format: '{site_name}/{username}',
            filename_format: '{media_id}_{filename}',
          }),
          previews_directory: '/mnt/storage/previews',
          subtitles_directory: '/mnt/storage/subtitles',
        }),
      );
    });

    expect(
      screen.getByText(/Configuration saved and shared options synchronized across cluster/i),
    ).toBeInTheDocument();
  });

  it('saves only to target node when cluster sync switch is turned off', async () => {
    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Hostname/i)).toBeInTheDocument();
    });

    // Turn OFF sync switch
    const syncCheckbox = screen.getByRole('checkbox', { name: /Sync to other backends: ON/i });
    fireEvent.click(syncCheckbox);

    // Click Save Configuration
    const saveButton = screen.getByRole('button', { name: /Save Configuration/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockUpdateRemoteSettings).toHaveBeenCalledWith(
        'alpha-worker-01',
        expect.objectContaining({
          hostname: 'alpha-worker-01',
        }),
      );
    });

    expect(mockSyncSettingsToAll).not.toHaveBeenCalled();
    expect(screen.getByText(/Node settings updated successfully/i)).toBeInTheDocument();
  });

  it('sends the new config version when saving twice without reopening', async () => {
    mockGetRemoteSettings
      .mockResolvedValueOnce({ backend_id: 'alpha-worker-01', settings: fixtureSettings, error: null })
      .mockResolvedValue({
        backend_id: 'alpha-worker-01',
        settings: { ...fixtureSettings, config_version: 4 },
        error: null,
      });
    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Hostname/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('checkbox', { name: /Sync to other backends: ON/i }));
    const saveButton = screen.getByRole('button', { name: /Save Configuration/i });

    fireEvent.click(saveButton);
    await waitFor(() => expect(mockGetRemoteSettings).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(saveButton).not.toBeDisabled());
    fireEvent.click(saveButton);

    await waitFor(() => expect(mockUpdateRemoteSettings).toHaveBeenCalledTimes(2));
    expect(mockUpdateRemoteSettings.mock.calls[0][1].expected_version).toBe(3);
    expect(mockUpdateRemoteSettings.mock.calls[1][1].expected_version).toBe(4);
  });

  it('turns on HTTPS for other machines for this node only', async () => {
    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole('checkbox', { name: 'Serve HTTPS for other machines' }));
    fireEvent.change(screen.getByLabelText('HTTPS port'), { target: { value: '9443' } });
    fireEvent.change(screen.getByLabelText('Address for other machines'), { target: { value: 'devbox.lan' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save & Sync to Cluster' }));

    await waitFor(() => {
      expect(mockUpdateRemoteSettings).toHaveBeenCalledWith(
        'alpha-worker-01',
        expect.objectContaining({
          backend: expect.objectContaining({ share_https: true, https_port: 9443, advertise_host: 'devbox.lan' }),
        }),
      );
    });
    // An address is per machine: never broadcast.
    await waitFor(() => expect(mockSyncSettingsToAll).toHaveBeenCalled());
    expect(mockSyncSettingsToAll.mock.calls[0][0]).not.toHaveProperty('backend');
  });

  it('broadcasts shared options immediately when clicking Sync Shared Now', async () => {
    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Sync Shared Now/i })).toBeInTheDocument();
    });

    const syncSharedNowBtn = screen.getByRole('button', { name: /Sync Shared Now/i });
    fireEvent.click(syncSharedNowBtn);

    await waitFor(() => {
      expect(mockSyncSettingsToAll).toHaveBeenCalledTimes(1);
    });

    expect(
      screen.getByText(/Shared options broadcast successfully to 2 backends/i),
    ).toBeInTheDocument();
    expect(mockUpdateRemoteSettings).not.toHaveBeenCalled();
  });

  it('displays error message when remote settings fail to load', async () => {
    mockGetRemoteSettings.mockResolvedValueOnce({
      backend_id: 'alpha-worker-01',
      settings: null,
      error: 'Backend node unreachable (503 Service Unavailable)',
    });

    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={vi.fn()} />);

    await waitFor(() => {
      expect(
        screen.getByText(/Failed to load node configuration: Backend node unreachable/i),
      ).toBeInTheDocument();
    });

    // Save button should be disabled
    const saveBtn = screen.getByRole('button', { name: /Save & Sync to Cluster/i });
    expect(saveBtn).toBeDisabled();
  });

  it('invokes onClose when clicking close button, clicking backdrop, or pressing Escape', async () => {
    const onClose = vi.fn();
    render(<RemoteConfigModal backendId="alpha-worker-01" onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Close configuration modal/i)).toBeInTheDocument();
    });

    // Close button
    fireEvent.click(screen.getByLabelText(/Close configuration modal/i));
    expect(onClose).toHaveBeenCalledTimes(1);

    // Escape key
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);

    // Backdrop click
    const backdrop = document.querySelector('.rc-modal-backdrop');
    expect(backdrop).not.toBeNull();
    if (backdrop) {
      fireEvent.click(backdrop);
      expect(onClose).toHaveBeenCalledTimes(3);
    }
  });
});
