import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getAuthList } from '../../src/api/auths';
import {
  getJobDetails, getJobTasks, getTaskTypes, listTemplates, streamJobTasks, updateJob,
} from '../../src/api/jobs';
import { getSubscriptions } from '../../src/api/subscriptions';
import type { Job, JobDetail, TaskDetail, TaskPageResponse } from '../../src/api/types/jobs';
import { JobDetailsModal } from '../../src/features/jobs/components/JobDetailsModal';
import { renderWithProviders } from './testUtils';

vi.mock('../../src/api/auths', () => ({ getAuthList: vi.fn() }));
vi.mock('../../src/api/subscriptions', () => ({ getSubscriptions: vi.fn() }));
vi.mock('../../src/api/jobs', () => ({
  cancelJob: vi.fn(), createJob: vi.fn(), createJobTemplateFromJob: vi.fn(),
  getJobDetails: vi.fn(), getJobTasks: vi.fn(), getTaskTypes: vi.fn(),
  instantiateTemplate: vi.fn(), listTemplates: vi.fn(), prioritizeJob: vi.fn(),
  retryJob: vi.fn(), streamJobTasks: vi.fn(), updateJob: vi.fn(),
}));

const job: Job = {
  job_id: 'job-edit-mps', job_name: 'MPS selection', status: 'pending',
  created_at: '2026-09-07T00:00:00Z', updated_at: null,
  task_count: 1_000_000, completed_tasks: 0, failed_tasks: 0, tasks: [],
  task_stats: {
    total: 1_000_000, ready: 2, blocked: 0, inflight: 0, deferred: 0,
    completed: 0, failed: 0, task_type_counts: { scrape: 1_000_000 },
  },
  created_by: 'webui_mps', is_scheduled: false,
  scheduled_for: null, interval_seconds: null, cron: null,
  run_count: 0, last_ran_at: null,
};

function task(userId: number): TaskDetail {
  return {
    task_id: `task-${userId}`, task_type: 'scrape_user', status: 'pending',
    site: 'onlyfans', username: `user-${userId}`, content_type: 'Profile',
    payload: {
      site: 'OnlyFans', user_id: userId, username: `user-${userId}`,
      content_types: ['Profile'], use_guest_auth: true,
    },
    started_at: null, completed_at: null, progress: 0,
    items_processed: 0, items_total: 0, error: null, result: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getAuthList).mockResolvedValue({ success: true, total: 0, auths: [] });
  vi.mocked(getTaskTypes).mockResolvedValue([]);
  vi.mocked(listTemplates).mockResolvedValue([]);
  vi.mocked(getSubscriptions).mockResolvedValue({ success: true, total: 0, subscriptions: [] });
  vi.mocked(streamJobTasks).mockReturnValue(() => {});
  vi.mocked(updateJob).mockResolvedValue(job);
});

async function openEditor({
  tasks = [task(41), task(42)], scheduledFor,
}: { tasks?: TaskDetail[]; scheduledFor?: string } = {}) {
  const displayedJob = {
    ...job, is_scheduled: Boolean(scheduledFor), scheduled_for: scheduledFor ?? null,
  };
  const detail: JobDetail = {
    job_id: job.job_id, job_name: job.job_name, job_type: 'mass_profile_scrape',
    status: 'pending', site: 'onlyfans', priority: 0, worker_id: null,
    retries: 0, max_retries: 3, created_at: job.created_at,
    started_at: null, completed_at: null, result_success: null,
    result_message: null, result_error: null,
    args: { mps_manifest: true, schedule: scheduledFor ? { scheduled_for: scheduledFor } : null },
    tasks: [], task_stats: job.task_stats, run_count: 0, last_ran_at: null,
  };
  vi.mocked(getJobDetails).mockResolvedValue(detail);
  vi.mocked(getJobTasks).mockResolvedValue({
    tasks, next_cursor: tasks.length ? String(tasks.length) : null,
    has_more: tasks.length > 0, scanned_count: tasks.length, offset: 0, limit: 100,
  });
  const rendered = renderWithProviders(
    <JobDetailsModal job={displayedJob} onClose={() => {}} layout="panel" />,
  );
  await waitFor(() => expect(getJobTasks).toHaveBeenCalled());
  fireEvent.click(screen.getByRole('tab', { name: 'Config' }));
  const edit = await screen.findByRole('button', { name: 'Edit Job' });
  await waitFor(() => expect(edit).toBeEnabled());
  fireEvent.click(edit);
  await screen.findByPlaceholderText('Enter a descriptive name for this job');
  return rendered;
}

function rename() {
  fireEvent.change(screen.getByPlaceholderText('Enter a descriptive name for this job'), {
    target: { value: 'Renamed selection' },
  });
}

async function save() {
  const saveButton = screen.getByRole('button', { name: /save changes/i });
  expect(saveButton).toBeEnabled();
  fireEvent.click(saveButton);
  await waitFor(() => expect(updateJob).toHaveBeenCalledTimes(1));
  return vi.mocked(updateJob).mock.calls[0][1];
}

describe('MPS job editor requests', () => {
  it('renames a million-task job without replacing the displayed task page', async () => {
    await openEditor();
    rename();
    expect(await save()).toEqual({ job_name: 'Renamed selection' });
  });

  it('allows metadata updates before any tasks have been admitted', async () => {
    await openEditor({ tasks: [] });
    rename();
    expect(await save()).toEqual({ job_name: 'Renamed selection' });
  });

  it('keeps metadata-only changes when the live task page refreshes during editing', async () => {
    const { queryClient } = await openEditor();
    rename();
    await act(async () => {
      queryClient.setQueriesData<TaskPageResponse>(
        { queryKey: ['jobTaskPage', job.job_id] },
        (page) => page && { ...page, tasks: [task(43), task(44)] },
      );
    });
    expect(await save()).toEqual({ job_name: 'Renamed selection' });
  });

  it('preserves an unchanged schedule including its original timestamp precision', async () => {
    await openEditor({ scheduledFor: '2030-01-02T03:04:56.789Z' });
    rename();
    expect(await save()).toEqual({ job_name: 'Renamed selection' });
  });

  it('sends an empty schedule explicitly when scheduling is disabled', async () => {
    await openEditor({ scheduledFor: '2030-01-02T03:04:56.789Z' });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Enable scheduling' }));
    expect(await save()).toEqual({ job_name: job.job_name, schedule: {} });
  });

  it('keeps an explicit task-list edit in the update request', async () => {
    await openEditor();
    fireEvent.click(screen.getAllByTitle('Remove task')[0]);
    expect(await save()).toEqual({
      job_name: job.job_name,
      tasks: [{ task_type: 'scrape_user', params: task(42).payload }],
    });
  });

  it('does not submit an explicitly emptied task list', async () => {
    await openEditor();
    fireEvent.click(screen.getAllByTitle('Remove task')[0]);
    fireEvent.click(screen.getByTitle('Remove task'));
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled();
    expect(updateJob).not.toHaveBeenCalled();
  });
});
