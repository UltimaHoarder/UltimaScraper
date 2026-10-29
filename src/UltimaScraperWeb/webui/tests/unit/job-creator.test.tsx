import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { JobCreator } from '../../src/components/jobs/JobCreator';
import { getAuthList } from '../../src/api/auths';
import { createJob, getTaskTypes, instantiateTemplate, listTemplates } from '../../src/api/jobs';
import { getSubscriptions } from '../../src/api/subscriptions';
import type { AuthListResponse } from '../../src/api/types/auths';
import type { TaskDefinition } from '../../src/api/types/jobs';
import { renderWithProviders } from './testUtils';

vi.mock('../../src/api/auths', () => ({
  getAuthList: vi.fn(),
}));

vi.mock('../../src/api/jobs', () => ({
  createJob: vi.fn(),
  getTaskTypes: vi.fn(),
  instantiateTemplate: vi.fn(),
  listTemplates: vi.fn(),
}));

vi.mock('../../src/api/subscriptions', () => ({
  getSubscriptions: vi.fn(),
}));

const authResponse: AuthListResponse = {
  success: true,
  total: 1,
  error: undefined,
  auths: [
    {
      id: 1,
      site: 'onlyfans',
      username: 'auth-main',
      user_id: 1001,
      status: 'ok',
      active: true,
      last_tested_at: null,
      created_at: null,
      cookie_preview: null,
      has_authorization: false,
      user_agent_preview: null,
      proxy_id: null,
      worker_shard: 0,
      is_age_verified: true,
      age_verification_required: false,
      spend: false,
      spender_type: null,
    },
  ],
};

const taskTypes: TaskDefinition[] = [
  {
    task_id: 'scrape_user',
    name: 'Scrape User',
    category: 'scrape',
    description: 'Scrape a single performer.',
    keywords: ['scrape'],
    parameters: [
      {
        name: 'site',
        label: 'Site',
        param_type: 'select',
        required: true,
        default: 'onlyfans',
        description: 'Target site',
        options: [
          { label: 'OnlyFans', value: 'onlyfans' },
          { label: 'Fansly', value: 'fansly' },
        ],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
      {
        name: 'username',
        label: 'Username',
        param_type: 'text',
        required: true,
        default: '',
        description: 'Target performer',
        options: [],
        placeholder: 'target-user',
        min_value: null,
        max_value: null,
      },
      {
        name: 'content_types',
        label: 'Content Types',
        param_type: 'multiselect',
        required: false,
        default: ['Posts', 'Messages', 'Stories', 'Highlights', 'ArchivedPosts', 'Profile'],
        description: 'Types of content to scrape',
        options: [
          { label: 'Posts', value: 'Posts' },
          { label: 'Messages', value: 'Messages' },
          { label: 'Stories', value: 'Stories' },
          { label: 'Highlights', value: 'Highlights' },
          { label: 'Archived Posts', value: 'ArchivedPosts' },
          { label: 'Profile', value: 'Profile' },
        ],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
      {
        name: 'download_media',
        label: 'Download Media',
        param_type: 'boolean',
        required: false,
        default: true,
        description: 'Download media files after scraping',
        options: [],
        placeholder: '',
        min_value: null,
        max_value: null,
      },
    ],
  },
];

describe('JobCreator', () => {
  it('creates a job from queued tasks', async () => {
    vi.mocked(getTaskTypes).mockResolvedValue(taskTypes);
    vi.mocked(getAuthList).mockResolvedValue(authResponse);
    vi.mocked(listTemplates).mockResolvedValue([]);
    vi.mocked(getSubscriptions).mockResolvedValue({
      success: true,
      subscriptions: [],
      total: 0,
    });
    vi.mocked(instantiateTemplate).mockResolvedValue({
      job_id: 'template-job',
      job_name: 'Template Job',
      status: 'pending',
      created_at: new Date().toISOString(),
      updated_at: null,
      task_count: 1,
      completed_tasks: 0,
      failed_tasks: 0,
      tasks: [],
      created_by: 'webui',
      is_scheduled: false,
      scheduled_for: null,
      interval_seconds: null,
      cron: null,
      run_count: 0,
      last_ran_at: null,
    });
    vi.mocked(createJob).mockResolvedValue({
      job_id: 'job-123',
      job_name: 'Creator Smoke',
      status: 'pending',
      created_at: new Date().toISOString(),
      updated_at: null,
      task_count: 1,
      completed_tasks: 0,
      failed_tasks: 0,
      tasks: [],
      created_by: 'webui',
      is_scheduled: false,
      scheduled_for: null,
      interval_seconds: null,
      cron: null,
      run_count: 0,
      last_ran_at: null,
    });

    renderWithProviders(<JobCreator />);

    await waitFor(() => {
      expect(screen.getByText('Create New Job')).toBeInTheDocument();
    });

    fireEvent.change(
      screen.getByPlaceholderText('Enter a descriptive name for this job'),
      { target: { value: 'Creator Smoke' } },
    );
    fireEvent.change(screen.getByPlaceholderText('target-user'), {
      target: { value: 'alice' },
    });

    fireEvent.click(screen.getByText('Add Task to Queue'));

    await waitFor(() => {
      expect(screen.getByText('Ready to create job with 1 task')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /create job/i }));

    await waitFor(() => {
      expect(createJob).toHaveBeenCalledWith({
        job_name: 'Creator Smoke',
        created_by: 'webui',
        ignore_space_requirements: true,
        schedule: undefined,
        tasks: [
          {
            task_type: 'scrape_user',
            params: {
              site: 'onlyfans',
              username: 'alice',
              content_types: ['Posts', 'Messages', 'Stories', 'Highlights', 'ArchivedPosts', 'Profile'],
              download_media: true,
              auth_id: 1,
            },
          },
        ],
      });
    });
  });
});
