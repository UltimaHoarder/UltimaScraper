import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { JobDetailsModal } from '../../src/features/jobs/components/JobDetailsModal';
import { getAuthList } from '../../src/api/auths';
import { listProxies } from '../../src/api/network';
import { getJobDetails, getJobRuntimeSamples, getJobTasks, getJobs, retryJob, streamJobTasks, pauseJob, resumeJob } from '../../src/api/jobs';
import type { Job, JobDetail, TaskDetail } from '../../src/api/types/jobs';
import type { NetworkProxy } from '../../src/api/types/network';
import { createTestQueryClient, renderWithProviders } from './testUtils';

vi.mock('../../src/api/auths', () => ({
  getAuthList: vi.fn(),
}));

vi.mock('../../src/api/network', () => ({
  listProxies: vi.fn(),
}));

vi.mock('../../src/api/jobs', () => ({
  cancelJob: vi.fn(),
  pauseJob: vi.fn(),
  resumeJob: vi.fn(),
  createJobTemplateFromJob: vi.fn(),
  getJobDetails: vi.fn(),
  getJobRuntimeSamples: vi.fn(),
  getJobTasks: vi.fn(),
  getJobs: vi.fn(),
  prioritizeJob: vi.fn(),
  retryJob: vi.fn(),
  streamJobTasks: vi.fn(),
  updateJob: vi.fn(),
}));

const jobFixture: Job = {
  job_id: 'job-12345678',
  job_name: 'Nightly Queue',
  status: 'running',
  created_at: new Date().toISOString(),
  updated_at: null,
  task_count: 1,
  completed_tasks: 0,
  failed_tasks: 0,
  tasks: [],
  task_stats: {
    total: 1,
    ready: 1,
    blocked: 0,
    inflight: 0,
    deferred: 0,
    completed: 0,
    failed: 0,
    task_type_counts: { download_media: 1 },
  },
  created_by: 'webui',
  is_scheduled: false,
  scheduled_for: null,
  interval_seconds: null,
  cron: null,
  run_count: 0,
  last_ran_at: null,
};

const detailFixture: JobDetail = {
  job_id: jobFixture.job_id,
  job_name: jobFixture.job_name,
  job_type: 'scrape',
  status: 'running',
  site: 'onlyfans',
  priority: 0,
  worker_id: 'worker-1',
  retries: 0,
  max_retries: 3,
  created_at: jobFixture.created_at,
  started_at: jobFixture.created_at,
  completed_at: null,
  result_success: null,
  result_message: null,
  result_error: null,
  args: { job_name: jobFixture.job_name },
  tasks: [],
  task_stats: jobFixture.task_stats,
  run_count: 1,
  last_ran_at: null,
};

describe('JobDetailsModal', () => {
  it('loads all pages of same-site history for comparison', async () => {
    const historicalJobs = Array.from({ length: 200 }, (_, index) => ({
      ...jobFixture,
      job_id: `historical-${index}`,
      site: 'onlyfans',
    }));
    vi.mocked(getJobs)
      .mockResolvedValueOnce({ jobs: historicalJobs, total: 201, page: 1, page_size: 200 })
      .mockResolvedValueOnce({
        jobs: [{
          ...jobFixture,
          job_id: 'historical-match',
          job_name: 'Matching Historical Run',
          site: 'onlyfans',
          // Only finished runs can be a comparison baseline.
          status: 'completed',
        }],
        total: 201,
        page: 2,
        page_size: 200,
      });
    vi.mocked(getJobDetails).mockResolvedValue({ ...detailFixture, status: 'completed' });
    vi.mocked(getJobRuntimeSamples).mockResolvedValue({
      samples: [],
      next_after_id: null,
      has_more: false,
    });
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal
        job={{ ...jobFixture, status: 'completed', site: 'onlyfans' }}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Diagnostics' }));

    await waitFor(() => expect(getJobs).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    expect(await screen.findByRole('option', { name: /Matching Historical Run/i })).toBeInTheDocument();

    expect(getJobs).toHaveBeenNthCalledWith(
      1,
      undefined,
      1,
      200,
      undefined,
      false,
      false,
      undefined,
      undefined,
      undefined,
      'onlyfans',
    );
    expect(getJobs).toHaveBeenNthCalledWith(
      2,
      undefined,
      2,
      200,
      undefined,
      false,
      false,
      undefined,
      undefined,
      undefined,
      'onlyfans',
    );
  });

  it('keeps the Pipeline modal dimensions when switching to Errors and Config', () => {
    vi.mocked(getJobDetails).mockResolvedValue(detailFixture);
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(<JobDetailsModal job={jobFixture} onClose={() => {}} />);

    const dialog = screen.getByRole('dialog', { name: /Job details:/ });
    vi.spyOn(dialog, 'getBoundingClientRect').mockReturnValue({
      x: 0,
      y: 0,
      width: 1120,
      height: 820,
      top: 0,
      right: 1120,
      bottom: 820,
      left: 0,
      toJSON: () => ({}),
    });

    fireEvent.click(screen.getByRole('tab', { name: /Errors/ }));
    expect(dialog).toHaveStyle({ width: '1120px', height: '820px' });

    fireEvent.click(screen.getByRole('tab', { name: 'Config' }));
    expect(dialog).toHaveStyle({ width: '1120px', height: '820px' });

    fireEvent.click(screen.getByRole('tab', { name: 'Pipeline' }));
    expect(dialog).not.toHaveStyle({ width: '1120px', height: '820px' });
  });

  it('shows cleanup progress immediately when opening a deleting job', () => {
    vi.mocked(getJobDetails).mockReturnValue(new Promise(() => {}));
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(streamJobTasks).mockReturnValue(() => {});
    renderWithProviders(<JobDetailsModal job={{ ...jobFixture, status: 'deleting',
      deletion_progress: { completed_stages: 2, total_stages: 9, rows: 2155035, partitions_dropped: 3, table: 'execution_attempts' },
    }} onClose={() => {}} />);
    const progress = screen.getByRole('progressbar', { name: 'Cleanup stages' });
    expect(progress).toHaveAttribute('value', '2');
    expect(progress).toHaveAttribute('max', '9');
    expect(screen.getByText('2,155,035')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Pipeline' })).not.toBeInTheDocument();
    expect(getJobDetails).not.toHaveBeenCalled();
    expect(screen.getByText('Cleaning execution_attempts')).toBeInTheDocument();
  });
  it.each(['running', 'paused'] as const)('offers the ledger control for a %s run', async (status) => {
    vi.mocked(getJobDetails).mockResolvedValue({ ...detailFixture, status, execution_engine: 'ledger' });
    vi.mocked(getJobTasks).mockResolvedValue({ tasks: [], next_cursor: null, has_more: false, scanned_count: 0, offset: 0, limit: 100 });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(streamJobTasks).mockReturnValue(() => {});
    vi.mocked(pauseJob).mockResolvedValue({ ...jobFixture, status: 'paused', execution_engine: 'ledger' });
    vi.mocked(resumeJob).mockResolvedValue({ ...jobFixture, status: 'running', execution_engine: 'ledger' });
    renderWithProviders(<JobDetailsModal job={{ ...jobFixture, status, execution_engine: 'ledger' }} onClose={() => {}} layout="panel" />);
    const control = await screen.findAllByRole('button', { name: status === 'paused' ? 'Resume Job' : 'Pause Job' });
    fireEvent.click(control[0]);
    await waitFor(() => expect(status === 'paused' ? resumeJob : pauseJob).toHaveBeenCalledWith(jobFixture.job_id));
  });

  it('keeps retained details visible when a live refresh fails', async () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(['jobDetails', jobFixture.job_id], detailFixture);
    vi.mocked(getJobDetails).mockRejectedValue(new Error('temporary refresh failure'));
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal job={jobFixture} onClose={() => {}} layout="panel" />,
      { queryClient },
    );

    expect(
      await screen.findByText('Live refresh failed. Showing the last loaded job details.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('Failed to load job details')).not.toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: /job execution runbook/i })).toBeInTheDocument();
  });

  it('shows materialization progress before task execution starts', async () => {
    const materializingJob: Job = {
      ...jobFixture,
      status: 'pending',
      task_count: 1_000,
      materialization_status: 'materializing',
      materialized_tasks: 250,
      materialization_total: 1_000,
      task_stats: {
        total: 1_000,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 0,
        failed: 0,
        task_type_counts: {},
      },
    };
    vi.mocked(getJobDetails).mockResolvedValue({
      ...detailFixture,
      status: 'pending',
      materialization_status: 'materializing',
      materialized_tasks: 250,
      materialization_total: 1_000,
      task_stats: materializingJob.task_stats,
    });
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({
      success: true,
      total: 0,
      auths: [],
    });
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal
        job={materializingJob}
        onClose={() => {}}
        layout="panel"
      />,
    );

    expect(
      await screen.findByRole('progressbar', { name: 'Job task materialization' }),
    ).toHaveAttribute('aria-valuenow', '25');
    expect(screen.getByText('materializing')).toBeInTheDocument();
    expect(
      await screen.findAllByText('Materializing 250 of 1,000 task records...'),
    ).not.toHaveLength(0);
  });

  it.each([
    { prepared: 1_999, completed: 0, failed: 0, eta: /ETA ~Estimating/ },
    { prepared: 31_920, completed: 0, failed: 0, eta: /ETA ~Estimating/ },
    { prepared: 31_920, completed: 15_960, failed: 0, eta: /ETA ~4m/ },
    { prepared: 31_920, completed: 0, failed: 15_960, eta: /ETA ~4m/ },
  ])('bases rolling-job ETA on terminal tasks with $prepared prepared, $completed completed and $failed failed', async ({ prepared, completed, failed, eta }) => {
    const startedAt = new Date(Date.now() - 240_000).toISOString();
    const rollingJob: Job = {
      ...jobFixture,
      created_at: startedAt,
      task_count: 31_920,
      materialization_status: 'materializing',
      materialized_tasks: prepared,
      materialization_total: 31_920,
      task_stats: {
        total: 31_920, ready: 343, blocked: 0, inflight: 1_656,
        deferred: 0, completed, failed, task_type_counts: { scrape: 31_920 },
      },
    };
    vi.mocked(getJobDetails).mockResolvedValue({
      ...detailFixture,
      created_at: startedAt,
      started_at: startedAt,
      materialization_status: 'materializing',
      materialized_tasks: prepared,
      materialization_total: 31_920,
      task_stats: rollingJob.task_stats,
    });
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [], next_cursor: null, has_more: false,
      scanned_count: 0, offset: 0, limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(<JobDetailsModal job={rollingJob} onClose={() => {}} layout="panel" />);

    expect(await screen.findByRole('progressbar', { name: 'Job task materialization' }))
      .toHaveAttribute('aria-valuenow', String(Math.round(prepared / 31_920 * 100)));
    expect(await screen.findAllByText(eta)).not.toHaveLength(0);
    expect(screen.queryByText('Wrapping up')).not.toBeInTheDocument();
  });

  it('shows a halted materialization as failed when the job has a terminal result error', async () => {
    const haltedJob: Job = {
      ...jobFixture,
      status: 'running',
      task_count: 1_000,
      materialization_status: 'materializing',
      materialized_tasks: 0,
      materialization_total: 1_000,
      task_stats: {
        total: 1_000,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 0,
        failed: 0,
        task_type_counts: {},
      },
    };
    vi.mocked(getJobDetails).mockResolvedValue({
      ...detailFixture,
      status: 'running',
      result_error: 'Scrape failed: Redis could not read database write result abc: No connection available.',
      materialization_status: 'materializing',
      materialized_tasks: 0,
      materialization_total: 1_000,
      task_stats: haltedJob.task_stats,
    });
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal job={haltedJob} onClose={() => {}} layout="panel" />,
    );

    expect(await screen.findByText(/^failed$/)).toBeInTheDocument();
    expect(screen.queryByRole('progressbar', { name: 'Job task materialization' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Materializing 0 of 1,000 task records/)).not.toBeInTheDocument();
  });

  it('distinguishes finalization and reports prepared-task progress', async () => {
    const finalizingJob: Job = {
      ...jobFixture,
      status: 'pending',
      task_count: 1_000,
      materialization_status: 'finalizing',
      materialized_tasks: 1_000,
      materialization_total: 1_000,
      task_stats: {
        total: 1_000,
        ready: 600,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 0,
        failed: 0,
        task_type_counts: { scrape: 1_000 },
      },
    };
    vi.mocked(getJobDetails).mockResolvedValue({
      ...detailFixture,
      status: 'pending',
      materialization_status: 'finalizing',
      materialized_tasks: 1_000,
      materialization_total: 1_000,
      task_stats: finalizingJob.task_stats,
    });
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal job={finalizingJob} onClose={() => {}} layout="panel" />,
    );

    expect(
      await screen.findByRole('progressbar', { name: 'Job task finalization' }),
    ).toHaveAttribute('aria-valuenow', '60');
    expect(screen.getByText('finalizing')).toBeInTheDocument();
    expect(
      await screen.findAllByText(
        'Finalizing 600 of 1,000 task records for execution...',
      ),
    ).not.toHaveLength(0);
  });

  it('labels a task page as loaded rather than the full stage count', async () => {
    const pagedTask: TaskDetail = {
      task_id: 'task-page-1',
      task_type: 'scrape',
      status: 'pending',
      site: 'onlyfans',
      username: '42',
      content_type: 'Profile',
      worker_id: null,
      started_at: null,
      completed_at: null,
      progress: 0,
      items_processed: 0,
      items_total: null,
      error: null,
      result: null,
    };
    const pagedStats = {
      total: 1_000,
      ready: 1_000,
      blocked: 0,
      inflight: 0,
      deferred: 0,
      completed: 0,
      failed: 0,
      task_type_counts: { scrape: 1_000 },
    };
    vi.mocked(getJobDetails).mockResolvedValue({
      ...detailFixture,
      task_stats: pagedStats,
    });
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [pagedTask],
      next_cursor: '1',
      has_more: true,
      scanned_count: 1,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal
        job={{ ...jobFixture, task_count: 1_000, task_stats: pagedStats }}
        onClose={() => {}}
        layout="panel"
      />,
    );

    expect(await screen.findByText('1 loaded of 1,000 tasks')).toBeInTheDocument();
  });

  it('renders streamed task updates when the live task stream emits events', async () => {
    vi.mocked(getJobDetails).mockResolvedValue(detailFixture);
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({
      success: true,
      total: 0,
      auths: [],
    });

    vi.mocked(streamJobTasks).mockImplementation((_jobId, onTask, onDone) => {
      const task: TaskDetail = {
        task_id: 'task-1',
        task_type: 'scrape_user',
        status: 'running',
        site: 'onlyfans',
        username: 'alice',
        content_type: 'Posts',
        worker_id: 'worker-task-17',
        started_at: new Date().toISOString(),
        completed_at: null,
        progress: 0.4,
        items_processed: 4,
        items_total: 10,
        error: null,
        result: null,
      };

      queueMicrotask(() => {
        onTask(task);
        onDone?.();
      });

      return () => {};
    });

    renderWithProviders(
      <JobDetailsModal
        job={jobFixture}
        onClose={() => {}}
        layout="panel"
      />,
    );

    await waitFor(() => {
      expect(getJobDetails).toHaveBeenCalledWith(jobFixture.job_id, false);
    });

    await waitFor(() => {
      expect(screen.getAllByText(/scrape posts/i).length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/current step · scrape/i)).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: /scrape posts progress/i })).toHaveAttribute(
      'aria-valuenow',
      '40',
    );
    expect(screen.getByText('of 10')).toBeInTheDocument();
    expect(screen.getAllByText(/worker-task-17/i).length).toBeGreaterThan(0);
  });

  it('requests filtered task pages when the pipeline filters change', async () => {
    vi.mocked(getJobDetails).mockResolvedValue({
      ...detailFixture,
      status: 'completed',
    });
    vi.mocked(getJobTasks)
      .mockResolvedValueOnce({
        tasks: [
          {
            task_id: 'task-seed',
            task_type: 'download_media',
            status: 'pending',
            site: 'onlyfans',
            username: 'alice',
            content_type: 'Posts',
            payload: null,
            started_at: null,
            completed_at: null,
            progress: 0,
            items_processed: 0,
            items_total: 10,
            error: null,
            result: null,
          },
        ],
        next_cursor: null,
        has_more: false,
        scanned_count: 1,
        offset: 0,
        limit: 100,
      })
      .mockResolvedValue({
        tasks: [],
        next_cursor: null,
        has_more: false,
        scanned_count: 0,
        offset: 0,
        limit: 100,
      });
    vi.mocked(streamJobTasks).mockImplementation(() => () => {});
    vi.mocked(getAuthList).mockResolvedValue({
      success: true,
      total: 0,
      auths: [],
    });

    renderWithProviders(
      <JobDetailsModal
        job={{ ...jobFixture, status: 'completed' }}
        onClose={() => {}}
        layout="panel"
      />,
    );

    await waitFor(() => {
      expect(getJobTasks).toHaveBeenCalledWith(jobFixture.job_id, {
        limit: 100,
        state: undefined,
        task_type: undefined,
        error_only: undefined,
      });
    });
    await waitFor(() => {
      expect(screen.getByLabelText(/task state filter/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/task state filter/i), {
      target: { value: 'failed' },
    });
    fireEvent.change(screen.getByLabelText(/task type filter/i), {
      target: { value: 'download_media' },
    });
    fireEvent.click(screen.getByLabelText(/errors only filter/i));

    await waitFor(() => {
      expect(getJobTasks).toHaveBeenLastCalledWith(jobFixture.job_id, {
        limit: 100,
        state: 'failed',
        task_type: 'download_media',
        error_only: true,
      });
    });
  });

  it('keeps live media telemetry inside the selected download pipeline step', async () => {
    const downloadTask: TaskDetail = {
      task_id: 'task-download',
      task_type: 'download_media',
      status: 'running',
      site: 'onlyfans',
      username: 'alice',
      content_type: 'Posts',
      payload: { auth_id: 101 },
      started_at: new Date().toISOString(),
      completed_at: null,
      progress: 0.3,
      items_processed: 3,
      items_total: 10,
      error: null,
      result: {
        message: 'Downloading 3/10 media files',
        metrics: {
          processed_bytes: 3 * 1024 * 1024,
          total_bytes: 10 * 1024 * 1024,
          speed_bps: 2 * 1024 * 1024,
        },
        output: {
          download_results: [
            {
              media_id: 782,
              status: 'downloaded',
              path: '/archive/alice/posts/782.jpg',
              bytes_written: 1024,
            },
          ],
        },
      },
    };

    vi.mocked(getJobDetails).mockResolvedValue({
      ...detailFixture,
      task_stats: {
        ...jobFixture.task_stats!,
        inflight: 1,
        ready: 0,
      },
    });
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [downloadTask],
      next_cursor: null,
      has_more: false,
      scanned_count: 1,
      offset: 0,
      limit: 100,
    });
    vi.mocked(streamJobTasks).mockImplementation(() => () => {});
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });

    renderWithProviders(
      <JobDetailsModal
        job={jobFixture}
        onClose={() => {}}
        layout="panel"
        liveEvent={{
          type: 'download_progress',
          event: 'download_progress',
          job_id: jobFixture.job_id,
          task_id: downloadTask.task_id,
          media_id: '783',
          path: '/archive/alice/posts/783.mp4',
          status: 'progress',
          processed_bytes: 4 * 1024 * 1024,
          expected_bytes: 10 * 1024 * 1024,
          speed_bps: 2 * 1024 * 1024,
          completed: 3,
          total: 10,
          worker_id: 'worker-9',
        }}
      />,
    );

    expect(await screen.findByLabelText('Selected file transfer')).toBeInTheDocument();
    expect(screen.getAllByText('783.mp4').length).toBeGreaterThan(0);
    expect(screen.getByText(/Posts · #783/i)).toBeInTheDocument();
    expect(screen.getAllByText('downloading').length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText(/Preview of 783.mp4/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText('2.0 MB/s').length).toBeGreaterThan(0);
    expect(screen.getByText('782.jpg')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: /job execution runbook/i })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: /run summary/i })).toBeInTheDocument();
  });

  it('previews completed profile images from the exact task result file', async () => {
    const profileTask: TaskDetail = {
      task_id: 'task-download-profile',
      task_type: 'download_media',
      status: 'completed',
      site: 'onlyfans',
      username: 'alice',
      content_type: 'Profile',
      payload: { auth_id: 101 },
      started_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
      progress: 1,
      items_processed: 2,
      items_total: 2,
      error: null,
      result: {
        message: 'Downloaded 2 profile media',
        output: {
          download_results: [
            {
              media_id: 11240751,
              status: 'downloaded',
              path: '/archive/alice/Profile/Avatars/avatar.jpg',
              bytes_written: 1024,
            },
          ],
        },
      },
    };

    vi.mocked(getJobDetails).mockResolvedValue({
      ...detailFixture,
      task_stats: {
        ...jobFixture.task_stats!,
        ready: 0,
        completed: 1,
      },
    });
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [profileTask],
      next_cursor: null,
      has_more: false,
      scanned_count: 1,
      offset: 0,
      limit: 100,
    });
    vi.mocked(streamJobTasks).mockImplementation(() => () => {});
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });

    const { container } = renderWithProviders(
      <JobDetailsModal job={jobFixture} onClose={() => {}} layout="panel" />,
    );

    expect((await screen.findAllByText('Download Profile')).length).toBeGreaterThan(0);
    const previews = Array.from(
      container.querySelectorAll<HTMLImageElement>('.jdm-runbook-media-preview img'),
    );
    expect(previews.length).toBeGreaterThan(0);
    expect(previews[0].src).toContain(
      `/api/v1/jobs/${jobFixture.job_id}/tasks/${profileTask.task_id}/files/0`,
    );

    fireEvent.error(previews[0]);
    await waitFor(() => {
      expect(previews[0].src).toContain('/api/v1/media/stream/onlyfans/11240751');
    });
  });

  it('turns recorded errors into a cause-scoped recovery console with the real retry scope', async () => {
    const failedJob: Job = {
      ...jobFixture,
      status: 'failed',
      failed_tasks: 1,
      task_stats: {
        ...jobFixture.task_stats!,
        ready: 0,
        failed: 1,
      },
    };
    const failedTask: TaskDetail = {
      task_id: 'task-download-failed',
      task_type: 'download_media',
      status: 'failed',
      site: 'onlyfans',
      username: 'alice',
      content_type: 'Posts',
      payload: { auth_id: 101 },
      started_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
      progress: 0.5,
      items_processed: 1,
      items_total: 2,
      error: 'Download worker stopped after media failures.',
      result: {
        message: 'Transfer stopped after media errors.',
        output: {
          failure_breakdown: {
            url_expired: 1,
            disk_full: 1,
            already_exists: 116,
          },
          download_results: [
            {
              content_id: 8800,
              media_id: 9000,
              status: 'skipped',
              errors: [{ reason: 'already_exists', message: 'File already exists on disk' }],
            },
            {
              content_id: 8801,
              media_id: 9001,
              status: 'failed',
              url: 'https://media.example.test/signed/9001',
              path: '/archive/alice/posts/9001.jpg',
              errors: [
                {
                  reason: 'url_expired',
                  message: 'The source URL expired before transfer started.',
                },
              ],
            },
            {
              content_id: 8802,
              media_id: 9002,
              status: 'failed',
              path: '/archive/alice/posts/9002.mp4',
              errors: [
                {
                  reason: 'disk_full',
                  message: 'The selected destination has insufficient capacity.',
                },
              ],
            },
          ],
        },
      },
    };

    vi.mocked(getJobDetails).mockResolvedValue({
      ...detailFixture,
      status: 'failed',
      completed_at: new Date().toISOString(),
      task_stats: failedJob.task_stats,
    });
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [failedTask],
      next_cursor: null,
      has_more: false,
      scanned_count: 1,
      offset: 0,
      limit: 100,
    });
    vi.mocked(streamJobTasks).mockImplementation(() => () => {});
    vi.mocked(retryJob).mockResolvedValue({
      ...failedJob,
      job_id: 'job-retry-1234',
      job_name: 'Retry: Nightly Queue',
      status: 'pending',
    });
    const onClose = vi.fn();

    renderWithProviders(
      <JobDetailsModal job={failedJob} onClose={onClose} layout="panel" />,
    );

    fireEvent.click(await screen.findByRole('tab', { name: /errors/i }));

    expect(await screen.findByRole('heading', { name: 'Recovery console' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /unclassified/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /inspect posts 8800 media 9000 evidence/i })).not.toBeInTheDocument();
    const expiredCause = screen.getByRole('tab', { name: /signed url expired/i });
    expect(expiredCause).toHaveAttribute('aria-selected', 'false');

    fireEvent.click(expiredCause);

    expect(expiredCause).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByText('URL_EXPIRED').length).toBeGreaterThan(0);
    expect(screen.getByText(/refresh source metadata/i)).toBeInTheDocument();
    expect(screen.getByText(/Posts 8801 · Media 9001/i)).toBeInTheDocument();
    expect(screen.getByText('1 failed task')).toBeInTheDocument();
    expect(screen.getByText('New pending job')).toBeInTheDocument();

    const mediaEvidenceButton = screen.getByRole('button', {
      name: /inspect posts 8801 media 9001 evidence/i,
    });
    expect(mediaEvidenceButton).toHaveAttribute('aria-expanded', 'false');
    expect(
      screen.queryByRole('region', { name: 'Selected affected evidence' }),
    ).not.toBeInTheDocument();

    fireEvent.click(mediaEvidenceButton);

    expect(mediaEvidenceButton).toHaveAttribute('aria-expanded', 'true');
    const evidenceInspector = screen.getByRole('region', {
      name: 'Selected affected evidence',
    });
    expect(within(evidenceInspector).getByText('Content ID')).toBeInTheDocument();
    expect(within(evidenceInspector).getByText('8801')).toBeInTheDocument();
    expect(within(evidenceInspector).getByText('Media ID')).toBeInTheDocument();
    expect(within(evidenceInspector).getByText('9001')).toBeInTheDocument();
    expect(within(evidenceInspector).getByText('Auth ID')).toBeInTheDocument();
    expect(within(evidenceInspector).getByText('101')).toBeInTheDocument();
    expect(
      within(evidenceInspector).getByText(/url_expired: the source url expired/i),
    ).toBeInTheDocument();
    expect(
      within(evidenceInspector).getByRole('link', { name: /open affected source media/i }),
    ).toHaveAttribute('target', '_blank');

    fireEvent.click(within(evidenceInspector).getByText('Raw evidence record'));
    expect(within(evidenceInspector).getByText(/"media_id": 9001/)).toBeInTheDocument();

    fireEvent.click(
      within(evidenceInspector).getByRole('button', { name: 'Close affected evidence' }),
    );
    expect(mediaEvidenceButton).toHaveAttribute('aria-expanded', 'false');
    expect(
      screen.queryByRole('region', { name: 'Selected affected evidence' }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /all failures/i }));
    const taskEvidenceButton = screen.getByRole('button', {
      name: /inspect download media posts task evidence/i,
    });
    fireEvent.click(taskEvidenceButton);

    const taskEvidenceInspector = screen.getByRole('region', {
      name: 'Selected affected evidence',
    });
    expect(within(taskEvidenceInspector).getByText('Task ID')).toBeInTheDocument();
    expect(
      within(taskEvidenceInspector).getByText('task-download-failed'),
    ).toBeInTheDocument();
    expect(
      within(taskEvidenceInspector).getByText('Download worker stopped after media failures.'),
    ).toBeInTheDocument();
    fireEvent.click(
      within(taskEvidenceInspector).getByRole('button', {
        name: 'Close affected evidence',
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Create retry job' }));

    await waitFor(() => {
      expect(retryJob).toHaveBeenCalledWith(failedJob.job_id);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it('renders live ETA timer badge, subtitle metrics, and pipeline ETA for a running job', async () => {
    const startedAt = new Date(Date.now() - 60_000).toISOString();
    const runningDetail: JobDetail = {
      ...detailFixture,
      status: 'running',
      started_at: startedAt,
      completed_at: null,
      task_stats: {
        total: 10,
        ready: 0,
        blocked: 0,
        inflight: 1,
        deferred: 0,
        completed: 4,
        failed: 0,
        task_type_counts: { download_media: 10 },
      },
    };

    const taskFixture: TaskDetail = {
      task_id: 'task-live-1',
      task_type: 'download_media',
      status: 'running',
      site: 'onlyfans',
      username: 'alice',
      content_type: 'Videos',
      worker_id: 'worker-eta-1',
      started_at: startedAt,
      completed_at: null,
      progress: 0.5,
      items_processed: 5,
      items_total: 10,
      error: null,
      result: null,
    };

    vi.mocked(getJobDetails).mockResolvedValue(runningDetail);
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [taskFixture],
      next_cursor: null,
      has_more: false,
      scanned_count: 1,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal
        job={{ ...jobFixture, task_stats: runningDetail.task_stats }}
        onClose={() => {}}
        layout="panel"
      />,
    );

    // Verify subtitle shows Elapsed and ETA
    expect(screen.getByText(/elapsed/i)).toBeInTheDocument();
    expect(screen.getAllByText(/ETA ~/i).length).toBeGreaterThan(0);

    // Verify run summary displays Job ETA
    expect(await screen.findByText('Job ETA')).toBeInTheDocument();
  });

  it('renders subtitle ETA and estimates even when details.started_at is null (falling back to job.created_at)', async () => {
    const runningDetailWithoutStart: JobDetail = {
      ...detailFixture,
      status: 'running',
      started_at: null,
      completed_at: null,
      task_stats: {
        total: 10,
        ready: 0,
        blocked: 0,
        inflight: 1,
        deferred: 0,
        completed: 2,
        failed: 0,
        task_type_counts: { download_media: 10 },
      },
    };

    vi.mocked(getJobDetails).mockResolvedValue(runningDetailWithoutStart);
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal
        job={{
          ...jobFixture,
          created_at: new Date(Date.now() - 30_000).toISOString(),
          task_stats: runningDetailWithoutStart.task_stats,
        }}
        onClose={() => {}}
        layout="panel"
      />,
    );

    // Subtitle should show Elapsed and ETA
    expect(screen.getByText(/elapsed/i)).toBeInTheDocument();
    expect(screen.getAllByText(/ETA ~/i).length).toBeGreaterThan(0);
  });

  it('switches to the Diagnostics tab and renders real-time performance graphs', async () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(['jobDetails', jobFixture.job_id], detailFixture);
    queryClient.setQueryData(['networkProxies'], []);
    vi.mocked(getJobDetails).mockResolvedValue(detailFixture);
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal
        job={jobFixture}
        onClose={() => {}}
      />,
      { queryClient },
    );

    const diagnosticsTab = screen.getByRole('tab', { name: 'Diagnostics' });
    expect(diagnosticsTab).toBeInTheDocument();

    fireEvent.click(diagnosticsTab);

    expect(await screen.findByText('Performance Overview')).toBeInTheDocument();
    expect(screen.getByText(/^[\d,]+ \/ [\d,]+ completed$/)).toBeInTheDocument();
    expect(screen.getByText(/Throughput Velocity \((Items|Tasks)\/sec\)/)).toBeInTheDocument();
    expect(screen.getByText('In-Flight Concurrency vs Route Ceiling')).toBeInTheDocument();
    expect(screen.getByText('HTTP & Proxy Health')).toBeInTheDocument();
  });

  it('correctly filters offline cluster backends and prioritizes settings worker pool size', async () => {
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(['jobDetails', jobFixture.job_id], detailFixture);
    queryClient.setQueryData(['networkProxies'], []);
    queryClient.setQueryData(['settings'], {
      worker_pool: { size: 8 },
    });
    queryClient.setQueryData(['system', 'backend'], {
      backend_id: 'backend-1',
      distributed_mode: true,
      redis_connected: true,
      worker_count: 16,
      active_workers: 0,
      pending_jobs: 0,
      workers: [],
    });
    queryClient.setQueryData(['system', 'all-backends'], {
      success: true,
      local_backend_id: 'backend-1',
      backends: [
        { backend_id: 'backend-1', status: 'online', max_workers: 16 },
        { backend_id: 'backend-dead', status: 'offline', max_workers: 16 },
      ],
    });

    vi.mocked(getJobDetails).mockResolvedValue(detailFixture);
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [],
      next_cursor: null,
      has_more: false,
      scanned_count: 0,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal
        job={jobFixture}
        onClose={() => {}}
      />,
      { queryClient },
    );

    const diagnosticsTab = screen.getByRole('tab', { name: 'Diagnostics' });
    fireEvent.click(diagnosticsTab);

    // The dead backend with 16 is filtered out, and the local backend's stale 16 is overridden by settings size (8)
    expect((await screen.findByText('In Flight')).closest('.jdr-perf-card')).toHaveTextContent('8 workers');
  });

  it('renders proxy card and ordered route fallback hops in pipeline runbook', async () => {
    const queryClient = createTestQueryClient();
    const proxyTask: TaskDetail = {
      started_at: null,
      completed_at: null,
      task_id: 'task-mps-1',
      task_type: 'scrape_profile',
      status: 'completed',
      site: 'onlyfans',
      username: 'onlyfans',
      content_type: 'profile',
      progress: 1,
      items_processed: 1,
      items_total: 1,
      error: null,
      proxy_routes: [
        'http://us.proxy.com:8080',
        'http://de.proxy.com:8080',
        null,
      ],
      proxy_hop_used: 1, // Succeeded on Hop 2 (DE)
      result: {
        output: {
          geo_blocked: true,
        },
      },
    };

    const jobWithProxyTask: Job = {
      ...jobFixture,
      task_count: 1,
      tasks: [
        {
          task_type: 'scrape_profile',
          content_type: 'profile',
          status: 'completed',
          username: 'onlyfans',
          site: 'onlyfans',
          auth_id: null,
          items_processed: 1,
          items_total: 1,
        },
      ],
    };

    const detailWithProxyTask: JobDetail = {
      ...detailFixture,
      tasks: [proxyTask],
    };

    const mockProxies = [
      {
        id: 'p1',
        url: 'http://us.proxy.com:8080',
        username: null,
        max_connections: 10,
        assigned_auths: [],
        group: 'US-East',
        geolocation: {
          ip: '1.2.3.4',
          success: true,
          country: 'United States',
          country_code: 'US',
          flag: { emoji: '🇺🇸' },
        },
      },
      {
        id: 'p2',
        url: 'http://de.proxy.com:8080',
        username: null,
        max_connections: 10,
        assigned_auths: [],
        group: 'EU-West',
        geolocation: {
          ip: '5.6.7.8',
          success: true,
          country: 'Germany',
          country_code: 'DE',
          flag: { emoji: '🇩🇪' },
        },
      },
    ];

    queryClient.setQueryData(['jobDetails', jobWithProxyTask.job_id], detailWithProxyTask);
    queryClient.setQueryData(['networkProxies'], mockProxies);

    vi.mocked(getJobDetails).mockResolvedValue(detailWithProxyTask);
    vi.mocked(listProxies).mockResolvedValue(mockProxies as NetworkProxy[]);
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [proxyTask],
      next_cursor: null,
      has_more: false,
      scanned_count: 1,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal
        job={jobWithProxyTask}
        onClose={() => {}}
      />,
      { queryClient },
    );

    expect(await screen.findByText('3 Hops Evaluated in Order')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Minimum hops used'), {
      target: { value: '3' },
    });
    expect(await screen.findByText('No tasks match the selected task filters.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Minimum hops used'), {
      target: { value: '2' },
    });
    fireEvent.click(screen.getByLabelText('Geo-blocked tasks filter'));

    // 1. Verify 4th summary number card in pipeline (Proxy)
    expect(await screen.findByText('Proxy')).toBeInTheDocument();
    expect(screen.getByText('🇩🇪 Germany')).toBeInTheDocument();
    expect(screen.getByText('Hop 2 of 3')).toBeInTheDocument();

    // 2. Verify ordered route sequence section
    expect(screen.getByText('Proxy Route Sequence')).toBeInTheDocument();
    expect(screen.getByText('3 Hops Evaluated in Order')).toBeInTheDocument();
    expect(screen.getByText('Resolved Hop 2')).toBeInTheDocument();

    // Verify each hop card and status
    expect(screen.getByText('Hop 1')).toBeInTheDocument();
    expect(screen.getByText('Primary')).toBeInTheDocument();
    expect(screen.getByText('us.proxy.com:8080')).toBeInTheDocument();

    expect(screen.getByText('Hop 2')).toBeInTheDocument();
    expect(screen.getByText('Fallback 1')).toBeInTheDocument();
    expect(screen.getByText('de.proxy.com:8080')).toBeInTheDocument();

    expect(screen.getByText('Hop 3')).toBeInTheDocument();
    expect(screen.getByText('Fallback 2 (Direct)')).toBeInTheDocument();
    expect(screen.getByText('Direct Connection')).toBeInTheDocument();

    // 3. Verify compact proxy badge on stage task button
    expect(screen.getByText(/🇩🇪 Hop 2\/3/)).toBeInTheDocument();
  });

  it('displays proxy route and configured route order in error evidence inspector', async () => {
    const queryClient = createTestQueryClient();
    const failedTask: TaskDetail = {
      started_at: null,
      completed_at: null,
      task_id: 'task-err-1',
      task_type: 'scrape_profile',
      status: 'failed',
      site: 'onlyfans',
      username: 'unknownuser',
      content_type: 'profile',
      progress: 0,
      items_processed: 0,
      items_total: 1,
      error: 'Could not resolve user via guest auth across 3 routes',
      proxy_routes: [
        'http://us.proxy.com:8080',
        'http://de.proxy.com:8080',
        null,
      ],
      proxy_hop_used: null,
    };

    const jobWithFailedTask: Job = {
      ...jobFixture,
      status: 'failed',
      task_count: 1,
      failed_tasks: 1,
      tasks: [
        {
          task_type: 'scrape_profile',
          content_type: 'profile',
          status: 'failed',
          username: 'unknownuser',
          site: 'onlyfans',
          auth_id: null,
          items_processed: 0,
          items_total: 1,
        },
      ],
      error_stats: {
        total: 1,
        groups: { 'Could not resolve user via guest auth across 3 routes': 1 },
      },
    };

    const detailWithFailedTask: JobDetail = {
      ...detailFixture,
      status: 'failed',
      tasks: [failedTask],
      error_stats: jobWithFailedTask.error_stats,
    };

    queryClient.setQueryData(['jobDetails', jobWithFailedTask.job_id], detailWithFailedTask);
    queryClient.setQueryData(['networkProxies'], []);

    vi.mocked(getJobDetails).mockResolvedValue(detailWithFailedTask);
    vi.mocked(listProxies).mockResolvedValue([]);
    vi.mocked(getJobTasks).mockResolvedValue({
      tasks: [failedTask],
      next_cursor: null,
      has_more: false,
      scanned_count: 1,
      offset: 0,
      limit: 100,
    });
    vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
    vi.mocked(streamJobTasks).mockReturnValue(() => {});

    renderWithProviders(
      <JobDetailsModal
        job={jobWithFailedTask}
        onClose={() => {}}
      />,
      { queryClient },
    );

    // Switch to Errors tab
    const errorsTab = screen.getByRole('tab', { name: /Errors/ });
    fireEvent.click(errorsTab);

    // Open evidence inspector
    const inspectButton = await screen.findByRole('button', { name: /Inspect.*evidence/i });
    fireEvent.click(inspectButton);

    // Check Proxy route field
    expect(screen.getByText('Proxy route')).toBeInTheDocument();
    expect(screen.getByText('Failed across 3 hops')).toBeInTheDocument();

    // Check Configured route order field
    expect(screen.getByText('Configured route order')).toBeInTheDocument();
    expect(
      screen.getByText(/Hop 1 \(Primary\): http:\/\/us\.proxy\.com:8080 \[failed\] → Hop 2 \(Fallback 1\): http:\/\/de\.proxy\.com:8080 \[failed\] → Hop 3 \(Fallback 2 \(Direct\)\): Direct \[failed\]/),
    ).toBeInTheDocument();
  });
});
