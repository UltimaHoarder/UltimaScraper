import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Job } from '../../src/api/types/jobs';
import { SystemPulseDashboard } from '../../src/features/dashboard/SystemPulseDashboard';
import { Dashboard } from '../../src/themes/ultima-atlas/views/dashboard/Dashboard';
import { renderWithProviders } from './testUtils';

const jobsApi = vi.hoisted(() => ({
  getActiveTasks: vi.fn(),
  getHealth: vi.fn(),
  getJobs: vi.fn(),
  getQueueStats: vi.fn(),
}));
const networkApi = vi.hoisted(() => ({
  listProxies: vi.fn(),
}));
const systemApi = vi.hoisted(() => ({
  getBackendStatus: vi.fn(),
}));
const webSocketHarness = vi.hoisted(() => ({
  options: undefined as unknown,
}));

vi.mock('../../src/api/jobs', () => jobsApi);
vi.mock('../../src/api/network', () => networkApi);
vi.mock('../../src/api/system', () => systemApi);
vi.mock('../../src/hooks/useWebSocket', () => ({
  useWebSocket: (options: unknown) => {
    webSocketHarness.options = options;
    return {
      isConnected: true,
      lastMessage: null,
      lastActivity: Date.now(),
      send: vi.fn(),
      reconnect: vi.fn(),
    };
  },
}));
vi.mock('../../src/themes/ultima-atlas/views/dashboard/InfrastructureScene', () => ({ default: () => null }));

const runningJob: Job = {
  job_id: 'job-running-pulse',
  job_name: 'Creator archive refresh',
  job_type: 'scrape',
  site: 'onlyfans',
  status: 'running',
  worker_id: 'worker-01',
  created_at: '2026-09-01T11:50:00Z',
  updated_at: '2026-09-01T12:00:00Z',
  task_count: 10,
  completed_tasks: 6,
  failed_tasks: 1,
};

const pendingJob: Job = {
  ...runningJob,
  job_id: 'job-pending-pulse',
  job_name: 'Priority subscription refresh',
  status: 'pending',
  worker_id: null,
  completed_tasks: 0,
  failed_tasks: 0,
};

const completedJob: Job = {
  ...runningJob,
  job_id: 'job-complete-pulse',
  job_name: 'Archive sweep',
  status: 'completed',
  completed_tasks: 10,
  failed_tasks: 0,
};

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
  webSocketHarness.options = undefined;
  jobsApi.getQueueStats.mockResolvedValue({
    instance_id: 'backend-pulse',
    distributed_mode: true,
    transitioning: false,
    local_queue_size: 0,
    redis_queue_size: 1,
    active_queue_type: 'redis',
    recovery_interval: 60,
    next_recovery_seconds: 42,
    last_recovery_at: '2026-09-01T11:59:00Z',
  });
  jobsApi.getHealth.mockResolvedValue({
    status: 'healthy',
    instance_id: 'backend-pulse',
    distributed_mode: true,
    transitioning: false,
    queue_type: 'redis',
    queue_size: 1,
    redis_connected: true,
  });
  jobsApi.getJobs.mockResolvedValue({
    jobs: [runningJob, pendingJob, completedJob],
    total: 3,
    page: 1,
    page_size: 200,
  });
  jobsApi.getActiveTasks.mockResolvedValue({
    total: 1,
    tasks: [
      {
        job_id: runningJob.job_id,
        job_name: runningJob.job_name,
        job_status: runningJob.status,
        job_total_tasks: runningJob.task_count,
        task_id: 'task-pulse-1',
        task_type: 'scrape',
        status: 'running',
        site: 'onlyfans',
        username: 'alice',
        content_type: 'Posts',
        started_at: '2026-09-01T11:59:00Z',
        completed_at: null,
        progress: 0.6,
        items_processed: 60,
        items_total: 100,
        items_scraped: 60,
        items_saved: 40,
        bytes_written: null,
        total_bytes: null,
        speed_bps: null,
        avg_speed_bps: null,
        error: null,
      },
    ],
  });
  systemApi.getBackendStatus.mockResolvedValue({
    backend_id: 'backend-pulse',
    distributed_mode: true,
    redis_connected: true,
    worker_count: 2,
    active_workers: 1,
    pending_jobs: 1,
    workers: [
      {
        worker_id: 'worker-01',
        status: 'busy',
        current_job: runningJob.job_id,
        jobs_completed: 12,
      },
      {
        worker_id: 'worker-02',
        status: 'idle',
        current_job: null,
        jobs_completed: 8,
      },
    ],
    system_stats: {
      timestamp: '2026-09-01T12:00:00Z',
      cpu_percent: 37.5,
      cpu_count: 16,
      memory_total: 64_000,
      memory_used: 32_000,
      memory_free: 32_000,
      memory_percent: 50,
      disks: [
        {
          device: 'nvme0n1',
          mount_point: '/data',
          total_bytes: 1_000_000,
          used_bytes: 400_000,
          free_bytes: 600_000,
          percent_used: 40,
          read_bytes_per_sec: 1_024,
          write_bytes_per_sec: 2_048,
        },
      ],
    },
  });
  networkApi.listProxies.mockResolvedValue([
    {
      id: 'proxy-1',
      url: 'http://proxy-one',
      username: null,
      max_connections: 20,
      assigned_auths: [1, 2],
      geolocation: { country: 'United Kingdom', region: 'England' },
    },
    {
      id: 'proxy-2',
      url: 'http://proxy-two',
      username: null,
      max_connections: 10,
      assigned_auths: [3],
      geolocation: { country: 'United States', region: 'Virginia' },
    },
  ]);
});

describe('SystemPulseDashboard', () => {
  it('shows Atlas worker dossiers using reported identity and assignment data', async () => {
    jobsApi.getHealth.mockResolvedValue({ status: 'ok' });
    renderWithProviders(<Dashboard />);
    fireEvent.click(await screen.findByRole('button', { name: 'worker-01: busy' }));
    const dossier = screen.getByRole('region', { name: 'Worker unit details' });
    expect(within(dossier).getByText(runningJob.job_id)).toBeInTheDocument();
    expect(within(dossier).getByText('12')).toBeInTheDocument();
    expect(screen.queryByText('Awaiting operations')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Acquisition pipeline' })).toHaveTextContent('2 units');
    expect(screen.getByText('Systems nominal')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close worker details' }));
    expect(screen.queryByRole('region', { name: 'Worker unit details' })).not.toBeInTheDocument();
  });

  it('shows unknown Atlas metrics when telemetry sources fail', async () => {
    jobsApi.getJobs.mockRejectedValue(new Error('Unavailable'));
    jobsApi.getActiveTasks.mockRejectedValue(new Error('Unavailable'));
    systemApi.getBackendStatus.mockRejectedValue(new Error('Unavailable'));
    renderWithProviders(<Dashboard />);
    await screen.findByText(/Dashboard source unavailable/);
    const metric = screen.getByText('Success rate').closest('article')!;
    expect(within(metric).getByText('--')).toBeInTheDocument();
    expect(screen.queryByText('Systems nominal')).not.toBeInTheDocument();
  });

  it('shows MPS completions when profile tasks turn over with zero item counters', async () => {
    const mpsJob: Job = {
      ...runningJob,
      job_id: 'job-mps',
      job_name: 'Renamed profile sweep',
      created_by: 'webui_mps',
      task_count: 674439,
      completed_tasks: 243775,
      failed_tasks: 0,
    };
    const profile = {
      job_id: mpsJob.job_id,
      task_id: 'profile-first',
      task_type: 'scrape',
      content_type: 'Profile',
      status: 'running',
      items_processed: 0,
      items_scraped: 0,
      items_saved: 0,
    };
    jobsApi.getJobs.mockResolvedValue({ jobs: [mpsJob] });
    jobsApi.getActiveTasks.mockResolvedValue({ total: 1, tasks: [profile] });

    const { queryClient } = renderWithProviders(<SystemPulseDashboard />);
    await screen.findByRole('button', { name: /Renamed profile sweep/i });
    const metric = screen.getByText('Items / sec').closest('article')!;
    const timestamp = queryClient.getQueryState(['pulse-jobs'])!.dataUpdatedAt;
    expect(within(metric).getByText('0')).toBeInTheDocument();

    await act(async () => {
      queryClient.setQueryData(['pulse-jobs'], {
        jobs: [{ ...mpsJob, completed_tasks: mpsJob.completed_tasks + 112 }],
      }, { updatedAt: timestamp + 4000 });
      queryClient.setQueryData(['pulse-active-tasks', false], {
        total: 1, tasks: [{ ...profile, task_id: 'profile-next' }],
      }, { updatedAt: timestamp + 4000 });
    });
    await waitFor(() => expect(within(metric).getByText('28.0')).toBeInTheDocument());

    // A later progress refresh must neither erase the completion rate nor add
    // the same profile again through its individual scrape/save counters.
    await act(async () => {
      queryClient.setQueryData(['pulse-active-tasks', false], {
        total: 1,
        tasks: [{ ...profile, task_id: 'profile-next', items_scraped: 1, items_saved: 1 }],
      }, { updatedAt: timestamp + 8000 });
    });
    await waitFor(() => expect(within(metric).getByText('28.0')).toBeInTheDocument());
  });

  it('maps live backend data into the System Pulse information architecture', async () => {
    renderWithProviders(<SystemPulseDashboard />);

    expect(await screen.findByRole('heading', { name: 'System pulse' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Scraping activity' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Active jobs' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Worker utilization' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Proxy fabric' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Recent events' })).toBeInTheDocument();

    const workerMetric = screen.getByText('Worker load').closest('article');
    const writeMetric = screen.getByText('Write throughput').closest('article');
    const activeJobsMetric = screen.getByText('Active jobs', { selector: 'span' }).closest('article');
    expect(workerMetric).not.toBeNull();
    expect(writeMetric).not.toBeNull();
    expect(activeJobsMetric).not.toBeNull();
    await waitFor(() => {
      expect(within(activeJobsMetric!).getByText('1')).toBeInTheDocument();
      expect(within(workerMetric!).getByText('50.0%')).toBeInTheDocument();
      expect(within(writeMetric!).getByText('2.00 KB/s')).toBeInTheDocument();
      expect(screen.getByText('United Kingdom · England')).toBeInTheDocument();
      expect(screen.getByText(/Creator archive refresh running/i)).toBeInTheDocument();
    });

    const runningJobButton = screen.getByRole('button', { name: /Creator archive refresh/i });
    expect(runningJobButton).toHaveAttribute('aria-pressed', 'true');
    expect(
      screen.getByRole('progressbar', { name: 'Creator archive refresh progress' }),
    ).toHaveAttribute('aria-valuenow', '70');
  });

  it('keeps an active task visible when its job row falls outside the jobs page', async () => {
    jobsApi.getJobs.mockResolvedValue({
      jobs: [completedJob],
      total: 201,
      page: 1,
      page_size: 200,
    });
    jobsApi.getActiveTasks.mockResolvedValue({
      total: 1,
      tasks: [
        {
          job_id: 'job-outside-page',
          job_name: 'Long-running archive',
          job_status: 'running',
          job_total_tasks: 40,
          task_id: 'task-outside-page',
          task_type: 'download',
          status: 'running',
          site: 'onlyfans',
          username: 'alice',
          content_type: 'Posts',
          started_at: '2026-09-01T10:00:00Z',
          completed_at: null,
          progress: 0.25,
          items_processed: 10,
          items_total: 40,
          items_scraped: null,
          items_saved: null,
          bytes_written: 2_048,
          total_bytes: 8_192,
          speed_bps: 1_024,
          avg_speed_bps: 1_024,
          error: null,
        },
      ],
    });

    renderWithProviders(<SystemPulseDashboard />);

    expect(
      await screen.findByRole('button', { name: /Long-running archive/i }),
    ).toBeInTheDocument();
    const activeJobsMetric = screen.getByText('Active jobs', { selector: 'span' }).closest('article');
    expect(activeJobsMetric).not.toBeNull();
    expect(within(activeJobsMetric!).getByText('1')).toBeInTheDocument();
  });

  it('persists the chosen range and can pause the live event stream', async () => {
    renderWithProviders(<SystemPulseDashboard />);
    await screen.findByRole('heading', { name: 'System pulse' });

    fireEvent.click(screen.getByRole('button', { name: '15 min' }));
    expect(screen.getByRole('region', { name: 'System pulse' })).toHaveAttribute(
      'data-pulse-range',
      '15 min',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save view' }));
    expect(window.localStorage.getItem('usr_system_pulse_range')).toBe('15 min');
    expect(screen.getByRole('button', { name: 'View saved' })).toBeInTheDocument();

    const options = webSocketHarness.options as {
      onMessage?: (event: Record<string, unknown>) => void;
    };
    act(() => {
      options.onMessage?.({
        type: 'log',
        level: 'warning',
        message: 'Transfer lane nearing capacity',
        source: 'worker-01',
        category: 'downloads',
        timestamp: '2026-09-01T12:00:01Z',
      });
    });
    expect(screen.getByText('Transfer lane nearing capacity')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    act(() => {
      options.onMessage?.({
        type: 'log',
        level: 'error',
        message: 'This event should remain buffered',
        source: 'worker-02',
        category: 'downloads',
        timestamp: '2026-09-01T12:00:02Z',
      });
    });
    expect(screen.queryByText('This event should remain buffered')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument();
    });
  });
});
