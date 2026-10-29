import { render, screen, fireEvent, renderHook, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { JobDiagnosticsReport } from '../../src/features/jobs/components/JobDiagnosticsReport';
import { computeHistoricalComparison } from '../../src/features/jobs/lib/historicalComparison';
import { computeJobDurationSeconds } from '../../src/features/jobs/lib/jobUtils';
import { useJobDiagnosticsTelemetry } from '../../src/features/jobs/lib/useJobDiagnosticsTelemetry';
import type { JobDiagnosticsTelemetry } from '../../src/features/jobs/lib/useJobDiagnosticsTelemetry';
import type { Job, JobDetail, JobRuntimeSample, TaskDetail } from '../../src/api/types/jobs';
import type { NetworkProxy } from '../../src/api/types/network';
import type { JobEtaResult } from '../../src/features/jobs/lib/jobEta';

it('exports receipt phase coverage and preserves unavailable legacy measurements', () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  const telemetry = {
    ...mockTelemetry,
    finalSummary: {
      ...mockTelemetry.finalSummary,
      writerOperationStats: {
        upsert_user: { count: 20, mean_batch_commands: 50, mean_batch_wall_ms: 100,
          receipt_phases_count: 10, mean_receipt_lock_ms: 1, mean_receipt_read_ms: 2, mean_write_fence_ms: 3 },
        upsert_invalid_user: { count: 5, mean_batch_commands: 20, mean_batch_wall_ms: 60 },
      },
    },
  };
  render(<JobDiagnosticsReport telemetry={telemetry} isLiveJob={false} workerPoolSize={128} />);
  const markdownReportButton = screen.getByRole('button', { name: /Copy Markdown Report/i });
  expect(markdownReportButton).toHaveTextContent('Markdown Report');
  expect(markdownReportButton).not.toHaveTextContent('Copy Markdown Report');
  expect(markdownReportButton.querySelector('.jdr-clipboard-icon')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Download Markdown Report' }).querySelector('.jdr-download-icon')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Diagnostic Bundle/ }).querySelector('.jdr-action-icon')).toBeInTheDocument();
  fireEvent.click(markdownReportButton);
  const markdown = writeText.mock.calls[0][0];
  expect(markdown).toContain('Receipt Lock and Recovery Read Timings');
  expect(markdown).toContain('| `upsert_user` | 10 | 1.00ms | 2.00ms | 3.00ms |');
  expect(markdown).toContain('| `upsert_invalid_user` | 0 | Unavailable | Unavailable | Unavailable |');
});

const mockSnapshots: JobDiagnosticsTelemetry['snapshots'] = [
    {
      timestamp: Date.now() - 60000,
      intervalStartTimestamp: Date.now() - 120000,
      completedDelta: 100,
      itemsDelta: 200,
      itemsAreAuthoritative: true,
      itemsProcessed: 200,
      completedTasks: 100,
      inflightTasks: 75,
      readyTasks: 9000,
      failedTasks: 2,
      throughputItemsPerSec: 38.5,
      throughputTasksPerSec: 19.2,
      p50Latency: 1.85,
      p95Latency: 2.95,
      activeProxies: 75,
      errorCount: 2,
    },
    {
      timestamp: Date.now(),
      intervalStartTimestamp: Date.now() - 60000,
      completedDelta: 120,
      itemsDelta: 250,
      itemsAreAuthoritative: true,
      itemsProcessed: 450,
      completedTasks: 220,
      inflightTasks: 85,
      readyTasks: 8880,
      failedTasks: 4,
      throughputItemsPerSec: 42.8,
      throughputTasksPerSec: 21.4,
      p50Latency: 1.9,
      p95Latency: 3.1,
      activeProxies: 85,
      errorCount: 4,
    },
];

const mockTelemetry: JobDiagnosticsTelemetry = {
  mpsRefillTrace: [],
  snapshots: mockSnapshots,
  chartSnapshots: mockSnapshots,
  throughput: {
    currentItemsPerSec: 42.8,
    currentTasksPerSec: 21.4,
    sma1mItemsPerSec: 40.6,
    sma1mTasksPerSec: 20.3,
    sma5mItemsPerSec: 39.5,
    sma5mTasksPerSec: 19.8,
    trend: 'increasing',
    trendDeltaPercent: 11.2,
    currentSampleDurationSec: 60,
    sma1mWindowSec: 60,
  },
  latencyPercentiles: {
    p50: 1.9,
    p90: 2.45,
    p95: 3.1,
    p99: 4.8,
    sampleCount: 150,
  },
  proxyCapacity: {
    totalRoutes: 108,
    enabledProxies: 107,
    directRoutes: 1,
    activeRoutes: 85,
    utilizationPercent: 78.7,
    isNearCapacity: false,
    isSaturated: false,
  },
  httpDistribution: {
    ok200: 95000,
    rateLimit429: 18,
    forbidden403: 4,
    notFound404: 120,
    serverError5xx: 2,
    timeoutErrors: 6,
    otherErrors: 1,
    totalObserved: 95151,
  },
  errorVelocity: {
    totalErrors: 31,
    errorsLast60s: 2,
    safetyThresholdLimit: 25,
    safetyMarginPercent: 8,
    trend: 'stable',
    rate429Count: 18,
    rate429PerMin: 1.2,
  },
  proxyAnomalies: [
    {
      proxyUrl: 'http://192.168.1.216:8892',
      displayUrl: 'http://192.168.1.216:8892',
      group: 'ProtonVPN',
      country: 'United States',
      countryFlag: '🇺🇸',
      totalAttempts: 450,
      failures: 12,
      rateLimits429: 8,
      timeouts: 4,
      failureRatePercent: 2.7,
      avgLatencySec: 4.2,
      anomalyScore: 86,
      status: 'critical',
      primaryIssue: 'Excessive 429 rate limits (8)',
    },
    {
      proxyUrl: 'http://192.168.1.216:8895',
      displayUrl: 'http://192.168.1.216:8895',
      group: 'ProtonVPN',
      country: 'United States',
      countryFlag: '🇺🇸',
      totalAttempts: 320,
      failures: 3,
      rateLimits429: 0,
      timeouts: 3,
      failureRatePercent: 0.9,
      avgLatencySec: 2.1,
      anomalyScore: 21,
      status: 'degraded',
      primaryIssue: 'Connection timeouts (3)',
    },
  ],
  finalSummary: {
    jobOutcome: 'running',
    totalDurationFormatted: '1h 24m 10s',
    totalDurationSec: 5050,
    overallAvgItemsPerSec: 41.5,
    overallAvgTasksPerSec: 20.8,
    peakItemsPerSec: 46.2,
    efficiencyPercent: 80.7,
    proxyBottleneckFactor: 0.84,
    theoreticalMaxItemsPerSec: 51.4,
    terminationReason: null,
    healthyProxyCount: 105,
    degradedProxyCount: 1,
    criticalProxyCount: 1,
    avgActiveConcurrency: 85,
    avgActiveProxyRoutes: 85,
    avgActiveProxyUtilization: 78.7,
    recommendations: [
      'Capacity Constraint: Worker pool (128) is bounded by proxy capacity (108 routes). Adding ~25 more proxy routes would enable 100% worker utilization.',
      'Route Health: 1 proxy route triggered repeated 429 rate limits.',
    ],
  },
  bottleneckAnalysis: {
    state: 'optimal',
    label: 'Optimal Concurrency',
    explanation:
      'Work is distributed across workers and routes without active queue or capacity contention.',
    rootCauseFindings: [
      'Telemetry indicates healthy operational equilibrium across proxy routes and worker execution.',
    ],
  },
  runningTasksCount: 85,
  readyTasksCount: 8880,
  totalTasksCount: 1057000,
  completedTasksCount: 95000,
  isLive: true,
  lastSampleTime: Date.now(),
};

// Full-job runtime telemetry was recorded, so the report uses measured wording.
const measuredTelemetry: JobDiagnosticsTelemetry = {
  ...mockTelemetry,
  finalSummary: { ...mockTelemetry.finalSummary, runtimeTelemetryComplete: true },
};

function makeComparisonJob(
  jobId: string,
  completedTasks: number,
  failedTasks = 0,
  taskCount = completedTasks + failedTasks,
): Job {
  return {
    job_id: jobId,
    job_name: jobId,
    status: 'completed',
    site: 'OnlyFans',
    created_at: '2026-10-01T12:00:00.000Z',
    started_at: '2026-10-01T12:00:00.000Z',
    completed_at: '2026-10-01T12:01:40.000Z',
    task_count: taskCount,
    completed_tasks: completedTasks,
    failed_tasks: failedTasks,
  } as unknown as Job;
}

function makeComparisonTelemetry(throughputUnit: 'items' | 'tasks', failedTasks = 0): JobDiagnosticsTelemetry {
  return {
    ...mockTelemetry,
    quality: {
      loadedTaskCount: 1000,
      totalTaskCount: 1000,
      coveragePercent: 100,
      isCompleteTaskSample: throughputUnit === 'items',
      throughputUnit,
      peakScope: 'complete_job',
    },
    throughput: { ...mockTelemetry.throughput, throughputUnit },
    errorVelocity: { ...mockTelemetry.errorVelocity, totalErrors: failedTasks },
    totalTasksCount: 1000,
    completedTasksCount: 1000 - failedTasks,
    finalSummary: {
      ...mockTelemetry.finalSummary,
      totalDurationSec: 100,
      totalDurationFormatted: '1m 40s',
      durationSource: 'job_metadata',
    },
  };
}

function renderComparisonView(
  telemetry: JobDiagnosticsTelemetry,
  currentJob: Job,
  baselineJob: Job,
  historicalJobs: Job[] = [baselineJob],
) {
  render(
    <JobDiagnosticsReport
      telemetry={telemetry}
      isLiveJob={false}
      jobId={currentJob.job_id}
      jobName={currentJob.job_name}
      site="OnlyFans"
      currentJob={currentJob}
      historicalJobs={historicalJobs}
      initialBaselineJobId={baselineJob.job_id}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
}

describe('JobDiagnosticsReport', () => {
  it('shows a compact table and marks incomparable throughput as partial', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const baselineJob = makeComparisonJob('baseline', 1000);
    renderComparisonView(makeComparisonTelemetry('items'), currentJob, baselineJob);

    expect(screen.getByRole('table', { name: /selected baseline and the fastest and slowest workload-matched runs/i })).toBeInTheDocument();
    expect(within(screen.getByTestId('comparison-table')).getAllByRole('columnheader').map((header) => header.textContent)).toEqual([
      'Metric', 'Current', 'Baseline', 'Best run', 'Worst run', 'Change',
    ]);
    expect(screen.getByTestId('comparison-status')).toHaveTextContent('Partial');
    expect(screen.getByTestId('comparison-status')).toHaveClass('is-partial');
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('41.5 items/s');
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('10.0 tasks/s');
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('Not comparable');
    expect(screen.getByTestId('comparison-row-failure-rate')).toHaveTextContent('0.0 pp');
    expect(screen.getByTestId('comparison-row-completed-tasks')).toHaveTextContent('0 tasks');
    expect(screen.getByText('0 tasks')).toHaveClass('is-neutral');
    expect(screen.queryByText(/Key Run-to-Run Variance/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId('regression-verdict-banner')).not.toBeInTheDocument();
    expect(screen.queryByTestId('http-proxy-health')).not.toBeInTheDocument();
  });

  it('compares against the fastest and slowest finished runs inside the task boundary', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const baselineJob = makeComparisonJob('baseline', 1000);
    const fastestJob = { ...makeComparisonJob('fastest-run', 1000), duration_seconds: 50 };
    const slowestJob = { ...makeComparisonJob('slowest-run', 1000), duration_seconds: 200 };
    const outsideBoundaryJob = {
      ...makeComparisonJob('outside-boundary-run', 1000),
      task_count: 1200,
      duration_seconds: 1,
    };
    renderComparisonView(
      makeComparisonTelemetry('tasks'),
      currentJob,
      baselineJob,
      [baselineJob, fastestJob, slowestJob, outsideBoundaryJob],
    );

    const throughputRow = screen.getByTestId('comparison-row-throughput');
    expect(throughputRow).toHaveTextContent('20.0 tasks/s');
    expect(throughputRow).toHaveTextContent('fastest-run');
    expect(throughputRow).toHaveTextContent('5.0 tasks/s');
    expect(throughputRow).toHaveTextContent('slowest-run');
    expect(screen.getByTestId('comparison-row-duration')).toHaveTextContent('50s');
    expect(screen.getByTestId('comparison-row-duration')).toHaveTextContent('3m 20s');
    expect(screen.getByTestId('comparison-row-failure-rate')).toHaveTextContent('fastest-run');
    expect(screen.getByTestId('comparison-row-failure-rate')).toHaveTextContent('slowest-run');
    expect(screen.getByTestId('comparison-table')).not.toHaveTextContent('outside-boundary-run');
  });

  it('excludes cancelled jobs from best and worst run extremes', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const baselineJob = makeComparisonJob('baseline', 1000);
    // Cancelled jobs that would otherwise be best (100 tasks/s) or worst (2 tasks/s)
    const cancelledFastJob = {
      ...makeComparisonJob('cancelled-fast-run', 1000),
      duration_seconds: 10,
      status: 'cancelled' as const,
    };
    const cancelledSlowJob = {
      ...makeComparisonJob('cancelled-slow-run', 1000),
      duration_seconds: 500,
      status: 'cancelled' as const,
    };
    // Valid completed runs
    const normalBestJob = {
      ...makeComparisonJob('normal-best-run', 1000),
      duration_seconds: 50,
      status: 'completed' as const,
    };
    const normalWorstJob = {
      ...makeComparisonJob('normal-worst-run', 1000),
      duration_seconds: 200,
      status: 'completed' as const,
    };

    renderComparisonView(
      makeComparisonTelemetry('tasks'),
      currentJob,
      baselineJob,
      [baselineJob, cancelledFastJob, cancelledSlowJob, normalBestJob, normalWorstJob],
    );

    const throughputRow = screen.getByTestId('comparison-row-throughput');
    // Must select normal-best-run and normal-worst-run, NOT cancelled jobs
    expect(throughputRow).toHaveTextContent('normal-best-run');
    expect(throughputRow).toHaveTextContent('20.0 tasks/s');
    expect(throughputRow).toHaveTextContent('normal-worst-run');
    expect(throughputRow).toHaveTextContent('5.0 tasks/s');
    expect(screen.getByTestId('comparison-table')).not.toHaveTextContent('cancelled-fast-run');
    expect(screen.getByTestId('comparison-table')).not.toHaveTextContent('cancelled-slow-run');
  });

  it('excludes running jobs from the baseline selector and comparison', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const completedBaselineJob = {
      ...makeComparisonJob('completed-baseline', 1000),
      duration_seconds: 100,
    };
    const runningJob = {
      ...makeComparisonJob('running-job-1', 1000),
      status: 'running' as const,
      completed_at: null,
    };
    const pendingJob = {
      ...makeComparisonJob('pending-job-2', 1000),
      status: 'pending' as const,
      completed_at: null,
    };

    render(
      <JobDiagnosticsReport
        telemetry={makeComparisonTelemetry('tasks')}
        isLiveJob={false}
        jobId={currentJob.job_id}
        jobName={currentJob.job_name}
        site="OnlyFans"
        currentJob={currentJob}
        historicalJobs={[runningJob, pendingJob, completedBaselineJob]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));

    const baselineSelect = screen.getByLabelText(/Select baseline historical run for comparison/i) as HTMLSelectElement;
    // Running and pending jobs should not be options in the baseline dropdown
    const optionValues = Array.from(baselineSelect.options).map((o) => o.value);
    expect(optionValues).not.toContain('running-job-1');
    expect(optionValues).not.toContain('pending-job-2');
    expect(optionValues).toContain('completed-baseline');

    // Default selected baseline must be the completed job, not the running job
    expect(baselineSelect.value).toBe('completed-baseline');

    // computeHistoricalComparison must return null if given a running job
    expect(computeHistoricalComparison(
      makeComparisonTelemetry('tasks'),
      'current',
      'current',
      'OnlyFans',
      false,
      runningJob,
    )).toBeNull();
  });

  it('does not select a running job even when initialBaselineJobId explicitly specifies it', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const completedBaselineJob = {
      ...makeComparisonJob('completed-baseline', 1000),
      duration_seconds: 100,
    };
    const runningJob = {
      ...makeComparisonJob('running-job-1', 1000),
      status: 'running' as const,
      completed_at: null,
    };

    render(
      <JobDiagnosticsReport
        telemetry={makeComparisonTelemetry('tasks')}
        isLiveJob={false}
        jobId={currentJob.job_id}
        jobName={currentJob.job_name}
        site="OnlyFans"
        currentJob={currentJob}
        historicalJobs={[runningJob, completedBaselineJob]}
        initialBaselineJobId="running-job-1"
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));

    const baselineSelect = screen.getByLabelText(/Select baseline historical run for comparison/i) as HTMLSelectElement;
    // Must fall back to completed-baseline, NOT select the running job
    expect(baselineSelect.value).toBe('completed-baseline');
  });

  it('renders empty historical jobs state when all historical jobs are running', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const runningJob = {
      ...makeComparisonJob('running-job-1', 1000),
      status: 'running' as const,
      completed_at: null,
    };

    render(
      <JobDiagnosticsReport
        telemetry={makeComparisonTelemetry('tasks')}
        isLiveJob={false}
        jobId={currentJob.job_id}
        jobName={currentJob.job_name}
        site="OnlyFans"
        currentJob={currentJob}
        historicalJobs={[runningJob]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));

    const baselineSelect = screen.getByLabelText(/Select baseline historical run for comparison/i) as HTMLSelectElement;
    expect(baselineSelect.value).toBe('');
    expect(screen.getByText('No historical runs available')).toBeInTheDocument();
    expect(screen.queryByTestId('comparison-table')).not.toBeInTheDocument();
  });

  it('shows the selected baseline average on the throughput graph only in Compare view', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const baselineJob = makeComparisonJob('baseline', 1000);
    const startTimestamp = Date.parse(currentJob.started_at!);
    const telemetry = {
      ...makeComparisonTelemetry('tasks'),
      chartSnapshots: mockSnapshots.map((snapshot, index) => ({
        ...snapshot,
        timestamp: startTimestamp + (index + 1) * 50_000,
        intervalStartTimestamp: startTimestamp + index * 50_000,
      })),
    };
    renderComparisonView(telemetry, currentJob, baselineJob);

    expect(screen.getByText(/Baseline avg \(10(?:\.0)?\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Best avg/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Worst avg/)).not.toBeInTheDocument();
    expect(screen.queryByTestId('http-proxy-health')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Telemetry$/i }));

    expect(screen.queryByText(/Baseline avg/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Best avg|Worst avg/)).not.toBeInTheDocument();
    const httpReport = screen.getByTestId('http-proxy-health');
    expect(httpReport.closest('.jdr-collapsible-stack')).toBeNull();
  });

  it('shows distinct best and worst historical averages on the throughput graph', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const baselineJob = makeComparisonJob('baseline', 1000);
    const fastestJob = { ...makeComparisonJob('fastest-run', 1000), duration_seconds: 50 };
    const slowestJob = { ...makeComparisonJob('slowest-run', 1000), duration_seconds: 200 };
    const startTimestamp = Date.parse(currentJob.started_at!);
    const telemetry = {
      ...makeComparisonTelemetry('tasks'),
      chartSnapshots: mockSnapshots.map((snapshot, index) => ({
        ...snapshot,
        timestamp: startTimestamp + (index + 1) * 50_000,
        intervalStartTimestamp: startTimestamp + index * 50_000,
      })),
    };

    renderComparisonView(
      telemetry,
      currentJob,
      baselineJob,
      [baselineJob, fastestJob, slowestJob],
    );

    expect(screen.getByText(/Baseline avg \(10(?:\.0)?\)/)).toBeInTheDocument();
    expect(screen.getByText(/Best avg \(20(?:\.0)?\)/)).toBeInTheDocument();
    expect(screen.getByText(/Worst avg \(5(?:\.0)?\)/)).toBeInTheDocument();
  });

  it('does not mix historical task rates into an item-rate throughput graph', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const baselineJob = makeComparisonJob('baseline', 1000);
    renderComparisonView(
      { ...makeComparisonTelemetry('items'), jobRuntimeSamples: [] },
      currentJob,
      baselineJob,
    );

    expect(screen.getByText('Throughput Velocity (Items/sec)')).toBeInTheDocument();
    expect(screen.queryByText(/Baseline avg|Best avg|Worst avg/)).not.toBeInTheDocument();
  });

  it('expands a chart and hides only its paired chart until collapsed', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const baselineJob = makeComparisonJob('baseline', 1000);
    renderComparisonView(makeComparisonTelemetry('tasks'), currentJob, baselineJob);

    const throughputCard = screen.getByText(/Throughput Velocity \(Tasks\/sec\)/).closest('.jdr-chart-card');
    const expandButton = screen.getByRole('button', { name: /Expand Throughput Velocity/ });
    expect(throughputCard).not.toHaveClass('is-expanded');

    fireEvent.click(expandButton);

    expect(throughputCard).toHaveClass('is-expanded');
    expect(screen.getByRole('button', { name: /Collapse Throughput Velocity/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('In-Flight Concurrency vs Route Ceiling').closest('.jdr-chart-card')).toHaveAttribute('hidden');
    expect(screen.getByText('Latency Percentiles (Seconds)').closest('.jdr-chart-card')).not.toHaveAttribute('hidden');

    fireEvent.click(screen.getByRole('button', { name: /Collapse Throughput Velocity/ }));

    expect(throughputCard).not.toHaveClass('is-expanded');
    expect(screen.getByText('In-Flight Concurrency vs Route Ceiling').closest('.jdr-chart-card')).not.toHaveAttribute('hidden');
  });

  it('keeps a regression verdict when failure rate independently regresses', () => {
    const currentJob = makeComparisonJob('current', 950, 50);
    const baselineJob = makeComparisonJob('baseline', 1000);
    renderComparisonView(makeComparisonTelemetry('items', 50), currentJob, baselineJob);

    expect(screen.getByTestId('comparison-status')).toHaveTextContent('Regression');
    expect(screen.getByTestId('comparison-status')).toHaveClass('is-regression');
    expect(screen.getByText('+5.0 pp')).toHaveClass('is-negative');
  });

  it('does not report a throughput delta against a zero-rate baseline', () => {
    const currentJob = makeComparisonJob('current', 1000);
    const baselineJob = makeComparisonJob('baseline', 0, 0, 1000);
    renderComparisonView(makeComparisonTelemetry('tasks'), currentJob, baselineJob);

    expect(screen.getByTestId('comparison-status')).toHaveTextContent('Partial');
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('20.8 tasks/s');
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('0.0 tasks/s');
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('Unavailable');
    expect(screen.getByTestId('comparison-row-throughput')).not.toHaveTextContent('%');
  });

  it('renders executive KPI cards answering core questions', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );

    const overview = screen.getByTestId('performance-overview');
    expect(overview).toHaveTextContent('42.8');
    expect(overview).toHaveTextContent('items/s');
    expect(screen.getByText('Throughput').closest('.jdr-perf-card')).toHaveTextContent('Live');
    expect(screen.getByText('In Flight').closest('.jdr-perf-card')).toHaveTextContent('85');
    expect(screen.getByRole('meter', { name: 'Live proxy utilization' })).toHaveAttribute('aria-valuenow', '78.7');
    expect(overview).toHaveTextContent('85 / 108 slots');
    expect(overview).toHaveTextContent('1.9s');
    expect(overview).toHaveTextContent('p95: 3.1s');
    expect(overview).toHaveTextContent('31 Failures');
    expect(overview).toHaveTextContent('2 / 25 limit in 60s');
  });

  it('uses the full-runtime scope even when only one task page is loaded', () => {
    render(<JobDiagnosticsReport isLiveJob={false} telemetry={{
      ...mockTelemetry,
      quality: { loadedTaskCount: 100, totalTaskCount: 10000, coveragePercent: 1,
        isCompleteTaskSample: false, throughputUnit: 'tasks', peakScope: 'loaded_sample' },
      finalSummary: { ...mockTelemetry.finalSummary, runtimeTelemetryComplete: true },
    }} />);
    expect(screen.getByText('Active-Window Efficiency').closest('.jdr-perf-card')).not.toHaveAttribute('title');
    fireEvent.focus(screen.getByRole('button', { name: 'Model efficiency methodology' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent('Full-job runtime aggregates');
    expect(screen.getByRole('tooltip')).not.toHaveTextContent('100 loaded tasks');
  });

  it('keeps the tooltip outside the scroll container and clamps it to the viewport', () => {
    const rectSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('jdr-info-popover')) {
        return { left: 0, right: 340, top: 0, bottom: 150, width: 340, height: 150, x: 0, y: 0, toJSON() {} };
      }
      return { left: window.innerWidth - 16, right: window.innerWidth, top: 20, bottom: 36, width: 16, height: 16, x: window.innerWidth - 16, y: 20, toJSON() {} };
    });
    try {
      const { container } = render(<JobDiagnosticsReport telemetry={mockTelemetry} isLiveJob={false} />);
      fireEvent.focus(screen.getByRole('button', { name: 'Worker occupancy methodology' }));
      const popup = screen.getByRole('tooltip');
      expect(container.contains(popup)).toBe(false);
      expect(popup).toHaveStyle({ position: 'fixed', left: `${window.innerWidth - 348}px` });
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    } finally {
      rectSpy.mockRestore();
    }
  });

  it('renders all four real-time performance line graphs', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );

    // Graph 1: Throughput
    expect(screen.getByText('Throughput Velocity (Items/sec)')).toBeInTheDocument();

    // Graph 2: Concurrency & Route Ceiling
    expect(
      screen.getByText('In-Flight Concurrency vs Route Ceiling'),
    ).toBeInTheDocument();

    // Graph 3: Latency Profile
    expect(screen.getByText('Latency Percentiles (Seconds)')).toBeInTheDocument();

    // Graph 4: Errors
    expect(screen.getByText('Error Accumulation Stream')).toBeInTheDocument();
  });

  it('renders HTTP response distribution percentages and counts (Q4)', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );

    expect(screen.getByText(/HTTP & Proxy Health/i)).toBeInTheDocument();
    expect(screen.getByText(/200 OK/i)).toBeInTheDocument();
    expect(screen.getAllByText(/429 Rate Limit/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/403 Forbidden/i)).toBeInTheDocument();
    expect(screen.getByText(/404 Not Found/i)).toBeInTheDocument();
    expect(screen.getByText(/5xx Errors/i)).toBeInTheDocument();
    expect(screen.getAllByText('Timeouts').length).toBeGreaterThan(0);
    expect(screen.getByTestId('http-proxy-health').querySelector('.jdr-proxy-table')).not.toBeNull();
  });

  it('renders problematic proxy outlier anomaly table (Q9)', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );

    expect(screen.getByText(/HTTP & Proxy Health/i)).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Timeouts/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Timeouts \(2\)/i })).toBeInTheDocument();
    expect(screen.getByText('http://192.168.1.216:8892')).toBeInTheDocument();
    expect(screen.getByText('http://192.168.1.216:8895')).toBeInTheDocument();
    expect(screen.getByText(/Excessive 429 rate limits \(8\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Connection timeouts \(3\)/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Copy Problematic Proxies/i })).toBeInTheDocument();
  });

  it('filters and sorts proxy table by timeouts', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );

    const timeoutsFilterBtn = screen.getByRole('button', { name: /Timeouts \(2\)/i });
    expect(timeoutsFilterBtn).toBeInTheDocument();
    fireEvent.click(timeoutsFilterBtn);

    expect(screen.getByText('http://192.168.1.216:8892')).toBeInTheDocument();
    expect(screen.getByText('http://192.168.1.216:8895')).toBeInTheDocument();

    const sortSelect = screen.getByLabelText(/Sort proxy anomalies by/i);
    fireEvent.change(sortSelect, { target: { value: 'timeouts' } });
    expect((sortSelect as HTMLSelectElement).value).toBe('timeouts');
  });

  it('copies problematic proxies to clipboard on button click', () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockImplementation(() => Promise.resolve()),
      },
    });
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );
    const copyButton = screen.getByRole('button', { name: /Copy Problematic Proxies/i });
    fireEvent.click(copyButton);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      'http://192.168.1.216:8892\nhttp://192.168.1.216:8895',
    );
  });

  it('renders Final Run Report verdict, efficiency, and removes recommendations from UI', () => {
    render(
      <JobDiagnosticsReport
        telemetry={measuredTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName="MPS Scrape Job"
        jobId="job-1234"
      />,
    );

    // Final Run Verdict banner should be present when isLiveJob is false
    expect(screen.queryByText('Final Run Performance Verdict')).not.toBeInTheDocument();
    expect(screen.getAllByText(/1h 24m 10s/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Active-Window Efficiency')).toBeInTheDocument();
    expect(screen.getByText('80.7%')).toBeInTheDocument();
    expect(screen.getByText(/Worker Occupancy/i)).toBeInTheDocument();
    expect(screen.getByText('78.7% Avg')).toBeInTheDocument();
    expect(screen.queryByText(/Operational Recommendations/i)).not.toBeInTheDocument();
  });

  it('keeps historical comparison in its Compare view, defaults to 10% task-count boundary, and allows customizing tolerance', () => {
    const currentJob: Job = {
      job_id: 'job-current',
      job_name: 'Current Run',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-09-19T10:00:00.000Z',
      updated_at: '2026-09-19T11:00:00.000Z',
      task_count: 1_057_000,
      completed_tasks: 1_057_000,
      failed_tasks: 0,
    };
    const similarJob: Job = {
      ...currentJob,
      job_id: 'job-similar',
      job_name: 'Similar Run',
      task_count: 1_100_000, // ~4.1% away
    };
    const moderateDiffJob: Job = {
      ...currentJob,
      job_id: 'job-moderate-diff',
      job_name: 'Moderate Diff Run',
      task_count: 1_115_000, // ~5.5% away (within 10%, outside 5%)
    };
    const farOutsideJob: Job = {
      ...currentJob,
      job_id: 'job-far-outside',
      job_name: 'Far Outside Run',
      task_count: 1_250_000, // ~18.3% away (outside 10%)
    };

    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName={currentJob.job_name}
        jobId={currentJob.job_id}
        site={currentJob.site}
        currentJob={currentJob}
        historicalJobs={[similarJob, moderateDiffJob, farOutsideJob]}
      />,
    );

    expect(screen.queryByTestId('historical-regression-card')).not.toBeInTheDocument();
    expect(screen.getByTestId('telemetry-details-stack')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));

    expect(screen.getByTestId('historical-regression-card')).toBeInTheDocument();
    expect(screen.queryByTestId('telemetry-details-stack')).not.toBeInTheDocument();
    // Default task-count matching remains adjustable.
    expect(screen.getByTestId('tolerance-select')).toHaveValue('10');

    // With default 10% tolerance, both similar (4.1%) and moderate (5.5%) runs match; far (18.3%) does not
    expect(screen.getByRole('option', { name: /Similar Run/i })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Moderate Diff Run/i })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Far Outside Run/i })).not.toBeInTheDocument();

    // Customize tolerance via UI: change to 5%
    const toleranceSelect = screen.getByTestId('tolerance-select');
    fireEvent.change(toleranceSelect, { target: { value: '5' } });

    expect(toleranceSelect).toHaveValue('5');
    expect(screen.getByRole('option', { name: /Similar Run/i })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Moderate Diff Run/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Far Outside Run/i })).not.toBeInTheDocument();

    // Customize tolerance via UI: change to 25%
    fireEvent.change(toleranceSelect, { target: { value: '25' } });
    expect(toleranceSelect).toHaveValue('25');
    expect(screen.getByRole('option', { name: /Far Outside Run/i })).toBeInTheDocument();

    // Customize tolerance via custom number input
    fireEvent.change(toleranceSelect, { target: { value: 'custom' } });
    const customInput = screen.getByTestId('tolerance-custom-input');
    expect(customInput).toBeInTheDocument();
    fireEvent.change(customInput, { target: { value: '3' } }); // 3% tolerance
    expect(toleranceSelect).toHaveValue('custom');
    expect(customInput).toHaveValue(3);
    expect(screen.getByText(/No prior historical jobs within ±3% of this run/i)).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Similar Run/i })).not.toBeInTheDocument();
  });

  it('displays customizable tolerance empty message when no historical runs fall within boundary', () => {
    const currentJob: Job = {
      updated_at: '2026-09-19T10:00:00.000Z',
      job_id: 'job-current-empty',
      job_name: 'Current Run',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-09-19T10:00:00.000Z',
      task_count: 327_500,
      completed_tasks: 327_500,
      failed_tasks: 0,
    };
    const historicalJob: Job = {
      ...currentJob,
      job_id: 'job-historical-diff',
      job_name: 'Prior Run',
      task_count: 400_000, // ~22% diff
    };

    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName={currentJob.job_name}
        jobId={currentJob.job_id}
        site={currentJob.site}
        currentJob={currentJob}
        historicalJobs={[historicalJob]}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    expect(screen.getByText(/No prior historical jobs within ±10% of this run's 327,500 tasks were found/i)).toBeInTheDocument();

    // Widening tolerance to 25% allows the prior run to appear
    const toleranceSelect = screen.getByTestId('tolerance-select');
    fireEvent.change(toleranceSelect, { target: { value: '25' } });
    expect(screen.getByRole('option', { name: /Prior Run/i })).toBeInTheDocument();
  });

  it('supports custom tolerance prop and triggers onTaskCountToleranceChange callback', () => {
    const currentJob: Job = {
      updated_at: '2026-09-19T10:00:00.000Z',
      job_id: 'job-current-prop',
      job_name: 'Current Run',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-09-19T10:00:00.000Z',
      task_count: 100_000,
      completed_tasks: 100_000,
      failed_tasks: 0,
    };
    const onToleranceChange = vi.fn();

    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={false}
        currentJob={currentJob}
        taskCountTolerancePercent={15}
        onTaskCountToleranceChange={onToleranceChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    expect(screen.getByTestId('tolerance-select')).toHaveValue('15');

    const toleranceSelect = screen.getByTestId('tolerance-select');
    fireEvent.change(toleranceSelect, { target: { value: '20' } });
    expect(onToleranceChange).toHaveBeenCalledWith(20);
    expect(screen.getByTestId('tolerance-select')).toHaveValue('20');
  });

  it('copies formatted Markdown report to clipboard', () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockImplementation(() => Promise.resolve()),
      },
    });
    render(
      <JobDiagnosticsReport
        telemetry={measuredTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName="MPS Scrape Job"
        jobId="job-1234"
      />,
    );

    const copyReportButtons = screen.getAllByRole('button', { name: /Copy/i });
    expect(copyReportButtons.length).toBeGreaterThan(0);
    fireEvent.click(copyReportButtons[0]);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('# Diagnostic Final Report: MPS Scrape Job'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Time-Weighted In-Flight Concurrency:** 85 active tasks avg (85 at close)'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Measured Active-Route Occupancy:** 85 / 108 route slots (78.7% measured utilization)'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Routes With Sampled Health Observations:** 2\n'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Observed Routes Without an Attributed Failure:** 0 / 2'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('2 observed proxies had an average latency of 3.15s.'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.not.stringContaining('Latency Percentile Profile & Tail Drag'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.not.stringContaining('| Avg Latency |'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('4 timeouts (Issue: Excessive 429 rate limits (8))'),
    );
  });

  it('does not label a completed job with task failures as halted', () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockImplementation(() => Promise.resolve()),
      },
    });
    const completedWithFailure: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      completedTasksCount: 99,
      totalTasksCount: 100,
      errorVelocity: {
        ...mockTelemetry.errorVelocity,
        totalErrors: 1,
      },
      finalSummary: {
        ...mockTelemetry.finalSummary,
        jobOutcome: 'completed',
        failedTaskCount: 1,
        terminationReason: 'Processed 12430 tasks with 1 failed task(s)',
      },
    };

    render(
      <JobDiagnosticsReport
        telemetry={completedWithFailure}
        isLiveJob={false}
        workerPoolSize={128}
        jobName="Completed With One Failure"
        jobId="job-completed-with-failure"
      />,
    );

    expect(screen.queryByText(/Halt Reason:/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: /Copy/i })[0]);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Failures:** 1 task failure(s); job completed'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.not.stringContaining('Failures:** Halted:'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Successful Tasks:** 99 / 100 (99.0%)'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Terminalized Tasks:** 100 / 100 (100.0%)'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('| **Task Success Rate** | 99 / 100 | 100% success | 99.0% succeeded |'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('| **Task Terminalization Rate** | 100 / 100 | 100% terminal | 100.0% terminalized |'),
    );
  });

  it('does not classify unobserved configured routes as healthy', () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockImplementation(() => Promise.resolve()),
      },
    });
    const telemetryWithoutRouteAttribution: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      proxyCapacity: {
        ...mockTelemetry.proxyCapacity,
        totalRoutes: 1656,
      },
      proxyAnomalies: [],
    };

    render(
      <JobDiagnosticsReport
        telemetry={telemetryWithoutRouteAttribution}
        isLiveJob={false}
        workerPoolSize={8}
        jobName="No Route Attribution"
        jobId="job-no-route-attribution"
      />,
    );

    fireEvent.click(screen.getAllByRole('button', { name: /Copy/i })[0]);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Routes With Sampled Health Observations:** 0\n'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('Per-route failure and lookup attribution were unavailable'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.not.stringContaining('1656 / 1656 routes'),
    );
  });

  it('calculates scaled throughput and active concurrency for completed runs with paginated tasks', () => {
    const startTime = new Date(Date.now() - 268000).toISOString();
    const endTime = new Date().toISOString();

    // Proxy count is not connection capacity; the planner records 108 route slots.
    const completedJob: Job = {
      metadata: { proxy_capacity: 108 },
      job_id: 'job-10630',
      job_name: 'Bulk Scrape',
      status: 'completed',
      created_at: startTime,
      updated_at: endTime,
      task_count: 10630,
      completed_tasks: 10630,
      failed_tasks: 0,
      task_stats: {
        total: 10630,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 10630,
        failed: 0,
        task_type_counts: {},
      },
    };

    const completedDetails: JobDetail = {
      ...completedJob,
      job_id: 'job-10630',
      job_name: 'Bulk Scrape',
      job_type: 'download',
      site: 'OnlyFans',
      priority: 1,
      worker_id: null,
      retries: 0,
      max_retries: 3,
      result_success: true,
      result_message: 'Success',
      result_error: null,
      args: {},
      tasks: [],
      started_at: startTime,
      completed_at: endTime,
      task_stats: {
        total: 10630,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 10630,
        failed: 0,
        task_type_counts: {},
      },
      error_stats: {
        total: 0,
        groups: {},
      },
    };

    // Simulate paginated slice of 50 tasks (out of 10,630)
    const paginatedTasks: TaskDetail[] = Array.from({ length: 50 }, (_, i) => ({
      task_id: `task-${i}`,
      task_type: 'download',
      content_type: 'post',
      site: 'OnlyFans',
      username: 'user',
      status: 'completed',
      progress: 100,
      items_processed: 1,
      items_total: 1,
      error: null,
      result: null,
      created_at: startTime,
      started_at: startTime,
      completed_at: endTime,
    }));

    const dummyProxies = Array.from({ length: 107 }, (_, i) => `http://192.168.1.${i}:8080`);

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        completedJob,
        completedDetails,
        paginatedTasks,
        dummyProxies as unknown as NetworkProxy[],
        false,
      ),
    );

    const summary = result.current.finalSummary;
    // 10,630 tasks in 268 seconds should be ~39.7 items/s, NOT 0.3 items/s
    expect(summary.overallAvgItemsPerSec).toBeCloseTo(39.7, 0);
    // Theoretical max: 108 routes / 2.1s ≈ 51.4; Efficiency: 39.7 / 51.4 ≈ 77% (or bounded by 100%)
    expect(summary.efficiencyPercent).toBeGreaterThan(50);
    // In-flight active concurrency should be calculated (not 0) even though runningTasksCount is 0 at downtime
    expect(summary.avgActiveConcurrency).toBeGreaterThan(0);
    expect(summary.avgActiveProxyRoutes).toBeGreaterThan(0);
    expect(summary.avgActiveProxyUtilization).toBeGreaterThan(0);
    // Healthy proxies should reflect all enabled routes (107 proxies + 1 direct = 108 routes)
    expect(summary.healthyProxyCount).toBe(108);
  });

  it("calculates Little's Law active concurrency of ~54.4 active tasks and tracks peak throughput", () => {
    const startTime = new Date(Date.now() - 268000).toISOString();
    const endTime = new Date().toISOString();

    // Proxy count is not connection capacity; the planner records 108 route slots.
    const completedJob: Job = {
      metadata: { proxy_capacity: 108 },
      job_id: 'job-10630-littles',
      job_name: 'Bulk Scrape',
      status: 'completed',
      created_at: startTime,
      updated_at: endTime,
      task_count: 10630,
      completed_tasks: 10630,
      failed_tasks: 0,
      task_stats: {
        total: 10630,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 10630,
        failed: 0,
        task_type_counts: {},
      },
    };

    const completedDetails: JobDetail = {
      ...completedJob,
      job_id: 'job-10630-littles',
      job_name: 'Bulk Scrape',
      job_type: 'download',
      site: 'OnlyFans',
      priority: 1,
      worker_id: null,
      retries: 0,
      max_retries: 3,
      result_success: true,
      result_message: 'Success',
      result_error: null,
      args: {},
      tasks: [],
      started_at: startTime,
      completed_at: endTime,
      task_stats: {
        total: 10630,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 10630,
        failed: 0,
        task_type_counts: {},
      },
      error_stats: {
        total: 0,
        groups: {},
      },
    };

    // 50 tasks with 1.37s duration (median latency = 1.37s)
    // with a 1-second burst cluster
    const paginatedTasks: TaskDetail[] = Array.from({ length: 50 }, (_, i) => {
      const offsetMs = i < 5 ? 100000 + i * 150 : 5000 * i;
      const tCompleted = new Date(new Date(startTime).getTime() + offsetMs).toISOString();
      const tStarted = new Date(new Date(tCompleted).getTime() - 1370).toISOString();
      return {
        task_id: `task-${i}`,
        task_type: 'download',
        content_type: 'post',
        site: 'OnlyFans',
        username: 'user',
        status: 'completed',
        progress: 100,
        items_processed: 1,
        items_total: 1,
        error: null,
        result: null,
        created_at: startTime,
        started_at: tStarted,
        completed_at: tCompleted,
      };
    });

    const dummyProxies = Array.from({ length: 107 }, (_, i) => `http://192.168.1.${i}:8080`);

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        completedJob,
        completedDetails,
        paginatedTasks,
        dummyProxies as unknown as NetworkProxy[],
        false,
      ),
    );

    const summary = result.current.finalSummary;
    // Little's Law: 39.7 items/s * 1.37s ≈ 54.4 active tasks
    expect(summary.avgActiveConcurrency).toBeCloseTo(54.4, 0);
    // A partial task page is not extrapolated into a fabricated full-job burst.
    expect(summary.peakItemsPerSec).toBeGreaterThanOrEqual(summary.overallAvgItemsPerSec);
  });

  it('renders stable error velocity when single failure occurs out of large task volume', () => {
    const jitterTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      errorVelocity: {
        totalErrors: 1,
        errorsLast60s: 1,
        safetyThresholdLimit: 25,
        safetyMarginPercent: 4,
        trend: 'stable',
        rate429Count: 0,
        rate429PerMin: 0,
      },
    };

    render(
      <JobDiagnosticsReport
        telemetry={jitterTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );

    expect(screen.getByRole('meter', { name: 'Failure rate' })).toBeInTheDocument();
    expect(screen.getByText('1 Failures (0 429s)')).toBeInTheDocument();
    expect(screen.queryByText('1 total failures (0 rate limits)')).not.toBeInTheDocument();
  });

  it('calculates active concurrency exceeding 108 without artificial clamping when proxy capacity is 556', () => {
    const startTime = new Date(Date.now() - 276000).toISOString();
    const endTime = new Date().toISOString();

    const completedJob: Job = {
      job_id: 'job-556-capacity',
      job_name: 'MPS Profile Scrape',
      status: 'completed',
      created_at: startTime,
      updated_at: endTime,
      task_count: 10640,
      completed_tasks: 10640,
      failed_tasks: 0,
      task_stats: {
        total: 10640,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 10640,
        failed: 0,
        task_type_counts: {},
      },
      metadata: {
        proxy_capacity: 556,
      },
    };

    const completedDetails: JobDetail = {
      ...completedJob,
      job_id: 'job-556-capacity',
      job_name: 'MPS Profile Scrape',
      job_type: 'mass_profile_scrape',
      site: 'OnlyFans',
      priority: 0,
      worker_id: null,
      retries: 0,
      max_retries: 3,
      result_success: true,
      result_message: 'Success',
      result_error: null,
      args: {},
      tasks: [],
      started_at: startTime,
      completed_at: endTime,
      task_stats: {
        total: 10640,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 10640,
        failed: 0,
        task_type_counts: {},
      },
      error_stats: {
        total: 0,
        groups: {},
      },
      metadata: {
        proxy_capacity: 556,
      },
    };

    // 50 tasks with 3.32s duration (median latency = 3.32s)
    const paginatedTasks: TaskDetail[] = Array.from({ length: 50 }, (_, i) => {
      const offsetMs = i * 2000;
      const tCompleted = new Date(new Date(startTime).getTime() + offsetMs + 10000).toISOString();
      const tStarted = new Date(new Date(tCompleted).getTime() - 3320).toISOString();
      return {
        task_id: `task-${i}`,
        task_type: 'scrape',
        content_type: 'profile',
        site: 'OnlyFans',
        username: 'user',
        status: 'completed',
        progress: 100,
        items_processed: 1,
        items_total: 1,
        error: null,
        result: null,
        created_at: startTime,
        started_at: tStarted,
        completed_at: tCompleted,
      };
    });

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        completedJob,
        completedDetails,
        paginatedTasks,
        undefined,
        false,
      ),
    );

    const summary = result.current.finalSummary;
    // Total routes should reflect the declared proxy capacity of 556
    expect(result.current.proxyCapacity.totalRoutes).toBe(556);
    // Little's Law: 38.6 items/s * 3.32s ≈ 128.2 active tasks (must NOT be clamped to 108)
    expect(summary.avgActiveConcurrency).toBeCloseTo(128.2, 0);
    expect(summary.avgActiveConcurrency).toBeGreaterThan(108);
    // Headroom warning must NOT fire because 556 exceeds the 128 worker pool
    const headroomRec = summary.recommendations.find((r) => r.includes('Proxy Capacity Headroom'));
    expect(headroomRec).toBeUndefined();
  });

  it('correctly adapts concurrency percentage and KPI meta to dynamic workerPoolSize (e.g. 32)', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={32}
      />,
    );

    // 85 running tasks / 32 workers ≈ 2.7x load
    expect(screen.getByText('In Flight').closest('.jdr-perf-card')).toHaveTextContent('32 workers · 2.7× load');
  });

  it('uses dynamic workerPoolSize in useJobDiagnosticsTelemetry recommendations and bottleneck factor', () => {
    const job = {
      ...mockTelemetry,
      job_id: 'job-dyn',
      status: 'completed',
      metadata: { proxy_capacity: 16 },
    } as unknown as Job;
    const dummyProxies = Array.from({ length: 15 }, (_, i) => `http://10.0.0.${i}:8080`) as unknown as NetworkProxy[];
    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        job,
        undefined,
        [],
        dummyProxies,
        false,
        32,
      ),
    );

    // 16 planned route slots < 32 workers -> bottleneck factor = 16 / 32 = 0.5
    expect(result.current.proxyCapacity.totalRoutes).toBe(16);
    expect(result.current.finalSummary.proxyBottleneckFactor).toBe(0.5);
    const headroomRec = result.current.finalSummary.recommendations.find((r) =>
      r.includes('below the 32 worker pool'),
    );
    expect(headroomRec).toBeDefined();
    expect(headroomRec).toContain('below the 32 worker pool');
  });

  it('omits System Bottleneck Diagnosis from the report', () => {
    const customTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      bottleneckAnalysis: {
        state: 'proxy_saturated',
        label: 'Proxy Route Saturated',
        explanation: 'Inflight concurrency reached the 108 proxy route ceiling.',
        rootCauseFindings: [
          'Rate limit hotspot: 18 total 429 requests.',
          'Proxy ceiling bound: worker pool exceeds proxy capacity.',
        ],
      },
    };

    render(
      <JobDiagnosticsReport
        telemetry={customTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );

    expect(screen.queryByTestId('bottleneck-card')).not.toBeInTheDocument();
  });

  it('supports downloading diagnostic JSON bundle and verifies print button is removed', () => {
    const createObjectURLMock = vi.fn().mockReturnValue('blob:test');
    const revokeObjectURLMock = vi.fn();
    window.URL.createObjectURL = createObjectURLMock;
    window.URL.revokeObjectURL = revokeObjectURLMock;

    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
        jobName="Benchmark Run"
        jobId="job-abc-123"
        site="OnlyFans"
      />,
    );

    // Click JSON bundle export button
    const bundleBtn = screen.getByText(/Diagnostic Bundle \(\.json\)/i);
    expect(bundleBtn).toBeInTheDocument();
    fireEvent.click(bundleBtn);
    expect(createObjectURLMock).toHaveBeenCalled();

    // Verify Print button is removed
    expect(screen.queryByText(/Print \/ PDF/i)).not.toBeInTheDocument();
  });

  it('filters and searches proxy anomalies in the triage table', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );

    // Initial state shows both anomalies
    expect(screen.getByText('http://192.168.1.216:8892')).toBeInTheDocument();
    expect(screen.getByText('http://192.168.1.216:8895')).toBeInTheDocument();

    // Search for 8892 specifically
    const searchInput = screen.getByPlaceholderText(/Filter by route URL, group, country/i);
    fireEvent.change(searchInput, { target: { value: '8892' } });

    expect(screen.getByText('http://192.168.1.216:8892')).toBeInTheDocument();
    expect(screen.queryByText('http://192.168.1.216:8895')).not.toBeInTheDocument();

    // Clear search
    const clearBtn = screen.getByLabelText(/Clear search/i);
    fireEvent.click(clearBtn);
    expect(screen.getByText('http://192.168.1.216:8895')).toBeInTheDocument();

    // Filter by 'Critical' only
    const criticalPill = screen.getByRole('button', { name: /Critical \(1\)/i });
    fireEvent.click(criticalPill);
    expect(screen.getByText('http://192.168.1.216:8892')).toBeInTheDocument();
    expect(screen.queryByText('http://192.168.1.216:8895')).not.toBeInTheDocument();
  });

  it('renders interactive crosshair and tooltip when moving mouse over SVG charts', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
      />,
    );

    const svgElements = screen.getAllByTestId('chart-svg');
    expect(svgElements.length).toBe(4);

    const firstSvg = svgElements[0];
    // Mock getBoundingClientRect
    vi.spyOn(firstSvg, 'getBoundingClientRect').mockReturnValue({
      left: 100,
      top: 50,
      width: 480,
      height: 140,
      right: 580,
      bottom: 190,
      x: 100,
      y: 50,
      toJSON: () => {},
    });

    // Fire mouse move near the middle of the chart
    fireEvent.mouseMove(firstSvg, { clientX: 300, clientY: 100 });

    // Expect the tooltip to identify the hovered sample by its wall-clock time
    const sampleClocks = mockSnapshots.map((snapshot) =>
      new Date(snapshot.timestamp).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
    );
    const tooltipHeader = document.querySelector('.jdr-tooltip-header');
    expect(tooltipHeader).not.toBeNull();
    expect(sampleClocks.some((clock) => tooltipHeader!.textContent?.includes(clock))).toBe(true);

    // Fire mouse leave
    fireEvent.mouseLeave(firstSvg);
  });

  it('computes bottleneckAnalysis in useJobDiagnosticsTelemetry for proxy saturated state', () => {
    const saturatedJob = {
      ...mockTelemetry,
      job_id: 'job-sat',
      status: 'running',
      metadata: { proxy_capacity: 16 },
      task_stats: {
        total: 1000,
        completed: 100,
        inflight: 16,
        ready: 500,
        failed: 0,
      },
    } as unknown as Job;

    const dummyProxies = Array.from({ length: 15 }, (_, i) => `http://10.0.0.${i}:8080`) as unknown as NetworkProxy[];

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        saturatedJob,
        undefined,
        [],
        dummyProxies,
        true,
        32,
      ),
    );

    expect(result.current.bottleneckAnalysis).toBeDefined();
    // 16 inflight == 16 planned route slots with 500 ready tasks -> proxy saturated!
    expect(result.current.bottleneckAnalysis.state).toBe('proxy_saturated');
    expect(result.current.bottleneckAnalysis.label).toContain('Proxy Route Saturated');
  });

  it('displays dynamic route ceiling label and subtitle matching proxyCapacity without hardcoded 108', () => {
    const customCapacityTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      proxyCapacity: {
        totalRoutes: 464,
        enabledProxies: 463,
        directRoutes: 1,
        activeRoutes: 400,
        utilizationPercent: 86.2,
        isNearCapacity: true,
        isSaturated: false,
      },
    };

    render(
      <JobDiagnosticsReport
        telemetry={customCapacityTelemetry}
        isLiveJob={true}
        workerPoolSize={32}
      />,
    );

    // Subtitle must render 464, not hardcoded 108
    expect(
      screen.getByText('Observed running-task count against 464 configured routes'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/against 108 configured routes/i)).not.toBeInTheDocument();

    // Line label and legend must render 464 Route Ceiling, not 108 Route Ceiling
    expect(screen.getAllByText(/464 Route Ceiling/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/108 Route Ceiling/i)).not.toBeInTheDocument();
  });

  it('displays dynamic safetyThresholdLimit denominator in error velocity card', () => {
    const scaledThresholdTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      errorVelocity: {
        totalErrors: 50,
        errorsLast60s: 50,
        safetyThresholdLimit: 533,
        safetyMarginPercent: 9,
        trend: 'stable',
        rate429Count: 0,
        rate429PerMin: 0,
      },
    };

    render(
      <JobDiagnosticsReport
        telemetry={scaledThresholdTelemetry}
        isLiveJob={true}
        workerPoolSize={32}
      />,
    );

    // Error velocity card should display 50 / 533 limit in 60s, NOT static 25
    expect(screen.getByText(/50 \/ 533 limit in 60s/i)).toBeInTheDocument();
    expect(screen.queryByText(/50 \/ 25 limit in 60s/i)).not.toBeInTheDocument();
  });

  it('correctly compares total worker concurrency demand against proxy capacity in anomaly detector', () => {
    const jobWithMetadata = {
      job_id: 'job-demand-test',
      status: 'running',
      metadata: {
        target_concurrency: 16,
        proxy_capacity: 464,
      },
      task_stats: {
        total: 10660,
        completed: 100,
        inflight: 464,
        ready: 5000,
        failed: 0,
      },
    } as unknown as Job;

    const dummyProxies = Array.from({ length: 463 }, (_, i) => `http://10.0.0.${i}:8080`) as unknown as NetworkProxy[];

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        jobWithMetadata,
        undefined,
        [],
        dummyProxies,
        true,
        32, // 32 workers * 16 target concurrency = 512 demand > 464 routes
      ),
    );

    expect(result.current.bottleneckAnalysis.state).toBe('proxy_saturated');
    const finding = result.current.bottleneckAnalysis.rootCauseFindings[0];
    // Must NOT say "worker pool (32) exceeds proxy capacity (464 routes)"
    expect(finding).not.toContain('worker pool (32) exceeds proxy capacity');
    // Must correctly state total worker concurrency demand (32 workers × 16 = 512) exceeds proxy capacity (464 routes)
    expect(finding).toContain('total worker concurrency demand (32 workers × 16 = 512) exceeds proxy capacity (464 routes)');
    // Safety threshold should scale to 533 for 10,660 tasks (5% budget)
    expect(result.current.errorVelocity.safetyThresholdLimit).toBe(533);
  });

  it('does not trigger false critical error velocity on 16 failures when dynamic threshold is 569', () => {
    const largeJob = {
      job_id: 'job-velocity-test',
      status: 'running',
      task_stats: {
        total: 11380, // 5% dynamic limit = 569
        completed: 1000,
        inflight: 300,
        ready: 4000,
        failed: 16,
      },
    } as unknown as Job;

    const tasks = Array.from({ length: 16 }, (_, i) => ({
      task_id: `task-${i}`,
      status: 'failed',
      completed_at: new Date().toISOString(),
    }));

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        largeJob,
        undefined,
        tasks as unknown as TaskDetail[],
        undefined,
        true,
        32,
      ),
    );

    expect(result.current.errorVelocity.safetyThresholdLimit).toBe(569);
    // 16 out of 569 is only ~3% safety budget, must NOT be critical
    expect(result.current.errorVelocity.trend).not.toBe('critical');
    const criticalFinding = result.current.bottleneckAnalysis.rootCauseFindings.find((f) =>
      f.includes('Critical error velocity'),
    );
    expect(criticalFinding).toBeUndefined();
  });

  it('suppresses false pipeline queue starvation alert when job is completed or in final drain', () => {
    const completedJob = {
      job_id: 'job-completed-drain',
      status: 'completed',
      task_stats: {
        total: 500,
        completed: 500,
        inflight: 0,
        ready: 0,
        failed: 0,
      },
    } as unknown as Job;

    const { result: completedResult } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        completedJob,
        undefined,
        [],
        undefined,
        false, // Not live
        32,
      ),
    );

    // Finished job with 0 inflight and 0 ready must NOT trigger queue starvation
    expect(completedResult.current.bottleneckAnalysis.state).not.toBe('queue_starved');
    // Without full-job runtime telemetry the hook reports no bottleneck rather than guessing.
    expect(completedResult.current.bottleneckAnalysis.label).toBe('Insufficient Runtime Telemetry');

    const drainingJob = {
      job_id: 'job-draining',
      status: 'running',
      task_stats: {
        total: 500,
        completed: 498,
        inflight: 2,
        ready: 0,
        failed: 0,
      },
    } as unknown as Job;

    const { result: drainingResult } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        drainingJob,
        undefined,
        [],
        undefined,
        true, // Live job
        32,
      ),
    );

    // In-flight (2) == remaining (500 - 498 = 2). Final drain state must NOT flag queue starvation
    expect(drainingResult.current.bottleneckAnalysis.state).not.toBe('queue_starved');
    expect(drainingResult.current.bottleneckAnalysis.label).toBe('No Confirmed Bottleneck');
  });

  it('uses one Telemetry tab for active and terminal jobs', () => {
    const { rerender } = render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName="Completed Run"
        jobId="job-completed-1"
      />,
    );

    // Both terminal and active jobs use the same Telemetry tab.
    expect(screen.getByRole('button', { name: /^Telemetry$/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Live Telemetry/i })).not.toBeInTheDocument();

    // Active jobs also have no separate live tab.
    rerender(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
        jobName="Active Run"
        jobId="job-active-1"
      />,
    );
    expect(screen.getByRole('button', { name: /^Telemetry$/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Live Telemetry/i })).not.toBeInTheDocument();
  });

  it('shows live metrics in Telemetry and omits the verdict until concluded', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={true}
        workerPoolSize={128}
        jobName="Active Run"
        jobId="job-active-1"
      />,
    );

    // Active view defaults to live telemetry; post-mortem verdict is omitted
    expect(screen.queryByText('Final Run Performance Verdict')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Telemetry' })).toHaveClass('active');
    expect(screen.getByText('● Live')).toBeInTheDocument();
  });

  it('scales X-axis full runtime timeline (T₀ → T_complete) in Final Run Report', () => {
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName="Macro Timeline Run"
        jobId="job-macro-1"
      />,
    );

    // Header indicates macro lifecycle timeline
    expect(screen.getByText('Job Lifecycle Macro Performance Graphs')).toBeInTheDocument();
    expect(
      screen.getByText('Lifecycle axis · retained observation points only · 1h 24m 10s'),
    ).toBeInTheDocument();

    // X-axis timeline markers (start, midpoint, completion) are rendered across charts
    expect(screen.getAllByText(/^T₀ \d/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/^50% · \d/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/T_complete \(1h 24m 10s\)/i).length).toBeGreaterThanOrEqual(1);
  });

  it('detects performance regression when current throughput drops >10% relative to baseline', () => {
    const mockHistoricalJobs: Job[] = [
      {
        job_id: 'job-baseline-faster',
        job_name: 'Prior Bulk Scrape',
        status: 'completed',
        site: 'OnlyFans',
        created_at: new Date(Date.now() - 200000).toISOString(),
        updated_at: new Date(Date.now() - 100000).toISOString(), // 100s duration
        task_count: 10000,
        completed_tasks: 6000, // 60.0 items/s vs current 41.5 items/s (-30.8%)
        failed_tasks: 10,
        task_stats: {
          total: 10000,
          completed: 6000,
          failed: 10,
          ready: 0,
          blocked: 0,
          inflight: 0,
          deferred: 0,
          task_type_counts: {},
        },
      } as unknown as Job,
    ];
    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName="Current Run"
        jobId="job-current-1"
        site="OnlyFans"
        currentJob={{
          ...mockHistoricalJobs[0],
          job_id: 'job-current-1',
          job_name: 'Current Run',
          task_count: 10000,
        }}
        historicalJobs={mockHistoricalJobs}
        initialBaselineJobId="job-baseline-faster"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    expect(screen.getByTestId('historical-regression-card')).toBeInTheDocument();
    expect(screen.getByTestId('comparison-status')).toHaveTextContent('Regression');
    expect(screen.getByTestId('comparison-status')).toHaveClass('is-regression');
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('−30.8%');
    expect(screen.queryByText(/Key Run-to-Run Variance/i)).not.toBeInTheDocument();
  });

  it('detects performance improvement when current throughput exceeds baseline by >10%', () => {
    const mockHistoricalJobs: Job[] = [
      {
        job_id: 'job-baseline-slower',
        job_name: 'Slow Prior Run',
        status: 'completed',
        site: 'OnlyFans',
        created_at: new Date(Date.now() - 200000).toISOString(),
        updated_at: new Date(Date.now() - 100000).toISOString(), // 100s
        task_count: 5000,
        completed_tasks: 2000, // 20.0 items/s vs current 41.5 items/s (+107.5%)
        failed_tasks: 20,
        task_stats: {
          total: 5000,
          completed: 2000,
          failed: 20,
          ready: 0,
          blocked: 0,
          inflight: 0,
          deferred: 0,
          task_type_counts: {},
        },
      } as unknown as Job,
    ];

    const improvementTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      finalSummary: {
        ...mockTelemetry.finalSummary,
        totalDurationSec: 90,
        totalDurationFormatted: '1m 30s',
        jobOutcome: 'completed',
      },
    };

    render(
      <JobDiagnosticsReport
        telemetry={improvementTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName="Current Run"
        jobId="job-current-1"
        site="OnlyFans"
        currentJob={{
          ...mockHistoricalJobs[0],
          job_id: 'job-current-1',
          job_name: 'Current Run',
          task_count: 5000,
        }}
        historicalJobs={mockHistoricalJobs}
        initialBaselineJobId="job-baseline-slower"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    expect(screen.getByTestId('comparison-status')).toHaveTextContent('Improvement');
    expect(screen.getByTestId('comparison-status')).toHaveClass('is-improvement');
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('+107.5%');
  });

  it('allows switching baseline job in dropdown and updates regression metrics', () => {
    const mockHistoricalJobs: Job[] = [
      {
        job_id: 'job-baseline-1',
        job_name: 'First Baseline',
        status: 'completed',
        site: 'OnlyFans',
        created_at: new Date(Date.now() - 200000).toISOString(),
        updated_at: new Date(Date.now() - 100000).toISOString(),
        task_count: 5000,
        completed_tasks: 2000,
        failed_tasks: 20,
      } as unknown as Job,
      {
        job_id: 'job-baseline-2',
        job_name: 'Second Baseline',
        status: 'completed',
        site: 'OnlyFans',
        created_at: new Date(Date.now() - 200000).toISOString(),
        updated_at: new Date(Date.now() - 100000).toISOString(),
        task_count: 5200,
        completed_tasks: 8000,
        failed_tasks: 5,
      } as unknown as Job,
    ];

    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName="Current Run"
        jobId="job-current-1"
        site="OnlyFans"
        currentJob={{
          ...mockHistoricalJobs[0],
          job_id: 'job-current-1',
          job_name: 'Current Run',
          task_count: 5000,
        }}
        historicalJobs={mockHistoricalJobs}
        initialBaselineJobId="job-baseline-1"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    const baselineSelect = screen.getByLabelText(/Select baseline historical run for comparison/i);
    expect((baselineSelect as HTMLSelectElement).value).toBe('job-baseline-1');

    // Switch to job-baseline-2
    fireEvent.change(baselineSelect, { target: { value: 'job-baseline-2' } });
    expect((baselineSelect as HTMLSelectElement).value).toBe('job-baseline-2');

    // Switch to none
    fireEvent.change(baselineSelect, { target: { value: '' } });
    expect(
      screen.getByText(/Select a similar-size historical job from the dropdown above to compute regression deltas/i),
    ).toBeInTheDocument();
  });

  it('embeds historical regression comparison in Markdown report and JSON bundle exports', () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockImplementation(() => Promise.resolve()),
      },
    });

    const createObjectURLMock = vi.fn().mockReturnValue('blob:test');
    window.URL.createObjectURL = createObjectURLMock;

    const mockHistoricalJobs: Job[] = [
      {
        job_id: 'job-prior-1',
        job_name: 'Prior Run Benchmark',
        status: 'completed',
        site: 'OnlyFans',
        created_at: new Date(Date.now() - 200000).toISOString(),
        updated_at: new Date(Date.now() - 100000).toISOString(),
        task_count: 5000,
        completed_tasks: 2000,
        failed_tasks: 20,
      } as unknown as Job,
    ];

    render(
      <JobDiagnosticsReport
        telemetry={mockTelemetry}
        isLiveJob={false}
        workerPoolSize={128}
        jobName="Current Export Test"
        jobId="job-export-1"
        site="OnlyFans"
        currentJob={{
          ...mockHistoricalJobs[0],
          job_id: 'job-export-1',
          job_name: 'Current Export Test',
          task_count: 5000,
        }}
        historicalJobs={mockHistoricalJobs}
        initialBaselineJobId="job-prior-1"
      />,
    );

    // Copy Markdown report
    const copyReportButton = screen.getByRole('button', { name: /Copy Markdown Report/i });
    fireEvent.click(copyReportButton);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('## 6. Historical Performance Regression Comparison'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('vs Baseline: Prior Run Benchmark - `job-prior-1`'),
    );

    // Export JSON bundle
    const bundleBtn = screen.getByRole('button', { name: /Diagnostic Bundle \(\.json\)/i });
    fireEvent.click(bundleBtn);
    expect(createObjectURLMock).toHaveBeenCalled();
  });

  it('excludes direct route from Section 4 and lists pure proxy routes when include_direct_connection is false', () => {
    const jobWithDirectExcluded: Job = {
      job_id: 'job-mps-no-direct',
      job_name: 'MPS Run Without Direct',
      status: 'completed',
      created_at: new Date(Date.now() - 100000).toISOString(),
      updated_at: new Date().toISOString(),
      task_count: 464,
      completed_tasks: 464,
      failed_tasks: 0,
      metadata: {
        include_direct_connection: false,
      },
    } as unknown as Job;

    // 464 pure proxy routes
    const dummyProxies = Array.from({ length: 464 }, (_, i) => `http://10.0.0.${i}:8080`) as unknown as NetworkProxy[];

    // Tasks including one with direct/undefined proxy and 6.43s elevated latency
    const tasks: TaskDetail[] = [
      {
        task_id: 'task-direct-latency',
        task_type: 'scrape',
        status: 'completed',
        started_at: '2026-09-16T12:00:00Z',
        completed_at: '2026-09-16T12:00:06.43Z',
        payload: {
          guest_proxy_url: undefined,
        },
      } as unknown as TaskDetail,
      ...Array.from({ length: 10 }, (_, i) => ({
        task_id: `task-p-${i}`,
        task_type: 'scrape',
        status: 'completed',
        started_at: '2026-09-16T12:00:00Z',
        completed_at: '2026-09-16T12:00:01.20Z',
        payload: {
          guest_proxy_url: `http://10.0.0.${i}:8080`,
        },
      } as unknown as TaskDetail)),
    ];

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        jobWithDirectExcluded,
        undefined,
        tasks,
        dummyProxies,
        false,
        32,
      ),
    );

    // Section 4 proxy anomalies must NOT contain direct
    expect(result.current.proxyAnomalies.some((p) => p.proxyUrl === 'direct')).toBe(false);
    expect(result.current.proxyAnomalies.every((p) => p.totalAttempts > 0 || p.failures > 0)).toBe(true);
    expect(result.current.proxyCapacity.directRoutes).toBe(0);

    // Render report and verify Section 4 lists pure proxy routes with no direct (Default) entry present
    render(
      <JobDiagnosticsReport
        telemetry={result.current}
        isLiveJob={false}
        workerPoolSize={32}
        jobName="MPS Run Without Direct"
        jobId="job-mps-no-direct"
      />,
    );

    expect(screen.queryByText(/Direct \/ Default/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Elevated latency \(6\.43s\)/i)).not.toBeInTheDocument();
  });

  it('excludes direct route by default for MPS jobs when include_direct_connection is omitted from metadata', () => {
    const mpsJobWithoutDirectFlag: Job = {
      job_id: 'job-mps-omitted-direct',
      job_name: 'MPS Profile Scrape (OnlyFans) 1-100',
      status: 'completed',
      created_at: new Date(Date.now() - 100000).toISOString(),
      updated_at: new Date().toISOString(),
      task_count: 107,
      completed_tasks: 107,
      failed_tasks: 0,
      metadata: {
        mps_manifest: true,
        job_resource_scope: 'mps',
        proxy_capacity: 464,
      },
    } as unknown as Job;

    const dummyProxies = Array.from({ length: 107 }, (_, i) => `http://10.0.0.${i}:8080`) as unknown as NetworkProxy[];
    const tasks: TaskDetail[] = [
      {
        task_id: 'task-direct-latency',
        task_type: 'scrape',
        status: 'completed',
        started_at: '2026-09-16T12:00:00Z',
        completed_at: '2026-09-16T12:00:08.00Z',
        payload: {
          guest_proxy_url: undefined,
        },
      } as unknown as TaskDetail,
    ];

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        mpsJobWithoutDirectFlag,
        undefined,
        tasks,
        dummyProxies,
        false,
        32,
      ),
    );

    expect(result.current.proxyCapacity.directRoutes).toBe(0);
    expect(result.current.proxyAnomalies.some((p) => p.proxyUrl === 'direct')).toBe(false);

    render(
      <JobDiagnosticsReport
        telemetry={result.current}
        isLiveJob={false}
        workerPoolSize={32}
        jobName="MPS Profile Scrape (OnlyFans) 1-100"
        jobId="job-mps-omitted-direct"
      />,
    );

    expect(screen.queryByText(/107 proxies \+ 1 direct/i)).not.toBeInTheDocument();
    expect(screen.getByText(/107 proxies/i)).toBeInTheDocument();
    expect(screen.queryByText(/Direct \/ Default/i)).not.toBeInTheDocument();
  });

  it('does not extrapolate a sampled completion burst to the full job', () => {
    const startTime = new Date(Date.now() - 100000).toISOString();
    const endTime = new Date().toISOString();

    const jobWithCapacity464: Job = {
      job_id: 'job-burst-test',
      job_name: 'MPS 464 Capacity Job',
      status: 'completed',
      created_at: startTime,
      updated_at: endTime,
      task_count: 1000,
      completed_tasks: 1000,
      failed_tasks: 0,
      metadata: {
        include_direct_connection: false,
        proxy_capacity: 464,
      },
    } as unknown as Job;

    // 464 proxies, with p50 ~ 1.0s -> theoreticalProxyMax = 464 / 1.0 = 464.0 items/s
    const dummyProxies = Array.from({ length: 464 }, (_, i) => `http://10.0.0.${i}:8080`) as unknown as NetworkProxy[];

    // 500 tasks completing within a 1-second cluster, each representing a
    // sampled multi-item completion. The scaled burst is intentionally above
    // the route-derived cap: 464 / min(1.0s, 0.5s) = 928 items/s.
    const burstClusterTasks: TaskDetail[] = Array.from({ length: 500 }, (_, i) => {
      const burstTime = new Date('2026-09-16T12:00:10.000Z').getTime() + (i * 2); // 500 tasks completed in 1000ms
      return {
        task_id: `task-burst-${i}`,
        task_type: 'scrape',
        status: 'completed',
        items_processed: 10,
        started_at: new Date(burstTime - 1000).toISOString(),
        completed_at: new Date(burstTime).toISOString(),
      } as unknown as TaskDetail;
    });

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        jobWithCapacity464,
        undefined,
        burstClusterTasks,
        dummyProxies,
        false,
        32,
      ),
    );

    expect(result.current.finalSummary.peakItemsPerSec).toBe(500);

    render(
      <JobDiagnosticsReport
        telemetry={result.current}
        isLiveJob={false}
        workerPoolSize={32}
        jobName="MPS 464 Capacity Job"
        jobId="job-burst-test"
      />,
    );

    expect(screen.getByRole('meter', { name: 'Throughput and observed burst' })).toHaveAttribute('aria-valuetext', expect.stringContaining(`observed burst: ${result.current.finalSummary.peakItemsPerSec} tasks/s`));
    expect(screen.getByText('Throughput Velocity (Tasks/sec)')).toBeInTheDocument();
  });

  it('computes baseline run duration from initial dispatch to completion (3m 09s) instead of worker pickup/updated_at timestamp (14s)', () => {
    // Baseline job representing job-fe10c14a96ae:
    // created_at: 12:00:00 (initial dispatch)
    // updated_at: 12:00:14 (worker startup / transition timestamp, 14 seconds after creation)
    // last_ran_at: 12:03:09 (actual completion timestamp, 189 seconds = 3m 09s after creation)
    // 10,680 completed tasks
    const baselineJob: Job = {
      job_id: 'job-fe10c14a96ae',
      job_name: 'MPS 10k Scrape Run',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-09-16T12:00:00.000Z',
      updated_at: '2026-09-16T12:00:14.000Z',
      last_ran_at: '2026-09-16T12:03:09.000Z',
      task_count: 10680,
      completed_tasks: 10680,
      failed_tasks: 0,
      task_stats: {
        total: 10680,
        completed: 10680,
        failed: 0,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        task_type_counts: {},
      },
    } as unknown as Job;

    // Direct helper check: duration must be 189s, NOT 14s
    const computedSec = computeJobDurationSeconds(baselineJob);
    expect(computedSec).toBe(189);

    // Current run telemetry with 55.0 items/s over 190 seconds (10,450 tasks)
    const currentTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      completedTasksCount: 10450,
      totalTasksCount: 10450,
      throughput: {
        ...mockTelemetry.throughput,
        currentItemsPerSec: 55.0,
      },
      finalSummary: {
        ...mockTelemetry.finalSummary,
        totalDurationSec: 190,
        totalDurationFormatted: '3m 10s',
        overallAvgItemsPerSec: 55.0,
        overallAvgTasksPerSec: 55.0,
        jobOutcome: 'completed',
      },
    };

    const comp = computeHistoricalComparison(
      currentTelemetry,
      'job-current-nominal',
      'Current MPS Run',
      'OnlyFans',
      false,
      baselineJob,
    );

    expect(comp).not.toBeNull();
    // Baseline duration should be 189s and formatted as "3m 9s" (NOT 14s!)
    expect(comp?.baselineJob?.durationSec).toBe(189);
    expect(comp?.baselineJob?.durationFormatted).toBe('3m 9s');
    // Baseline throughput should be ~56.5 items/s (NOT 762.9 items/s!)
    expect(comp?.baselineJob?.avgItemsPerSec).toBe(56.5);
    // Delta between 55.0 and 56.5 is -2.7% -> status must be 'parity', NOT false-positive 'regression'
    expect(comp?.deltas.status).toBe('parity');
    expect(comp?.deltas.verdictTitle).toContain('Performance Parity');

    // Render report and verify UI elements
    render(
      <JobDiagnosticsReport
        telemetry={currentTelemetry}
        isLiveJob={false}
        workerPoolSize={32}
        jobName="Current MPS Run"
        jobId="job-current-nominal"
        site="OnlyFans"
        historicalJobs={[baselineJob]}
        initialBaselineJobId="job-fe10c14a96ae"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    // Baseline duration in UI card must show 3m 9s (NOT 14s)
    expect(screen.getByTestId('comparison-row-duration')).toHaveTextContent('3m 9s');
    expect(screen.getByTestId('comparison-status')).toHaveTextContent('Parity');
    expect(screen.queryByText(/^14s$/)).not.toBeInTheDocument();
    // False-positive 95.4% degradation alert must NOT be present
    expect(screen.queryByText(/95\.4% Degradation/i)).not.toBeInTheDocument();
  });

  it('computes baseline run duration using started_at (2m 9s) instead of queue created_at (2m 56s) and flags regression accurately', () => {
    // Baseline job representing job-acf2:
    // created_at: 12:00:00 (enqueued / created)
    // started_at: 12:00:47 (claimed and started executing by worker, 47s after creation)
    // completed_at: 12:02:56 (completed, 129s = 2m 09s active execution)
    // 11,980 completed tasks -> 11,980 / 129 = 92.9 items/s
    const baselineJob: Job = {
      job_id: 'job-acf2',
      job_name: 'MPS 12k Scrape Run Baseline',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-09-16T12:00:00.000Z',
      started_at: '2026-09-16T12:00:47.000Z',
      completed_at: '2026-09-16T12:02:56.000Z',
      task_count: 11980,
      completed_tasks: 11980,
      failed_tasks: 0,
      task_stats: {
        total: 11980,
        completed: 11980,
        failed: 0,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        task_type_counts: {},
      },
    } as unknown as Job;

    // Direct helper check: duration must be 129s (2m 9s), NOT 176s (2m 56s)
    const computedSec = computeJobDurationSeconds(baselineJob);
    expect(computedSec).toBe(129);

    // Current run (job-43d9) with 11,980 tasks in 157s (2m 37s) = 76.3 items/s
    const currentTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      completedTasksCount: 11980,
      totalTasksCount: 11980,
      throughput: {
        ...mockTelemetry.throughput,
        currentItemsPerSec: 76.3,
      },
      finalSummary: {
        ...mockTelemetry.finalSummary,
        totalDurationSec: 157,
        totalDurationFormatted: '2m 37s',
        overallAvgItemsPerSec: 76.3,
        overallAvgTasksPerSec: 76.3,
        jobOutcome: 'completed',
      },
    };

    const comp = computeHistoricalComparison(
      currentTelemetry,
      'job-43d9',
      'Current MPS Run',
      'OnlyFans',
      false,
      baselineJob,
    );

    expect(comp).not.toBeNull();
    // Baseline duration must be 129s = 2m 9s (NOT 2m 56s!)
    expect(comp?.baselineJob?.durationSec).toBe(129);
    expect(comp?.baselineJob?.durationFormatted).toBe('2m 9s');
    expect(comp?.baselineJob?.startedAt).toBe('2026-09-16T12:00:47.000Z');

    // Baseline throughput must be 92.9 items/s (NOT 68.1 items/s!)
    expect(comp?.baselineJob?.avgItemsPerSec).toBe(92.9);

    // Current run (76.3 items/s) vs Baseline (92.9 items/s) is a -17.9% regression!
    expect(comp?.deltas.throughputDeltaPercent).toBe(-17.9);
    expect(comp?.deltas.status).toBe('regression');
    expect(comp?.deltas.verdictTitle).toContain('Throughput Degradation');

    // Render report and verify UI elements reflect 2m 9s and 92.9 items/s
    render(
      <JobDiagnosticsReport
        telemetry={currentTelemetry}
        isLiveJob={false}
        jobName="Current MPS Run"
        jobId="job-43d9"
        historicalJobs={[baselineJob]}
        initialBaselineJobId="job-acf2"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    // Baseline duration in UI card must show 2m 9s (NOT 2m 56s!)
    expect(screen.getByTestId('comparison-row-duration')).toHaveTextContent('2m 9s');
    expect(screen.queryByText('2m 56s')).not.toBeInTheDocument();
    // Baseline throughput in the comparison table must show its unit and correct rate.
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('92.9 items/s');
    expect(screen.queryByText('68.1 items/s')).not.toBeInTheDocument();
    // Must NOT show false-positive +12% improvement
    expect(screen.queryByText(/Throughput Gain/i)).not.toBeInTheDocument();
    expect(screen.getByTestId('comparison-status')).toHaveClass('is-regression');
    expect(screen.getByTestId('comparison-row-duration')).toHaveTextContent('+28s');
    expect(screen.getByTestId('comparison-row-duration').querySelector('.jdr-comparison-change')).toHaveClass('is-negative');
  });

  it('prefers baselineJobDetail over summary historical job when provided', () => {
    // Summary historical job without started_at (falls back to created_at)
    const summaryJob: Job = {
      job_id: 'job-acf2',
      job_name: 'MPS Run Summary',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-09-16T12:00:00.000Z',
      completed_at: '2026-09-16T12:02:56.000Z', // 176s if started_at missing
      task_count: 11980,
      completed_tasks: 11980,
      failed_tasks: 0,
    } as unknown as Job;

    // Detailed baseline job with exact started_at
    const detailedBaselineJob: JobDetail = {
      job_type: 'scrape',
      job_id: 'job-acf2',
      job_name: 'MPS Run Detail',
      status: 'completed',
      site: 'OnlyFans',
      priority: 0,
      worker_id: 'worker-1',
      retries: 0,
      max_retries: 3,
      created_at: '2026-09-16T12:00:00.000Z',
      started_at: '2026-09-16T12:00:47.000Z',
      completed_at: '2026-09-16T12:02:56.000Z', // 129s = 2m 9s
      result_success: true,
      result_message: 'Success',
      result_error: null,
      args: null,
      tasks: [],
      task_stats: {
        total: 11980,
        completed: 11980,
        failed: 0,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        task_type_counts: {},
      },
    };

    const currentTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      completedTasksCount: 11980,
      totalTasksCount: 11980,
      throughput: {
        ...mockTelemetry.throughput,
        currentItemsPerSec: 76.3,
      },
      finalSummary: {
        ...mockTelemetry.finalSummary,
        totalDurationSec: 157,
        totalDurationFormatted: '2m 37s',
        overallAvgItemsPerSec: 76.3,
        overallAvgTasksPerSec: 76.3,
        jobOutcome: 'completed',
      },
    };

    const onBaselineJobChange = vi.fn();

    render(
      <JobDiagnosticsReport
        telemetry={currentTelemetry}
        isLiveJob={false}
        jobName="Current Run"
        jobId="job-43d9"
        historicalJobs={[summaryJob]}
        initialBaselineJobId="job-acf2"
        baselineJobDetail={detailedBaselineJob}
        onBaselineJobChange={onBaselineJobChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    // Notified baseline change on mount
    expect(onBaselineJobChange).toHaveBeenCalledWith('job-acf2');

    // Baseline duration rendered must be 2m 9s from detailed baseline job
    expect(screen.getByTestId('comparison-row-duration')).toHaveTextContent('2m 9s');
    expect(screen.queryByText('2m 56s')).not.toBeInTheDocument();
    expect(screen.getByTestId('comparison-row-throughput')).toHaveTextContent('92.9 items/s');
  });

  it('calculates projected duration (elapsed + ETA) for an ongoing job with jobEta instead of comparing raw elapsed time', () => {
    // Baseline completed job: 1,598,499 tasks in 1,994s (33m 14s)
    const baselineJob: Job = {
      job_id: 'job-baseline-1',
      job_name: 'MPS OnlyFans 2026-10-20 06:55:41 UTC',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-10-20T06:55:41.000Z',
      started_at: '2026-10-20T06:55:41.000Z',
      completed_at: '2026-10-20T07:28:55.000Z',
      task_count: 1598499,
      completed_tasks: 1598499,
      failed_tasks: 0,
    } as unknown as Job;

    // Ongoing job: completed 929,242 tasks out of 1,598,499 in 1,121s (18m 41s)
    const ongoingTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      completedTasksCount: 929242,
      totalTasksCount: 1598499,
      throughput: {
        ...mockTelemetry.throughput,
        currentTasksPerSec: 828.9,
        throughputUnit: 'tasks',
      },
      quality: {
        loadedTaskCount: 929242,
        totalTaskCount: 1598499,
        coveragePercent: 58.1,
        isCompleteTaskSample: false,
        throughputUnit: 'tasks',
        peakScope: 'loaded_sample',
      },
      finalSummary: {
        ...mockTelemetry.finalSummary,
        totalDurationSec: 1121,
        totalDurationFormatted: '18m 41s',
        overallAvgTasksPerSec: 828.9,
        overallAvgItemsPerSec: 828.9,
        jobOutcome: 'running',
        durationSource: 'job_metadata',
      },
    };

    const mockEta: JobEtaResult = {
      status: 'running',
      elapsedSeconds: 1121,
      remainingSeconds: 807,
      formattedElapsed: '18m 41s',
      formattedRemaining: '13m 27s',
      completionDate: new Date(Date.now() + 807 * 1000),
      formattedCompletionTime: '07:42 AM',
      label: 'Est. finish 07:42 AM',
      tooltip: 'Estimated completion at 07:42 AM (~13m 27s left)',
    };

    const comp = computeHistoricalComparison(
      ongoingTelemetry,
      'job-live-mps',
      'Ongoing MPS Run',
      'OnlyFans',
      true,
      baselineJob,
      undefined,
      0.1,
      mockEta,
    );

    expect(comp).not.toBeNull();
    // Must identify as projected duration
    expect(comp?.currentRun.isProjectedDuration).toBe(true);
    // Projected duration should be 1,121s + 807s = 1,928s (32m 8s), NOT raw elapsed 18m 41s
    expect(comp?.currentRun.durationSec).toBe(1928);
    expect(comp?.currentRun.durationFormatted).toBe('32m 8s');
    expect(comp?.currentRun.elapsedSec).toBe(1121);
    expect(comp?.currentRun.elapsedFormatted).toBe('18m 41s');
    expect(comp?.currentRun.remainingSec).toBe(807);
    expect(comp?.currentRun.remainingFormatted).toBe('13m 27s');

    // Delta compared to baseline (1,994s) must be -66s (-1m 6s), NOT false-positive -873s (-14m 33s)
    expect(comp?.deltas.durationDeltaSec).toBe(-66);
    expect(comp?.deltas.durationDeltaPercent).toBeCloseTo(-3.3, 1);
    expect(comp?.deltas.durationComparable).toBe(true);

    // Render in UI
    render(
      <JobDiagnosticsReport
        telemetry={ongoingTelemetry}
        isLiveJob={true}
        jobEta={mockEta}
        jobName="Ongoing MPS Run"
        jobId="job-live-mps"
        historicalJobs={[baselineJob]}
        initialBaselineJobId="job-baseline-1"
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    const durationRow = screen.getByTestId('comparison-row-duration');
    expect(durationRow).toHaveTextContent('Projected');
    expect(durationRow).toHaveTextContent('~32m 8s');
    expect(durationRow).toHaveTextContent('Elapsed 18m 41s');
    expect(durationRow).toHaveTextContent('33m 14s');
    // Delta must show ~−1m 6s, NOT −14m 33s
    expect(durationRow).toHaveTextContent('~−1m 6s');
    expect(screen.queryByText('−14m 33s')).not.toBeInTheDocument();

    const tasksRow = screen.getByTestId('comparison-row-completed-tasks');
    expect(tasksRow).toHaveTextContent('929,242');
    expect(tasksRow).toHaveTextContent('of 1,598,499');
  });

  it('derives projected duration using remaining tasks and throughput when jobEta is omitted for an ongoing job', () => {
    const baselineJob: Job = {
      job_id: 'job-baseline-2',
      job_name: 'Baseline Run',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-10-20T06:00:00.000Z',
      started_at: '2026-10-20T06:00:00.000Z',
      completed_at: '2026-10-20T06:03:20.000Z', // 200s
      task_count: 10000,
      completed_tasks: 10000,
      failed_tasks: 0,
    } as unknown as Job;

    // Ongoing job: 5,000 tasks done out of 10,000 in 100s -> 50 tasks/s, 5,000 remaining -> ETA 100s -> projected 200s
    const ongoingTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      completedTasksCount: 5000,
      totalTasksCount: 10000,
      throughput: {
        ...mockTelemetry.throughput,
        currentTasksPerSec: 50,
        throughputUnit: 'tasks',
      },
      errorVelocity: {
        ...mockTelemetry.errorVelocity,
        totalErrors: 0,
      },
      quality: {
        loadedTaskCount: 5000,
        totalTaskCount: 10000,
        coveragePercent: 50,
        isCompleteTaskSample: false,
        throughputUnit: 'tasks',
        peakScope: 'loaded_sample',
      },
      finalSummary: {
        ...mockTelemetry.finalSummary,
        totalDurationSec: 100,
        totalDurationFormatted: '1m 40s',
        overallAvgTasksPerSec: 50,
        overallAvgItemsPerSec: 50,
        jobOutcome: 'running',
        durationSource: 'job_metadata',
      },
    };

    const comp = computeHistoricalComparison(
      ongoingTelemetry,
      'job-ongoing-derived',
      'Derived Ongoing Job',
      'OnlyFans',
      true,
      baselineJob,
    );

    expect(comp).not.toBeNull();
    expect(comp?.currentRun.isProjectedDuration).toBe(true);
    expect(comp?.currentRun.durationSec).toBe(200);
    expect(comp?.currentRun.durationFormatted).toBe('3m 20s');
    expect(comp?.currentRun.elapsedSec).toBe(100);
    expect(comp?.currentRun.remainingSec).toBe(100);
    // Delta should be 0s parity with baseline (200s vs 200s)
    expect(comp?.deltas.durationDeltaSec).toBe(0);
  });

  it('marks duration change as in-progress when ongoing job has unknown total tasks', () => {
    const baselineJob: Job = {
      job_id: 'job-baseline-3',
      job_name: 'Baseline Run',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-10-20T06:00:00.000Z',
      started_at: '2026-10-20T06:00:00.000Z',
      completed_at: '2026-10-20T06:03:20.000Z',
      task_count: 10000,
      completed_tasks: 10000,
      failed_tasks: 0,
    } as unknown as Job;

    // Ongoing job without total tasks count: totalTasksCount: 0
    const ongoingTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      completedTasksCount: 5000,
      totalTasksCount: 0,
      throughput: {
        ...mockTelemetry.throughput,
        currentTasksPerSec: 50,
        throughputUnit: 'tasks',
      },
      finalSummary: {
        ...mockTelemetry.finalSummary,
        totalDurationSec: 100,
        totalDurationFormatted: '1m 40s',
        overallAvgTasksPerSec: 50,
        overallAvgItemsPerSec: 50,
        jobOutcome: 'running',
        durationSource: 'job_metadata',
      },
    };

    const comp = computeHistoricalComparison(
      ongoingTelemetry,
      'job-ongoing-unknown',
      'Unknown Total Tasks Job',
      'OnlyFans',
      true,
      baselineJob,
    );

    expect(comp).not.toBeNull();
    expect(comp?.currentRun.isProjectedDuration).toBe(false);
    expect(comp?.deltas.durationComparable).toBe(false);

    render(
      <JobDiagnosticsReport
        telemetry={ongoingTelemetry}
        isLiveJob={true}
        jobName="Unknown Total Tasks Job"
        jobId="job-ongoing-unknown"
        historicalJobs={[baselineJob]}
        initialBaselineJobId="job-baseline-3"
        taskCountTolerancePercent={1000}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Compare/i }));
    const durationRow = screen.getByTestId('comparison-row-duration');
    expect(durationRow).toHaveTextContent('In progress');
  });

  it('computes throughputDiagnostics identifying capacity gap, idle routes, and tail drag', () => {
    const jobWithDeficit: Job = {
      job_id: 'job-deficit-test',
      job_name: 'MPS 464 Concurrency Test',
      status: 'completed',
      created_at: '2026-09-16T12:00:00.000Z',
      completed_at: '2026-09-16T12:02:00.000Z', // 120s
      task_count: 5000,
      completed_tasks: 5000,
      failed_tasks: 10,
      metadata: {
        include_direct_connection: false,
        proxy_capacity: 464,
        target_concurrency: 4, // 8 workers * 4 concurrency = 32 slots << 464 routes
      },
    } as unknown as Job;

    // 464 proxies
    const dummyProxies = Array.from({ length: 464 }, (_, i) => `http://10.0.0.${i}:8080`) as unknown as NetworkProxy[];

    // Tasks with median ~1.2s and tail ~4.8s
    const sampleTasks: TaskDetail[] = [
      ...Array.from({ length: 90 }, (_, i) => ({
        task_id: `task-fast-${i}`,
        status: 'completed',
        items_processed: 1,
        started_at: '2026-09-16T12:00:00.000Z',
        completed_at: '2026-09-16T12:00:01.200Z',
      } as unknown as TaskDetail)),
      ...Array.from({ length: 10 }, (_, i) => ({
        task_id: `task-slow-${i}`,
        status: 'completed',
        items_processed: 1,
        started_at: '2026-09-16T12:00:00.000Z',
        completed_at: '2026-09-16T12:00:04.800Z',
      } as unknown as TaskDetail)),
      {
        task_id: 'task-429',
        status: 'failed',
        error: 'HTTP 429 Too Many Requests',
        started_at: '2026-09-16T12:00:00.000Z',
        completed_at: '2026-09-16T12:00:02.000Z',
      } as unknown as TaskDetail,
    ];

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        jobWithDeficit,
        undefined,
        sampleTasks,
        dummyProxies,
        false,
        8, // 8 workers
      ),
    );

    const diag = result.current.throughputDiagnostics;
    expect(diag).toBeDefined();
    expect(diag?.theoreticalProxyMaxItemsPerSec).toBeGreaterThan(300); // 464 / 1.2s ≈ 386.7
    expect(diag?.theoreticalWorkerMaxItemsPerSec).toBeLessThan(50); // 32 slots / 1.2s ≈ 26.7
    expect(diag?.governingBottleneck).toBe('worker_concurrency');
    expect(diag?.idleProxyRoutes).toBeGreaterThan(350);
    expect(diag?.idleProxyPercent).toBeGreaterThan(70);
    expect(diag?.latencySpreadRatio).toBeGreaterThanOrEqual(3.5); // 4.8 / 1.2 = 4.0
    expect(diag?.tailLatencyDragPercent).toBeGreaterThan(0);

    // Loss factors
    const factorNames = diag?.lossFactors.map((f) => f.factor) ?? [];
    expect(factorNames).toContain('Insufficient Runtime Telemetry');
    expect(factorNames).not.toContain('Worker Concurrency Deficit');
    expect(factorNames).not.toContain('Tail Latency Drag');
    expect(factorNames).toContain('Upstream Rate Limiting (HTTP 429)');
  });

  it('does not call live throughput nominal when runtime measurements are missing', () => {
    const job = {
      job_id: 'job-ledger-incomplete', job_name: 'Ledger run', status: 'running',
      created_at: '2026-10-03T00:00:00.000Z', task_count: 32300,
      completed_tasks: 3469, failed_tasks: 0, metadata: { proxy_capacity: 1656 },
    } as unknown as Job;
    const { result } = renderHook(() => useJobDiagnosticsTelemetry(job, undefined, [], [], true, 8));
    expect(result.current.finalSummary.runtimeTelemetryComplete).toBe(false);
    expect(result.current.finalSummary.recommendations.join(' ')).toMatch(/runtime telemetry is incomplete/i);
    expect(result.current.finalSummary.recommendations.join(' ')).not.toMatch(/nominal|no anomalies/i);
  });

  it('uses complete runtime aggregates for mean-duration efficiency and phase diagnosis', () => {
    const completedJob = {
      job_id: 'job-runtime-aggregate',
      job_name: 'Runtime Aggregate',
      status: 'completed',
      site: 'OnlyFans',
      created_at: '2026-09-20T00:00:00.000Z',
      started_at: '2026-09-20T00:00:00.000Z',
      completed_at: '2026-09-20T00:00:10.000Z',
      task_count: 100,
      completed_tasks: 100,
      failed_tasks: 0,
      metadata: { proxy_capacity: 100 },
    } as unknown as Job;
    const details = {
      ...completedJob,
      task_stats: {
        total: 100,
        ready: 0,
        blocked: 0,
        inflight: 0,
        deferred: 0,
        completed: 100,
        failed: 0,
        task_type_counts: { scrape: 100 },
      },
      error_stats: { total: 0, groups: {} },
      runtime_telemetry: {
        version: 1,
        scope: 'full_job_aggregate',
        task_count: 100,
        succeeded_tasks: 100,
        failed_tasks: 0,
        first_started_at: '2026-09-20T00:00:00.000Z',
        last_finished_at: '2026-09-20T00:00:10.000Z',
        active_window_ms: 10_000,
        task_duration_sum_ms: 200_000,
        mean_task_duration_ms: 2_000,
        mean_queue_wait_ms: 30_000,
        mean_setup_ms: 100,
        mean_handler_ms: 1_600,
        mean_handler_exclusive_ms: 600,
        mean_handler_guest_init_ms: 100,
        handler_guest_init_count: 200,
        mean_handler_initial_lookup_ms: 350,
        handler_initial_lookup_count: 200,
        mean_handler_refresh_api_ms: 75,
        handler_refresh_api_count: 100,
        mean_handler_fallback_retry_ms: 50,
        handler_fallback_retry_count: 100,
        mean_handler_serialization_ms: 25,
        handler_serialization_count: 100,
        mean_writer_ms: 1_000,
        mean_post_ms: 100,
        mean_release_ms: 100,
        time_weighted_inflight: 20,
        route_attempts: 200,
        route_active_sum_ms: 100_000,
        time_weighted_active_routes: 10,
        mean_claim_wait_ms: 5,
        mean_writer_admission_ms: 10,
        mean_writer_admission_serialization_ms: 1,
        mean_writer_admission_capacity_wait_ms: 5,
        mean_writer_admission_redis_ms: 2,
        mean_writer_admission_overhead_detail_ms: 2,
        mean_writer_queue_ms: 700,
        mean_writer_execution_ms: 200,
        mean_writer_commit_ms: 50,
        mean_writer_overhead_ms: 25,
        mean_writer_batch_peer_work_ms: 20,
        mean_writer_delivery_ms: 15,
        mean_writer_result_publication_ms: 9,
        mean_writer_result_observation_ms: 5,
        mean_writer_result_delivery_residual_ms: 1,
        writer_result_delivery_split_coverage_ratio: 0.9,
        writer_result_cache_hits: 90,
        writer_receipt_fallbacks: 10,
        writer_result_cache_hit_ratio: 0.9,
        writer_split_missing_reasons: { result_cache_miss: 10 },
        writer_operation_stats: {
          upsert_user: {
            count: 80,
            mean_batch_commands: 50,
            mean_batch_wall_ms: 125,
          },
        },
        writer_domain_stats: {
          user: {
            count: 80,
            mean_batch_commands: 50,
            mean_batch_wall_ms: 125,
          },
        },
        writer_timed_submits: 100,
        writer_timing_coverage_ratio: 1,
        mean_writer_connection_checkout_ms: 2,
        mean_writer_receipt_lookup_ms: 4,
        mean_writer_receipt_finalize_ms: 6,
        mean_writer_payload_ms: 8,
        mean_writer_user_row_ms: 10,
        mean_writer_alias_ms: 12,
        mean_writer_authority_ms: 14,
        writer_authority_rows_examined: 200,
        writer_authority_rows_skipped: 150,
        writer_authority_rows_upserted: 50,
        mean_writer_profile_ms: 30,
        mean_writer_social_ms: 18,
        mean_writer_flush_ms: 20,
        mean_writer_queue_commands_at_start: 600,
        max_writer_queue_commands_at_start: 800,
        mean_writer_queue_bytes_at_start: 1_048_576,
        max_writer_queue_bytes_at_start: 2_097_152,
        mean_writer_active_lanes: 7.5,
        max_writer_active_lanes: 8,
        mean_writer_batch_commands: 80,
        mean_writer_batch_fill_ratio: 0.8,
        mean_writer_lane_idle_ms: 11,
        mean_writer_lane_predecessor_wait_ms: 12,
        mean_writer_refill_wait_ms: 13,
        writer_configured_concurrency: 8,
        writer_configured_batch_size: 100,
        writer_window_commands: 800,
        writer_queue_max_commands: 800,
        writer_queue_max_bytes: 268_435_456,
        writer_refill_min_commands: 50,
        writer_refill_min_commands_per_lane: 75,
        max_worker_completion_gap_ms: 95_300,
        ready_queue_recovery_count: 0,
        ready_queue_recovered_tasks: 0,
        steady_task_count: 80,
        steady_window_ms: 8_000,
        steady_throughput: 10,
        steady_mean_task_duration_ms: 2_000,
        ramp_window_ms: 1_000,
        drain_window_ms: 1_000,
        ready_nonempty_ratio: 1,
        mean_ready_depth: 50,
        max_ready_depth: 90,
        workers_seen: 10,
        expected_workers: 10,
        time_weighted_participating_workers: 9.8,
        time_weighted_effective_worker_capacity: 98,
      },
    } as unknown as JobDetail;

    const { result } = renderHook(() =>
      useJobDiagnosticsTelemetry(completedJob, details, [], undefined, false, 10),
    );

    expect(result.current.finalSummary.runtimeTelemetryComplete).toBe(true);
    expect(result.current.finalSummary.meanTaskDurationSec).toBe(2);
    expect(result.current.finalSummary.meanHandlerSec).toBe(0.6);
    expect(result.current.finalSummary.avgActiveConcurrency).toBe(20);
    expect(result.current.finalSummary.avgActiveProxyRoutes).toBe(10);
    expect(result.current.finalSummary.activeWindowThroughput).toBe(10);
    // Measured effective worker capacity (98 slots) / 2s mean duration, not configured 10 × 10.
    expect(result.current.finalSummary.theoreticalMaxItemsPerSec).toBe(49);
    expect(result.current.finalSummary.theoreticalProxyMaxItemsPerSec).toBe(100);
    expect(result.current.finalSummary.theoreticalWorkerMaxItemsPerSec).toBe(49);
    expect(result.current.finalSummary.capacityModelBottleneck).toBe('worker_slots');
    expect(result.current.finalSummary.meanRouteActiveDurationSec).toBe(1);
    expect(result.current.finalSummary.meanRouteAttemptDurationSec).toBe(0.5);
    expect(result.current.finalSummary.routeAttemptsPerTask).toBe(2);
    expect(result.current.finalSummary.meanHandlerInitialLookupMs).toBe(350);
    expect(result.current.finalSummary.meanHandlerResidualMs).toBe(0);
    expect(result.current.finalSummary.dominantHandlerSubphase).toBe('Initial User Lookup');
    expect(result.current.finalSummary.efficiencyPercent).toBe(20.4);
    expect(result.current.finalSummary.steadyStateEfficiencyPercent).toBe(20.4);
    // Ready-queue sample ratios are not time-based evidence, so the gap stays unattributed.
    expect(result.current.finalSummary.occupancyGapClassification).toBe('insufficient_data');
    expect(result.current.finalSummary.occupancyGapExplanation).toContain(
      'Task-completion samples and lifetime intervals cannot distinguish',
    );
    expect(result.current.finalSummary.dominantWriterSubphase).toBe('Writer Queue');
    expect(result.current.finalSummary.writerTimingCoveragePercent).toBe(100);
    expect(result.current.finalSummary.dominantWriterExecutionSubphase).toBe(
      'Profile Records',
    );
    expect(result.current.finalSummary.writerConfiguredConcurrency).toBe(8);
    expect(result.current.finalSummary.meanWriterActiveLanes).toBe(7.5);
    expect(result.current.finalSummary.meanWriterAdmissionCapacityWaitMs).toBe(5);
    expect(result.current.finalSummary.meanWriterResultPublicationMs).toBe(9);
    expect(result.current.finalSummary.meanWriterResultObservationMs).toBe(5);
    expect(result.current.finalSummary.meanWriterResultDeliveryResidualMs).toBe(1);
    expect(result.current.finalSummary.writerResultDeliverySplitCoveragePercent).toBe(90);
    expect(result.current.finalSummary.meanWriterBatchPeerWorkMs).toBe(20);
    expect(result.current.finalSummary.writerTimedSubmits).toBe(100);
    expect(result.current.finalSummary.writerSubmitsPerTask).toBe(1);
    expect(result.current.finalSummary.writerSubmitsPerSec).toBe(10);
    expect(result.current.finalSummary.writerResultCacheHitPercent).toBe(90);
    expect(result.current.finalSummary.writerReceiptFallbacks).toBe(10);
    expect(result.current.finalSummary.writerAuthorityRowsExamined).toBe(200);
    expect(result.current.finalSummary.writerAuthorityRowsSkipped).toBe(150);
    expect(result.current.finalSummary.writerAuthorityRowsUpserted).toBe(50);
    expect(result.current.finalSummary.writerAuthoritySkipPercent).toBe(75);
    expect(result.current.finalSummary.writerOperationStats?.upsert_user.mean_batch_commands).toBe(50);
    expect(result.current.finalSummary.meanWriterBatchFillPercent).toBe(80);
    expect(result.current.finalSummary.writerWindowCommands).toBe(800);
    expect(result.current.finalSummary.maxWriterQueueCommandsAtStart).toBe(800);
    expect(result.current.finalSummary.writerRefillMinCommands).toBe(50);
    expect(result.current.bottleneckAnalysis.state).toBe('writer_constrained');
    expect(result.current.bottleneckAnalysis.label).toBe(
      'Writer Queue / Admission Backpressure',
    );
    expect(result.current.bottleneckAnalysis.rootCauseFindings).toContain(
      'Dominant task service phase: Writer Queue / Admission Backpressure at 1.00s per task; primary measured subphase: Writer Queue.',
    );
    expect(result.current.bottleneckAnalysis.rootCauseFindings).toContain(
      'Writer profiling covers 100% of acknowledged writes. The largest measured subphase is Writer Queue at 0.700s per task.',
    );
    expect(result.current.throughputDiagnostics?.lossFactors[0].factor).toBe(
      'Writer Queue / Admission Backpressure',
    );
    expect(result.current.finalSummary.recommendations[0]).toMatch(
      /cannot distinguish steady-state work-supply gaps/i,
    );
    expect(result.current.finalSummary.recommendations[1]).toMatch(/writer queue/i);
    const handlerDominantDetails = {
      ...details,
      runtime_telemetry: {
        ...(details.runtime_telemetry as NonNullable<JobDetail['runtime_telemetry']>),
        mean_handler_ms: 5_819,
        mean_handler_exclusive_ms: 3_434,
        mean_writer_ms: 2_385,
        mean_handler_initial_lookup_ms: 2_088.81,
      },
    } as unknown as JobDetail;

    const { result: handlerDominantResult } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        completedJob,
        handlerDominantDetails,
        [],
        undefined,
        false,
        10,
      ),
    );

    expect(handlerDominantResult.current.bottleneckAnalysis.state).toBe('handler_constrained');
    expect(handlerDominantResult.current.bottleneckAnalysis.label).toBe(
      'Handler / Upstream Time Dominant',
    );
    expect(handlerDominantResult.current.bottleneckAnalysis.rootCauseFindings).toContain(
      'Dominant task service phase: Handler / Upstream Work at 3.43s per task; primary measured subphase: Initial User Lookup.',
    );
    expect(handlerDominantResult.current.throughputDiagnostics?.lossFactors[0].factor).toBe(
      'Handler / Upstream Work',
    );
    expect(handlerDominantResult.current.finalSummary.recommendations[0]).toMatch(
      /cannot distinguish steady-state work-supply gaps/i,
    );
    expect(handlerDominantResult.current.finalSummary.recommendations[1]).toMatch(
      /handler work is the largest measured phase/i,
    );
    expect(handlerDominantResult.current.finalSummary.recommendations[2]).toMatch(
      /secondary service-time target: writer queue wait/i,
    );
    const intermittentSupplyDetails = {
      ...details,
      runtime_telemetry: {
        ...(details.runtime_telemetry as NonNullable<JobDetail['runtime_telemetry']>),
        ready_nonempty_ratio: 0.605,
        mean_claim_wait_ms: 9.58,
        mean_handler_ms: 6_320,
        mean_handler_exclusive_ms: 1_278,
        mean_writer_ms: 5_042,
        mean_writer_queue_ms: 2_972.76,
        mean_writer_admission_ms: 1_621.1,
        mean_writer_execution_ms: 22.15,
        mean_writer_commit_ms: 1.16,
        mean_writer_batch_fill_ratio: 0.055,
        writer_timing_coverage_ratio: 0.738,
      },
    } as unknown as JobDetail;

    // 1 Hz ready-queue timeline: non-empty for 5 of the 8 steady-state seconds (62.5%).
    const runStartMs = Date.parse('2026-09-20T00:00:00.000Z');
    const intermittentReadyTimeline: JobRuntimeSample[] = Array.from({ length: 11 }, (_, second) => ({
      cursor: `${second}`,
      timestamp_ms: runStartMs + second * 1_000,
      total: 100,
      ready: second >= 1 && second <= 5 ? 5 : 0,
      inflight: 10,
      completed: second * 10,
      failed: 0,
    }));
    const { result: intermittentSupplyResult } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        completedJob,
        intermittentSupplyDetails,
        [],
        undefined,
        false,
        10,
        undefined,
        intermittentReadyTimeline,
      ),
    );

    expect(intermittentSupplyResult.current.finalSummary.occupancyGapClassification).toBe(
      'intermittent_ready_supply',
    );
    expect(intermittentSupplyResult.current.bottleneckAnalysis.state).toBe(
      'writer_constrained',
    );
    expect(intermittentSupplyResult.current.bottleneckAnalysis.label).toBe(
      'Writer Queue / Admission Backpressure',
    );
    expect(intermittentSupplyResult.current.finalSummary.recommendations[0]).toMatch(
      /writer batching is fragmented/i,
    );
    expect(intermittentSupplyResult.current.finalSummary.recommendations[1]).toMatch(
      /occupancy observation:.*intermittent runnable-work supply/i,
    );
    const stalledDetails = {
      ...details,
      runtime_telemetry: {
        ...(details.runtime_telemetry as NonNullable<JobDetail['runtime_telemetry']>),
        ready_queue_recovery_count: 1,
        ready_queue_recovered_tasks: 76,
        max_worker_completion_gap_ms: 95_300,
      },
    } as unknown as JobDetail;

    const { result: stalledResult } = renderHook(() =>
      useJobDiagnosticsTelemetry(completedJob, stalledDetails, [], undefined, false, 10),
    );

    expect(stalledResult.current.finalSummary.occupancyGapClassification).toBe('routing_stall');
    expect(stalledResult.current.finalSummary.readyQueueRecoveredTasks).toBe(76);
    expect(stalledResult.current.bottleneckAnalysis.state).toBe('routing_stall');
    expect(stalledResult.current.bottleneckAnalysis.label).toBe('Ready-Queue Routing Stall');
    expect(stalledResult.current.finalSummary.recommendations[0]).toMatch(
      /routing recovery restored 76 ready tasks/i,
    );

    const aboveModelDetails = {
      ...details,
      runtime_telemetry: {
        ...(details.runtime_telemetry as NonNullable<JobDetail['runtime_telemetry']>),
        steady_throughput: 60,
      },
    } as unknown as JobDetail;
    const { result: aboveModelResult } = renderHook(() =>
      useJobDiagnosticsTelemetry(completedJob, aboveModelDetails, [], undefined, false, 10),
    );
    expect(aboveModelResult.current.finalSummary.steadyStateCapacityItemsPerSec).toBe(49);
    expect(aboveModelResult.current.finalSummary.steadyStateEfficiencyPercent).toBe(122.4);

    const shortMetadataJob = {
      ...completedJob,
      completed_at: '2026-09-20T00:00:05.000Z',
    } as unknown as Job;
    const shortMetadataDetails = {
      ...details,
      completed_at: '2026-09-20T00:00:05.000Z',
    } as unknown as JobDetail;
    const { result: durationGuardResult } = renderHook(() =>
      useJobDiagnosticsTelemetry(
        shortMetadataJob,
        shortMetadataDetails,
        [],
        undefined,
        false,
        10,
      ),
    );
    expect(durationGuardResult.current.finalSummary.durationSource).toBe(
      'task_active_window',
    );
    expect(durationGuardResult.current.finalSummary.totalDurationSec).toBe(10);
    expect(durationGuardResult.current.finalSummary.overallAvgItemsPerSec).toBe(10);
    expect(durationGuardResult.current.finalSummary.durationDiscrepancyPercent).toBe(-50);
    expect(durationGuardResult.current.finalSummary.recommendations[0]).toMatch(
      /metadata duration.*shorter.*task-active window/i,
    );
  });

  it('renders and exports nested ledger admission and SQL timings', () => {
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    render(<JobDiagnosticsReport isLiveJob={false} jobId="job-ledger" jobName="Ledger timing" telemetry={{
      ...mockTelemetry,
      chartSnapshots: [],
      mpsRefillTrace: [],
      ledgerStats: {
        writer_prepare: { ms: 120, count: 2 },
        writer_prepare_execution: { ms: 40, count: 2 },
        writer_prepare_admission: { ms: 80, count: 2 },
        writer_prepare_batch_wait_admission: { ms: 45, count: 2 },
      },
    }} />);
    expect(screen.getByText('Ledger Checkpoint Timing')).toBeInTheDocument();
    expect(screen.getByText('writer prepare')).toBeInTheDocument();
    expect(screen.getByText('Mean admission and dispatch')).toBeInTheDocument();
    expect(screen.getByText('Mean batch queue wait')).toBeInTheDocument();
    expect(screen.getByText('22.50ms')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Copy Markdown Report/i }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('| writer_prepare | 2 | 60.00ms | 20.00ms | 40.00ms | 22.50ms |'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('These spans are nested, not additional task phases.'),
    );
  });

  it('renders enriched Markdown report with structured tables, throughput loss decomposition, and tuning knobs', () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockImplementation(() => Promise.resolve()),
      },
    });

    const enrichedTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      finalSummary: {
        ...mockTelemetry.finalSummary,
        writerAuthorityRowsExamined: 200,
        writerAuthorityRowsSkipped: 150,
        writerAuthorityRowsUpserted: 50,
        writerAuthoritySkipPercent: 75,
      },
      throughputDiagnostics: {
        theoreticalProxyMaxItemsPerSec: 244.2,
        theoreticalWorkerMaxItemsPerSec: 100.0,
        governingCeilingItemsPerSec: 100.0,
        governingBottleneck: 'worker_concurrency',
        activeConcurrency: 54,
        idleProxyRoutes: 410,
        idleProxyPercent: 88.4,
        proxyUtilizationPercent: 11.6,
        workerUtilizationPercent: 54.0,
        workerPoolSize: 8,
        workerConcurrencyDemand: 100,
        targetConcurrency: 12,
        latencySpreadRatio: 3.2,
        tailLatencyDragPercent: 28.5,
        peakToAvgRatio: 1.8,
        lossFactors: [
          {
            factor: 'Insufficient Runtime Telemetry',
            severity: 'moderate',
            estimatedLossItemsPerSec: 0,
            description: 'Worker participation, ready-queue supply, and full-job phase measurements are unavailable.',
            remedy: 'Use a telemetry-complete run before changing worker concurrency or claim-batch size.',
          },
        ],
      },
    };

    render(
      <JobDiagnosticsReport
        telemetry={enrichedTelemetry}
        isLiveJob={false}
        workerPoolSize={8}
        jobName="MPS Full Scrape Benchmark"
        jobId="job-diag-enriched"
        site="OnlyFans"
      />,
    );

    // Verify Throughput Constraint Factors are rendered in the UI
    expect(screen.queryByText(/Throughput Constraint Factors:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Insufficient Runtime Telemetry/i)).not.toBeInTheDocument();

    // Click Copy Markdown Report
    const copyReportButtons = screen.getAllByRole('button', { name: /Copy/i });
    fireEvent.click(copyReportButtons[0]);

    // Check table headers and enriched markdown content
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('### Performance & Capacity Utilization Summary:'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('### Writer SQL / User-Sync Detail:'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('200 examined; 150 unchanged skipped; 50 upserted (75% skipped)'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('### Writer Configuration & Pressure:'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('### Throughput Gap & Efficiency Loss Decomposition:'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Dominant Task Service Phase:**'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('- **Primary Measured Service Subphase:**'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('| **Insufficient Runtime Telemetry** | `MODERATE` | Unavailable (telemetry gap) |'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('2 observed proxies had an average latency of 3.15s.'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('### HTTP Response Breakdown Table:'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('### Environment Tuning Guardrail:'),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('Runtime telemetry is incomplete; this report cannot establish that worker concurrency or claim batching is limiting.'),
    );
  });

  it('automatically transitions from live view to final run report when job finishes', () => {
    const liveTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      finalSummary: {
        ...mockTelemetry.finalSummary,
        jobOutcome: 'running',
        overallAvgItemsPerSec: 35.5,
        peakItemsPerSec: 50.0,
      },
    };

    const runningJob: Job = {
      job_id: 'job-live-transition',
      job_name: 'Test Active Run',
      status: 'running',
      created_at: new Date(Date.now() - 30000).toISOString(),
      updated_at: new Date().toISOString(),
      task_count: 100,
      completed_tasks: 20,
      failed_tasks: 0,
    };

    const { rerender } = render(
      <JobDiagnosticsReport
        telemetry={liveTelemetry}
        isLiveJob={true}
        workerPoolSize={8}
        currentJob={runningJob}
        jobName="Test Active Run"
        jobId="job-live-transition"
        site="OnlyFans"
      />,
    );

    // While job is active, live telemetry is active and final report banner is not visible
    expect(screen.getByRole('button', { name: 'Telemetry' })).toHaveClass('active');
    expect(screen.queryByText(/Final Run Performance Verdict/i)).not.toBeInTheDocument();

    // Now the job finishes (becomes terminal status and isLiveJob = false)
    const completedJob: Job = {
      ...runningJob,
      status: 'completed',
      last_activity_at: new Date().toISOString(),
      completed_tasks: 100,
    };
    const completedTelemetry: JobDiagnosticsTelemetry = {
      ...mockTelemetry,
      finalSummary: {
        ...mockTelemetry.finalSummary,
        jobOutcome: 'completed',
        overallAvgItemsPerSec: 41.2,
        peakItemsPerSec: 52.0,
      },
    };

    rerender(
      <JobDiagnosticsReport
        telemetry={completedTelemetry}
        isLiveJob={false}
        workerPoolSize={8}
        currentJob={completedJob}
        jobName="Test Active Run"
        jobId="job-live-transition"
        site="OnlyFans"
      />,
    );

    // The same tab now shows averages and the final performance verdict.
    expect(screen.getByRole('button', { name: 'Telemetry' })).toHaveClass('active');
    expect(screen.queryByRole('button', { name: 'Live Telemetry' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Final Run Performance Verdict/i)).not.toBeInTheDocument();
    expect(screen.getByRole('meter', { name: 'Throughput and observed burst' })).toHaveAttribute('aria-valuetext', expect.stringContaining('observed burst: 52'));
    expect(screen.queryByText(/Observed burst 52/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Average Metrics')).not.toBeInTheDocument();
    expect(screen.getByText('Throughput').closest('.jdr-perf-card')).toHaveTextContent('41.2');
    expect(screen.getByText('In Flight').closest('.jdr-perf-card')).toHaveTextContent('active tasks');
    expect(screen.getByText('Average Proxy Usage')).toBeInTheDocument();
    expect(screen.getAllByText(/41.2/i).length).toBeGreaterThan(0);
  });

  describe('MPS Diagnostics UI Clean Up & Progressive Disclosure', () => {
    it('removes diagnostic warning banner while preserving tooltips and underlying quality metadata', () => {
      const sampledTelemetry: JobDiagnosticsTelemetry = {
        ...mockTelemetry,
        quality: {
          isCompleteTaskSample: false,
          loadedTaskCount: 100,
          totalTaskCount: 713952,
          throughputUnit: 'items',
          coveragePercent: 0.014,
          peakScope: 'loaded_sample',
        },
        finalSummary: {
          ...mockTelemetry.finalSummary,
          runtimeTelemetryComplete: false,
        },
      };

      render(
        <JobDiagnosticsReport
          telemetry={sampledTelemetry}
          isLiveJob={false}
          workerPoolSize={8}
        />,
      );

      // Verify the large diagnostic notice warning banner is removed
      expect(screen.queryByRole('status')).not.toBeInTheDocument();
      expect(
        screen.queryByText(/rates, peaks, latency, errors, and proxy breakdowns are based on the loaded task sample/i),
      ).not.toBeInTheDocument();

      // Verify metric-level tooltip communicates uncertainty without a large banner
      const throughputCard = screen.getByText('Estimated Model Efficiency').closest('.jdr-perf-card');
      expect(throughputCard).not.toHaveAttribute('title');
      fireEvent.focus(screen.getByRole('button', { name: 'Model efficiency methodology' }));
      expect(screen.getByRole('tooltip')).toHaveTextContent('100 loaded tasks');
    });

    it('collapses Terminal State and Timing sections by default and supports expanding', () => {
      const timingTelemetry: JobDiagnosticsTelemetry = {
        ...mockTelemetry,
        ledgerStats: {
          writer_prepare: { ms: 120, count: 2 },
          writer_prepare_execution: { ms: 40, count: 2 },
          writer_prepare_admission: { ms: 80, count: 2 },
        },
        terminalStats: {
          before_counter: { ms: 50, count: 5 },
          counter_transition: { ms: 10, count: 5 },
        },
      };

      render(
        <JobDiagnosticsReport
          telemetry={timingTelemetry}
          isLiveJob={false}
          workerPoolSize={8}
        />,
      );

      // Ledger Checkpoint Timing is collapsed by default
      const ledgerToggle = screen.getByRole('button', { name: /Ledger Checkpoint Timing/i });
      expect(ledgerToggle).toHaveAttribute('aria-expanded', 'false');
      expect(ledgerToggle).toHaveTextContent('▶');

      // Terminal State Timing Detail is collapsed by default
      const terminalToggle = screen.getByRole('button', { name: /Terminal State Timing Detail/i });
      expect(terminalToggle).toHaveAttribute('aria-expanded', 'false');
      expect(terminalToggle).toHaveTextContent('▶');

      // Click to expand Ledger Checkpoint Timing
      fireEvent.click(ledgerToggle);
      expect(ledgerToggle).toHaveAttribute('aria-expanded', 'true');
      expect(ledgerToggle).toHaveTextContent('▼');

      // Click to expand Terminal State Timing Detail
      fireEvent.click(terminalToggle);
      expect(terminalToggle).toHaveAttribute('aria-expanded', 'true');
      expect(terminalToggle).toHaveTextContent('▼');
    });

    it('moves proxy route explanations into contextual tooltip and collapses route lookup table', () => {
      const routeStatsTelemetry: JobDiagnosticsTelemetry = {
        ...mockTelemetry,
        finalSummary: {
          ...mockTelemetry.finalSummary,
          routeLookupStats: null, // unavailable route timings
        },
      };

      render(
        <JobDiagnosticsReport
          telemetry={routeStatsTelemetry}
          isLiveJob={false}
          workerPoolSize={8}
        />,
      );

      const routeTableContainer = screen.getByTestId('route-lookup-attribution');
      expect(routeTableContainer).toHaveClass('is-collapsed');

      // The explanation paragraph is NOT in the main dashboard layout
      expect(
        screen.queryByText(/Route IDs are opaque labels; proxy hosts and credentials are omitted/i),
      ).not.toBeInTheDocument();

      // The standalone unavailable message is NOT in the main dashboard layout
      expect(
        screen.queryByText(/Per-route timings are unavailable for this run or backend version/i),
      ).not.toBeInTheDocument();

      // Info tooltip icon exists
      const infoBtn = screen.getByRole('button', { name: /Route lookup timing explanation/i });
      expect(infoBtn).toBeInTheDocument();
      expect(infoBtn).toHaveAttribute('aria-expanded', 'false');

      // Clicking info icon opens tooltip popover
      fireEvent.click(infoBtn);
      expect(infoBtn).toHaveAttribute('aria-expanded', 'true');
      expect(
        screen.getByText(/Route IDs are opaque labels; proxy hosts and credentials are omitted/i),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Per-route timings are unavailable for this run or backend version/i),
      ).toBeInTheDocument();

      // Pressing Escape closes tooltip
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(
        screen.queryByText(/Route IDs are opaque labels; proxy hosts and credentials are omitted/i),
      ).not.toBeInTheDocument();

      // Route lookup table header toggle expands table
      const routeHeaderToggle = screen.getByRole('button', { name: /Per-Route User Lookup Timing/i });
      expect(routeHeaderToggle).toHaveAttribute('aria-expanded', 'false');
      fireEvent.click(routeHeaderToggle);
      expect(routeHeaderToggle).toHaveAttribute('aria-expanded', 'true');
    });
  });

  describe('MPS Diagnostics Metrics Redesign Into Visual Analytics', () => {
    it('renders Performance Overview visual analytics with bullet charts, segmented health bar, and proportional failure rate', () => {
      const visualTelemetry: JobDiagnosticsTelemetry = {
        ...mockTelemetry,
        completedTasksCount: 284886,
        proxyCapacity: {
          ...mockTelemetry.proxyCapacity,
          totalRoutes: 2656,
          enabledProxies: 2656,
        },
        errorVelocity: {
          ...mockTelemetry.errorVelocity,
          totalErrors: 114,
          rate429Count: 0,
        },
        finalSummary: {
          ...mockTelemetry.finalSummary,
          jobOutcome: 'completed',
          throughputUnit: 'tasks',
          efficiencyPercent: 69.4,
          overallAvgItemsPerSec: 477.6,
          theoreticalMaxItemsPerSec: 688.1,
          capacityModelBottleneck: 'proxy_routes',
          runtimeTelemetryComplete: false,
          avgActiveProxyUtilization: 70.3,
          avgActiveConcurrency: 2261.4,
          healthyProxyCount: 2618,
          degradedProxyCount: 38,
          criticalProxyCount: 0,
          recommendations: ['Capacity constraint recommendation'],
        },
      };

      render(
        <JobDiagnosticsReport
          telemetry={visualTelemetry}
          isLiveJob={false}
          workerPoolSize={8}
          jobName="Visual Analytics Run"
          jobId="job-visual-1"
        />,
      );

      const overview = screen.getByTestId('performance-overview');
      expect(overview).toBeInTheDocument();
      expect(screen.getByText('Performance Overview')).toBeInTheDocument();
      expect(screen.getByText('Whole-run averages · Efficiency · Reliability')).toBeInTheDocument();

      // 1. Model Efficiency bullet chart
      expect(screen.getByText('Estimated Model Efficiency')).toBeInTheDocument();
      expect(screen.getByText('69.4%')).toBeInTheDocument();
      expect(screen.getByText(/477.6 \/ 688.1 tasks\/s/i)).toBeInTheDocument();
      const bulletChart = screen.getByRole('progressbar', { name: /Model Efficiency/i });
      expect(bulletChart).toHaveAttribute('aria-valuenow', '69.4');

      // 2. Worker Occupancy utilization bar
      expect(screen.getByText('Estimated Worker Occupancy')).toBeInTheDocument();
      expect(screen.getByText('70.3% Avg')).toBeInTheDocument();
      expect(screen.getByText(/~2261.4 in-flight tasks/i)).toBeInTheDocument();
      const utilBar = screen.getByRole('progressbar', { name: /Worker Occupancy/i });
      expect(utilBar).toHaveAttribute('aria-valuenow', '70.3');

      // 3. Proxy Fleet Health segmented bar
      expect(screen.getByText('Proxy Fleet Health')).toBeInTheDocument();
      expect(screen.getByText('2618 / 2656')).toBeInTheDocument();
      expect(screen.getByText(/98.6% Healthy/i)).toBeInTheDocument();
      expect(screen.getByText(/2618 Healthy/i)).toBeInTheDocument();
      expect(screen.getByText(/38 Degraded/i)).toBeInTheDocument();

      // 4. Failure Rate prominent indicator
      expect(screen.getByText('Failure Rate')).toBeInTheDocument();
      expect(screen.getByText('0.04%')).toBeInTheDocument();
      expect(screen.getByText(/114 Failures \(0 429s\)/i)).toBeInTheDocument();

      // Operational Recommendations must NOT be rendered in the UI
      expect(screen.queryByText(/Operational Recommendations/i)).not.toBeInTheDocument();

      // Test failure rate tooltip
      const failureInfoBtn = screen.getByRole('button', { name: /Failure rate details/i });
      fireEvent.click(failureInfoBtn);
      expect(screen.getByText(/114 total failures out of 285,000 attempted tasks/i)).toBeInTheDocument();
      expect(screen.getByText(/Includes 0 rate limit \(HTTP 429\) errors/i)).toBeInTheDocument();
    });

    it('hides unavailable timing, steady-state, and worker participation metrics without rendering N/A cards', () => {
      const incompleteTelemetry: JobDiagnosticsTelemetry = {
        ...mockTelemetry,
        finalSummary: {
          ...mockTelemetry.finalSummary,
          jobOutcome: 'completed',
          runtimeTelemetryComplete: false,
          meanQueueWaitSec: null,
          meanHandlerSec: null,
          meanWriterSec: null,
          meanTaskDurationSec: null,
          steadyStateEfficiencyPercent: null,
          workersSeen: null,
          expectedWorkers: null,
          readyTimelineNonemptyPercent: null,
          readyNonemptySamples: null,
        },
      };

      render(
        <JobDiagnosticsReport
          telemetry={incompleteTelemetry}
          isLiveJob={false}
          workerPoolSize={8}
        />,
      );

      // Duration breakdown chart must NOT be rendered
      expect(screen.queryByTestId('duration-breakdown')).not.toBeInTheDocument();

      // No N/A cards for individual timing phases
      expect(screen.queryByText('Queue Wait')).not.toBeInTheDocument();
      expect(screen.queryByText('Handler')).not.toBeInTheDocument();
      expect(screen.queryByText('Writer Wait')).not.toBeInTheDocument();
      expect(screen.queryByText('Mean Task Duration')).not.toBeInTheDocument();
      expect(screen.queryByText('Steady-State Efficiency')).not.toBeInTheDocument();
      expect(screen.queryByText('Worker Participation')).not.toBeInTheDocument();
      expect(screen.queryByText(/Unavailable for this run/i)).not.toBeInTheDocument();
    });

    it('renders stacked task duration breakdown chart when actual timing telemetry exists', () => {
      const timingTelemetry: JobDiagnosticsTelemetry = {
        ...mockTelemetry,
        finalSummary: {
          ...mockTelemetry.finalSummary,
          jobOutcome: 'completed',
          runtimeTelemetryComplete: true,
          meanTaskDurationSec: 2.0,
          meanQueueWaitSec: 0.2,
          meanHandlerSec: 1.4,
          meanWriterSec: 0.4,
        },
      };

      render(
        <JobDiagnosticsReport
          telemetry={timingTelemetry}
          isLiveJob={false}
          workerPoolSize={8}
        />,
      );

      const durationBreakdown = screen.getByTestId('duration-breakdown');
      expect(durationBreakdown).toBeInTheDocument();
      expect(screen.getByText(/Mean Task Duration:/i)).toBeInTheDocument();
      expect(screen.getByText('2.00s')).toBeInTheDocument();

      expect(screen.getByText(/Queue Wait: 0.20s \(10.0%\)/i)).toBeInTheDocument();
      expect(screen.getByText(/Handler: 1.40s \(70.0%\)/i)).toBeInTheDocument();
      expect(screen.getByText(/Writer Wait: 0.40s \(20.0%\)/i)).toBeInTheDocument();
    });

    it('provides expandable Telemetry & Sampling Details for secondary metrics', () => {
      const secondaryTelemetry: JobDiagnosticsTelemetry = {
        ...mockTelemetry,
        finalSummary: {
          ...mockTelemetry.finalSummary,
          jobOutcome: 'completed',
          steadyStateEfficiencyPercent: 72.5,
          occupancyGapClassification: 'steady_state_saturated',
          workersSeen: 8,
          expectedWorkers: 8,
          readyTimelineNonemptyPercent: 94.7,
          readyTimelineCoveredSeconds: 550.8,
        },
      };

      render(
        <JobDiagnosticsReport
          telemetry={secondaryTelemetry}
          isLiveJob={false}
          workerPoolSize={8}
        />,
      );

      const detailsToggle = screen.getByRole('button', { name: /Telemetry & Sampling Details/i });
      expect(detailsToggle).toBeInTheDocument();
      expect(screen.getByTestId('performance-overview').compareDocumentPosition(detailsToggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(detailsToggle).toHaveAttribute('aria-expanded', 'false');

      // Click to expand
      fireEvent.click(detailsToggle);
      expect(detailsToggle).toHaveAttribute('aria-expanded', 'true');

      expect(screen.getByText(/Steady-State Efficiency \(10–90%\)/i)).toBeInTheDocument();
      expect(screen.getByText('72.5%')).toBeInTheDocument();
      expect(screen.getByText('Worker Participation')).toBeInTheDocument();
      expect(screen.getByText('8 / 8')).toBeInTheDocument();
      expect(screen.getByText(/Ready Queue Availability/i)).toBeInTheDocument();
      expect(screen.getByText('94.7% covered')).toBeInTheDocument();
      expect(screen.getByText(/Ready tasks observed in 94.7% of 550.8s time-sampled intervals/i)).toBeInTheDocument();
    });
  });
});
