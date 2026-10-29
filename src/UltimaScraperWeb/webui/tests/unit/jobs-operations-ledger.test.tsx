import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Job } from '../../src/api/types/jobs';
import { JobsOperationsLedger } from '../../src/features/jobs/components/JobsOperationsLedger';

const runningJob: Job = {
  job_id: 'job-running-1234',
  job_name: 'Creator archive refresh',
  job_type: 'scrape_and_download',
  site: 'onlyfans',
  status: 'running',
  priority: -1,
  worker_id: 'worker-09',
  created_at: '2026-08-31T18:42:00Z',
  updated_at: '2026-08-31T18:49:00Z',
  task_count: 10,
  completed_tasks: 6,
  failed_tasks: 0,
  task_stats: {
    total: 10,
    ready: 1,
    blocked: 1,
    inflight: 2,
    deferred: 0,
    completed: 6,
    failed: 0,
    task_type_counts: { scrape_user: 5, download_media: 5 },
  },
  error_stats: { total: 0, groups: {} },
  created_by: 'media-ops',
  is_scheduled: false,
  scheduled_for: null,
  interval_seconds: null,
  cron: null,
  run_count: 1,
  last_ran_at: null,
  last_activity_at: '2026-08-31T18:49:00Z',
};

const failedJob: Job = {
  ...runningJob,
  job_id: 'job-failed-5678',
  job_name: 'Paid message recovery',
  job_type: 'scrape_paid',
  status: 'failed',
  priority: 0,
  worker_id: null,
  task_count: 5,
  completed_tasks: 3,
  failed_tasks: 2,
  task_stats: {
    total: 5,
    ready: 0,
    blocked: 0,
    inflight: 0,
    deferred: 0,
    completed: 3,
    failed: 2,
    task_type_counts: { scrape_paid: 5 },
  },
  error_stats: { total: 2, groups: { expired: 2 } },
  created_by: 'recovery-bot',
  is_scheduled: true,
  interval_seconds: 21600,
  run_count: 4,
};

function renderLedger(overrides: Partial<React.ComponentProps<typeof JobsOperationsLedger>> = {}) {
  const props: React.ComponentProps<typeof JobsOperationsLedger> = {
    jobs: [runningJob, failedJob],
    total: 125,
    page: 1,
    pageSize: 50,
    statusFilter: 'all',
    searchQuery: '',
    onSearchChange: vi.fn(),
    onStatusFilterChange: vi.fn(),
    onPageChange: vi.fn(),
    onPageSizeChange: vi.fn(),
    onJobClick: vi.fn(),
    onPrioritizeJobs: vi.fn(),
    onRetryJobs: vi.fn(),
    onRequestCancelJobs: vi.fn(),
    onRequestDeleteJobs: vi.fn(),
    onRequestDeleteOlderThan: vi.fn(),
    onNewJob: vi.fn(),
    onNotice: vi.fn(),
    ...overrides,
  };

  render(<JobsOperationsLedger {...props} />);
  return props;
}

describe('JobsOperationsLedger', () => {
  it('shows durable deletion stages and committed rows instead of scrape progress', () => {
    renderLedger({ jobs: [{ ...runningJob, status: 'deleting',
      deletion_progress: { completed_stages: 2, total_stages: 9, rows: 2155035, table: 'execution_attempts' } }] });
    const progress = screen.getByRole('progressbar');
    expect(progress).toHaveAttribute('aria-valuenow', '22');
    expect(screen.getByText('2/9')).toBeInTheDocument();
    expect(progress).toHaveAttribute('title', '2/9 stages · 2,155,035 rows removed · execution_attempts');
    expect(progress).toHaveAttribute('aria-valuetext', '2/9 stages · 2,155,035 rows removed · execution_attempts');
    fireEvent.click(screen.getByRole('button', { name: /Actions for Creator archive refresh/i }));
    expect(screen.queryByRole('menuitem', { name: 'Cancel job' })).not.toBeInTheDocument();
  });
  it('shows background materialization progress before execution starts', () => {
    const materializingJob: Job = {
      ...runningJob,
      job_id: 'job-materializing',
      job_name: 'MPS profile sweep',
      status: 'pending',
      task_count: 40_000,
      completed_tasks: 0,
      failed_tasks: 0,
      materialization_status: 'materializing',
      materialized_tasks: 10_000,
      materialization_total: 40_000,
      task_stats: {
        total: 40_000,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 0,
        failed: 0,
        task_type_counts: {},
      },
    };

    renderLedger({ jobs: [materializingJob], total: 1 });

    expect(screen.getByText('Materializing')).toBeInTheDocument();
    expect(
      screen.getByRole('progressbar', { name: /MPS profile sweep progress/i }),
    ).toHaveAttribute('aria-valuenow', '25');
  });

  it('shows finalization progress from prepared task state instead of written records', () => {
    const finalizingJob: Job = {
      ...runningJob,
      job_id: 'job-finalizing',
      job_name: 'MPS finalizing sweep',
      status: 'pending',
      task_count: 40_000,
      completed_tasks: 0,
      failed_tasks: 0,
      materialization_status: 'finalizing',
      materialized_tasks: 40_000,
      materialization_total: 40_000,
      task_stats: {
        total: 40_000,
        ready: 28_000,
        blocked: 0,
        inflight: 0,
        deferred: 2_000,
        completed: 0,
        failed: 0,
        task_type_counts: { scrape: 40_000 },
      },
    };

    renderLedger({ jobs: [finalizingJob], total: 1 });

    expect(screen.getByText('Finalizing')).toBeInTheDocument();
    expect(
      screen.getByRole('progressbar', { name: /MPS finalizing sweep progress/i }),
    ).toHaveAttribute('aria-valuenow', '75');
  });

  it('renders authoritative queue fields and routes primary interactions', () => {
    const props = renderLedger();

    expect(screen.getByRole('heading', { name: 'Operations ledger' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Jobs operations ledger' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Workers' })).toBeInTheDocument();
    expect(screen.getAllByText('OnlyFans')).toHaveLength(2);
    expect(screen.getByText('worker-09')).toBeInTheDocument();
    expect(screen.getByText('Front')).toBeInTheDocument();
    expect(screen.getByText('every 6h')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: /Creator archive refresh progress/i })).toHaveAttribute('aria-valuenow', '60');

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search operations ledger' }), {
      target: { value: 'archive' },
    });
    expect(props.onSearchChange).toHaveBeenCalledWith('archive');

    fireEvent.click(screen.getByRole('button', { name: 'Failed' }));
    expect(props.onStatusFilterChange).toHaveBeenCalledWith('failed');

    fireEvent.click(screen.getByText('Creator archive refresh').closest('button')!);
    expect(props.onJobClick).toHaveBeenCalledWith(runningJob);

    fireEvent.click(screen.getByRole('button', { name: /New job/i }));
    expect(props.onNewJob).toHaveBeenCalledOnce();
  });

  it('provides concise task counts for mobile target details', () => {
    const jobs = [
      {
        ...runningJob,
        task_count: 14_034_000,
        task_stats: { ...runningJob.task_stats!, total: 14_034_000 },
      },
      {
        ...failedJob,
        task_count: 12_930_000,
        task_stats: { ...failedJob.task_stats!, total: 12_930_000 },
      },
    ];

    renderLedger({ jobs, total: jobs.length });

    expect(screen.getByTitle('14,034,000 tasks')).toHaveTextContent('14m tasks');
    expect(screen.getByTitle('12,930,000 tasks')).toHaveTextContent('12.9m tasks');
  });

  it('uses the mock bulk workflow with only backend-supported actions', () => {
    const props = renderLedger();

    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all visible jobs' }));
    expect(screen.getByText('2 jobs selected')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Move to front (1)' }));
    expect(props.onPrioritizeJobs).toHaveBeenCalledWith([runningJob.job_id]);

    fireEvent.click(screen.getByRole('button', { name: 'Retry failed (1)' }));
    expect(props.onRetryJobs).toHaveBeenCalledWith([failedJob.job_id]);

    fireEvent.click(screen.getByRole('button', { name: 'Cancel jobs (1)' }));
    expect(props.onRequestCancelJobs).toHaveBeenCalledWith([runningJob.job_id]);

    fireEvent.click(screen.getByRole('button', { name: 'Delete jobs (2)' }));
    expect(props.onRequestDeleteJobs).toHaveBeenCalledWith([
      runningJob.job_id,
      failedJob.job_id,
    ]);

    fireEvent.click(screen.getByRole('button', { name: 'Delete jobs' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Older than 7 days/ }));
    expect(props.onRequestDeleteOlderThan).toHaveBeenCalledWith(24 * 7);
  });

  it('supports column selection, local filters, sorting, and server pagination', () => {
    const props = renderLedger();

    fireEvent.click(screen.getByRole('button', { name: 'Columns 14' }));
    const columns = screen.getByRole('group', { name: 'Visible columns' });
    fireEvent.click(within(columns).getByRole('checkbox', { name: 'Owner' }));
    expect(screen.queryByRole('columnheader', { name: 'Owner' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Filters' }));
    fireEvent.change(screen.getByLabelText('Schedule'), { target: { value: 'scheduled' } });
    expect(screen.queryByText('Creator archive refresh')).not.toBeInTheDocument();
    expect(screen.getByText('Paid message recovery')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Progress/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Page 2' }));
    expect(props.onPageChange).toHaveBeenCalledWith(2);

    fireEvent.change(screen.getByLabelText('Rows'), { target: { value: '100' } });
    expect(props.onPageSizeChange).toHaveBeenCalledWith(100);
  });

  it('renders active filter chips and allows clearing them via chip click and clear all', () => {
    const onTypeFilterChange = vi.fn();
    const onOwnerFilterChange = vi.fn();
    const onScheduleFilterChange = vi.fn();

    renderLedger({
      typeFilter: 'mass profile scrape',
      onTypeFilterChange,
      ownerFilter: 'operator',
      onOwnerFilterChange,
      scheduleFilter: 'scheduled',
      onScheduleFilterChange,
    });

    const activeGroup = screen.getByRole('group', { name: 'Active filters' });
    expect(activeGroup).toBeInTheDocument();
    expect(within(activeGroup).getByText('mass profile scrape')).toBeInTheDocument();
    expect(within(activeGroup).getByText('operator')).toBeInTheDocument();
    expect(within(activeGroup).getByText('scheduled')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Remove Type: mass profile scrape filter' }));
    expect(onTypeFilterChange).toHaveBeenCalledWith('all');

    fireEvent.click(screen.getByRole('button', { name: 'Clear all' }));
    expect(onTypeFilterChange).toHaveBeenCalledWith('all');
    expect(onOwnerFilterChange).toHaveBeenCalledWith('all');
    expect(onScheduleFilterChange).toHaveBeenCalledWith('all');
  });

  it('offers pause and resume for ledger jobs in the row menu', () => {
    const ledgerJob = { ...runningJob, execution_engine: 'ledger' };
    const pausedJob = { ...runningJob, job_id: 'job-paused-9999', job_name: 'Paused scan',
      execution_engine: 'ledger', status: 'paused' as const };
    const props = renderLedger({ jobs: [ledgerJob, pausedJob, failedJob], onPauseResumeJob: vi.fn() });

    fireEvent.click(screen.getByRole('button', { name: `Actions for ${ledgerJob.job_name}` }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Pause job' }));
    expect(props.onPauseResumeJob).toHaveBeenCalledWith(ledgerJob.job_id, 'pause');

    fireEvent.click(screen.getByRole('button', { name: `Actions for ${pausedJob.job_name}` }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Resume job' }));
    expect(props.onPauseResumeJob).toHaveBeenCalledWith(pausedJob.job_id, 'resume');

    // Not offered for jobs on other engines or for finished jobs.
    fireEvent.click(screen.getByRole('button', { name: `Actions for ${failedJob.job_name}` }));
    expect(screen.queryByRole('menuitem', { name: /Pause job|Resume job/ })).toBeNull();
  });
});
