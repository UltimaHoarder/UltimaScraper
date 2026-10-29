import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { JobsPage } from '../../src/themes/ultima-atlas/views/jobs/JobsPage';
import { renderWithProviders } from './testUtils';

const jobsApi = vi.hoisted(() => ({
  cancelJob: vi.fn(),
  deleteJobs: vi.fn(),
  getJobs: vi.fn(),
  prioritizeJob: vi.fn(),
  retryJob: vi.fn(),
}));
const webSocketHarness = vi.hoisted(() => ({
  options: undefined as unknown,
}));

vi.mock('../../src/api/jobs', () => jobsApi);
vi.mock('../../src/components/jobs/JobCreator', () => ({
  JobCreator: () => null,
}));
vi.mock('../../src/features/jobs/components/JobDetailsModal', () => ({
  JobDetailsModal: () => null,
}));
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

beforeEach(() => {
  webSocketHarness.options = undefined;
  jobsApi.getJobs.mockResolvedValue({
    jobs: [],
    total: 0,
    page: 1,
    page_size: 50,
    available_types: ['mass_profile_scrape', 'scrape'],
  });
});

describe('JobsPage live refresh', () => {
  it('hides API commands by default and allows showing them', async () => {
    renderWithProviders(<JobsPage />, { route: '/jobs' });
    await waitFor(() => {
      expect(jobsApi.getJobs).toHaveBeenLastCalledWith(
        undefined,
        1,
        50,
        undefined,
        false,
        false,
        undefined,
        undefined,
        undefined,
      );
    });
    fireEvent.click(screen.getByRole('button', { name: /filters/i }));
    const toggle = screen.getByRole('checkbox', { name: 'Show API commands' });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(jobsApi.getJobs).toHaveBeenLastCalledWith(
        undefined,
        1,
        50,
        undefined,
        false,
        true,
        undefined,
        undefined,
        undefined,
      );
    });
  });

  it('filters by type and resets pagination to page 1', async () => {
    jobsApi.getJobs.mockResolvedValueOnce({
      jobs: [],
      total: 3,
      page: 1,
      page_size: 50,
      available_types: ['mass_profile_scrape', 'scrape'],
    });

    renderWithProviders(<JobsPage />, { route: '/jobs?page=2' });
    await waitFor(() => {
      expect(jobsApi.getJobs).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByRole('button', { name: /filters/i }));
    const typeSelect = screen.getByLabelText('Type');
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'mass profile scrape' })).toBeInTheDocument();
    });
    fireEvent.change(typeSelect, { target: { value: 'mass profile scrape' } });

    await waitFor(() => {
      expect(jobsApi.getJobs).toHaveBeenLastCalledWith(
        undefined,
        1,
        50,
        undefined,
        false,
        false,
        'mass profile scrape',
        undefined,
        undefined,
      );
    });
  });

  it('ignores task/progress event floods and coalesces lifecycle refreshes', async () => {
    renderWithProviders(<JobsPage />, { route: '/jobs' });

    await waitFor(() => {
      expect(jobsApi.getJobs).toHaveBeenCalledTimes(1);
    });

    const options = webSocketHarness.options as {
      onMessage?: (event: Record<string, unknown>) => void;
    };

    act(() => {
      for (let index = 0; index < 25; index += 1) {
        options.onMessage?.({
          event: 'task_progress',
          type: 'task_progress',
          job_id: 'job-mps-live',
          task_id: `task-${index}`,
        });
        options.onMessage?.({
          event: 'task_completed',
          type: 'task_completed',
          job_id: 'job-mps-live',
          task_id: `task-${index}`,
        });
        options.onMessage?.({
          event: 'job_progress',
          type: 'job_progress',
          job_id: 'job-mps-live',
        });
      }
    });

    expect(jobsApi.getJobs).toHaveBeenCalledTimes(1);

    act(() => {
      for (let index = 0; index < 10; index += 1) {
        options.onMessage?.({
          event: 'job_completed',
          type: 'job_completed',
          job_id: 'job-mps-live',
        });
      }
    });

    await waitFor(() => {
      expect(jobsApi.getJobs).toHaveBeenCalledTimes(2);
    });
  });

  it('confirms selected deletion and sends the bulk deletion request', async () => {
    jobsApi.getJobs.mockResolvedValue({
      jobs: [{
        job_id: 'job-delete-1',
        job_name: 'Materializing sweep',
        status: 'pending',
        created_at: '2026-08-31T18:42:00Z',
        updated_at: '2026-08-31T18:49:00Z',
        task_count: 10,
        completed_tasks: 0,
        failed_tasks: 0,
        materialization_status: 'materializing',
        materialized_tasks: 4,
        materialization_total: 10,
      }],
      total: 1,
      page: 1,
      page_size: 50,
    });
    let finishDeletion!: (value: unknown) => void;
    jobsApi.deleteJobs.mockImplementation((_request, onProgress) => {
      onProgress({ completed: 0, total: 1, job_id: 'job-delete-1', status: 'cancelled' });
      onProgress({ completed: 0, total: 1, rows: 25000, table: 'execution_outbox' });
      return new Promise((resolve) => { finishDeletion = resolve; });
    });

    renderWithProviders(<JobsPage />, { route: '/jobs' });

    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: 'Select Materializing sweep' })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Select Materializing sweep' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete jobs (1)' }));

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText(/materializing work is cancelled first/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete jobs' }));

    await waitFor(() => {
      expect(jobsApi.deleteJobs).toHaveBeenCalledWith({ job_ids: ['job-delete-1'] }, expect.any(Function));
    });

    expect(screen.getByRole('progressbar', { name: 'Job deletion progress' })).not.toHaveAttribute('value');
    expect(screen.getByText(/25,000 history rows removed/)).toBeInTheDocument();
    expect(screen.getByText('Cancelled')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toBeDisabled();
    await act(async () => finishDeletion({ requested: 1, deleted: 1, failed: 0, failures: [] }));

    fireEvent.click(screen.getByRole('button', { name: 'Delete jobs' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Older than 7 days/ }));
    const ageDialog = screen.getByRole('dialog');
    expect(within(ageDialog).getByRole('heading', { name: 'Delete jobs older than 7 days?' })).toBeInTheDocument();
    fireEvent.click(within(ageDialog).getByRole('button', { name: 'Cancel' }));
  });
});
