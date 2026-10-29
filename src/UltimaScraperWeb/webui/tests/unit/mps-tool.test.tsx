import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { analyzeMps, createMpsJob, discoverBounds, getSiteBounds, previewMpsProxies } from '../../src/api/mps';
import { MPSTool } from '../../src/features/tools/components/MPSTool';
import type {
  MPSAnalyzeResponse,
  MPSBoundaryDiscoveryResponse,
  MPSCreateJobResponse,
} from '../../src/api/types/mps';
import { renderWithProviders } from './testUtils';

type MockAsyncFunction<T extends (...args: never[]) => Promise<unknown>> = T & {
  mockResolvedValue(value: Awaited<ReturnType<T>>): MockAsyncFunction<T>;
  mockResolvedValueOnce(value: Awaited<ReturnType<T>>): MockAsyncFunction<T>;
};

vi.mock('../../src/api/mps', () => ({
  analyzeMps: vi.fn(),
  createMpsJob: vi.fn(),
  previewMpsProxies: vi.fn(),
  discoverBounds: vi.fn(),
  getSiteBounds: vi.fn(),
}));

vi.mock('../../src/features/jobs/components/JobDetailsModal', () => ({
  JobDetailsModal: ({ job, onClose }: { job: { job_id: string }; onClose: () => void }) => (
    <div role="dialog" aria-label="Job details">
      {job.job_id}<button onClick={onClose}>Close job details</button>
    </div>
  ),
}));

const analysisFixture: MPSAnalyzeResponse = {
  site: 'OnlyFans',
  database_min_id: 1,
  database_max_id: 10_000,
  start_id: 1,
  end_id: 10_000,
  range_size: 10_000,
  existing_user_count: 100,
  invalid_user_count: 0,
  invalid_table_ready: true,
  invalid_eligible_count: 0,
  existing_eligible_count: 50,
  missing_count: 2_000,
  candidate_count: 2_050,
  missing_range_count: 10,
  missing_range_count_exact: true,
  candidate_range_count: 10,
  missing_ranges_truncated: false,
  missing_ranges: [{ start_id: 10, end_id: 20, count: 11 }],
  missing_ids_preview: [10, 11, 12],
  candidate_ranges_preview: [{ start_id: 10, end_id: 20, count: 11 }],
  candidate_ids_preview: [10, 11, 12],
  candidate_preview_truncated: true,
  candidate_offset: 0,
  planned_batch_size: 500,
  planned_candidate_count: 500,
  remaining_candidate_count: 2_050,
  next_candidate_offset: 500,
  has_next_batch: true,
  recommended_batch_size: 1_000,
  batch_recommendations: [
    { batch_size: 250, label: 'Conservative', reason: 'Test carefully.' },
    { batch_size: 1_000, label: 'Balanced', reason: 'Repeatable throughput.' },
  ],
  warnings: [],
  requires_confirmation: false,
};

const createFixture: MPSCreateJobResponse = {
  job: {
    job_id: 'job-123',
    job_name: 'MPS Job',
    status: 'pending',
    created_at: new Date().toISOString(),
    updated_at: null,
    task_count: 500,
    completed_tasks: 0,
    failed_tasks: 0,
    tasks: [],
    task_stats: {
      total: 500,
      ready: 500,
      blocked: 0,
      inflight: 0,
      deferred: 0,
      completed: 0,
      failed: 0,
      task_type_counts: {},
    },
    error_stats: {
      total: 0,
      groups: {},
    },
    created_by: 'webui_mps',
    is_scheduled: false,
    scheduled_for: null,
    interval_seconds: null,
    cron: null,
    run_count: 0,
    last_ran_at: null,
    last_activity_at: null,
    materialization_status: 'queued',
    materialized_tasks: 0,
    materialization_total: 500,
  },
  candidate_offset: 0,
  selected_profiles: 500,
  total_missing_in_range: 2_000,
  total_invalid_eligible_in_range: 0,
  total_existing_eligible_in_range: 50,
  total_candidates_in_range: 2_050,
  remaining_candidate_count: 1_550,
  next_candidate_offset: 500,
  has_next_batch: true,
  recommended_batch_size: 1_000,
  next_batch_size: 500,
  batch_recommendations: analysisFixture.batch_recommendations,
  warnings: [],
  proxies_configured: 5,
  proxies_used: 2,
  direct_connection_included: false,
  proxy_mode: 'unassigned_only',
  proxy_urls_preview: ['socks5://127.0.0.1:9050'],
};

const proxyPreviewFixture = {
  site: 'OnlyFans',
  use_proxies: true,
  proxy_mode: 'unassigned_only' as const,
  proxies_configured: 5,
  proxies_used: 1,
  direct_connection_included: false,
  proxy_urls: ['socks5://127.0.0.1:9050'],
};

const discoveryFixture: MPSBoundaryDiscoveryResponse = {
  site: 'OnlyFans',
  discovered_start_id: 1,
  discovered_end_id: 50_000,
  highest_observed_id: 48_500,
  lowest_observed_id: 1,
  estimated_total_users: 12_500,
  estimated_density: 0.25,
  density_margin_of_error: 0.04,
  confidence_level: 0.95,
  population_confidence_interval: [10_000, 15_000],
  highest_id_confidence_interval: [48_000, 52_000],
  total_probes_used: 42,
  valid_probes_count: 15,
  warnings: [],
  observations: [
    { user_id: 10_000, is_valid: true, phase: 'exponential' },
    { user_id: 20_000, is_valid: true, phase: 'exponential' },
    { user_id: 48_500, is_valid: true, phase: 'refinement' },
    { user_id: 50_000, is_valid: false, phase: 'refinement' },
  ],
};

const analyzeMpsMock = analyzeMps as MockAsyncFunction<typeof analyzeMps>;
const createMpsJobMock = createMpsJob as MockAsyncFunction<typeof createMpsJob>;
const previewMpsProxiesMock = previewMpsProxies as MockAsyncFunction<typeof previewMpsProxies>;

describe('MPSTool', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
    HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
    analyzeMpsMock.mockResolvedValue(analysisFixture);
    createMpsJobMock.mockResolvedValue(createFixture);
    previewMpsProxiesMock.mockResolvedValue(proxyPreviewFixture);
    vi.mocked(getSiteBounds).mockResolvedValue({
      site: 'OnlyFans',
      database_min_id: 1,
      database_max_id: 10_000,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('uses clear defaults for new and missing profile candidates', async () => {
    renderWithProviders(<MPSTool />);

    expect(
      screen.getByRole('checkbox', { name: /new or missing profiles/i }),
    ).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /existing profiles/i })).not.toBeChecked();
    expect(
      screen.getByRole('checkbox', { name: /previously not found profiles/i }),
    ).not.toBeChecked();
    expect(screen.queryByText('Recheck cooldown')).not.toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    await waitFor(() => {
      expect(analyzeMps).toHaveBeenCalledWith(
        expect.objectContaining({
          ignore_missing_ids: false,
          include_invalid: false,
          invalid_last_checked_older_than_hours: null,
          include_existing_users: false,
          existing_last_checked_older_than_hours: null,
          batch_size: null,
        }),
      );
    });
    expect(
      screen.getByLabelText('Max profiles (optional)'),
    ).toHaveValue(25_000);
  });

  it('presents the live candidate analysis as the ID-space map workflow', async () => {
    renderWithProviders(<MPSTool />);

    expect(screen.getByRole('heading', { name: 'ID-space map' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Sources' })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Run' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /existing profiles/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    expect(screen.getByRole('region', { name: 'Provider ID-space map' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Analyze' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Full Analyze' })).toBeInTheDocument();
  });

  it('excludes direct connection from lookup routes by default when proxies are used', async () => {
    previewMpsProxiesMock.mockResolvedValueOnce({
      ...proxyPreviewFixture,
      proxies_configured: 5,
      proxies_used: 2,
    });
    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Configure lookup routes' }));
    expect(await screen.findByText('2 proxies / 5 configured')).toBeInTheDocument();
    expect(screen.queryByText('Direct connection (raw IP)')).not.toBeInTheDocument();
  });

  it('includes direct connection when explicitly checked', async () => {
    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: 'Configure lookup routes' }));
    const directCheckbox = await screen.findByRole('checkbox', {
      name: /include direct connection as fallback route/i,
    });
    expect(directCheckbox).not.toBeChecked();

    previewMpsProxiesMock.mockResolvedValueOnce({
      site: 'OnlyFans',
      use_proxies: true,
      proxy_mode: 'unassigned_only',
      proxies_configured: 5,
      proxies_used: 2,
      direct_connection_included: true,
      proxy_urls: ['socks5://127.0.0.1:9050'],
    });

    fireEvent.click(directCheckbox);

    await waitFor(() => {
      expect(previewMpsProxies).toHaveBeenLastCalledWith(
        expect.objectContaining({
          include_direct_connection: true,
        }),
      );
    });
    expect(await screen.findByText('Direct connection (raw IP)')).toBeInTheDocument();
    expect(screen.getByText('2 proxies + direct / 5 configured')).toBeInTheDocument();
  });

  it('queues a million-profile batch without a limit or blocking confirmation', async () => {
    const confirmMock = vi.fn(() => false);
    vi.stubGlobal('confirm', confirmMock);
    analyzeMpsMock.mockResolvedValueOnce({
      ...analysisFixture,
      range_size: 563_546_692,
      candidate_count: 1_000_000,
      remaining_candidate_count: 1_000_000,
      planned_batch_size: 1_000_000,
      planned_candidate_count: 1_000_000,
      warnings: ['Use a bounded batch unless the full sweep is intentional.'],
      requires_confirmation: true,
    });
    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    const maxProfilesInput = screen.getByLabelText(/max profiles/i);
    expect(maxProfilesInput).not.toHaveAttribute('max');
    fireEvent.change(maxProfilesInput, {
      target: { value: '1000000' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Create Job' }));

    await waitFor(() => {
      expect(createMpsJob).toHaveBeenCalledWith(
        expect.objectContaining({ max_profiles: 1_000_000 }),
      );
    });
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it('requires a candidate source and maps an existing-only refresh to the API', async () => {
    renderWithProviders(<MPSTool />);

    fireEvent.click(screen.getByRole('checkbox', { name: /new or missing profiles/i }));

    expect(screen.getByRole('button', { name: 'Full Analyze' })).toBeDisabled();
    expect(
      screen.getByText(
        'Select new/missing, previously not found, existing profiles, or any combination.',
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: /existing profiles/i }));

    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'weeks' } });
    expect(screen.getByRole('button', { name: 'Full Analyze' })).toBeEnabled();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    await waitFor(() => {
      expect(analyzeMps).toHaveBeenCalledWith(
        expect.objectContaining({
          ignore_missing_ids: true,
          include_invalid: false,
          invalid_last_checked_older_than_hours: null,
          include_existing_users: true,
          existing_last_checked_older_than_hours: 336,
        }),
      );
    });
  });

  it('can analyze only previously not-found profiles with the default seven-day cooldown', async () => {
    analyzeMpsMock.mockResolvedValueOnce({
      ...analysisFixture,
      invalid_user_count: 5,
      invalid_eligible_count: 3,
      missing_count: 0,
      candidate_count: 3,
      missing_range_count: 0,
      candidate_range_count: 2,
      missing_ranges: [],
      missing_ids_preview: [],
      candidate_ranges_preview: [
        { start_id: 42, end_id: 43, count: 2 },
        { start_id: 50, end_id: 50, count: 1 },
      ],
      candidate_ids_preview: [42, 43, 50],
      candidate_preview_truncated: false,
      remaining_candidate_count: 3,
    });
    renderWithProviders(<MPSTool />);

    fireEvent.click(screen.getByRole('checkbox', { name: /new or missing profiles/i }));
    fireEvent.click(screen.getByRole('checkbox', { name: /previously not found profiles/i }));

    expect(screen.getByLabelText('Amount')).toHaveValue(7);
    expect(screen.getByLabelText('Unit')).toHaveValue('days');
    expect(
      screen.getByText('Profiles checked within the last 7 days stay out of this run.'),
    ).toBeInTheDocument();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    await waitFor(() => {
      expect(analyzeMps).toHaveBeenCalledWith(
        expect.objectContaining({
          ignore_missing_ids: true,
          include_invalid: true,
          invalid_last_checked_older_than_hours: 168,
          include_existing_users: false,
          existing_last_checked_older_than_hours: null,
        }),
      );
    });
    expect(screen.getByText('Dense pockets')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /target candidate range 42 - 43/i })).toBeInTheDocument();
    expect(screen.queryByText('Candidate IDs (Preview)')).not.toBeInTheDocument();
    expect(screen.queryByText('42, 43, 50')).not.toBeInTheDocument();
    const adaptiveButton = screen.getByRole('button', {
      name: 'Use adaptive batch size',
    });
    expect(adaptiveButton).toBeEnabled();

    fireEvent.click(adaptiveButton);

    expect(
      screen.getByLabelText('Max profiles (optional)'),
    ).toHaveValue(1_000_000);
  });

  it('keeps the adaptive-batch control visible and applies it when available', async () => {
    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    const adaptiveButton = await screen.findByRole('button', {
      name: 'Use adaptive batch size',
    });
    expect(adaptiveButton).toBeEnabled();
    fireEvent.click(adaptiveButton);

    expect(
      screen.getByPlaceholderText('All candidates (no limit)'),
    ).toHaveValue(25_000);
  });

  it('analyzes the next batch using continuation metadata from the created job', async () => {
    analyzeMpsMock
      .mockResolvedValueOnce(analysisFixture)
      .mockResolvedValueOnce({
        ...analysisFixture,
        candidate_offset: 500,
        remaining_candidate_count: 1_550,
        planned_candidate_count: 500,
        next_candidate_offset: 1_000,
      });
    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    await waitFor(() => {
      expect(analyzeMps).toHaveBeenCalledWith(
        expect.objectContaining({ candidate_offset: 0, batch_size: null }),
      );
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Create Job' })).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText(/max profiles/i), {
      target: { value: '500' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Create Job' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Analyze Next Batch' })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Analyze Next Batch' }));

    await waitFor(() => {
      expect(analyzeMps).toHaveBeenLastCalledWith(
        expect.objectContaining({ candidate_offset: 500, batch_size: 500 }),
      );
    });
  });

  it('queues the next batch directly with the suggested offset', async () => {
    createMpsJobMock
      .mockResolvedValueOnce(createFixture)
      .mockResolvedValueOnce({
        ...createFixture,
        candidate_offset: 500,
        next_candidate_offset: 1_000,
        remaining_candidate_count: 1_050,
      });

    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Create Job' })).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/max profiles/i), {
      target: { value: '500' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Job' }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Queue Next Batch' })).toBeInTheDocument();
    });
    const notification = screen.getByRole('status');
    expect(notification).toHaveTextContent(/Job job-123 accepted\. Materializing 500 profile tasks in the background\./);
    expect(notification.closest('.toast-container')?.parentElement).toBe(document.body);
    expect(document.querySelector('.tools-alert.success')).not.toBeInTheDocument();
    expect(screen.getByText('Materializing')).toBeInTheDocument();
    const pocketsPanel = screen.getByRole('region', { name: 'Candidate range pockets' });
    const runPanel = screen.getByRole('complementary', { name: 'Run' });
    expect(pocketsPanel).toContainElement(screen.getByText('Materializing'));
    expect(pocketsPanel).toContainElement(screen.getByText('Remaining'));
    expect(pocketsPanel).toContainElement(screen.getByText('Next Offset'));
    expect(pocketsPanel).toContainElement(screen.getByRole('button', { name: 'Queue Next Batch' }));
    expect(pocketsPanel).toContainElement(screen.getByRole('button', { name: 'Analyze Next Batch' }));
    expect(runPanel).not.toContainElement(screen.getByText('Next Offset'));
    expect(document.querySelector('.mps-ops-continuation')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Close notification' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.getByText('Materializing')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Queue Next Batch' }));

    await waitFor(() => {
      expect(createMpsJob).toHaveBeenLastCalledWith(
        expect.objectContaining({ candidate_offset: 500, max_profiles: 500 }),
      );
    });
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('1,050 candidate(s) remain'));
  });

  it('queues every remaining candidate when max profiles is blank', async () => {
    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    fireEvent.change(screen.getByLabelText(/max profiles/i), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Job' }));

    await waitFor(() => {
      expect(createMpsJob).toHaveBeenCalledWith(
        expect.objectContaining({
          max_profiles: null,
          max_route_hops: 3,
          conclusive_miss_threshold: 3,
        }),
      );
    });
    expect(createMpsJob).toHaveBeenCalledWith(
      expect.not.objectContaining({ all_remaining: expect.anything() }),
    );
  });

  it('displays configurable thresholds and submits customized threshold values', async () => {
    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: 'Configure lookup routes' }));
    expect(screen.getByText('Configurable Thresholds')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'Lookup routes' })).toBeInTheDocument();

    if (!screen.queryByRole('dialog')) fireEvent.click(screen.getByRole('button', { name: 'Configure lookup routes' }));
    const hopsInput = screen.getByLabelText('Max Route Hops');
    const missThresholdInput = screen.getByLabelText('Conclusive Miss Threshold');

    expect(hopsInput).toHaveValue(3);
    expect(missThresholdInput).toHaveValue(3);

    expect(screen.getByLabelText('Proxy Strategy')).toBeInTheDocument();

    fireEvent.change(hopsInput, { target: { value: '4' } });
    fireEvent.change(missThresholdInput, { target: { value: '2' } });

    expect(hopsInput).toHaveValue(4);
    expect(missThresholdInput).toHaveValue(2);

    fireEvent.click(screen.getByRole('button', { name: 'Close lookup routes' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create Job' }));

    await waitFor(() => {
      expect(createMpsJob).toHaveBeenCalledWith(
        expect.objectContaining({
          max_route_hops: 4,
          conclusive_miss_threshold: 2,
        }),
      );
    });
  });

  it('falls back to default threshold of 3 when threshold inputs are cleared', async () => {
    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    if (!screen.queryByRole('dialog')) fireEvent.click(screen.getByRole('button', { name: 'Configure lookup routes' }));
    const hopsInput = screen.getByLabelText('Max Route Hops');
    const missThresholdInput = screen.getByLabelText('Conclusive Miss Threshold');

    fireEvent.change(hopsInput, { target: { value: '' } });
    fireEvent.change(missThresholdInput, { target: { value: '' } });

    fireEvent.click(screen.getByRole('button', { name: 'Close lookup routes' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create Job' }));

    await waitFor(() => {
      expect(createMpsJob).toHaveBeenCalledWith(
        expect.objectContaining({
          max_route_hops: 3,
          conclusive_miss_threshold: 3,
        }),
      );
    });
  });

  it('automatically prefills max profiles with the adaptive batch recommendation upon analysis', async () => {
    analyzeMpsMock.mockResolvedValueOnce({
      ...analysisFixture,
      range_size: 100_000,
      missing_count: 50_000,
      candidate_count: 50_000,
    });

    renderWithProviders(<MPSTool />);

    // Before analysis, ops panel and max profiles input are not yet displayed
    expect(screen.getByLabelText(/max profiles/i)).toHaveValue(null);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    // After analysis, max profiles is automatically prefilled with adaptive batch (50% missing -> 10,000)
    expect(screen.getByLabelText(/max profiles/i)).toHaveValue(10_000);
  });

  it('preserves manual user overrides to max profiles across re-analysis', async () => {
    renderWithProviders(<MPSTool />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    // Manually set max profiles to custom value
    const maxProfilesInput = screen.getByLabelText(/max profiles/i);
    fireEvent.change(maxProfilesInput, { target: { value: '1234' } });
    expect(maxProfilesInput).toHaveValue(1234);

    // Trigger full analysis
    fireEvent.click(screen.getByRole('button', { name: 'Full Analyze' }));
    await waitFor(() => expect(analyzeMps).toHaveBeenLastCalledWith(expect.objectContaining({ bounded: false })));

    // Manual override must be preserved, not overwritten by adaptive recommendation
    expect(screen.getByLabelText(/max profiles/i)).toHaveValue(1234);
  });

  it('clicking a candidate range chip sets first and last profile IDs', async () => {
    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    // The fixture has candidate_ranges_preview: [{ start_id: 10, end_id: 20, count: 11 }]
    const rangeChipBtn = screen.getByRole('button', {
      name: /target candidate range 10 - 20/i,
    });
    expect(rangeChipBtn).toBeInTheDocument();

    fireEvent.click(rangeChipBtn);
    expect(screen.getByLabelText(/first profile id/i)).toHaveValue(10);
    expect(screen.getByLabelText(/last profile id/i)).toHaveValue(20);
  });

  it('derives adaptive batch sizing from missing density rather than truncated range count', async () => {
    analyzeMpsMock.mockResolvedValueOnce({
      ...analysisFixture,
      range_size: 100_000_000,
      candidate_count: 10_000_000,
      missing_count: 10_000_000,
      missing_range_count: 1000,
      candidate_range_count: 1000,
      candidate_preview_truncated: true,
      candidate_ranges_preview: [{start_id: 581775598, end_id: 593173835, count: 11398238}],
    });
    renderWithProviders(<MPSTool />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    const button = screen.getByRole('button', { name: 'Use adaptive batch size' });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    // 10,000,000 / 100,000,000 = 10% density -> 50,000 profiles
    expect(screen.getByLabelText(/max profiles/i)).toHaveValue(50_000);
    expect(screen.getByText(/Showing complete ranges/)).toBeInTheDocument();
  });

  it('debounces selection edits and analyzes the final boundary', async () => {
    renderWithProviders(<MPSTool />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    const firstId = screen.getByLabelText(/first profile id/i);
    fireEvent.click(screen.getByText('ID boundaries'));
    fireEvent.change(firstId, { target: { value: '100' } });
    fireEvent.change(firstId, { target: { value: '200' } });
    fireEvent.change(firstId, { target: { value: '300' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    expect(analyzeMps).toHaveBeenCalledTimes(2);
    expect(analyzeMps).toHaveBeenLastCalledWith(expect.objectContaining({ start_id: 300, bounded: true }));
  });

  it('ignores an old analysis that finishes after the selection changes', async () => {
    let resolveOld!: (result: MPSAnalyzeResponse) => void;
    vi.mocked(analyzeMps).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    renderWithProviders(<MPSTool />);
    await waitFor(() => expect(analyzeMps).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText(/first profile id/i), { target: { value: '500' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    resolveOld({ ...analysisFixture, candidate_count: 99999999 });
    await waitFor(() => expect(screen.getByLabelText('Max profiles (optional)')).toHaveValue(25_000));
    expect(screen.queryByText('99,999,999')).not.toBeInTheDocument();
  });

  it('runs quick analysis automatically and keeps Full Analyze available', async () => {
    renderWithProviders(<MPSTool />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());
    expect(analyzeMps).toHaveBeenCalledWith(expect.objectContaining({ bounded: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Full Analyze' }));
    await waitFor(() => expect(analyzeMps).toHaveBeenLastCalledWith(expect.objectContaining({ bounded: false })));
  });

  it('displays the spinner on the Full Analyze button when full analysis is running and omits status text', async () => {
    let resolveAnalysis: (val: MPSAnalyzeResponse) => void;
    vi.mocked(analyzeMps)
      .mockResolvedValueOnce(analysisFixture)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveAnalysis = resolve; }));

    renderWithProviders(<MPSTool />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    const fullAnalyzeButton = screen.getByRole('button', { name: 'Full Analyze' });
    expect(fullAnalyzeButton.querySelector('.mps-analysis-spinner')).not.toBeInTheDocument();

    fireEvent.click(fullAnalyzeButton);

    await waitFor(() => expect(fullAnalyzeButton.querySelector('.mps-analysis-spinner')).toBeInTheDocument());
    expect(screen.queryByText('Full analysis running…')).not.toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    resolveAnalysis!(analysisFixture);
    await waitFor(() => expect(fullAnalyzeButton.querySelector('.mps-analysis-spinner')).not.toBeInTheDocument());
    expect(screen.queryByText('Full analysis running…')).not.toBeInTheDocument();
  });

  it('only shows Open Job button after a job is created, and opens the created job', async () => {
    vi.mocked(analyzeMps).mockResolvedValue(analysisFixture);
    vi.mocked(createMpsJob).mockResolvedValue(createFixture);

    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    // Before creating a job, "Open Job" should NOT be shown
    expect(screen.queryByRole('button', { name: 'Open Job' })).not.toBeInTheDocument();

    // Create the job
    fireEvent.click(screen.getByRole('button', { name: 'Create Job' }));

    // After creating the job, "Open Job" should be shown
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Open Job' })).toBeInTheDocument();
    });

    // Invalidate analysis by changing the first profile ID -> "Open Job" disappears
    fireEvent.click(screen.getByRole('button', { name: 'Open Job' }));
    expect(screen.getByRole('dialog', { name: 'Job details' })).toHaveTextContent('job-123');
    fireEvent.click(screen.getByRole('button', { name: 'Close job details' }));
    expect(screen.queryByRole('dialog', { name: 'Job details' })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/first profile id/i), { target: { value: '250' } });
    expect(screen.queryByRole('button', { name: 'Open Job' })).not.toBeInTheDocument();
  });

  it('opens boundary discovery modal, shows live probes and results, and applies boundaries to MPS', async () => {
    vi.mocked(analyzeMps).mockResolvedValue(analysisFixture);
    vi.mocked(discoverBounds).mockResolvedValue(discoveryFixture);

    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    const discoverButton = screen.getByRole('button', { name: 'Discover Boundaries' });
    fireEvent.click(discoverButton);

    // Modal is opened
    expect(
      screen.getByRole('dialog', { name: /discover user id boundaries/i }),
    ).toBeInTheDocument();

    // Opening modal does NOT automatically start discovery
    expect(discoverBounds).not.toHaveBeenCalled();

    // User explicitly starts discovery
    const startDiscoveryButton = screen.getByRole('button', { name: /Start Discovery/i });
    fireEvent.click(startDiscoveryButton);

    await waitFor(() => {
      expect(discoverBounds).toHaveBeenCalledWith({
        site: 'OnlyFans',
        min_id: 10_000,
        max_probes: 50,
      });
    });

    // Modal displays live probe observations and results summary
    await waitFor(() => {
      expect(screen.getByText('✓ Boundary Discovery Complete')).toBeInTheDocument();
      expect(screen.getAllByText(/1 – 50,000/).length).toBeGreaterThan(0);
      expect(screen.getByText(/~12,500/)).toBeInTheDocument();
    });

    // Probe rows are rendered
    expect(screen.getAllByText('48,500').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Valid User ✓').length).toBeGreaterThan(0);
    expect(screen.getByText('Not Found ✗')).toBeInTheDocument();

    // Click Apply to MPS
    const applyButton = screen.getByRole('button', { name: /Apply to MPS/i });
    fireEvent.click(applyButton);

    // Modal closes
    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: /discover user id boundaries/i }),
      ).not.toBeInTheDocument();
    });

    // ID inputs in MPS are populated
    expect(screen.getByLabelText(/first profile id/i)).toHaveValue(1);
    expect(screen.getByLabelText(/last profile id/i)).toHaveValue(50_000);

    expect(
      screen.getByText(/Discovered boundaries for OnlyFans: IDs 1 – 50,000/i),
    ).toBeInTheDocument();
  });

  it('prefills starting ID immediately from getSiteBounds without waiting for analysis to finish', async () => {
    vi.mocked(analyzeMps).mockImplementation(() => new Promise(() => {}));
    vi.mocked(getSiteBounds).mockResolvedValue({
      site: 'OnlyFans',
      database_min_id: 42,
      database_max_id: 88_888,
    });

    renderWithProviders(<MPSTool />);

    // Click discover boundaries before analysis has completed
    fireEvent.click(screen.getByRole('button', { name: 'Discover Boundaries' }));

    // Modal is open immediately
    expect(screen.getByRole('dialog', { name: /discover user id boundaries/i })).toBeInTheDocument();

    // Starting ID is prefilled immediately from database_max_id (88,888) without waiting for analysis
    await waitFor(() => {
      expect(screen.getByTitle(/starting id for exponential discovery/i)).toHaveValue(88_888);
    });
  });

  it('can close the boundary discovery modal without applying', async () => {
    vi.mocked(analyzeMps).mockResolvedValue(analysisFixture);
    vi.mocked(discoverBounds).mockResolvedValue(discoveryFixture);

    renderWithProviders(<MPSTool />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Create Job' })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: 'Discover Boundaries' }));

    expect(
      screen.getByRole('dialog', { name: /discover user id boundaries/i }),
    ).toBeInTheDocument();

    // Click Close
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: /discover user id boundaries/i }),
      ).not.toBeInTheDocument();
    });

    // ID inputs remain unchanged
    expect(screen.getByLabelText(/first profile id/i)).toHaveValue(null);
    expect(screen.getByLabelText(/last profile id/i)).toHaveValue(null);
  });
});

