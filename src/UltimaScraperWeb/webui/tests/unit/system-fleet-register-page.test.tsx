import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getSettings } from '../../src/api/settings';
import {
  analyzeDatabase,
  cancelDatabaseOperation,
  controlRuntimePower,
  getAllBackends,
  getBackendStatus,
  getDatabaseOverview,
  getDrives,
  reindexDatabase,
  vacuumDatabase,
} from '../../src/api/system';
import type { SettingsResponse } from '../../src/api/types/settings';
import type {
  AllBackendsResponse,
  BackendStatusResponse,
  DatabaseOverviewResponse,
  DrivesResponse,
} from '../../src/api/types/system';
import {
  connectionHome,
  getConnectionTicket,
  getWebUIUpdate,
  listClusters,
  listConnections,
  listDeployments,
  listWebUIClients,
  registerExistingInstall,
  revokeWebUIClient,
  scanHostKey,
  type WebUIClientSession,
  type WebUIUpdateStatus,
} from '../../src/api/webui';
import { SystemFleetRegisterPage } from '../../src/features/system/SystemFleetRegisterPage';
import { renderWithProviders } from './testUtils';

vi.mock('../../src/api/system', () => ({
  addDirectory: vi.fn(),
  analyzeDatabase: vi.fn(),
  cancelDatabaseOperation: vi.fn(),
  controlRuntimePower: vi.fn(),
  getAllBackends: vi.fn(),
  getBackendStatus: vi.fn(),
  getDatabaseOverview: vi.fn(),
  getDrives: vi.fn(),
  reindexDatabase: vi.fn(),
  removeDirectory: vi.fn(),
  updateDirectoryConfig: vi.fn(),
  vacuumDatabase: vi.fn(),
}));

vi.mock('../../src/api/settings', () => ({
  getSettings: vi.fn(),
  updateSettings: vi.fn(),
}));

const mockWebUIUpdate: WebUIUpdateStatus = {
  version: '0.2.0',
  install_kind: 'container',
  channel: 'release',
  index: 'https://pypi.org/simple',
  latest: '0.2.0',
  update_available: false,
  can_update: false,
  reason: 'Up to date',
};

vi.mock('../../src/api/webui', () => ({
  listClusters: vi.fn().mockResolvedValue({ members: [], clusters: [] }),
  connectionHome: vi.fn((id: string) => (id === 'default' ? '/' : `/b/${id}/`)),
  listDeployments: vi.fn().mockResolvedValue([]),
  registerExistingInstall: vi.fn(),
  operateDeployment: vi.fn(),
  detectHost: vi.fn().mockResolvedValue({ needs_sudo_for: [], facts: {} }),
  getWebUIUpdate: vi.fn().mockResolvedValue({
    version: '0.2.0',
    install_kind: 'container',
    channel: 'release',
    index: 'https://pypi.org/simple',
    latest: '0.2.0',
    update_available: false,
    can_update: false,
    reason: 'Up to date',
  }),
  triggerWebUIUpdate: vi.fn().mockResolvedValue({ task_id: 'update-1' }),
  listConnections: vi.fn().mockResolvedValue([]),
  addConnection: vi.fn(),
  removeConnection: vi.fn(),
  setPluginTrust: vi.fn(),
  signOutOfWebUI: vi.fn(),
  testConnection: vi.fn(),
  scanHostKey: vi.fn().mockResolvedValue({
    algorithm: 'ssh-ed25519',
    fingerprint: 'SHA256:abc123mock',
    key: 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMockKey123',
  }),
  listWebUIClients: vi.fn().mockResolvedValue([]),
  revokeWebUIClient: vi.fn().mockResolvedValue(undefined),
  getConnectionTicket: vi.fn().mockResolvedValue({
    ticket: 'usr://ticket/mockticket',
  }),
}));

const mockBackendStatus: BackendStatusResponse = {
  backend_id: 'cluster-node',
  distributed_mode: false,
  redis_connected: true,
  worker_count: 1,
  active_workers: 0,
  pending_jobs: 0,
  workers: [],
  system_stats: null,
};

const mockAllBackends: AllBackendsResponse = {
  success: true,
  local_backend_id: 'cluster-node',
  local_hostname: 'cluster-node-main',
  backends: [],
  total_backends: 1,
};

const mockDrives: DrivesResponse = {
  backend_id: 'cluster-node',
  drives: [
    {
      path: '/mnt/drive-primary',
      device: '/dev/sdc',
      total_bytes: 12600000000000,
      used_bytes: 12588800000000,
      free_bytes: 11200000000,
      percent_used: 99.9,
      is_configured: true,
      directory_count: 1,
      configured_directories: ['/mnt/drive-primary/data'],
      is_available: true,
    },
    {
      path: '/mnt/drive-secondary',
      device: '/dev/sdb',
      total_bytes: 915800000000,
      used_bytes: 358500000000,
      free_bytes: 557300000000,
      percent_used: 35.9,
      is_configured: false,
      directory_count: 0,
      configured_directories: [],
      is_available: true,
    },
  ],
};

const mockSettings: SettingsResponse = {
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
  worker_pool: { enabled: true, size: 4, sites: ['onlyfans'], max_claimed_jobs: 2 },
  backend: { backend_id: 'cluster-node', execution_mode: 'local' },
  redis: { host: 'localhost', port: 6379, db: 0, password: null, enabled: false },
  network: {
    guest_route_rate_limit: 0,
    guest_session_pool: false,
    max_connections: 32,
    proxies: [],
    proxy_fallback: false,
    downloads: { max_concurrency: 4, per_domain_concurrency: 2, head_concurrency: 1, buffer_size_bytes: 1024 },
  },
  download_setup: {
    drives: [
      {
        minimum_space: 0,
        store: true,
        scan_existing: true,
        overflow: false,
        directories: ['/mnt/drive-primary/data'],
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
  metadata_setup: { drives: [], directory_format: '{site_name}/{user_username}' },
  previews_directory: null,
  subtitles_directory: null,
  drm: { device_client_blob_filepath: null, device_private_key_filepath: null },
  sites: { onlyfans: { blacklists: [] }, fansly: { blacklists: [] } },
  config_path: '/tmp/config.json',
  config_version: 1,
  is_configured: true,
};

const mockDatabaseOverview: DatabaseOverviewResponse = {
  success: true,
  backend_id: 'cluster-node',
  total_databases: 3,
  total_size_bytes: 265400000000,
  server_version: 'PostgreSQL 16.2',
  databases: [
    {
      site: 'management',
      database_name: 'ultima_archive',
      schema_name: 'management',
      host: 'localhost',
      port: 5432,
      is_connected: true,
      status: 'healthy',
      total_size_bytes: 260000000000,
      total_size_pretty: '260.0 GB',
      table_count: 307,
      total_live_tuples: 92000000,
      row_counts_estimated: true,
      total_dead_tuples: 240000,
      bloat_percent: 0.26,
      last_vacuum: '2026-10-23T08:00:00Z',
      last_analyze: '2026-10-23T08:00:00Z',
      tables: [
        {
          table_name: 'job_tasks',
          live_tuples: 50000000,
          dead_tuples: 100000,
          total_bytes: 120000000000,
          table_bytes: 70000000000,
          index_bytes: 50000000000,
          last_vacuum: '2026-10-23T08:00:00Z',
          last_autovacuum: null,
          last_analyze: '2026-10-23T08:00:00Z',
          last_autoanalyze: null,
        },
      ],
    },
    {
      site: 'onlyfans',
      database_name: 'ultimascraper_site_onlyfans',
      schema_name: 'onlyfans',
      host: 'localhost',
      port: 5432,
      is_connected: true,
      status: 'healthy',
      total_size_bytes: 3200000000,
      total_size_pretty: '3.2 GB',
      table_count: 8,
      total_live_tuples: 145000,
      total_dead_tuples: 230,
      bloat_percent: 0.16,
      last_vacuum: '2026-10-23T08:00:00Z',
      last_analyze: '2026-10-23T08:00:00Z',
      tables: [
        {
          table_name: 'users',
          live_tuples: 120000,
          dead_tuples: 150,
          total_bytes: 2100000000,
          table_bytes: 1500000000,
          index_bytes: 600000000,
          last_vacuum: '2026-10-23T08:00:00Z',
          last_autovacuum: null,
          last_analyze: '2026-10-23T08:00:00Z',
          last_autoanalyze: null,
        },
        {
          table_name: 'posts',
          live_tuples: 25000,
          dead_tuples: 80,
          total_bytes: 1100000000,
          table_bytes: 800000000,
          index_bytes: 300000000,
          last_vacuum: '2026-10-23T08:00:00Z',
          last_autovacuum: null,
          last_analyze: '2026-10-23T08:00:00Z',
          last_autoanalyze: null,
        },
      ],
    },
    {
      site: 'fansly',
      database_name: 'ultimascraper_site_fansly',
      schema_name: 'fansly',
      host: 'localhost',
      port: 5432,
      is_connected: true,
      status: 'warning',
      total_size_bytes: 2200000000,
      total_size_pretty: '2.2 GB',
      table_count: 5,
      total_live_tuples: 45000,
      total_dead_tuples: 15000,
      bloat_percent: 25.0,
      last_vacuum: null,
      last_analyze: null,
      tables: [
        {
          table_name: 'users',
          live_tuples: 40000,
          dead_tuples: 14000,
          total_bytes: 1800000000,
          table_bytes: 1200000000,
          index_bytes: 600000000,
          last_vacuum: null,
          last_autovacuum: null,
          last_analyze: null,
          last_autoanalyze: null,
        },
      ],
    },
  ],
};

describe('SystemFleetRegisterPage mounts grouping', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getBackendStatus).mockResolvedValue(mockBackendStatus);
    vi.mocked(getAllBackends).mockResolvedValue(mockAllBackends);
    vi.mocked(getDrives).mockResolvedValue(mockDrives);
    vi.mocked(getSettings).mockResolvedValue(mockSettings);
    vi.mocked(getDatabaseOverview).mockResolvedValue(mockDatabaseOverview);
    vi.mocked(listClusters).mockResolvedValue({ members: [], clusters: [] });
    vi.mocked(listDeployments).mockResolvedValue([]);
    vi.mocked(listWebUIClients).mockResolvedValue([]);
    vi.mocked(revokeWebUIClient).mockResolvedValue(undefined);
  });

  it('separates mounts with directories into Assigned and mounts without into Unassigned', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    // Switch to mounts tab
    const mountsTabBtn = await screen.findByRole('button', { name: /mounts/i });
    fireEvent.click(mountsTabBtn);

    // Verify Assigned section divider is rendered with count
    const assignedDivider = await screen.findByRole('button', { name: /collapse assigned mounts/i });
    expect(assignedDivider).toBeInTheDocument();
    expect(assignedDivider).toHaveTextContent(/Assigned/i);
    expect(assignedDivider).toHaveTextContent(/1 mount/i);

    // Verify Unassigned section divider is rendered with count
    const unassignedDivider = screen.getByRole('button', { name: /collapse unassigned mounts/i });
    expect(unassignedDivider).toBeInTheDocument();
    expect(unassignedDivider).toHaveTextContent(/Unassigned/i);
    expect(unassignedDivider).toHaveTextContent(/1 mount/i);

    // Verify the rows exist
    expect(screen.getByText('/mnt/drive-primary')).toBeInTheDocument();
    expect(screen.getByText('/mnt/drive-secondary')).toBeInTheDocument();
  });

  it('toggles collapse and expand when clicking section dividers', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    const mountsTabBtn = await screen.findByRole('button', { name: /mounts/i });
    fireEvent.click(mountsTabBtn);

    const unassignedDivider = await screen.findByRole('button', { name: /collapse unassigned mounts/i });
    expect(screen.getByText('/mnt/drive-secondary')).toBeInTheDocument();

    // Click to collapse unassigned section
    fireEvent.click(unassignedDivider);

    // /mnt/drive-secondary should now be hidden
    expect(screen.queryByText('/mnt/drive-secondary')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /expand unassigned mounts/i })).toBeInTheDocument();

    // /mnt/drive-primary should still be visible
    expect(screen.getByText('/mnt/drive-primary')).toBeInTheDocument();

    // Click to expand unassigned section again
    const expandBtn = screen.getByRole('button', { name: /expand unassigned mounts/i });
    fireEvent.click(expandBtn);

    expect(screen.getByText('/mnt/drive-secondary')).toBeInTheDocument();
  });
});

describe('SystemFleetRegisterPage runtime power controls', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getBackendStatus).mockResolvedValue(mockBackendStatus);
    vi.mocked(getAllBackends).mockResolvedValue(mockAllBackends);
    vi.mocked(getDrives).mockResolvedValue(mockDrives);
    vi.mocked(getSettings).mockResolvedValue(mockSettings);
    vi.mocked(getDatabaseOverview).mockResolvedValue(mockDatabaseOverview);
    vi.mocked(listClusters).mockResolvedValue({ members: [], clusters: [] });
    vi.mocked(listDeployments).mockResolvedValue([]);
    vi.mocked(listWebUIClients).mockResolvedValue([]);
    vi.mocked(revokeWebUIClient).mockResolvedValue(undefined);
  });

  it('restarts only after confirmation and reports that services are restarting', async () => {
    vi.mocked(controlRuntimePower).mockResolvedValue({ action: 'restart', status: 'accepted', supervisor_pid: 42 });
    renderWithProviders(<SystemFleetRegisterPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Restart runtime' }));
    expect(controlRuntimePower).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Restart runtime' }));

    await waitFor(() =>
      expect(controlRuntimePower).toHaveBeenCalledWith(
        'restart',
        expect.arrayContaining(['api', 'database_writer', 'worker_pool', 'plugins', 'webui']),
      ),
    );
    expect(await screen.findByText('Restarting UltimaScraper')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Shut down' })).toBeDisabled();
  });

  it('allows choosing specific services to restart and updates button label', async () => {
    vi.mocked(controlRuntimePower).mockResolvedValue({
      action: 'restart',
      status: 'accepted',
      supervisor_pid: 42,
      targets: ['worker_pool', 'plugins'],
    });
    renderWithProviders(<SystemFleetRegisterPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Restart runtime' }));
    const dialog = screen.getByRole('dialog');

    // Click preset "Workers & Plugins"
    fireEvent.click(within(dialog).getByRole('button', { name: 'Workers & Plugins' }));
    expect(within(dialog).getByRole('button', { name: 'Restart selected (2)' })).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Restart selected (2)' }));
    await waitFor(() =>
      expect(controlRuntimePower).toHaveBeenCalledWith('restart', ['worker_pool', 'plugins']),
    );
  });

  it('disables restart confirmation when all services are deselected', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Restart runtime' }));
    const dialog = screen.getByRole('dialog');

    fireEvent.click(within(dialog).getByRole('button', { name: 'Clear' }));
    const restartBtn = within(dialog).getByRole('button', { name: 'Select services' });
    expect(restartBtn).toBeDisabled();
  });

  it('cancelling the shutdown dialog sends nothing', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Shut down' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /cancel/i }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(controlRuntimePower).not.toHaveBeenCalled();
  });

  it('shows why the launcher refused the request', async () => {
    vi.mocked(controlRuntimePower).mockRejectedValue(new Error('This backend was not started by the UltimaScraper launcher'));
    renderWithProviders(<SystemFleetRegisterPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Shut down' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Shut down' }));

    expect(await screen.findByText(/not started by the UltimaScraper launcher/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Shut down' })).toBeEnabled();
  });
});

describe('SystemFleetRegisterPage database operations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getBackendStatus).mockResolvedValue(mockBackendStatus);
    vi.mocked(getAllBackends).mockResolvedValue(mockAllBackends);
    vi.mocked(getDrives).mockResolvedValue(mockDrives);
    vi.mocked(getSettings).mockResolvedValue(mockSettings);
    vi.mocked(getDatabaseOverview).mockResolvedValue(mockDatabaseOverview);
    vi.mocked(listClusters).mockResolvedValue({ members: [], clusters: [] });
    vi.mocked(listDeployments).mockResolvedValue([]);
    vi.mocked(listWebUIClients).mockResolvedValue([]);
    vi.mocked(revokeWebUIClient).mockResolvedValue(undefined);
    vi.mocked(getWebUIUpdate).mockResolvedValue(mockWebUIUpdate);
    vi.mocked(listConnections).mockResolvedValue([]);
    vi.mocked(connectionHome).mockImplementation((id: string) => (id === 'default' ? '/' : `/b/${id}/`));
    vi.mocked(vacuumDatabase).mockResolvedValue({
      success: true,
      message: 'Vacuum (analyze) completed on schema onlyfans',
      site: 'onlyfans',
      table_name: null,
      mode: 'standard',
      duration_seconds: 0.12,
    });
    vi.mocked(analyzeDatabase).mockResolvedValue({
      success: true,
      message: 'Analyze completed on schema onlyfans',
      site: 'onlyfans',
      table_name: null,
      duration_seconds: 0.05,
    });
    vi.mocked(reindexDatabase).mockResolvedValue({
      success: true,
      message: 'Reindex completed on schema onlyfans',
      site: 'onlyfans',
      table_name: null,
      duration_seconds: 0.2,
    });
  });

  it('renders database tab with correct badge count', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    expect(dbTabBtn).toBeInTheDocument();
    await waitFor(() => expect(dbTabBtn).toHaveTextContent('3'));
  });

  it('switches to database tab and displays site rows', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    fireEvent.click(dbTabBtn);

    expect(await screen.findByText('management')).toBeInTheDocument();
    expect(screen.getByText('onlyfans')).toBeInTheDocument();
    expect(screen.getByText('fansly')).toBeInTheDocument();
    expect(screen.getByText('260.0 GB')).toBeInTheDocument();
    expect(screen.getByText('3.2 GB')).toBeInTheDocument();
    expect(screen.getByText('2.2 GB')).toBeInTheDocument();
    expect(screen.getByText('Needs vacuum')).toBeInTheDocument();
  });

  it('labels PostgreSQL row counts as estimates and keeps exact counts plain', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    fireEvent.click(await screen.findByRole('button', { name: /^database/i }));

    const estimated = await screen.findByText(/~50,000,000 rows \(estimate\)/);
    expect(estimated).toHaveAttribute('title', expect.stringMatching(/not an exact COUNT/));
    // Sites without the flag (exact counts) show no estimate marker.
    expect(screen.getAllByText(/^[0-9,]+ live rows$/)).toHaveLength(2);
  });

  it('opens vacuum modal for specific site and executes vacuum', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    fireEvent.click(dbTabBtn);

    const vacuumBtns = await screen.findAllByRole('button', { name: /^vacuum$/i });
    fireEvent.click(vacuumBtns[0]);

    // Modal dialog is opened
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/Vacuum Database · management/i)).toBeInTheDocument();

    // Confirm vacuum execution
    const runBtn = screen.getByRole('button', { name: /run vacuum/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(vacuumDatabase).toHaveBeenCalledWith(
        expect.objectContaining({
          site: 'management',
          full: false,
          analyze: true,
        }),
      );
    });

    expect(await screen.findByText(/Vacuum completed/i)).toBeInTheDocument();
  });

  it('executes analyze and reindex actions from table rows', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    fireEvent.click(dbTabBtn);

    const analyzeBtns = await screen.findAllByRole('button', { name: /^analyze$/i });
    fireEvent.click(analyzeBtns[0]);

    await waitFor(() => {
      expect(analyzeDatabase).toHaveBeenCalledWith({ site: 'management', table_name: undefined });
    });

    const reindexBtns = await screen.findAllByRole('button', { name: /^reindex$/i });
    fireEvent.click(reindexBtns[0]);

    await waitFor(() => {
      expect(reindexDatabase).toHaveBeenCalledWith({ site: 'management', table_name: undefined });
    });
  });

  it('opens inspection modal and lists table details', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    fireEvent.click(dbTabBtn);

    const inspectBtn = await screen.findByRole('button', { name: /inspect onlyfans database/i });
    fireEvent.click(inspectBtn);

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText(/ultimascraper_site_onlyfans/i)).toBeInTheDocument();
    expect(within(dialog).getByText('users')).toBeInTheDocument();
    expect(within(dialog).getByText('posts')).toBeInTheDocument();
  });

  it('shows pending feedback and disables buttons when analyzing a database', async () => {
    let resolveAnalyze!: (val: { success: boolean; message: string; site: string; table_name: null; duration_seconds: number }) => void;
    vi.mocked(analyzeDatabase).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveAnalyze = resolve;
        }),
    );

    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    fireEvent.click(dbTabBtn);

    const analyzeBtns = await screen.findAllByRole('button', { name: /^analyze$/i });
    fireEvent.click(analyzeBtns[0]);

    // Active in-progress banner and button spinner text are visible
    expect(await screen.findByText(/Analyze in progress/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /analyzing…/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /analyzing…/i })).toBeDisabled();

    // Resolve the analyze mutation
    resolveAnalyze({
      success: true,
      message: 'Analyze completed on schema onlyfans',
      site: 'onlyfans',
      table_name: null,
      duration_seconds: 1.2,
    });

    const completedNotices = await screen.findAllByText(/Analyze completed/i);
    expect(completedNotices.length).toBeGreaterThan(0);
  });

  it('shows in-progress notice and table-level spinner inside inspection modal', async () => {
    let resolveAnalyzeTable!: (val: { success: boolean; message: string; site: string; table_name: string; duration_seconds: number }) => void;
    vi.mocked(analyzeDatabase).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveAnalyzeTable = resolve;
        }),
    );

    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    fireEvent.click(dbTabBtn);

    const inspectBtn = await screen.findByRole('button', { name: /inspect onlyfans database/i });
    fireEvent.click(inspectBtn);

    const dialog = await screen.findByRole('dialog');
    const tableAnalyzeBtns = within(dialog).getAllByRole('button', { name: /^analyze$/i });
    fireEvent.click(tableAnalyzeBtns[0]);

    // Modal shows notice and specific button spinner text
    expect(await within(dialog).findByText(/Analyze in progress/i)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /analyzing…/i })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /analyzing…/i })).toBeDisabled();

    // Resolve analyze
    resolveAnalyzeTable({
      success: true,
      message: 'Analyze completed on table users',
      site: 'onlyfans',
      table_name: 'users',
      duration_seconds: 0.5,
    });

    const modalCompletedNotices = await within(dialog).findAllByText(/Analyze completed/i);
    expect(modalCompletedNotices.length).toBeGreaterThan(0);
  });

  it('displays persistent vacuum progress and disables buttons across page refresh', async () => {
    vi.mocked(getDatabaseOverview).mockResolvedValueOnce({
      ...mockDatabaseOverview,
      active_operations: [
        {
          id: 'op_123_vacuum_management',
          operation_type: 'vacuum',
          site: 'management',
          table_name: null,
          current_table: 'job_tasks',
          tables_completed: 14,
          tables_total: 307,
          phase: 'scanning heap',
          progress_percent: 65.4,
          heap_blks_total: 10000,
          heap_blks_scanned: 6540,
          heap_blks_vacuumed: 3200,
          started_at: '2026-10-23T22:00:00Z',
          duration_seconds: 42.5,
          status: 'running',
          message: 'Vacuuming table job_tasks (15/307) in management · Phase: scanning heap (65.4%)',
        },
      ],
    });

    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    fireEvent.click(dbTabBtn);

    // After refresh/load, active progress banner is rendered from server active_operations
    expect(await screen.findByText(/Vacuum in progress/i)).toBeInTheDocument();
    expect(screen.getByText(/Vacuuming table job_tasks \(15\/307\) in management/i)).toBeInTheDocument();
    expect(screen.getByText('65.4%')).toBeInTheDocument();

    // Management row shows vacuuming spinner state and is disabled
    expect(screen.getByRole('button', { name: /vacuuming…/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /vacuuming…/i })).toBeDisabled();
  });

  it('shows background execution notice when vacuum mutation errors but server is still executing', async () => {
    vi.mocked(getDatabaseOverview).mockResolvedValue(mockDatabaseOverview);
    vi.mocked(vacuumDatabase).mockImplementation(async () => {
      vi.mocked(getDatabaseOverview).mockResolvedValue({
        ...mockDatabaseOverview,
        active_operations: [
          {
            id: 'op_running_vacuum',
            operation_type: 'vacuum',
            site: 'management',
            table_name: null,
            current_table: 'job_tasks',
            tables_completed: 0,
            tables_total: 1,
            phase: 'rebuilding index',
            progress_percent: 100,
            heap_blks_total: 6000000,
            heap_blks_scanned: 6000000,
            heap_blks_vacuumed: null,
            started_at: '2026-10-24T22:00:00Z',
            duration_seconds: 610.0,
            status: 'running',
            message: 'Vacuuming table job_tasks in management · Phase: rebuilding index',
          },
        ],
      });
      throw new Error('timeout of 600000ms exceeded');
    });

    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    fireEvent.click(dbTabBtn);

    const vacuumBtns = await screen.findAllByRole('button', { name: /^vacuum$/i });
    fireEvent.click(vacuumBtns[0]);

    const runBtn = screen.getByRole('button', { name: /run vacuum/i });
    fireEvent.click(runBtn);

    expect(await screen.findByText(/Vacuum running in background/i)).toBeInTheDocument();
    expect(
      screen.getByText(/maintenance operation is actively executing on the database server/i),
    ).toBeInTheDocument();
  });

  it('allows user to cancel an active database operation from the progress banner', async () => {
    vi.mocked(getDatabaseOverview).mockResolvedValue({
      ...mockDatabaseOverview,
      active_operations: [
        {
          id: 'op_running_vacuum',
          operation_type: 'vacuum',
          site: 'management',
          table_name: null,
          current_table: 'job_tasks',
          tables_completed: 15,
          tables_total: 307,
          phase: 'scanning heap',
          progress_percent: 65.4,
          heap_blks_total: 10000,
          heap_blks_scanned: 6540,
          heap_blks_vacuumed: null,
          started_at: '2026-10-24T22:00:00Z',
          duration_seconds: 12.5,
          status: 'running',
          message: 'Vacuuming table job_tasks (15/307) in management…',
        },
      ],
    });
    vi.mocked(cancelDatabaseOperation).mockResolvedValue({
      success: true,
      message: 'Cancelled 1 active database operation(s).',
      cancelled_count: 1,
    });

    renderWithProviders(<SystemFleetRegisterPage />);

    const dbTabBtn = await screen.findByRole('button', { name: /^database/i });
    fireEvent.click(dbTabBtn);

    const cancelBtn = await screen.findByRole('button', { name: /cancel operation/i });
    expect(cancelBtn).toBeInTheDocument();
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(cancelDatabaseOperation).toHaveBeenCalledWith('management', undefined);
    });
    expect(await screen.findByText(/Operation cancelled/i)).toBeInTheDocument();
  });

  it('renders the cluster tab and switches to the cluster section', async () => {
    vi.mocked(getAllBackends).mockResolvedValue({
      ...mockAllBackends,
      backends: [
        {
          backend_id: 'cluster-node',
          hostname: 'cluster-node-main',
          status: 'online',
          last_seen: new Date().toISOString(),
          max_workers: 10,
          version: '0.1.0',
          drives: [],
          workers: [],
          active_workers: 0,
          pending_jobs: 0,
          cluster_id: 'test-cluster-uuid-1234',
        },
        {
          backend_id: 'alpha-remote',
          hostname: 'alpha',
          status: 'online',
          last_seen: new Date().toISOString(),
          max_workers: 4,
          version: '0.1.0',
          drives: [],
          workers: [],
          active_workers: 0,
          pending_jobs: 0,
          cluster_id: 'test-cluster-uuid-1234',
        },
      ],
      total_backends: 2,
    });

    renderWithProviders(<SystemFleetRegisterPage />);

    // Check cluster pill in summary
    const clusterPill = await screen.findByRole('button', { name: /inspect cluster topology/i });
    expect(clusterPill).toBeInTheDocument();
    expect(clusterPill).toHaveTextContent(/test-clu/i);

    // Check cluster tab button
    const tabs = screen.getByRole('group', { name: /resource type/i });
    const clusterTabBtn = within(tabs).getByRole('button', { name: /^clusters/i });
    expect(clusterTabBtn).toBeInTheDocument();

    // Click cluster tab
    fireEvent.click(clusterTabBtn);

    // Verify Cluster Overview & Infrastructure are displayed
    expect(await screen.findByRole('heading', { name: 'Cluster test-clu' })).toBeInTheDocument();
    expect(screen.getByTitle('Copy the cluster id test-cluster-uuid-1234')).toBeInTheDocument();
    expect(screen.getByText(/PostgreSQL Archive Database/i)).toBeInTheDocument();
    expect(screen.getByText(/Redis Distributed Broker/i)).toBeInTheDocument();
    expect(screen.getByText(/Cluster Fleet Nodes/i)).toBeInTheDocument();
    expect(screen.getByText('alpha-remote')).toBeInTheDocument();

    // Actions on the cluster are in Manage cluster; creating or joining one is on the page.
    expect(screen.getByRole('link', { name: 'Create or join a cluster' })).toHaveAttribute('href', '/setup');
    expect(screen.queryByRole('button', { name: /\+ Add host/i })).not.toBeInTheDocument();

    // Verify individual worker metro breakdown pills (e.g. "4w", "10w") are not rendered
    expect(screen.queryByText(/4w/)).not.toBeInTheDocument();

    // Add host opens its choices in a dialog.
    fireEvent.click(screen.getByRole('button', { name: 'Manage cluster' }));
    fireEvent.click(screen.getByRole('button', { name: /^Add host/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Add host' });
    expect(within(dialog).getByRole('button', { name: /^Install/ })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: /^Connect/ })).toBeInTheDocument();
    // A WebUI is not a host: it is invited from the cluster page.
    expect(within(dialog).queryByRole('button', { name: /WebUI/ })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }));

    // One cluster: listed once, open, and nothing to switch to.
    expect(screen.getAllByRole('region', { name: /^Cluster / })).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Open' })).not.toBeInTheDocument();
  });

  it('lists every cluster and opens another one', async () => {
    vi.mocked(listClusters).mockResolvedValue({
      members: [],
      clusters: [
        {
          cluster_id: 'cluster-alpha',
          connection_ids: ['alpha-conn'],
          suggestions: [],
          conflicting_backend_ids: [],
        },
        {
          cluster_id: 'cluster-beta',
          connection_ids: [],
          suggestions: [],
          conflicting_backend_ids: [],
        },
      ],
    });

    vi.mocked(getAllBackends).mockResolvedValue({
      ...mockAllBackends,
      backends: [
        {
          backend_id: 'node-alpha',
          hostname: 'alpha-host',
          status: 'online',
          last_seen: new Date().toISOString(),
          max_workers: 2,
          version: '0.1.0',
          drives: [],
          workers: [],
          active_workers: 0,
          pending_jobs: 0,
          cluster_id: 'cluster-alpha',
        },
        {
          backend_id: 'node-beta',
          hostname: 'beta-host',
          status: 'online',
          last_seen: new Date().toISOString(),
          max_workers: 4,
          version: '0.1.0',
          drives: [],
          workers: [],
          active_workers: 0,
          pending_jobs: 0,
          cluster_id: 'cluster-beta',
        },
      ],
      total_backends: 2,
    });

    renderWithProviders(<SystemFleetRegisterPage />);

    // Check cluster tab button reports 2
    const tabs = screen.getByRole('group', { name: /resource type/i });
    const clusterTabBtn = await within(tabs).findByRole('button', { name: /clusters/i });
    expect(clusterTabBtn).toBeInTheDocument();
    await waitFor(() => {
      expect(clusterTabBtn).toHaveTextContent('2');
    });

    // Click cluster tab
    fireEvent.click(clusterTabBtn);

    // Initial cluster is cluster-alpha
    expect(await screen.findByTitle('Copy the cluster id cluster-alpha')).toBeInTheDocument();

    // Both clusters are listed; the other one opens with Open.
    const regions = screen.getAllByRole('region', { name: /^Cluster / });
    expect(regions).toHaveLength(2);
    const alpha = regions.find((region) => within(region).queryByTitle('Copy the cluster id cluster-alpha'))!;
    const beta = regions.find((region) => within(region).queryByTitle('Copy the cluster id cluster-beta'))!;
    expect(within(alpha).queryByRole('button', { name: 'Open' })).not.toBeInTheDocument();
    fireEvent.click(within(beta).getByRole('button', { name: 'Open' }));

    // Now cluster-beta is the one shown in full, and cluster-alpha can be opened.
    await waitFor(() => {
      const after = screen.getAllByRole('region', { name: /^Cluster / });
      const alphaAfter = after.find((region) => within(region).queryByTitle('Copy the cluster id cluster-alpha'))!;
      expect(within(alphaAfter).getByRole('button', { name: 'Open' })).toBeInTheDocument();
    });
  });
});

describe('SystemFleetRegisterPage remote backend inspect modal lifecycle operations', () => {
  const mockRemoteBackends: AllBackendsResponse = {
    success: true,
    local_backend_id: 'cluster-node',
    local_hostname: 'cluster-node-main',
    backends: [
      {
        backend_id: 'cluster-node',
        hostname: 'cluster-node-main',
        status: 'online',
        last_seen: new Date().toISOString(),
        max_workers: 4,
        version: '0.1.0',
        drives: [],
        workers: [],
        active_workers: 0,
        pending_jobs: 0,
        cluster_id: 'test-cluster',
      },
      {
        backend_id: 'alpha-remote',
        hostname: 'alpha',
        status: 'online',
        last_seen: new Date().toISOString(),
        max_workers: 4,
        version: '0.1.0',
        drives: [],
        workers: [],
        active_workers: 0,
        pending_jobs: 0,
        cluster_id: 'test-cluster',
      },
    ],
    total_backends: 2,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getBackendStatus).mockResolvedValue(mockBackendStatus);
    vi.mocked(getAllBackends).mockResolvedValue(mockRemoteBackends);
    vi.mocked(getDrives).mockResolvedValue(mockDrives);
    vi.mocked(getSettings).mockResolvedValue(mockSettings);
    vi.mocked(getDatabaseOverview).mockResolvedValue(mockDatabaseOverview);
    vi.mocked(listClusters).mockResolvedValue({ members: [], clusters: [] });
    vi.mocked(listDeployments).mockResolvedValue([]);
    vi.mocked(listWebUIClients).mockResolvedValue([]);
    vi.mocked(revokeWebUIClient).mockResolvedValue(undefined);
    vi.mocked(scanHostKey).mockResolvedValue({
      algorithm: 'ssh-ed25519',
      fingerprint: 'SHA256:abc123mock',
      key: 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMockKey123',
    });
    vi.mocked(getConnectionTicket).mockResolvedValue({
      ticket: 'usr://ticket/mockticket',
      name: 'alpha',
      base_url: 'http://127.0.0.1:8000',
      warning: null,
    });
  });

  it('renders Repair, Upgrade, and Uninstall buttons when inspecting a remote backend', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    const inspectBtn = await screen.findByRole('button', { name: 'Inspect alpha' });
    fireEvent.click(inspectBtn);

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Remote Operations')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Repair' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upgrade' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Uninstall' })).toBeInTheDocument();
  });

  it('shows SSH connection registration form when an unregistered remote backend action is clicked', async () => {
    renderWithProviders(<SystemFleetRegisterPage />);

    const inspectBtn = await screen.findByRole('button', { name: 'Inspect alpha' });
    fireEvent.click(inspectBtn);

    const repairBtn = await screen.findByRole('button', { name: 'Repair' });
    fireEvent.click(repairBtn);

    expect(
      screen.getByText(/This remote backend is not yet linked to a deployment record. To run/i),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText('alpha')).toBeInTheDocument();

    // Toggle off
    fireEvent.click(repairBtn);
    expect(
      screen.queryByText(/This remote backend is not yet linked to a deployment record/i),
    ).not.toBeInTheDocument();
  });

  it('fills Target Host with the address the backend reports', async () => {
    vi.mocked(getAllBackends).mockResolvedValue({
      ...mockRemoteBackends,
      backends: mockRemoteBackends.backends.map((item) =>
        item.backend_id === 'alpha-remote' ? { ...item, address: '192.168.50.120' } : item,
      ),
    });
    renderWithProviders(<SystemFleetRegisterPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Inspect alpha' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Repair' }));

    expect(screen.getByLabelText(/Target Host \/ IP/i)).toHaveValue('192.168.50.120');
  });

  it('submits registration when user fills and submits the SSH registration form', async () => {
    vi.mocked(registerExistingInstall).mockResolvedValue({
      id: 'dep-alpha',
      name: 'alpha',
      target: '192.168.1.100',
      details: {
        kind: 'ssh',
        host: '192.168.1.100',
        install_dir: '/opt/usv',
        project: 'ultimascraper',
        version: '0.1.0',
        image_source: 'registry',
        architecture: 'x86_64',
      },
      connection_id: null,
    });

    renderWithProviders(<SystemFleetRegisterPage />);

    const inspectBtn = await screen.findByRole('button', { name: 'Inspect alpha' });
    fireEvent.click(inspectBtn);

    const repairBtn = await screen.findByRole('button', { name: 'Repair' });
    fireEvent.click(repairBtn);

    const hostInput = screen.getByLabelText(/Target Host \/ IP/i);
    fireEvent.change(hostInput, { target: { value: '192.168.1.100' } });

    const submitBtn = screen.getByRole('button', { name: /Connect & Repair/i });
    fireEvent.submit(submitBtn.closest('form')!);

    await waitFor(() => {
      expect(registerExistingInstall).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'alpha',
          target: expect.objectContaining({ host: '192.168.1.100' }),
        }),
      );
    });
  });

  it('renders OperationPanel directly when matching deployment exists', async () => {
    vi.mocked(listDeployments).mockResolvedValue([
      {
        id: 'dep-alpha',
        name: 'alpha',
        target: 'alpha',
        details: {
          kind: 'ssh',
          host: '192.168.1.100',
          username: 'operator',
          install_dir: '~/ultimascraper',
          project: 'ultimascraper',
          version: '0.1.0',
          image_source: 'registry',
          architecture: 'x86_64',
        },
        connection_id: null,
      },
    ]);

    renderWithProviders(<SystemFleetRegisterPage />);

    const inspectBtn = await screen.findByRole('button', { name: 'Inspect alpha' });
    fireEvent.click(inspectBtn);

    const dialog = screen.getByRole('dialog');
    const upgradeBtn = within(dialog).getByRole('button', { name: 'Upgrade' });
    fireEvent.click(upgradeBtn);

    // Shows action hint from ACTION_HINTS.upgrade
    expect(
      screen.getByText(/Moves to another image version. Data and settings are kept./i),
    ).toBeInTheDocument();
    // In OperationPanel, the action trigger button plus form submit button are present
    expect(within(dialog).getAllByRole('button', { name: 'Upgrade' })).toHaveLength(2);

    // Toggle off by clicking the top action button
    fireEvent.click(upgradeBtn);
    expect(
      screen.queryByText(/Moves to another image version. Data and settings are kept./i),
    ).not.toBeInTheDocument();
  });

  it('renders the clients tab, displays connected sessions, and allows disconnecting a client session', async () => {
    const mockClients: WebUIClientSession[] = [
      {
        id: 'sess-current-1234',
        ip_address: '127.0.0.1',
        user_agent: 'Mozilla/5.0 Chrome/122.0.0.0 Safari/537.36',
        device_info: 'Chrome on Linux',
        is_local: true,
        created_at: Date.now() / 1000 - 3600,
        last_seen: Date.now() / 1000 - 10,
        is_current: true,
      },
      {
        id: 'sess-remote-5678',
        ip_address: '192.168.1.50',
        user_agent: 'Mozilla/5.0 Safari/605.1.15',
        device_info: 'Safari on macOS',
        is_local: false,
        created_at: Date.now() / 1000 - 7200,
        last_seen: Date.now() / 1000 - 600,
        is_current: false,
      },
    ];
    vi.mocked(listWebUIClients).mockResolvedValue(mockClients);

    renderWithProviders(<SystemFleetRegisterPage />);

    // Clients tab exists and shows count of 2
    const clientsTab = await screen.findByRole('button', { name: /^Clients/i });
    expect(clientsTab).toBeInTheDocument();
    await waitFor(() => expect(within(clientsTab).getByText('2')).toBeInTheDocument());

    // Click Clients tab
    fireEvent.click(clientsTab);

    // Displays both clients
    expect(await screen.findByText('Chrome on Linux')).toBeInTheDocument();
    expect(screen.getByText('Safari on macOS')).toBeInTheDocument();
    expect(screen.getByText('This device')).toBeInTheDocument();
    expect(screen.getByText('127.0.0.1')).toBeInTheDocument();
    expect(screen.getByText('192.168.1.50')).toBeInTheDocument();

    // Disconnect remote client
    const disconnectBtn = screen.getByRole('button', { name: 'Disconnect' });
    fireEvent.click(disconnectBtn);

    // Confirm dialog opens
    expect(screen.getByText('Disconnect Safari on macOS?')).toBeInTheDocument();
    const confirmBtn = screen.getByRole('button', { name: 'Disconnect client' });
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(revokeWebUIClient).toHaveBeenCalledWith('sess-remote-5678');
    });
  });

  it('displays connection ticket in backend inspection modal and copies to clipboard', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    renderWithProviders(<SystemFleetRegisterPage />);

    const inspectBtn = await screen.findByRole('button', { name: 'Inspect alpha' });
    fireEvent.click(inspectBtn);

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Connection Ticket')).toBeInTheDocument();

    const copyTicketBtn = screen.getByRole('button', { name: 'Copy Ticket' });
    expect(copyTicketBtn).toBeInTheDocument();

    fireEvent.click(copyTicketBtn);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith('usr://ticket/mockticket');
    });
  });

  it('allows copying connection ticket directly from the cluster nodes table', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    renderWithProviders(<SystemFleetRegisterPage />);

    // Wait for backends query to load
    await screen.findByRole('button', { name: 'Inspect alpha' });

    const tabs = screen.getByRole('group', { name: /resource type/i });
    const clusterTabBtn = within(tabs).getByRole('button', { name: /clusters/i });
    fireEvent.click(clusterTabBtn);

    const copyNodeBtn = await screen.findByRole('button', {
      name: 'Copy connection ticket for alpha',
    });
    fireEvent.click(copyNodeBtn);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith('usr://ticket/mockticket');
    });
  });
});

describe('SystemFleetRegisterPage notification system', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getBackendStatus).mockResolvedValue(mockBackendStatus);
    vi.mocked(getAllBackends).mockResolvedValue(mockAllBackends);
    vi.mocked(getDrives).mockResolvedValue(mockDrives);
    vi.mocked(getSettings).mockResolvedValue(mockSettings);
    vi.mocked(listClusters).mockResolvedValue({ members: [], clusters: [] });
    vi.mocked(listDeployments).mockResolvedValue([]);
    vi.mocked(listWebUIClients).mockResolvedValue([]);
    vi.mocked(getDatabaseOverview).mockResolvedValue(mockDatabaseOverview);
  });

  it('displays toast notifications when telemetry queries fail', async () => {
    vi.mocked(getDatabaseOverview).mockRejectedValue(new Error('Network Error'));
    vi.mocked(getDrives).mockRejectedValue(new Error('Drive failed'));

    renderWithProviders(<SystemFleetRegisterPage />);

    expect(await screen.findByText('Database telemetry unavailable')).toBeInTheDocument();
    expect(await screen.findByText('Network Error')).toBeInTheDocument();
    expect(await screen.findByText('Local storage telemetry unavailable')).toBeInTheDocument();
    expect(await screen.findByText('Drive failed')).toBeInTheDocument();

    const toastContainer = document.body.querySelector('.toast-container');
    expect(toastContainer).not.toBeNull();
  });

  it('suppresses telemetry error toasts while runtime restart is in progress', async () => {
    vi.mocked(controlRuntimePower).mockResolvedValue({ action: 'restart', status: 'accepted', supervisor_pid: 42 });

    renderWithProviders(<SystemFleetRegisterPage />);

    fireEvent.click(await screen.findByRole('button', { name: 'Restart runtime' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Restart runtime' }));

    expect(await screen.findByText('Restarting UltimaScraper')).toBeInTheDocument();
    expect(
      screen.getByText('Every service is stopping and will start again. This page reconnects when the web UI is back.'),
    ).toBeInTheDocument();

    // Telemetry errors should not spawn error toasts while restarting
    expect(screen.queryByText('Database telemetry unavailable')).not.toBeInTheDocument();
    expect(screen.queryByText('Local runtime telemetry unavailable')).not.toBeInTheDocument();
  });
});



