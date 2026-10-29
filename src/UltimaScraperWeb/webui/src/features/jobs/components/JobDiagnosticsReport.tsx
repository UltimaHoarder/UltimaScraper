import { createPortal } from 'react-dom';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { NavIcon } from '../../../components/layout/NavIcon';
import type { NavIconName } from '../../../components/layout/navigation';
import type { Job, JobDetail } from '../../../api/types/jobs';
import {
  MAX_CHART_LINE_GAP_MS,
  bucketRuntimeThroughputTimeline,
  buildRuntimeThroughputTimeline,
  chooseRuntimeBucketMs,
  formatBucketDuration,
  formatChartClock,
  formatElapsedMs,
  refillBatchLabel,
  refillStageLabel,
  rollingRuntimeThroughput,
  type ChartMarker,
} from '../lib/diagnosticsChartUtils';
import {
  ROUTE_LOOKUP_DISPLAY_LIMIT,
  downloadTextFile,
  formatRouteLookupOutcomes,
  generateDiagnosticJsonBundle,
  generateMarkdownReport,
  getRouteLookupRows,
} from '../lib/diagnosticsReportExport';
import { computeJobDurationSeconds, formatDuration, isJobRunningStatus } from '../lib/jobUtils';
import type { JobDiagnosticsTelemetry } from '../lib/useJobDiagnosticsTelemetry';
import type { JobEtaResult } from '../lib/jobEta';
import {
  DEFAULT_TASK_COUNT_TOLERANCE_PERCENT,
  comparableTaskCount,
  computeHistoricalComparison,
  isSimilarTaskCount,
  isTaskCountTolerancePreset,
} from '../lib/historicalComparison';
import { SvgLineChart } from './SvgLineChart';
import './JobDiagnosticsReport.css';

function TelemetryBar({ value, limit, label, tone, description: detail, markers = [] }: {
  value: number;
  limit: number;
  label: string;
  tone: 'throughput' | 'concurrency' | 'latency' | 'errors';
  description?: string;
  markers?: Array<{ value: number; label: string; className: string }>;
}) {
  const available = Number.isFinite(value) && Number.isFinite(limit) && limit > 0;
  const percent = available ? Math.max(0, Math.min(100, value / limit * 100)) : 0;
  const defaultDescription = available ? `${label}: ${value.toLocaleString()} / ${limit.toLocaleString()}` : `${label}: unavailable`;
  const tooltipText = detail ?? defaultDescription;
  return (
    <div className={`jdr-telemetry-bar is-${tone}`} role="meter" aria-label={label}
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-valuetext={tooltipText}
      title={tooltipText} tabIndex={0}>
      <div style={{ width: `${percent}%` }} />
      {markers.map((marker) => {
        const markerPercent = available ? Math.max(0, Math.min(100, marker.value / limit * 100)) : 0;
        return (
          <span
            key={marker.label}
            className={`jdr-telemetry-marker ${marker.className}`}
            style={{ left: `${markerPercent}%` }}
            title={marker.label}
            aria-hidden="true"
          />
        );
      })}
    </div>
  );
}

type ProxySortKey = 'anomalyScore' | 'failures' | 'rateLimits429' | 'timeouts' | 'avgLatencySec' | 'totalAttempts';
const STORAGE_KEY_TOLERANCE = 'usr:job-diagnostics:task-tolerance-percent';

function formatComparisonRate(value: number, unit: string): string {
  return `${value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} ${unit}`;
}

function formatSignedPercent(value: number): string {
  if (value === 0) return '0.0%';
  return `${value > 0 ? '+' : '−'}${Math.abs(value).toFixed(1)}%`;
}

function formatSignedPercentagePoints(value: number): string {
  if (value === 0) return '0.0 pp';
  return `${value > 0 ? '+' : '−'}${Math.abs(value).toFixed(1)} pp`;
}

function formatSignedDuration(value: number): string {
  if (value === 0) return '0s';
  return `${value > 0 ? '+' : '−'}${formatDuration(Math.abs(value))}`;
}

function formatSignedTaskCount(value: number): string {
  const absolute = Math.abs(value);
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${absolute.toLocaleString()} ${absolute === 1 ? 'task' : 'tasks'}`;
}

function comparisonDeltaTone(value: number, positiveIsGood: boolean): 'is-positive' | 'is-negative' | 'is-neutral' {
  if (value === 0) return 'is-neutral';
  return (value > 0) === positiveIsGood ? 'is-positive' : 'is-negative';
}

interface HistoricalRunReference {
  job: Job | JobDetail;
  tasksPerSecond: number;
  durationSeconds: number;
  failureRatePercent: number;
  completedTasks: number;
}

function HistoricalRunCell({
  run,
  metric,
  throughputUnit = 'tasks/s',
}: {
  run: HistoricalRunReference | null;
  metric: 'throughput' | 'duration' | 'failureRate' | 'completedTasks';
  throughputUnit?: string;
}) {
  if (!run) return <td>—</td>;

  const value = metric === 'throughput'
    ? formatComparisonRate(run.tasksPerSecond, throughputUnit)
    : metric === 'duration'
      ? formatDuration(run.durationSeconds)
      : metric === 'failureRate'
        ? `${run.failureRatePercent.toFixed(1)}%`
        : run.completedTasks.toLocaleString();
  const label = run.job.job_name || run.job.job_id;

  return (
    <td>
      <span className="jdr-comparison-run-value">
        <strong>{value}</strong>
        <small title={`${label} · ${run.job.job_id}`}>{label}</small>
      </span>
    </td>
  );
}

function getStoredTolerancePercent(fallback: number): number {
  if (typeof window === 'undefined' || !window.localStorage) return fallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY_TOLERANCE);
    if (!raw) return fallback;
    const parsed = parseFloat(raw);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function DiagnosticGlyph({ name, children, iconClassName }: { name: NavIconName; children: ReactNode; iconClassName?: string }) {
  return <><NavIcon name={name} className={`jdr-atlas-icon ${iconClassName ?? ''}`} /><span className="jdr-legacy-icon" aria-hidden="true">{children}</span></>;
}

function InfoTooltip({
  content,
  ariaLabel = 'Information',
}: {
  content: ReactNode;
  ariaLabel?: string;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement>(null);
  const popoverRef = useRef<HTMLSpanElement>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [position, setPosition] = useState({ left: 8, top: 8 });
  const keepOpen = () => {
    if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
    setIsOpen(true);
  };
  const closeSoon = () => {
    closeTimerRef.current = setTimeout(() => setIsOpen(false), 120);
  };
  useEffect(() => () => {
    if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
  }, []);
  useLayoutEffect(() => {
    if (!isOpen) return;
    const place = () => {
      const anchor = containerRef.current?.getBoundingClientRect();
      const popup = popoverRef.current?.getBoundingClientRect();
      if (!anchor || !popup) return;
      const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
      const viewportHeight = window.innerHeight;
      const left = Math.max(8, Math.min(anchor.right - popup.width, viewportWidth - popup.width - 8));
      const below = anchor.bottom + 6;
      const top = below + popup.height <= viewportHeight - 8
        ? below : Math.max(8, anchor.top - popup.height - 6);
      setPosition({ left, top });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [isOpen]);


  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (e: MouseEvent | TouchEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node) && !popoverRef.current?.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
      }
    };
    document.addEventListener('pointerdown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  return (
    <span
      ref={containerRef}
      className={`jdr-info-tooltip-wrapper ${isOpen ? 'is-active' : ''}`}
      onMouseEnter={keepOpen}
      onMouseLeave={closeSoon}
    >
      <button
        type="button"
        className="jdr-info-icon-btn"
        aria-label={ariaLabel}
        aria-expanded={isOpen}
        onClick={(e) => {
          e.stopPropagation();
          keepOpen();
        }}
        onFocus={() => setIsOpen(true)}
        onBlur={() => {
          setTimeout(() => {
            if (
              containerRef.current &&
              !containerRef.current.contains(document.activeElement)
            ) {
              setIsOpen(false);
            }
          }, 150);
        }}
      >
        <span aria-hidden="true" className="jdr-info-glyph">ℹ</span>
      </button>
      {isOpen && createPortal(
        <span className="jdr-container" style={{ display: 'contents' }}>
        <span
          ref={popoverRef}
          style={{ position: 'fixed', left: position.left, top: position.top }}
          onMouseEnter={keepOpen}
          onMouseLeave={closeSoon}
          className="jdr-info-popover"
          role="tooltip"
          onClick={(e) => e.stopPropagation()}
        >
          {content}
        </span>
        </span>, document.body
      )}
    </span>
  );
}

export interface JobDiagnosticsReportProps {
  telemetry: JobDiagnosticsTelemetry;
  isLiveJob: boolean;
  jobEta?: JobEtaResult | null;
  workerPoolSize?: number;
  jobName?: string | null;
  jobId?: string;
  site?: string | null;
  historicalJobs?: Job[];
  currentJob?: Job | JobDetail | null;
  chartNow?: number;
  initialBaselineJobId?: string | null;
  baselineJobDetail?: JobDetail | null;
  defaultTaskCountTolerancePercent?: number;
  taskCountTolerancePercent?: number;
  onTaskCountToleranceChange?: (tolerancePercent: number) => void;
  onBaselineJobChange?: (baselineJobId: string | null) => void;
}

export function JobDiagnosticsReport({
  telemetry,
  isLiveJob,
  jobEta,
  workerPoolSize = 32,
  jobName,
  jobId,
  site,
  historicalJobs = [],
  currentJob,
  chartNow,
  initialBaselineJobId,
  baselineJobDetail,
  defaultTaskCountTolerancePercent,
  taskCountTolerancePercent: propTaskCountTolerancePercent,
  onTaskCountToleranceChange,
  onBaselineJobChange,
}: JobDiagnosticsReportProps) {
  const resolvedJobName = jobName || currentJob?.job_name || 'Job Run';
  const resolvedJobId = jobId || currentJob?.job_id || 'job';
  const resolvedSite = site || currentJob?.site || 'OnlyFans';

  const isTerminal =
    !isLiveJob ||
    telemetry.finalSummary.jobOutcome === 'completed' ||
    telemetry.finalSummary.jobOutcome === 'failed' ||
    currentJob?.status === 'completed' ||
    currentJob?.status === 'failed' ||
    currentJob?.status === 'cancelled';

  const [activeView, setActiveView] = useState<'telemetry' | 'compare'>('telemetry');

  const [taskCountTolerancePercent, setTaskCountTolerancePercentState] = useState<number>(() => {
    if (propTaskCountTolerancePercent != null) return propTaskCountTolerancePercent;
    return getStoredTolerancePercent(
      defaultTaskCountTolerancePercent ?? DEFAULT_TASK_COUNT_TOLERANCE_PERCENT,
    );
  });

  const [isCustomTolerance, setIsCustomTolerance] = useState<boolean>(() => {
    const initial =
      propTaskCountTolerancePercent ??
      getStoredTolerancePercent(
        defaultTaskCountTolerancePercent ?? DEFAULT_TASK_COUNT_TOLERANCE_PERCENT,
      );
    return initial < 1000 && !isTaskCountTolerancePreset(initial);
  });

  // Follow a controlled tolerance prop; state above was already initialised from it.
  const [previousPropTolerance, setPreviousPropTolerance] = useState(propTaskCountTolerancePercent);
  if (propTaskCountTolerancePercent !== previousPropTolerance) {
    setPreviousPropTolerance(propTaskCountTolerancePercent);
    if (propTaskCountTolerancePercent != null) {
      setTaskCountTolerancePercentState(propTaskCountTolerancePercent);
      setIsCustomTolerance(
        propTaskCountTolerancePercent < 1000 &&
          !isTaskCountTolerancePreset(propTaskCountTolerancePercent),
      );
    }
  }

  // undefined: pick a baseline automatically; null: comparison disabled by the
  // user; string: the user's explicit choice while it remains comparable.
  const [baselineChoice, setBaselineChoice] = useState<string | null | undefined>(
    initialBaselineJobId ?? undefined,
  );

  const updateTolerancePercent = (newPercent: number) => {
    setBaselineChoice((choice) => (choice === null ? undefined : choice));
    setTaskCountTolerancePercentState(newPercent);
    onTaskCountToleranceChange?.(newPercent);
    try {
      if (typeof window !== 'undefined' && window.localStorage) {
        window.localStorage.setItem(STORAGE_KEY_TOLERANCE, String(newPercent));
      }
    } catch {
      // Ignore storage errors
    }
  };

  const taskCountToleranceBoundary =
    taskCountTolerancePercent >= 1000 ? Infinity : taskCountTolerancePercent / 100;

  const currentTaskCount = comparableTaskCount(currentJob) ?? telemetry.totalTasksCount;

  const availableHistoricalJobs = useMemo(() => {
    if (!historicalJobs || historicalJobs.length === 0) return [];
    return historicalJobs.filter(
      (h) =>
        h.job_id !== resolvedJobId &&
        !isJobRunningStatus(h.status) &&
        isSimilarTaskCount(currentTaskCount, comparableTaskCount(h), taskCountToleranceBoundary),
    );
  }, [currentTaskCount, historicalJobs, resolvedJobId, taskCountToleranceBoundary]);

  const historicalRunExtremes = useMemo(() => {
    const finishedRuns: HistoricalRunReference[] = availableHistoricalJobs
      .map((summaryJob) => baselineJobDetail?.job_id === summaryJob.job_id
        ? baselineJobDetail
        : summaryJob)
      .filter((job) => {
        const normStatus = String(job.status || '').toLowerCase();
        return normStatus === 'completed' || normStatus === 'failed';
      })
      .map((job) => {
        const counters = job as Job & {
          completed_tasks?: number;
          failed_tasks?: number;
          task_count?: number;
        };
        const completedTasks = counters.completed_tasks ?? job.task_stats?.completed ?? 0;
        const failedTasks = counters.failed_tasks ?? job.task_stats?.failed ?? 0;
        const totalTasks = counters.task_count ?? job.task_stats?.total ?? completedTasks + failedTasks;
        const durationSeconds = computeJobDurationSeconds(job);
        return {
          job,
          tasksPerSecond: completedTasks / durationSeconds,
          durationSeconds,
          failureRatePercent: totalTasks > 0 ? (failedTasks / totalTasks) * 100 : 0,
          completedTasks,
        };
      })
      .filter((run) => Number.isFinite(run.tasksPerSecond));

    if (finishedRuns.length === 0) return { best: null, worst: null };

    return {
      best: finishedRuns.reduce((best, run) =>
        run.tasksPerSecond > best.tasksPerSecond ? run : best),
      worst: finishedRuns.reduce((worst, run) =>
        run.tasksPerSecond < worst.tasksPerSecond ? run : worst),
    };
  }, [availableHistoricalJobs, baselineJobDetail]);

  const selectedBaselineId = useMemo(() => {
    if (baselineChoice === null) return null;
    if (baselineChoice !== undefined && availableHistoricalJobs.some((h) => h.job_id === baselineChoice)) {
      return baselineChoice;
    }
    const match =
      availableHistoricalJobs.find((h) => (resolvedSite ? h.site === resolvedSite : true)) ||
      availableHistoricalJobs[0];
    return match ? match.job_id : null;
  }, [availableHistoricalJobs, baselineChoice, resolvedSite]);

  useEffect(() => {
    onBaselineJobChange?.(selectedBaselineId);
  }, [selectedBaselineId, onBaselineJobChange]);

  const selectedBaselineJob = useMemo(() => {
    if (!selectedBaselineId) return null;
    return availableHistoricalJobs.find((h) => h.job_id === selectedBaselineId) || null;
  }, [availableHistoricalJobs, selectedBaselineId]);

  const effectiveBaselineJob = useMemo(() => {
    const candidate =
      (baselineJobDetail?.job_id === selectedBaselineId ? baselineJobDetail : null) ||
      selectedBaselineJob;
    if (!candidate || isJobRunningStatus(candidate.status)) return null;
    return candidate;
  }, [baselineJobDetail, selectedBaselineId, selectedBaselineJob]);

  const comparison = useMemo(() => {
    return computeHistoricalComparison(
      telemetry,
      resolvedJobId,
      resolvedJobName,
      resolvedSite,
      isLiveJob,
      effectiveBaselineJob,
      currentJob,
      taskCountToleranceBoundary,
      jobEta,
    );
  }, [
    telemetry,
    resolvedJobId,
    resolvedJobName,
    resolvedSite,
    isLiveJob,
    effectiveBaselineJob,
    currentJob,
    taskCountToleranceBoundary,
    jobEta,
  ]);
  const [copiedBadProxies, setCopiedBadProxies] = useState(false);
  const [copiedReport, setCopiedReport] = useState(false);
  const [proxySearchTerm, setProxySearchTerm] = useState('');
  const [proxyStatusFilter, setProxyStatusFilter] = useState<'all' | 'critical' | 'degraded' | '429' | 'timeouts'>('all');
  const [proxySortKey, setProxySortKey] = useState<ProxySortKey>('anomalyScore');
  const [proxySortOrder, setProxySortOrder] = useState<'asc' | 'desc'>('desc');
  const [isLedgerTimingExpanded, setIsLedgerTimingExpanded] = useState(false);
  const [isTerminalTimingExpanded, setIsTerminalTimingExpanded] = useState(false);
  const [isGuestAuthExpanded, setIsGuestAuthExpanded] = useState(false);
  const [isRouteLookupExpanded, setIsRouteLookupExpanded] = useState(false);
  const [isMpsRefillExpanded, setIsMpsRefillExpanded] = useState(false);
  const [isTelemetryDetailsExpanded, setIsTelemetryDetailsExpanded] = useState(false);
  const [expandedChart, setExpandedChart] = useState<{ id: string; group: string } | null>(null);
  const toggleExpandedChart = (id: string, group: string) => {
    setExpandedChart((current) => current?.id === id ? null : { id, group });
  };

  const {
    chartSnapshots: allChartSnapshots = [],
    jobRuntimeSamples = [],
    mpsRefillTrace = [],
    throughput,
    latencyPercentiles,
    proxyCapacity,
    httpDistribution,
    errorVelocity,
    proxyAnomalies,
    finalSummary,
    runningTasksCount,
  } = telemetry;
  const routeLookupRows = useMemo(
    () => getRouteLookupRows(finalSummary.routeLookupStats),
    [finalSummary.routeLookupStats],
  );
  const throughputUnit =
    telemetry.quality?.throughputUnit ??
    finalSummary.throughputUnit ??
    throughput.throughputUnit ??
    'items';
  const throughputShortLabel = throughputUnit === 'items' ? 'items/s' : 'tasks/s';
  const comparisonCurrentThroughput = comparison
    ? throughputUnit === 'items'
      ? finalSummary.overallAvgItemsPerSec || throughput.currentItemsPerSec || comparison.currentRun.completedTasks / (comparison.currentRun.elapsedSec || comparison.currentRun.durationSec)
      : finalSummary.overallAvgTasksPerSec || throughput.currentTasksPerSec || comparison.currentRun.completedTasks / (comparison.currentRun.elapsedSec || comparison.currentRun.durationSec)
    : 0;
  const baselineThroughput = comparison?.baselineJob?.avgItemsPerSec ?? 0;
  const throughputDeltaAvailable = Boolean(
    comparison && comparison.throughputComparable !== false && baselineThroughput > 0,
  );
  const comparisonThroughputDeltaPercent = throughputDeltaAvailable
    ? Number((((comparisonCurrentThroughput - baselineThroughput) / baselineThroughput) * 100).toFixed(1))
    : 0;
  const comparisonWorkloadComparable = Boolean(
    comparison?.baselineJob && isSimilarTaskCount(
      comparison.currentRun.totalTasks,
      comparison.baselineJob.totalTasks,
      taskCountToleranceBoundary,
    ),
  );
  const comparisonHasIndependentRegression = Boolean(
    comparison && (
      comparison.deltas.failureRateDeltaPercent >= 3 ||
      (comparison.deltas.durationDeltaPercent >= 25 && comparisonWorkloadComparable)
    ),
  );
  const comparisonStatus = comparison
    ? comparisonHasIndependentRegression || (throughputDeltaAvailable && comparisonThroughputDeltaPercent <= -10)
      ? 'regression'
      : !throughputDeltaAvailable
        ? 'partial'
        : throughputDeltaAvailable && comparisonThroughputDeltaPercent >= 10 && comparison.deltas.failureRateDeltaPercent <= 0.5
          ? 'improvement'
          : 'parity'
    : null;
  const nowForChart = Number.isFinite(chartNow)
    ? chartNow!
    : telemetry.lastSampleTime;
  const snapshots = useMemo(
    () => isTerminal
      ? allChartSnapshots
      : allChartSnapshots.filter((snapshot) => snapshot.timestamp >= nowForChart - 3 * 60 * 1000),
    [isTerminal, allChartSnapshots, nowForChart],
  );
  const chartTimestamps = useMemo(
    () => snapshots.map((snapshot) => snapshot.timestamp),
    [snapshots],
  );
  const chartSampleIntervals = useMemo(
    () => snapshots.map((snapshot) => snapshot.timestamp - snapshot.intervalStartTimestamp),
    [snapshots],
  );
  const startedAtValue = currentJob && 'started_at' in currentJob
    ? currentJob.started_at
    : currentJob?.created_at;
  const completedAtValue = currentJob && 'completed_at' in currentJob
    ? currentJob.completed_at
    : null;
  const startedAtMs = startedAtValue ? Date.parse(startedAtValue) : Number.NaN;
  const completedAtMs = completedAtValue ? Date.parse(completedAtValue) : Number.NaN;
  const firstObservedAt = chartTimestamps[0] ?? nowForChart;
  const lastObservedAt = chartTimestamps[chartTimestamps.length - 1] ?? nowForChart;
  const chartTimeDomain: [number, number] = isTerminal
    ? [
        Number.isFinite(startedAtMs) ? startedAtMs : firstObservedAt,
        Number.isFinite(completedAtMs) ? completedAtMs : lastObservedAt,
      ]
    : [nowForChart - 3 * 60 * 1000, nowForChart];
  if (chartTimeDomain[1] <= chartTimeDomain[0]) {
    chartTimeDomain[1] = chartTimeDomain[0] + 1;
  }
  const [chartDomainStart, chartDomainEnd] = chartTimeDomain;
  const refillMarkers = useMemo<ChartMarker[]>(() =>
    mpsRefillTrace
      .filter((event) =>
        ['queued', 'tasks_published', 'tasks_activated'].includes(event.stage) &&
        event.timestamp_ms >= chartDomainStart &&
        event.timestamp_ms <= chartDomainEnd,
      )
      .slice(-24)
      .map((event) => ({
        timestamp: event.timestamp_ms,
        label: refillStageLabel(event.stage),
        color: 'var(--jdr-chart-warning, #d29922)',
      })),
  [chartDomainStart, chartDomainEnd, mpsRefillTrace]);
  const handleCopyReport = () => {
    const report = generateMarkdownReport(
      telemetry,
      resolvedJobName,
      resolvedJobId,
      resolvedSite,
      comparison,
    );
    navigator.clipboard.writeText(report).then(() => {
      setCopiedReport(true);
      setTimeout(() => setCopiedReport(false), 2000);
    });
  };

  const handleDownloadReport = () => {
    const report = generateMarkdownReport(
      telemetry,
      resolvedJobName,
      resolvedJobId,
      resolvedSite,
      comparison,
    );
    downloadTextFile(`job-diagnostic-${resolvedJobId}.md`, report);
  };

  const handleDownloadJsonBundle = () => {
    const json = generateDiagnosticJsonBundle(
      telemetry,
      resolvedJobName,
      resolvedJobId,
      resolvedSite,
      comparison,
    );
    downloadTextFile(
      `job-diagnostic-${resolvedJobId}-bundle.json`,
      json,
      'application/json;charset=utf-8;',
    );
  };

  const filteredAndSortedProxies = useMemo(() => {
    let list = [...proxyAnomalies];

    if (proxyStatusFilter === 'critical') {
      list = list.filter((p) => p.status === 'critical');
    } else if (proxyStatusFilter === 'degraded') {
      list = list.filter((p) => p.status === 'degraded');
    } else if (proxyStatusFilter === '429') {
      list = list.filter((p) => p.rateLimits429 > 0);
    } else if (proxyStatusFilter === 'timeouts') {
      list = list.filter((p) => p.timeouts > 0);
    }

    if (proxySearchTerm.trim()) {
      const term = proxySearchTerm.toLowerCase();
      list = list.filter(
        (p) =>
          p.displayUrl.toLowerCase().includes(term) ||
          (p.group && p.group.toLowerCase().includes(term)) ||
          (p.country && p.country.toLowerCase().includes(term)) ||
          p.primaryIssue.toLowerCase().includes(term),
      );
    }

    list.sort((a, b) => {
      let diff = 0;
      if (proxySortKey === 'anomalyScore') diff = b.anomalyScore - a.anomalyScore;
      else if (proxySortKey === 'failures') diff = b.failures - a.failures;
      else if (proxySortKey === 'rateLimits429') diff = b.rateLimits429 - a.rateLimits429;
      else if (proxySortKey === 'timeouts') diff = b.timeouts - a.timeouts;
      else if (proxySortKey === 'avgLatencySec') diff = b.avgLatencySec - a.avgLatencySec;
      else if (proxySortKey === 'totalAttempts') diff = b.totalAttempts - a.totalAttempts;
      return proxySortOrder === 'asc' ? -diff : diff;
    });

    return list;
  }, [proxyAnomalies, proxySearchTerm, proxyStatusFilter, proxySortKey, proxySortOrder]);

  // Extract series data for charts
  // Keep the plotted unit consistent with the telemetry quality contract. A
  // partial task page cannot support an authoritative item-rate chart.
  const hasJobRuntimeHistory = jobRuntimeSamples.length >= 2;
  const chartThroughputLabel = hasJobRuntimeHistory
    ? 'Tasks/sec'
    : throughputUnit === 'items' ? 'Items/sec' : 'Tasks/sec';
  const throughputItemsSeries = useMemo(
    () => snapshots.map((snapshot) =>
      throughputUnit === 'items'
        ? snapshot.itemsAreAuthoritative ? snapshot.throughputItemsPerSec : null
        : snapshot.throughputTasksPerSec,
    ),
    [snapshots, throughputUnit],
  );

  const throughputSmaSeries = useMemo(() => {
    // Weight by observed time, not sample count, so slower polls do not distort
    // the trend line. Each point is a rate over its actual backend interval.
    return snapshots.map((snapshot, idx) => {
      const cutoff = snapshot.timestamp - 5_000;
      let amount = 0;
      let coveredMs = 0;
      for (let sampleIdx = idx; sampleIdx >= 0; sampleIdx -= 1) {
        const sample = snapshots[sampleIdx];
        if (sample.timestamp <= cutoff) break;
        const intervalMs = sample.timestamp - sample.intervalStartTimestamp;
        if (intervalMs <= 0) continue;
        if (throughputUnit === 'items' && !sample.itemsAreAuthoritative) continue;
        const overlapMs = Math.max(
          0,
          Math.min(sample.timestamp, snapshot.timestamp) -
            Math.max(sample.intervalStartTimestamp, cutoff),
        );
        if (overlapMs <= 0) continue;
        if (overlapMs < intervalMs) continue;
        const delta = throughputUnit === 'items' ? sample.itemsDelta : sample.completedDelta;
        amount += delta;
        coveredMs += intervalMs;
      }
      return coveredMs > 0
        ? Number((amount / (coveredMs / 1000)).toFixed(1))
        : null;
    });
  }, [snapshots, throughputUnit]);

  const runningConcurrencySeries = useMemo(
    () => snapshots.map((s) => s.inflightTasks),
    [snapshots],
  );

  const latencyP50Series = useMemo(
    () => snapshots.map((s) => s.p50Latency),
    [snapshots],
  );

  const latencyP95Series = useMemo(
    () => snapshots.map((s) => s.p95Latency),
    [snapshots],
  );

  const errorVelocitySeries = useMemo(
    () => snapshots.map((s) => s.errorCount),
    [snapshots],
  );
  const jobRuntimeTimeline = useMemo(
    () => buildRuntimeThroughputTimeline(jobRuntimeSamples),
    [jobRuntimeSamples],
  );
  // Lifecycle charts scale their bucket with job duration so long runs stay
  // legible; the live 3-minute window keeps per-second samples.
  const runtimeBucketMs = isTerminal
    ? chooseRuntimeBucketMs(chartDomainEnd - chartDomainStart)
    : 1_000;
  const runtimeAverageWindowMs = 5 * runtimeBucketMs;
  const runtimeLineGapMs = Math.max(MAX_CHART_LINE_GAP_MS, 2 * runtimeBucketMs);
  const visibleJobRuntimeTimeline = useMemo(
    () => isTerminal
      ? bucketRuntimeThroughputTimeline(jobRuntimeTimeline, runtimeBucketMs)
      : jobRuntimeTimeline.filter(
          (sample) => sample.timestamp >= nowForChart - 3 * 60 * 1_000,
        ),
    [isTerminal, jobRuntimeTimeline, nowForChart, runtimeBucketMs],
  );
  const runtimeThroughputSeries = useMemo(
    () => rollingRuntimeThroughput(visibleJobRuntimeTimeline, runtimeAverageWindowMs),
    [runtimeAverageWindowMs, visibleJobRuntimeTimeline],
  );
  const throughputChartTimestamps = hasJobRuntimeHistory
    ? visibleJobRuntimeTimeline.map((sample) => sample.timestamp)
    : chartTimestamps;
  const throughputChartIntervals = hasJobRuntimeHistory
    ? visibleJobRuntimeTimeline.map((sample) => sample.intervalMs)
    : chartSampleIntervals;
  const throughputChartValues = hasJobRuntimeHistory
    ? visibleJobRuntimeTimeline.map((sample) => sample.throughput)
    : throughputItemsSeries;
  const throughputChartAverage = hasJobRuntimeHistory
    ? runtimeThroughputSeries
    : throughputSmaSeries;
  const showThroughputComparisonReferences =
    activeView === 'compare' && chartThroughputLabel === 'Tasks/sec';
  const isBaselineThroughputRun = (run: HistoricalRunReference | null) => Boolean(
    run && (
      run.job.job_id === comparison?.baselineJob?.jobId ||
      (throughputDeltaAvailable &&
        Number(run.tasksPerSecond.toFixed(1)) === Number(baselineThroughput.toFixed(1)))
    ),
  );
  const throughputComparisonReferences = showThroughputComparisonReferences
    ? [
      ...(throughputDeltaAvailable
        ? [{
          value: baselineThroughput,
          label: 'Baseline avg',
          color: 'var(--jdr-chart-baseline, #a371f7)',
        }]
        : []),
      ...(historicalRunExtremes.best &&
        !isBaselineThroughputRun(historicalRunExtremes.best)
        ? [{
          value: Number(historicalRunExtremes.best.tasksPerSecond.toFixed(1)),
          label: 'Best avg',
          color: 'var(--jdr-chart-success, #3fb950)',
        }]
        : []),
      ...(historicalRunExtremes.worst &&
        !isBaselineThroughputRun(historicalRunExtremes.worst)
        ? [{
          value: Number(historicalRunExtremes.worst.tasksPerSecond.toFixed(1)),
          label: 'Worst avg',
          color: 'var(--jdr-chart-warning, #d29922)',
        }]
        : []),
    ]
    : [];
  const concurrencyChartTimestamps = jobRuntimeSamples.length > 0
    ? visibleJobRuntimeTimeline.map((sample) => sample.timestamp)
    : chartTimestamps;
  const concurrencyChartValues = jobRuntimeSamples.length > 0
    ? visibleJobRuntimeTimeline.map((sample) => sample.inflight)
    : runningConcurrencySeries;
  const recentRefillEvents = useMemo(() => {
    const ordered = [...mpsRefillTrace].sort((left, right) => left.timestamp_ms - right.timestamp_ms);
    const firstVisibleIndex = Math.max(0, ordered.length - 16);
    return ordered.slice(firstVisibleIndex).reverse().map((event, reverseIndex) => {
      const index = ordered.length - 1 - reverseIndex;
      const previous = ordered.slice(0, index).reverse().find(
        (candidate) => candidate.cycle === event.cycle,
      );
      return {
        event,
        elapsedSincePreviousMs: previous
          ? Math.max(0, event.timestamp_ms - previous.timestamp_ms)
          : null,
      };
    });
  }, [mpsRefillTrace]);

  // Copy bad proxies helper
  const handleCopyBadProxies = () => {
    const bad = proxyAnomalies
      .filter((p) => p.status !== 'healthy')
      .map((p) => p.proxyUrl)
      .join('\n');
    if (!bad) return;
    navigator.clipboard.writeText(bad).then(() => {
      setCopiedBadProxies(true);
      setTimeout(() => setCopiedBadProxies(false), 2000);
    });
  };

  // HTTP Percentages
  const totalHttp = Math.max(1, httpDistribution.totalObserved);
  const pct200 = ((httpDistribution.ok200 / totalHttp) * 100).toFixed(1);
  const pct429 = ((httpDistribution.rateLimit429 / totalHttp) * 100).toFixed(1);
  const pct403 = ((httpDistribution.forbidden403 / totalHttp) * 100).toFixed(1);
  const pct404 = ((httpDistribution.notFound404 / totalHttp) * 100).toFixed(1);
  const pct5xx = ((httpDistribution.serverError5xx / totalHttp) * 100).toFixed(1);
  const pctTimeout = ((httpDistribution.timeoutErrors / totalHttp) * 100).toFixed(1);
  const latestObservedRate = throughputUnit === 'items'
    ? throughput.currentItemsPerSec
    : throughput.currentTasksPerSec;
  const overviewThroughput = isTerminal
    ? (throughputUnit === 'items' ? finalSummary.overallAvgItemsPerSec : finalSummary.overallAvgTasksPerSec)
    : latestObservedRate;
  const throughputBarMaximum = Math.max(1, finalSummary.theoreticalMaxItemsPerSec, overviewThroughput, finalSummary.peakItemsPerSec);
  const throughputBasePercent = Math.max(0, overviewThroughput / throughputBarMaximum * 100);
  const throughputBurstPercent = Math.max(0, (finalSummary.peakItemsPerSec - overviewThroughput) / throughputBarMaximum * 100);
  const overviewConcurrency = isTerminal ? finalSummary.avgActiveConcurrency : runningTasksCount;
  const overviewProxyRoutes = isTerminal ? finalSummary.avgActiveProxyRoutes : proxyCapacity.activeRoutes;
  const overviewProxyUtilization = isTerminal ? finalSummary.avgActiveProxyUtilization : proxyCapacity.utilizationPercent;
  // ── Performance Overview Computations ──
  const efficiencyCurrentThroughput = !isTerminal ? latestObservedRate : finalSummary.runtimeTelemetryComplete
    ? finalSummary.activeWindowThroughput
    : finalSummary.overallAvgItemsPerSec;
  const governingCapacityModelLabel = finalSummary.capacityModelBottleneck === 'proxy_routes'
    ? 'route'
    : 'worker-slot';
  const workerConcurrencyCapacity = Math.max(
    1,
    telemetry.throughputDiagnostics?.workerConcurrencyDemand
      ?? workerPoolSize * (telemetry.throughputDiagnostics?.targetConcurrency ?? 1),
  );
  const workerOccupancyPercent = !isTerminal
    ? Math.min(100, Number((runningTasksCount / workerConcurrencyCapacity * 100).toFixed(1)))
    : telemetry.throughputDiagnostics?.workerUtilizationPercent
    ?? finalSummary.avgActiveProxyUtilization;
  const totalFleetRoutes = proxyCapacity.totalRoutes > 0
    ? proxyCapacity.totalRoutes
    : Math.max(1, finalSummary.healthyProxyCount + finalSummary.degradedProxyCount + finalSummary.criticalProxyCount);
  const healthyPct = Math.min(100, (finalSummary.healthyProxyCount / totalFleetRoutes) * 100);
  const degradedPct = Math.min(100 - healthyPct, (finalSummary.degradedProxyCount / totalFleetRoutes) * 100);
  const criticalPct = Math.min(100 - healthyPct - degradedPct, (finalSummary.criticalProxyCount / totalFleetRoutes) * 100);
  const failureEvaluationAttempts = Math.max(
    1,
    telemetry.completedTasksCount + errorVelocity.totalErrors,
  );
  const failureRatePercent = (errorVelocity.totalErrors / failureEvaluationAttempts) * 100;
  const failureRateFormatted = failureRatePercent > 0 && failureRatePercent < 0.01
    ? '<0.01'
    : failureRatePercent.toFixed(2);

  const completeDurationValues = {
    meanTaskDurationSec: finalSummary.meanTaskDurationSec,
    meanQueueWaitSec: finalSummary.meanQueueWaitSec,
    meanSetupSec: finalSummary.meanSetupSec,
    meanHandlerSec: finalSummary.meanHandlerSec,
    meanWriterSec: finalSummary.meanWriterSec,
    meanPostSec: finalSummary.meanPostSec,
    meanReleaseSec: finalSummary.meanReleaseSec,
  };
  const completeDurationHasValues = finalSummary.runtimeTelemetryComplete && Object.values(completeDurationValues)
    .some((value) => value != null && value > 0);
  const sampledDurationValues = telemetry.durationBreakdown && telemetry.durationBreakdown.taskCount > 0
    ? telemetry.durationBreakdown
    : null;
  const currentDurationValues = completeDurationHasValues ? completeDurationValues : sampledDurationValues;
  const hasCurrentDurationTelemetry = Boolean(
    currentDurationValues && Object.values(currentDurationValues)
      .some((value) => typeof value === 'number' && value > 0),
  );
  const durationPhases: Array<{ id: string; label: string; sec: number; className: string }> = [];
  const [durationTelemetryCache, setDurationTelemetryCache] = useState<{
    jobId: string;
    signature: string;
    phases: typeof durationPhases;
    meanSec: number;
    sampleCount: number | null;
    expectedTaskCount: number | null;
    isPartial: boolean;
  } | null>(null);
  if (hasCurrentDurationTelemetry && currentDurationValues) {
    if (currentDurationValues.meanQueueWaitSec != null && currentDurationValues.meanQueueWaitSec > 0) {
      durationPhases.push({
        id: 'queue',
        label: 'Queue Wait',
        sec: currentDurationValues.meanQueueWaitSec,
        className: 'jdr-phase-slice-queue',
      });
    }
    if (currentDurationValues.meanSetupSec != null && currentDurationValues.meanSetupSec > 0) {
      durationPhases.push({
        id: 'setup',
        label: 'Setup',
        sec: currentDurationValues.meanSetupSec,
        className: 'jdr-phase-slice-setup',
      });
    }
    if (currentDurationValues.meanHandlerSec != null && currentDurationValues.meanHandlerSec > 0) {
      durationPhases.push({
        id: 'handler',
        label: 'Handler',
        sec: currentDurationValues.meanHandlerSec,
        className: 'jdr-phase-slice-handler',
      });
    }
    if (currentDurationValues.meanWriterSec != null && currentDurationValues.meanWriterSec > 0) {
      durationPhases.push({
        id: 'writer',
        label: 'Writer Wait',
        sec: currentDurationValues.meanWriterSec,
        className: 'jdr-phase-slice-writer',
      });
    }
    if (currentDurationValues.meanPostSec != null && currentDurationValues.meanPostSec > 0) {
      durationPhases.push({
        id: 'post',
        label: 'Post',
        sec: currentDurationValues.meanPostSec,
        className: 'jdr-phase-slice-post',
      });
    }
    if (currentDurationValues.meanReleaseSec != null && currentDurationValues.meanReleaseSec > 0) {
      durationPhases.push({
        id: 'release',
        label: 'Release',
        sec: currentDurationValues.meanReleaseSec,
        className: 'jdr-phase-slice-release',
      });
    }
  }

  const currentPhaseSumSec = durationPhases.reduce((acc, p) => acc + p.sec, 0);
  const currentMeanDurationSec = currentDurationValues?.meanTaskDurationSec != null && currentDurationValues.meanTaskDurationSec > 0
    ? currentDurationValues.meanTaskDurationSec
    : currentPhaseSumSec;
  const currentDurationIsPartial = Boolean(hasCurrentDurationTelemetry && !finalSummary.runtimeTelemetryComplete);
  const currentDurationSampleCount = currentDurationIsPartial ? sampledDurationValues?.taskCount ?? null : null;
  const currentDurationExpectedTaskCount = currentDurationIsPartial ? sampledDurationValues?.expectedTaskCount ?? null : null;
  const currentDurationSignature = JSON.stringify([
    durationPhases,
    currentMeanDurationSec,
    currentDurationSampleCount,
    currentDurationExpectedTaskCount,
    currentDurationIsPartial,
  ]);
  if (hasCurrentDurationTelemetry) {
    const cacheIsCurrent = durationTelemetryCache?.jobId === resolvedJobId
      && durationTelemetryCache.signature === currentDurationSignature;
    if (!cacheIsCurrent) {
      setDurationTelemetryCache({
        jobId: resolvedJobId,
        signature: currentDurationSignature,
        phases: durationPhases,
        meanSec: currentMeanDurationSec,
        sampleCount: currentDurationSampleCount,
        expectedTaskCount: currentDurationExpectedTaskCount,
        isPartial: currentDurationIsPartial,
      });
    }
  }
  const cachedDurationTelemetry = durationTelemetryCache?.jobId === resolvedJobId
    ? durationTelemetryCache
    : null;
  const hasDurationTelemetry = hasCurrentDurationTelemetry || cachedDurationTelemetry !== null;
  const displayedDurationPhases = hasCurrentDurationTelemetry
    ? durationPhases
    : cachedDurationTelemetry?.phases ?? [];
  const phaseSumSec = displayedDurationPhases.reduce((acc, p) => acc + p.sec, 0);
  const effectiveMeanDurationSec = hasCurrentDurationTelemetry && currentDurationValues?.meanTaskDurationSec != null && currentDurationValues.meanTaskDurationSec > 0
    ? currentDurationValues.meanTaskDurationSec
    : cachedDurationTelemetry?.meanSec ?? phaseSumSec;
  const displayedDurationIsPartial = hasCurrentDurationTelemetry
    ? currentDurationIsPartial
    : cachedDurationTelemetry?.isPartial ?? false;
  const displayedDurationSampleCount = hasCurrentDurationTelemetry
    ? currentDurationSampleCount
    : cachedDurationTelemetry?.sampleCount ?? null;
  const displayedDurationExpectedTaskCount = hasCurrentDurationTelemetry
    ? currentDurationExpectedTaskCount
    : cachedDurationTelemetry?.expectedTaskCount ?? null;
  const durationDenominatorSec = Math.max(0.001, effectiveMeanDurationSec, phaseSumSec);

  const proxyScrollRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const wrapper = proxyScrollRef.current;
    const table = wrapper?.querySelector('table');
    if (!wrapper || !table) {
      wrapper?.style.removeProperty('--jdr-proxy-scroll-height');
      return;
    }
    const measure = () => {
      const rows = table.tBodies[0]?.rows;
      const lastVisibleRow = rows?.[Math.min(10, rows.length) - 1];
      if (!lastVisibleRow) return;
      const scrollbarHeight = wrapper.offsetHeight - wrapper.clientHeight;
      const height = lastVisibleRow.getBoundingClientRect().bottom - table.getBoundingClientRect().top + scrollbarHeight + 1;
      wrapper.style.setProperty('--jdr-proxy-scroll-height', `${height}px`);
    };
    measure();
    window.addEventListener('resize', measure);
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    observer?.observe(table);
    return () => {
      window.removeEventListener('resize', measure);
      observer?.disconnect();
    };
  }, [filteredAndSortedProxies]);

  const hasSecondaryTelemetry = Boolean(
    finalSummary.steadyStateEfficiencyPercent != null ||
    (finalSummary.workersSeen != null && finalSummary.expectedWorkers != null) ||
    finalSummary.readyTimelineNonemptyPercent != null ||
    finalSummary.readyNonemptySamples != null ||
    (telemetry.quality && !telemetry.quality.isCompleteTaskSample)
  );

  return (
    <div className="jdr-container">
      {/* ── Top View Switcher & Export Bar ── */}
      <div className="jdr-top-actions-bar">
        <div className="jdr-view-switcher">
          <button
            type="button"
            className={`jdr-view-btn ${activeView === 'telemetry' ? 'active' : ''}`}
            onClick={() => setActiveView('telemetry')}
          >
            <DiagnosticGlyph name="logs">📋</DiagnosticGlyph> Telemetry
          </button>
          <button
            type="button"
            className={`jdr-view-btn ${activeView === 'compare' ? 'active' : ''}`}
            onClick={() => setActiveView('compare')}
          >
            <DiagnosticGlyph name="statistics">⚖️</DiagnosticGlyph> Compare
          </button>
        </div>

        <div className="jdr-export-actions">
          <div className="jdr-markdown-actions" role="group" aria-label="Markdown report actions">
            <button
              type="button"
              className="jdr-action-btn"
              onClick={handleCopyReport}
              aria-label={copiedReport ? 'Markdown Report copied to clipboard' : 'Copy Markdown Report to clipboard'}
              title={copiedReport ? 'Markdown Report copied to clipboard' : 'Copy Markdown Report to clipboard'}
            >
              {copiedReport ? (
                <span aria-hidden="true">✓</span>
              ) : (
                <svg className="jdr-clipboard-icon" viewBox="0 0 16 16" aria-hidden="true">
                  <rect x="3.25" y="3.25" width="9.5" height="11" rx="1.5" />
                  <path d="M6 3.25v-1h4v1M6 7h4M6 9.5h4" />
                </svg>
              )}
              <span>Markdown Report</span>
            </button>
            <button
              type="button"
              className="jdr-action-btn jdr-icon-action-btn"
              onClick={handleDownloadReport}
              aria-label="Download Markdown Report"
              title="Download Markdown Report"
            >
              <svg className="jdr-download-icon" viewBox="0 0 16 16" aria-hidden="true">
                <path d="M8 1.75v8m0 0 3-3m-3 3-3-3M2.75 10.5v2.25c0 .55.45 1 1 1h8.5c.55 0 1-.45 1-1V10.5" />
              </svg>
            </button>
          </div>
          <div className="jdr-diagnostic-actions">
            <button
              type="button"
              className="jdr-action-btn jdr-bundle-btn"
              onClick={handleDownloadJsonBundle}
            >
              <DiagnosticGlyph name="database" iconClassName="jdr-action-icon">📦</DiagnosticGlyph> Diagnostic Bundle (.json)
            </button>
          </div>
        </div>
      </div>

      {/* ── Final Run Summary Section ── */}
      {activeView === 'telemetry' && (
        <div className="jdr-final-summary-card">
          {/* ── Performance Overview: Visual Analytics ── */}
          <div className="jdr-perf-overview" data-testid="performance-overview">
            <div className="jdr-perf-header">
              <div className="jdr-section-title" style={{ margin: 0 }}>
                <span>Performance Overview</span>
                <span className="jdr-perf-subtitle">{isTerminal ? 'Whole-run averages · Efficiency · Reliability' : '● Live'}</span>
              </div>
            </div>

            <div className="jdr-perf-grid">
              <div className="jdr-perf-card">
                <div className="jdr-perf-card-header">
                  <span className="jdr-perf-card-label">Throughput</span>
                  <span className="jdr-perf-card-sub">{isTerminal ? 'Average' : 'Live'}</span>
                </div>
                <div className="jdr-perf-card-metric">
                  <span className="jdr-perf-card-value">{overviewThroughput.toLocaleString()}</span>
                  <span className="jdr-perf-card-sub">{throughputShortLabel}</span>
                </div>
                <div className="jdr-segmented-bar" role="meter" tabIndex={0}
                  aria-label="Throughput and observed burst"
                  aria-valuemin={0} aria-valuemax={throughputBarMaximum} aria-valuenow={overviewThroughput}
                  aria-valuetext={`${isTerminal ? 'Average' : 'Live'}: ${overviewThroughput} ${throughputShortLabel}; observed burst: ${finalSummary.peakItemsPerSec} ${throughputShortLabel}`}>
                  <div className="jdr-segment is-throughput" style={{ width: `${throughputBasePercent}%` }}
                    title={`${isTerminal ? 'Average' : 'Live'}: ${overviewThroughput} ${throughputShortLabel}`} />
                  <div className="jdr-segment is-burst" style={{ width: `${throughputBurstPercent}%` }}
                    title={`Observed burst: ${finalSummary.peakItemsPerSec} ${throughputShortLabel}`} />
                </div>
                <div className="jdr-perf-legend">
                  <span className="jdr-perf-legend-item"><span className="jdr-legend-dot-mini is-throughput" />{isTerminal ? 'Average' : 'Live'}</span>
                  <span className="jdr-perf-legend-item"><span className="jdr-legend-dot-mini is-burst" />Burst</span>
                </div>
              </div>

              <div className="jdr-perf-card">
                <div className="jdr-perf-card-header">
                  <span className="jdr-perf-card-label">In Flight</span>
                  <span className="jdr-perf-card-sub">{isTerminal ? 'Average' : 'Live'}</span>
                </div>
                <div className="jdr-perf-card-metric">
                  <span className="jdr-perf-card-value">{overviewConcurrency.toLocaleString()}</span>
                  <span className="jdr-perf-card-sub">active tasks</span>
                </div>
                <TelemetryBar value={overviewConcurrency} limit={proxyCapacity.totalRoutes}
                  label={`${isTerminal ? 'Average' : 'Live'} in-flight tasks vs route ceiling`} tone="concurrency" />
                <span className="jdr-perf-card-caption">
                  {workerPoolSize} workers · {(overviewConcurrency / Math.max(1, workerPoolSize)).toFixed(1)}× load
                  {isTerminal && !finalSummary.runtimeTelemetryComplete && ' · Estimated'}
                </span>
              </div>

              {/* 1. Model Efficiency: Horizontal bullet chart */}
              <div className="jdr-perf-card">
                <div className="jdr-perf-card-header">
                  <span className="jdr-perf-card-label">
                    {!isTerminal ? 'Live Model Efficiency' : finalSummary.runtimeTelemetryComplete ? 'Active-Window Efficiency' : 'Estimated Model Efficiency'}
                  </span>
                  <InfoTooltip
                    ariaLabel="Model efficiency methodology"
                    content={
                      <div>
                        <p style={{ margin: '0 0 0.35rem' }}>
                          Efficiency is the ratio of achieved throughput ({efficiencyCurrentThroughput} {throughputShortLabel}) against the governing {governingCapacityModelLabel} capacity ceiling ({finalSummary.theoreticalMaxItemsPerSec} {throughputShortLabel}).
                        </p>
                        <p style={{ margin: 0, color: 'var(--color-text-secondary, #8b949e)', fontStyle: 'italic' }}>
                          {finalSummary.runtimeTelemetryComplete
                            ? 'Full-job runtime aggregates supply timing across the active execution window; the task-list page does not limit this metric.'
                            : `Job-wide task counters supply throughput. Capacity uses latency from ${telemetry.quality?.loadedTaskCount ?? 0} loaded tasks because complete runtime timing is unavailable. This is a model estimate.`}
                        </p>
                      </div>
                    }
                  />
                </div>
                <div className="jdr-perf-card-metric">
                  <span className="jdr-perf-card-value">{isTerminal ? finalSummary.efficiencyPercent : Number((latestObservedRate / Math.max(1, finalSummary.theoreticalMaxItemsPerSec) * 100).toFixed(1))}%</span>
                  <span className="jdr-perf-card-sub">
                    {efficiencyCurrentThroughput} / {finalSummary.theoreticalMaxItemsPerSec} {throughputShortLabel}
                  </span>
                </div>
                <div
                  className="jdr-bullet-chart"
                  role="progressbar"
                  aria-label="Model Efficiency"
                  aria-valuenow={isTerminal ? finalSummary.efficiencyPercent : Number((latestObservedRate / Math.max(1, finalSummary.theoreticalMaxItemsPerSec) * 100).toFixed(1))}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div className="jdr-bullet-track">
                    <div
                      className="jdr-bullet-fill"
                      style={{ width: `${Math.min(100, Math.max(0, isTerminal ? finalSummary.efficiencyPercent : latestObservedRate / Math.max(1, finalSummary.theoreticalMaxItemsPerSec) * 100))}%` }}
                    />
                    <div
                      className="jdr-bullet-target"
                      title={`Governing capacity ceiling: ${finalSummary.theoreticalMaxItemsPerSec} ${throughputShortLabel}`}
                    />
                  </div>
                </div>
                <span className="jdr-perf-card-caption">
                  Governing {finalSummary.capacityModelBottleneck === 'proxy_routes' ? 'route' : 'worker-slot'} model ({finalSummary.runtimeTelemetryComplete ? 'active-window' : 'whole-job rate'})
                </span>
              </div>

              {/* 2. Worker Occupancy: Horizontal utilization bar */}
              <div className="jdr-perf-card">
                <div className="jdr-perf-card-header">
                  <span className="jdr-perf-card-label">
                    {!isTerminal ? 'Worker Occupancy' : finalSummary.runtimeTelemetryComplete ? 'Worker Occupancy' : 'Estimated Worker Occupancy'}
                  </span>
                  <InfoTooltip
                    ariaLabel="Worker occupancy methodology"
                    content={
                      <div>
                        <p style={{ margin: '0 0 0.35rem' }}>
                          {!isTerminal ? `Current task concurrency (${overviewConcurrency}) versus modeled worker capacity (${workerConcurrencyCapacity} concurrent tasks) across ${workerPoolSize} workers.` : finalSummary.runtimeTelemetryComplete
                            ? `Measured time-weighted task concurrency (${overviewConcurrency}) versus worker capacity (${workerConcurrencyCapacity} concurrent tasks) across ${workerPoolSize} workers.`
                            : `Estimated ~${overviewConcurrency} concurrent in-flight tasks derived using Little’s Law (L = λ · W) from lifetime throughput and sampled latency.`}
                        </p>
                        <p style={{ margin: 0, color: 'var(--color-text-secondary, #8b949e)', fontStyle: 'italic' }}>
                          {!isTerminal ? 'Current running task count from job telemetry.' : finalSummary.runtimeTelemetryComplete
                            ? 'Directly measured time-weighted value.'
                            : 'Modeled estimate derived from sample rates; not a directly measured time-weighted value.'}
                        </p>
                      </div>
                    }
                  />
                </div>
                <div className="jdr-perf-card-metric">
                  <span className="jdr-perf-card-value">{workerOccupancyPercent}%{isTerminal ? ' Avg' : ''}</span>
                  <span className="jdr-perf-card-sub">
                    ~{overviewConcurrency} in-flight tasks
                  </span>
                </div>
                <div
                  className="jdr-util-chart"
                  role="progressbar"
                  aria-label="Worker Occupancy"
                  aria-valuenow={workerOccupancyPercent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div className="jdr-util-track">
                    <div
                      className="jdr-util-fill"
                      style={{ width: `${Math.min(100, Math.max(0, workerOccupancyPercent))}%` }}
                    />
                  </div>
                </div>
                <span className="jdr-perf-card-caption">
                  {!isTerminal ? `${overviewConcurrency} active tasks across ${workerPoolSize} workers` : finalSummary.runtimeTelemetryComplete
                    ? `${overviewConcurrency} time-weighted tasks across ${workerPoolSize} workers`
                    : `${overviewConcurrency} estimated concurrent tasks (Little’s Law)`}
                </span>
              </div>

              {/* 3. Proxy Fleet Health: Segmented horizontal bar */}
              <div className="jdr-perf-card">
                <div className="jdr-perf-card-header">
                  <span className="jdr-perf-card-label">Proxy Fleet Health</span>
                  <InfoTooltip
                    ariaLabel="Proxy fleet health distribution"
                    content={
                      <div>
                        <p style={{ margin: '0 0 0.35rem' }}>
                          Distribution across {totalFleetRoutes} configured routes:
                        </p>
                        <ul style={{ margin: 0, paddingLeft: '1.1rem', fontSize: '0.72rem' }}>
                          <li>Healthy: {finalSummary.healthyProxyCount} ({healthyPct.toFixed(1)}%)</li>
                          <li>Degraded: {finalSummary.degradedProxyCount} ({degradedPct.toFixed(1)}%)</li>
                          <li>Critical: {finalSummary.criticalProxyCount} ({criticalPct.toFixed(1)}%)</li>
                        </ul>
                      </div>
                    }
                  />
                </div>
                <div className="jdr-perf-card-metric">
                  <span className="jdr-perf-card-value">
                    {finalSummary.healthyProxyCount} / {totalFleetRoutes}
                  </span>
                  <span className="jdr-perf-card-sub">
                    {healthyPct.toFixed(1)}% Healthy
                  </span>
                </div>
                <div className="jdr-segmented-bar" role="meter" aria-label="Proxy fleet health distribution">
                  {healthyPct > 0 && (
                    <div
                      className="jdr-segment is-healthy"
                      style={{ width: `${healthyPct}%` }}
                      title={`Healthy: ${finalSummary.healthyProxyCount}`}
                    />
                  )}
                  {degradedPct > 0 && (
                    <div
                      className="jdr-segment is-degraded"
                      style={{ width: `${degradedPct}%` }}
                      title={`Degraded: ${finalSummary.degradedProxyCount}`}
                    />
                  )}
                  {criticalPct > 0 && (
                    <div
                      className="jdr-segment is-critical"
                      style={{ width: `${criticalPct}%` }}
                      title={`Critical: ${finalSummary.criticalProxyCount}`}
                    />
                  )}
                </div>
                <div className="jdr-perf-legend">
                  <span className="jdr-perf-legend-item">
                    <span className="jdr-legend-dot-mini is-healthy" /> {finalSummary.healthyProxyCount} Healthy
                  </span>
                  <span className="jdr-perf-legend-item">
                    <span className="jdr-legend-dot-mini is-degraded" /> {finalSummary.degradedProxyCount} Degraded
                  </span>
                  {finalSummary.criticalProxyCount > 0 && (
                    <span className="jdr-perf-legend-item">
                      <span className="jdr-legend-dot-mini is-critical" /> {finalSummary.criticalProxyCount} Critical
                    </span>
                  )}
                </div>
              </div>

              <div className="jdr-perf-card">
                <div className="jdr-perf-card-header">
                  <span className="jdr-perf-card-label">{isTerminal ? 'Average Proxy Usage' : 'Proxy Usage'}</span>
                </div>
                <div className="jdr-perf-card-metric">
                  <span className="jdr-perf-card-value">{overviewProxyUtilization}%</span>
                  <span className="jdr-perf-card-sub">{overviewProxyRoutes} / {proxyCapacity.totalRoutes} slots</span>
                </div>
                <div className="jdr-util-chart" role="meter" aria-label={isTerminal ? 'Average proxy utilization' : 'Live proxy utilization'}
                  aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.max(0, Math.min(100, overviewProxyUtilization))}>
                  <div className="jdr-util-track"><div className="jdr-util-fill"
                    style={{ width: `${Math.max(0, Math.min(100, overviewProxyUtilization))}%` }} /></div>
                </div>
                <span className="jdr-perf-card-caption">
                  {proxyCapacity.enabledProxies} proxies{proxyCapacity.directRoutes > 0 && <> · {proxyCapacity.directRoutes} direct</>}
                </span>
              </div>

              <div className="jdr-perf-card">
                <div className="jdr-perf-card-header">
                  <div className="jdr-perf-card-label-row">
                    <span className="jdr-perf-card-label">Task Latency</span>
                    <InfoTooltip
                      ariaLabel="Latency percentiles explained"
                      content={
                        <div>
                          <p style={{ margin: '0 0 0.35rem' }}>
                            A percentile is the task duration at or below which that share of sampled tasks completed. p50 is the median; p90 means 90% completed at or below that time and 10% took longer. p95 and p99 show the slower tail, with about 1% of tasks taking longer than p99.
                          </p>
                          <p style={{ margin: 0, color: 'var(--color-text-secondary, #8b949e)' }}>
                            The bar scales to p99, fills to the median, and marks p90, p95, and p99. Based on {latencyPercentiles.sampleCount.toLocaleString()} task samples.
                          </p>
                        </div>
                      }
                    />
                  </div>
                </div>
                <div className="jdr-perf-card-metric">
                  <span className="jdr-perf-card-value">{latencyPercentiles.p50}s</span>
                  <span className="jdr-perf-card-sub">Median</span>
                </div>
                <TelemetryBar value={latencyPercentiles.p50} limit={latencyPercentiles.p99}
                  label="Task latency percentiles"
                  description={`Median: ${latencyPercentiles.p50}s · p90: ${latencyPercentiles.p90}s · p95: ${latencyPercentiles.p95}s · p99: ${latencyPercentiles.p99}s`}
                  markers={[
                    { value: latencyPercentiles.p90, label: `p90: ${latencyPercentiles.p90}s`, className: 'is-p90' },
                    { value: latencyPercentiles.p95, label: `p95: ${latencyPercentiles.p95}s`, className: 'is-p95' },
                    { value: latencyPercentiles.p99, label: `p99: ${latencyPercentiles.p99}s`, className: 'is-p99' },
                  ]}
                  tone="latency" />
                <div className="jdr-perf-legend jdr-latency-legend">
                  <span className="jdr-perf-legend-item"><span className="jdr-legend-dot-mini is-latency-p90" />p90: {latencyPercentiles.p90}s</span>
                  <span className="jdr-perf-legend-item"><span className="jdr-legend-dot-mini is-latency-p95" />p95: {latencyPercentiles.p95}s</span>
                  <span className="jdr-perf-legend-item"><span className="jdr-legend-dot-mini is-latency-p99" />p99: {latencyPercentiles.p99}s</span>
                </div>
              </div>

              {/* 4. Failure Rate: Minimal visual indicator with proportional bar */}
              <div className="jdr-perf-card">
                <div className="jdr-perf-card-header">
                  <span className="jdr-perf-card-label">Failure Rate</span>
                  <InfoTooltip
                    ariaLabel="Failure rate details"
                    content={
                      <div>
                        <p style={{ margin: '0 0 0.35rem' }}>
                          {errorVelocity.totalErrors} total failures out of {failureEvaluationAttempts.toLocaleString()} attempted tasks ({failureRatePercent.toFixed(2)}%).
                        </p>
                        <p style={{ margin: 0, color: 'var(--color-text-secondary, #8b949e)' }}>
                          Includes {errorVelocity.rate429Count} rate limit (HTTP 429) errors.
                        </p>
                      </div>
                    }
                  />
                </div>
                <div className="jdr-perf-card-metric">
                  <span className="jdr-perf-card-value">{failureRateFormatted}%</span>
                  <span className="jdr-perf-card-sub">
                    {errorVelocity.totalErrors} Failures ({errorVelocity.rate429Count} 429s)
                  </span>
                </div>
                <div
                  className="jdr-failure-chart"
                  role="meter"
                  aria-label="Failure rate"
                  aria-valuenow={failureRatePercent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div className="jdr-failure-track">
                    <div
                      className={`jdr-failure-fill ${
                        failureRatePercent > 5
                          ? 'is-danger'
                          : failureRatePercent > 1
                            ? 'is-warning'
                            : 'is-nominal'
                      }`}
                      style={{
                        width: `${Math.min(100, Math.max(failureRatePercent > 0 ? 1 : 0, failureRatePercent))}%`,
                      }}
                    />
                  </div>
                </div>
                {!isTerminal && <span className="jdr-perf-card-caption">
                  {errorVelocity.errorsLast60s} / {errorVelocity.safetyThresholdLimit} limit in {Math.round(errorVelocity.errorWindowSeconds ?? 60)}s
                </span>}
              </div>
            </div>

            {/* ── Task Duration Breakdown ── */}
            {(hasDurationTelemetry || !isTerminal) && (
              <div className="jdr-duration-breakdown-card" data-testid="duration-breakdown">
                <div className="jdr-duration-header">
                  <div className="jdr-duration-title">
                    <span>Task Duration Breakdown</span>
                    <InfoTooltip
                      ariaLabel="Task duration breakdown explanation"
                      content={
                        <p style={{ margin: 0 }}>
                          {displayedDurationIsPartial
                            ? `Partial runtime averages from ${displayedDurationSampleCount?.toLocaleString() ?? 0} of ${displayedDurationExpectedTaskCount?.toLocaleString() ?? 0} terminal tasks. Queue wait represents backlog admission wait; Handler is exclusive worker execution; Writer wait is database transaction wait.`
                            : 'Mutually exclusive service and wait phases measured across full-job worker execution. Queue wait represents backlog admission wait; Handler is exclusive worker execution; Writer wait is database transaction wait.'}
                        </p>
                      }
                    />
                  </div>
                  <div className="jdr-duration-mean">
                    {hasDurationTelemetry
                      ? <span>Mean Task Duration: <strong>{effectiveMeanDurationSec.toFixed(2)}s</strong></span>
                      : <span>Timing data pending</span>}
                    {displayedDurationIsPartial && displayedDurationSampleCount != null && (
                      <span className="jdr-duration-sample">
                        {displayedDurationSampleCount.toLocaleString()} / {(displayedDurationExpectedTaskCount ?? displayedDurationSampleCount).toLocaleString()} tasks
                      </span>
                    )}
                  </div>
                </div>
                {hasDurationTelemetry ? (
                  <>
                    <div className="jdr-duration-stacked-bar">
                      {displayedDurationPhases.map((phase) => {
                        const widthPct = Math.min(100, (phase.sec / durationDenominatorSec) * 100);
                        return (
                          <div
                            key={phase.id}
                            className={`jdr-duration-phase-slice ${phase.className}`}
                            style={{ width: `${widthPct}%` }}
                            title={`${phase.label}: ${phase.sec.toFixed(2)}s (${widthPct.toFixed(1)}%)`}
                          />
                        );
                      })}
                    </div>
                    <div className="jdr-duration-legend">
                      {displayedDurationPhases.map((phase) => (
                        <span key={phase.id} className="jdr-perf-legend-item">
                          <span className={`jdr-legend-dot-mini ${phase.className}`} />
                          {phase.label}: {phase.sec.toFixed(2)}s ({((phase.sec / durationDenominatorSec) * 100).toFixed(1)}%)
                        </span>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="jdr-duration-empty">Timing details will appear after the first task completes.</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Historical Performance Comparison Section ── */}
      {activeView === 'compare' && (
        <div className="jdr-regression-card" data-testid="historical-regression-card">
          <div className="jdr-regression-header">
            <div className="jdr-regression-title-row">
              <h3 className="jdr-regression-title">Run comparison</h3>
              {comparisonStatus && (
                <span
                  className={`jdr-comparison-status is-${comparisonStatus}`}
                  data-testid="comparison-status"
                  aria-label={`Comparison status: ${comparisonStatus}`}
                >
                  {comparisonStatus === 'partial'
                    ? 'Partial'
                    : comparisonStatus.charAt(0).toUpperCase() + comparisonStatus.slice(1)}
                </span>
              )}
            </div>

            <div className="jdr-regression-controls">
              <div className="jdr-regression-select-wrapper">
                <label htmlFor="jdr-tolerance-select" className="jdr-baseline-label">
                  Task match:
                </label>
                <select
                  id="jdr-tolerance-select"
                  className="jdr-baseline-select jdr-tolerance-select"
                  data-testid="tolerance-select"
                  value={
                    isCustomTolerance
                      ? 'custom'
                      : taskCountToleranceBoundary === Infinity
                        ? 'any'
                        : isTaskCountTolerancePreset(taskCountTolerancePercent)
                          ? String(taskCountTolerancePercent)
                          : 'custom'
                  }
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val === 'any') {
                      setIsCustomTolerance(false);
                      updateTolerancePercent(999999);
                    } else if (val === 'custom') {
                      setIsCustomTolerance(true);
                    } else {
                      setIsCustomTolerance(false);
                      updateTolerancePercent(Number(val));
                    }
                  }}
                  aria-label="Select task count match tolerance percentage"
                >
                  <option value="5">±5%</option>
                  <option value="10">±10% (Default)</option>
                  <option value="15">±15%</option>
                  <option value="20">±20%</option>
                  <option value="25">±25%</option>
                  <option value="50">±50%</option>
                  <option value="100">±100%</option>
                  <option value="any">Any (All runs)</option>
                  <option value="custom">Custom...</option>
                </select>

                {isCustomTolerance && (
                  <div className="jdr-tolerance-custom-inline">
                    <span className="jdr-tolerance-prefix">±</span>
                    <input
                      id="jdr-custom-tolerance-input"
                      data-testid="tolerance-custom-input"
                      type="number"
                      min="0"
                      max="1000"
                      step="1"
                      className="jdr-tolerance-number-input"
                      value={taskCountTolerancePercent >= 1000 ? 10 : taskCountTolerancePercent}
                      onChange={(e) => {
                        const parsed = parseFloat(e.target.value);
                        if (!Number.isNaN(parsed) && parsed >= 0) {
                          updateTolerancePercent(parsed);
                        }
                      }}
                      aria-label="Custom task count tolerance percentage"
                    />
                    <span className="jdr-tolerance-suffix">%</span>
                  </div>
                )}
              </div>

              <div className="jdr-regression-select-wrapper">
                <label htmlFor="jdr-baseline-select" className="jdr-baseline-label">
                  Baseline Run:
                </label>
                <select
                  id="jdr-baseline-select"
                  className="jdr-baseline-select"
                  data-testid="baseline-select"
                  value={selectedBaselineId || ''}
                  onChange={(e) => {
                    setBaselineChoice(e.target.value || null);
                  }}
                  aria-label="Select baseline historical run for comparison"
                >
                  {availableHistoricalJobs.length === 0 ? (
                    <option value="">No historical runs available</option>
                  ) : (
                    <>
                      <option value="">None (Disable Comparison)</option>
                      {availableHistoricalJobs.map((hJob) => {
                        const dateStr = hJob.created_at
                          ? new Date(hJob.created_at).toLocaleDateString()
                          : '';
                        return (
                          <option key={hJob.job_id} value={hJob.job_id}>
                            {hJob.job_name || hJob.job_id} ({dateStr} · {hJob.status} · {(hJob.task_count || hJob.completed_tasks)?.toLocaleString()} tasks)
                          </option>
                        );
                      })}
                    </>
                  )}
                </select>
              </div>
            </div>
          </div>

          {comparison ? (
            <div className="jdr-regression-body">
              <table className="jdr-comparison-table" data-testid="comparison-table">
                <caption className="sr-only">Current run compared with the selected baseline and the fastest and slowest workload-matched runs</caption>
                <colgroup>
                  <col className="is-metric" />
                  <col className="is-current" />
                  <col className="is-baseline" />
                  <col className="is-best" />
                  <col className="is-worst" />
                  <col className="is-change" />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">Metric</th>
                    <th scope="col">Current</th>
                    <th scope="col">Baseline</th>
                    <th scope="col" title="Highest completed tasks per second among finished runs within the selected task-count boundary">Best run</th>
                    <th scope="col" title="Lowest completed tasks per second among finished runs within the selected task-count boundary">Worst run</th>
                    <th scope="col">Change</th>
                  </tr>
                </thead>
                <tbody>
                  <tr data-testid="comparison-row-throughput">
                    <th scope="row">Throughput</th>
                    <td>{formatComparisonRate(comparisonCurrentThroughput, throughputShortLabel)}</td>
                    <td>{formatComparisonRate(
                      baselineThroughput,
                      comparison.throughputComparable === false ? 'tasks/s' : throughputShortLabel,
                    )}</td>
                    <HistoricalRunCell
                      run={historicalRunExtremes.best}
                      metric="throughput"
                      throughputUnit={comparison.throughputComparable === false ? 'tasks/s' : throughputShortLabel}
                    />
                    <HistoricalRunCell
                      run={historicalRunExtremes.worst}
                      metric="throughput"
                      throughputUnit={comparison.throughputComparable === false ? 'tasks/s' : throughputShortLabel}
                    />
                    <td>
                      {comparison.throughputComparable === false ? (
                        <span className="jdr-comparison-change is-unavailable">Not comparable</span>
                      ) : throughputDeltaAvailable ? (
                        <span className={`jdr-comparison-change ${comparisonDeltaTone(comparisonThroughputDeltaPercent, true)}`}>
                          {formatSignedPercent(comparisonThroughputDeltaPercent)}
                        </span>
                      ) : (
                        <span className="jdr-comparison-change is-unavailable">Unavailable</span>
                      )}
                    </td>
                  </tr>
                  <tr data-testid="comparison-row-duration">
                    <th scope="row">
                      Duration
                      {comparison.currentRun.isProjectedDuration && (
                        <small style={{ display: 'block', fontWeight: 400, fontSize: '0.62rem', color: 'var(--color-text-tertiary, #8b949e)' }}>
                          Projected
                        </small>
                      )}
                    </th>
                    <td>
                      {comparison.currentRun.isProjectedDuration ? (
                        <span className="jdr-comparison-run-value">
                          <strong>~{comparison.currentRun.durationFormatted}</strong>
                          <small title={`Elapsed: ${comparison.currentRun.elapsedFormatted} · ETA: ~${comparison.currentRun.remainingFormatted}`}>
                            Elapsed {comparison.currentRun.elapsedFormatted}
                          </small>
                        </span>
                      ) : comparison.deltas.durationComparable === false ? (
                        <span className="jdr-comparison-run-value">
                          <strong>{comparison.currentRun.durationFormatted}</strong>
                          <small title="In progress · ETA unavailable">In progress</small>
                        </span>
                      ) : (
                        comparison.currentRun.durationFormatted
                      )}
                    </td>
                    <td>{comparison.baselineJob?.durationFormatted ?? '—'}</td>
                    <HistoricalRunCell run={historicalRunExtremes.best} metric="duration" />
                    <HistoricalRunCell run={historicalRunExtremes.worst} metric="duration" />
                    <td>
                      {comparison.deltas.durationComparable === false ? (
                        <span className="jdr-comparison-change is-unavailable">In progress</span>
                      ) : (
                        <span className={`jdr-comparison-change ${comparisonDeltaTone(comparison.deltas.durationDeltaSec, false)}`}>
                          {comparison.currentRun.isProjectedDuration ? '~' : ''}{formatSignedDuration(comparison.deltas.durationDeltaSec)}
                        </span>
                      )}
                    </td>
                  </tr>
                  <tr data-testid="comparison-row-failure-rate">
                    <th scope="row">Failure rate</th>
                    <td>{comparison.currentRun.failureRatePercent.toFixed(1)}%</td>
                    <td>{comparison.baselineJob ? `${comparison.baselineJob.failureRatePercent.toFixed(1)}%` : '—'}</td>
                    <HistoricalRunCell run={historicalRunExtremes.best} metric="failureRate" />
                    <HistoricalRunCell run={historicalRunExtremes.worst} metric="failureRate" />
                    <td>
                      <span className={`jdr-comparison-change ${comparisonDeltaTone(comparison.deltas.failureRateDeltaPercent, false)}`}>
                        {formatSignedPercentagePoints(comparison.deltas.failureRateDeltaPercent)}
                      </span>
                    </td>
                  </tr>
                  <tr data-testid="comparison-row-completed-tasks">
                    <th scope="row">Completed tasks</th>
                    <td>
                      {isLiveJob && comparison.currentRun.totalTasks > comparison.currentRun.completedTasks ? (
                        <span className="jdr-comparison-run-value">
                          <strong>{comparison.currentRun.completedTasks.toLocaleString()}</strong>
                          <small title={`${comparison.currentRun.completedTasks.toLocaleString()} of ${comparison.currentRun.totalTasks.toLocaleString()} total tasks`}>
                            of {comparison.currentRun.totalTasks.toLocaleString()}
                          </small>
                        </span>
                      ) : (
                        comparison.currentRun.completedTasks.toLocaleString()
                      )}
                    </td>
                    <td>{comparison.baselineJob?.completedTasks.toLocaleString() ?? '—'}</td>
                    <HistoricalRunCell run={historicalRunExtremes.best} metric="completedTasks" />
                    <HistoricalRunCell run={historicalRunExtremes.worst} metric="completedTasks" />
                    <td>
                      <span className="jdr-comparison-change is-neutral">
                        {formatSignedTaskCount(comparison.deltas.completedTasksDelta)}
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : (
            <div className="jdr-regression-empty">
              {availableHistoricalJobs.length === 0
                ? (taskCountToleranceBoundary === Infinity
                    ? 'No prior historical jobs were found.'
                    : `No prior historical jobs within ±${taskCountTolerancePercent}% of this run's ${currentTaskCount.toLocaleString()} tasks were found.`)
                : 'Select a similar-size historical job from the dropdown above to compute regression deltas.'}
            </div>
          )}
        </div>
      )}

      {/* ── Section 2: Real-Time / Macro Performance Line Graphs ── */}
      <div>
        <div className="jdr-section-title">
          <span>
            {isTerminal
              ? 'Job Lifecycle Macro Performance Graphs'
              : 'Real-Time Performance Graphs'}
          </span>
          <span>
            {isTerminal
              ? `Lifecycle axis · retained observation points only · ${finalSummary.totalDurationFormatted}`
              : jobRuntimeSamples.length > 0
                ? 'Last 3 minutes · job-wide Redis task counters and browser-captured latency/error observations'
                : 'Last 3 minutes · backend interval observations captured while job details are open'}
          </span>
        </div>

        <div className={`jdr-graphs-grid${expandedChart ? ' has-expanded' : ''}`}>
          {/* Graph 1: Live Items/sec Throughput */}
          <SvgLineChart
            chartId="throughput"
            chartGroup="throughput-concurrency"
            expandedChartId={expandedChart?.id ?? null}
            expandedChartGroup={expandedChart?.group ?? null}
            onToggleExpand={toggleExpandedChart}
            title={`Throughput Velocity (${chartThroughputLabel})`}
            subtitle={
              hasJobRuntimeHistory
                ? runtimeBucketMs > 1_000
                  ? `Job-wide terminal-task counter delta per ${formatBucketDuration(runtimeBucketMs)} bucket, over the time its samples cover; gaps stay blank`
                  : 'Job-wide terminal-task counter delta divided by each measured sample interval; gaps stay blank'
                : isTerminal
                  ? 'Browser-captured interval rates; no stored job-wide timeline is available'
                  : 'Counter delta divided by elapsed time between backend readings; gaps stay blank'
            }
            referenceLines={throughputComparisonReferences}
            unit="/s"
            timestamps={throughputChartTimestamps}
            sampleIntervalMs={throughputChartIntervals}
            maxLineGapMs={hasJobRuntimeHistory ? runtimeLineGapMs : MAX_CHART_LINE_GAP_MS}
            timeDomain={chartTimeDomain}
            timeScaleMode={isTerminal ? 'full' : 'live'}
            totalDurationFormatted={finalSummary.totalDurationFormatted}
            emptyMessage={isTerminal
              ? 'No stored job-wide timeline is available; browser observations appear only if details were open during the job.'
              : 'Waiting for a second timestamped backend reading...'}
            series={[
              {
                name: hasJobRuntimeHistory
                  ? `Job-wide ${chartThroughputLabel}`
                  : `Observed ${chartThroughputLabel}`,
                values: throughputChartValues,
                color: 'var(--jdr-chart-primary, #388bfd)',
                strokeWidth: 2,
              },
              {
                name: `Observed rolling average (up to ${
                  formatBucketDuration(hasJobRuntimeHistory ? runtimeAverageWindowMs : 5_000)
                })`,
                values: throughputChartAverage,
                color: 'var(--jdr-chart-secondary, #d29922)',
                strokeWidth: 1.5,
                isDashed: true,
              },
            ]}
          />

          {/* Graph 2: Concurrency & Proxy Saturation */}
          <SvgLineChart
            chartId="concurrency"
            chartGroup="throughput-concurrency"
            expandedChartId={expandedChart?.id ?? null}
            expandedChartGroup={expandedChart?.group ?? null}
            onToggleExpand={toggleExpandedChart}
            title="In-Flight Concurrency vs Route Ceiling"
            subtitle={jobRuntimeSamples.length > 0
              ? runtimeBucketMs > 1_000
                ? `Mean job-wide in-flight tasks per ${formatBucketDuration(runtimeBucketMs)} bucket against ${proxyCapacity.totalRoutes} configured routes`
                : `Job-wide Redis in-flight task samples against ${proxyCapacity.totalRoutes} configured routes`
              : `Observed running-task count against ${proxyCapacity.totalRoutes} configured routes`}
            unit=" tasks"
            timestamps={concurrencyChartTimestamps}
            maxLineGapMs={jobRuntimeSamples.length > 0 ? runtimeLineGapMs : MAX_CHART_LINE_GAP_MS}
            timeDomain={chartTimeDomain}
            timeMarkers={refillMarkers}
            timeScaleMode={isTerminal ? 'full' : 'live'}
            totalDurationFormatted={finalSummary.totalDurationFormatted}
            emptyMessage={isTerminal
              ? 'No stored job-wide timeline is available; browser observations appear only if details were open during the job.'
              : 'Waiting for a timestamped backend reading...'}
            referenceLine={{
              value: proxyCapacity.totalRoutes,
              label: `${proxyCapacity.totalRoutes} Route Ceiling`,
              color: 'var(--jdr-chart-capacity, #f85149)',
            }}
            series={[
              {
                name: 'Inflight Tasks',
                values: concurrencyChartValues,
                color: 'var(--jdr-chart-success, #3fb950)',
                strokeWidth: 2,
              },
            ]}
          />

          {/* Graph 3: Latency Percentiles Over Time */}
          <SvgLineChart
            chartId="latency"
            chartGroup="latency-errors"
            expandedChartId={expandedChart?.id ?? null}
            expandedChartGroup={expandedChart?.group ?? null}
            onToggleExpand={toggleExpandedChart}
            title="Latency Percentiles (Seconds)"
            subtitle="p50 and p95 from the task sample returned with each browser-captured reading"
            unit="s"
            timestamps={chartTimestamps}
            timeDomain={chartTimeDomain}
            timeScaleMode={isTerminal ? 'full' : 'live'}
            totalDurationFormatted={finalSummary.totalDurationFormatted}
            emptyMessage={isTerminal
              ? 'No browser-captured latency observations were retained; this chart records samples only while job details are open.'
              : 'Waiting for a timestamped backend reading...'}
            series={[
              {
                name: 'p50 Latency',
                values: latencyP50Series,
                color: 'var(--jdr-chart-latency, #58a6ff)',
                strokeWidth: 2,
              },
              {
                name: 'p95 Latency',
                values: latencyP95Series,
                color: 'var(--jdr-chart-tail, #bc8cff)',
                strokeWidth: 1.8,
              },
            ]}
          />

          {/* Graph 4: Cumulative Errors Over Time */}
          <SvgLineChart
            chartId="errors"
            chartGroup="latency-errors"
            expandedChartId={expandedChart?.id ?? null}
            expandedChartGroup={expandedChart?.group ?? null}
            onToggleExpand={toggleExpandedChart}
            title="Error Accumulation Stream"
            subtitle={
              isTerminal
                ? 'Error totals at captured observation times; blank spans are unobserved'
                : 'Error total reported by the backend at each timestamped reading'
            }
            unit=" errs"
            timestamps={chartTimestamps}
            timeDomain={chartTimeDomain}
            timeScaleMode={isTerminal ? 'full' : 'live'}
            totalDurationFormatted={finalSummary.totalDurationFormatted}
            emptyMessage={isTerminal
              ? 'No browser-captured error snapshots were retained; job-wide Redis history stores task counters, not error categories.'
              : 'Waiting for a timestamped backend reading...'}
            series={[
              {
                name: 'Errors',
                values: errorVelocitySeries,
                color: 'var(--jdr-chart-error, #f85149)',
                strokeWidth: 2,
              },
            ]}
          />
        </div>

      </div>

      {/* ── HTTP outcomes and proxy routes ── */}
      {activeView === 'telemetry' && (
      <div className="jdr-table-container jdr-network-section" data-testid="http-proxy-health">
        <div className="jdr-table-header-row">
          <div className="jdr-section-title" style={{ margin: 0 }}>
            <span>HTTP & Proxy Health</span>
            <span>
              {totalHttp.toLocaleString()} requests · {proxyAnomalies.filter((p) => p.status !== 'healthy').length} outliers
            </span>
          </div>
          {proxyAnomalies.some((p) => p.status !== 'healthy') && (
            <button
              type="button"
              className="jdr-copy-button"
              onClick={handleCopyBadProxies}
            >
              <DiagnosticGlyph name="network">{copiedBadProxies ? '✓' : '📋'}</DiagnosticGlyph>
              {copiedBadProxies ? ' Copied to Clipboard' : ' Copy Problematic Proxies'}
            </button>
          )}
        </div>

        <div className="jdr-http-summary" aria-label="HTTP response distribution">
          {/* Stacked Percentage Bar */}
          <div className="jdr-http-bar-wrapper">
            {httpDistribution.ok200 > 0 && (
              <div
                className="jdr-http-segment is-200"
                style={{ width: `${pct200}%` }}
                title={`200 OK: ${httpDistribution.ok200} (${pct200}%)`}
              />
            )}
            {httpDistribution.rateLimit429 > 0 && (
              <div
                className="jdr-http-segment is-429"
                style={{ width: `${pct429}%` }}
                title={`429 Rate Limit: ${httpDistribution.rateLimit429} (${pct429}%)`}
              />
            )}
            {httpDistribution.forbidden403 > 0 && (
              <div
                className="jdr-http-segment is-403"
                style={{ width: `${pct403}%` }}
                title={`403 Forbidden: ${httpDistribution.forbidden403} (${pct403}%)`}
              />
            )}
            {httpDistribution.notFound404 > 0 && (
              <div
                className="jdr-http-segment is-404"
                style={{ width: `${pct404}%` }}
                title={`404 Not Found: ${httpDistribution.notFound404} (${pct404}%)`}
              />
            )}
            {httpDistribution.serverError5xx > 0 && (
              <div
                className="jdr-http-segment is-5xx"
                style={{ width: `${pct5xx}%` }}
                title={`5xx Server Error: ${httpDistribution.serverError5xx} (${pct5xx}%)`}
              />
            )}
            {httpDistribution.timeoutErrors > 0 && (
              <div
                className="jdr-http-segment is-timeout"
                style={{ width: `${pctTimeout}%` }}
                title={`Timeouts: ${httpDistribution.timeoutErrors} (${pctTimeout}%)`}
              />
            )}
          </div>

          {/* Legend Cards */}
          <div className="jdr-http-summary-legend">
            <div className="jdr-http-summary-stat">
              <span className="jdr-http-code-label">
                <i className="jdr-legend-dot" style={{ backgroundColor: 'var(--jdr-chart-success, #2ea043)' }} />
                200 OK
              </span>
              <span className="jdr-http-code-count">
                {httpDistribution.ok200.toLocaleString()} ({pct200}%)
              </span>
            </div>

            <div className="jdr-http-summary-stat">
              <span className="jdr-http-code-label">
                <i className="jdr-legend-dot" style={{ backgroundColor: 'var(--jdr-chart-warning, #d29922)' }} />
                429 Limits
              </span>
              <span className="jdr-http-code-count">
                {httpDistribution.rateLimit429.toLocaleString()} ({pct429}%)
              </span>
            </div>

            <div className="jdr-http-summary-stat">
              <span className="jdr-http-code-label">
                <i className="jdr-legend-dot" style={{ backgroundColor: 'var(--jdr-chart-error, #f85149)' }} />
                403 Forbidden
              </span>
              <span className="jdr-http-code-count">
                {httpDistribution.forbidden403.toLocaleString()} ({pct403}%)
              </span>
            </div>

            <div className="jdr-http-summary-stat">
              <span className="jdr-http-code-label">
                <i className="jdr-legend-dot" style={{ backgroundColor: 'var(--jdr-chart-not-found, #a371f7)' }} />
                404 Not Found
              </span>
              <span className="jdr-http-code-count">
                {httpDistribution.notFound404.toLocaleString()} ({pct404}%)
              </span>
            </div>

            <div className="jdr-http-summary-stat">
              <span className="jdr-http-code-label">
                <i className="jdr-legend-dot" style={{ backgroundColor: 'var(--jdr-chart-error, #da3633)' }} />
                5xx Errors
              </span>
              <span className="jdr-http-code-count">
                {httpDistribution.serverError5xx.toLocaleString()} ({pct5xx}%)
              </span>
            </div>

            <div className="jdr-http-summary-stat">
              <span className="jdr-http-code-label">
                <i className="jdr-legend-dot" style={{ backgroundColor: 'var(--jdr-chart-timeout, #f0883e)' }} />
                Timeouts
              </span>
              <span className="jdr-http-code-count">
                {httpDistribution.timeoutErrors.toLocaleString()} ({pctTimeout}%)
              </span>
            </div>
          </div>
        </div>

        {/* ── Proxy Triage Toolbar ── */}
        <div className="jdr-proxy-toolbar">
          <div className="jdr-proxy-search-box">
            <input
              type="text"
              className="jdr-proxy-search-input"
              placeholder="Filter by route URL, group, country..."
              value={proxySearchTerm}
              onChange={(e) => setProxySearchTerm(e.target.value)}
              aria-label="Filter proxy anomalies"
            />
            {proxySearchTerm && (
              <button
                type="button"
                className="jdr-search-clear-btn"
                onClick={() => setProxySearchTerm('')}
                aria-label="Clear search"
              >
                ✕
              </button>
            )}
          </div>

          <div className="jdr-proxy-filter-pills">
            <button
              type="button"
              className={`jdr-filter-pill ${proxyStatusFilter === 'all' ? 'active' : ''}`}
              onClick={() => setProxyStatusFilter('all')}
            >
              All ({proxyAnomalies.length})
            </button>
            <button
              type="button"
              className={`jdr-filter-pill is-danger ${proxyStatusFilter === 'critical' ? 'active' : ''}`}
              onClick={() => setProxyStatusFilter('critical')}
            >
              Critical ({proxyAnomalies.filter((p) => p.status === 'critical').length})
            </button>
            <button
              type="button"
              className={`jdr-filter-pill is-warning ${proxyStatusFilter === 'degraded' ? 'active' : ''}`}
              onClick={() => setProxyStatusFilter('degraded')}
            >
              Degraded ({proxyAnomalies.filter((p) => p.status === 'degraded').length})
            </button>
            <button
              type="button"
              className={`jdr-filter-pill is-info ${proxyStatusFilter === '429' ? 'active' : ''}`}
              onClick={() => setProxyStatusFilter('429')}
            >
              429 Limits ({proxyAnomalies.filter((p) => p.rateLimits429 > 0).length})
            </button>
            <button
              type="button"
              className={`jdr-filter-pill is-warning ${proxyStatusFilter === 'timeouts' ? 'active' : ''}`}
              onClick={() => setProxyStatusFilter('timeouts')}
            >
              Timeouts ({proxyAnomalies.filter((p) => p.timeouts > 0).length})
            </button>
          </div>

          <div className="jdr-proxy-sort-select-wrapper">
            <label htmlFor="jdr-sort-select" className="jdr-sort-label">
              Sort:
            </label>
            <select
              id="jdr-sort-select"
              className="jdr-sort-select"
              value={proxySortKey}
              onChange={(e) => setProxySortKey(e.target.value as ProxySortKey)}
              aria-label="Sort proxy anomalies by"
            >
              <option value="anomalyScore">Anomaly Severity</option>
              <option value="failures">Failures</option>
              <option value="rateLimits429">429 Rate Limits</option>
              <option value="timeouts">Timeouts</option>
              <option value="avgLatencySec">Latency</option>
              <option value="totalAttempts">Total Requests</option>
            </select>
            <button
              type="button"
              className="jdr-sort-order-btn"
              onClick={() => setProxySortOrder((prev) => (prev === 'desc' ? 'asc' : 'desc'))}
              title={`Toggle sort order (current: ${proxySortOrder})`}
              aria-label="Toggle sort order"
            >
              {proxySortOrder === 'desc' ? '↓' : '↑'}
            </button>
          </div>
        </div>

        <div ref={proxyScrollRef} className="jdr-table-wrapper jdr-proxy-anomalies-scroll">
          {filteredAndSortedProxies.length === 0 ? (
            <p className="jdr-chart-empty">
              {proxyAnomalies.length === 0
                ? 'No proxy telemetry available yet.'
                : 'No proxy routes match your active filter/search criteria.'}
            </p>
          ) : (
            <table className="jdr-proxy-table">
              <thead>
                <tr>
                  <th>Proxy Route</th>
                  <th>Group / Location</th>
                  <th>Total Requests</th>
                  <th>Failures</th>
                  <th>429 Rate Limits</th>
                  <th>Timeouts</th>
                  <th>Avg Latency</th>
                  <th>Health Status / Primary Issue</th>
                </tr>
              </thead>
              <tbody>
                {filteredAndSortedProxies.map((anomaly) => (
                  <tr key={anomaly.proxyUrl}>
                    <td className="jdr-proxy-url">{anomaly.displayUrl}</td>
                    <td>
                      {anomaly.countryFlag && <span>{anomaly.countryFlag} </span>}
                      {anomaly.group || anomaly.country || (anomaly.proxyUrl === 'direct' ? 'Direct / Default' : 'Unassigned')}
                    </td>
                    <td>{anomaly.totalAttempts.toLocaleString()}</td>
                    <td>
                      <span
                        style={{
                          color: anomaly.failures > 0 ? 'var(--jdr-chart-error, #f85149)' : 'inherit',
                          fontWeight: anomaly.failures > 0 ? 600 : 'normal',
                        }}
                      >
                        {anomaly.failures}
                      </span>
                    </td>
                    <td>
                      <span
                        style={{
                          color: anomaly.rateLimits429 > 0 ? 'var(--jdr-chart-warning, #d29922)' : 'inherit',
                          fontWeight: anomaly.rateLimits429 > 0 ? 600 : 'normal',
                        }}
                      >
                        {anomaly.rateLimits429}
                      </span>
                    </td>
                    <td>
                      <span
                        style={{
                          color: anomaly.timeouts > 0 ? 'var(--jdr-chart-timeout, #f0883e)' : 'inherit',
                          fontWeight: anomaly.timeouts > 0 ? 600 : 'normal',
                        }}
                      >
                        {anomaly.timeouts}
                      </span>
                    </td>
                    <td>{anomaly.avgLatencySec}s</td>
                    <td>
                      <span
                        className={`jdr-issue-badge ${
                          anomaly.status === 'critical' ? 'is-critical' : ''
                        }`}
                      >
                        {anomaly.status === 'critical' && <span className="jdr-legacy-icon" aria-hidden="true">🚨 </span>}
                        {anomaly.status === 'degraded' && <span className="jdr-legacy-icon" aria-hidden="true">⚠️ </span>}
                        {anomaly.status === 'healthy' && '🟢 '}
                        {anomaly.primaryIssue}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

      </div>
      )}

      {activeView === 'telemetry' && (
      <div className="jdr-collapsible-stack" data-testid="telemetry-details-stack">
        {/* ── Telemetry & Secondary Details (Collapsible, only rendered when secondary telemetry exists) ── */}
        {hasSecondaryTelemetry && (
          <section className={`jdr-section jdr-collapsible-section ${!isTelemetryDetailsExpanded ? 'is-collapsed' : ''}`}>
            <button
              type="button"
              className="jdr-section-toggle"
              onClick={() => setIsTelemetryDetailsExpanded((prev) => !prev)}
              aria-expanded={isTelemetryDetailsExpanded}
            >
              <span className="jdr-accordion-chevron" aria-hidden="true">
                {isTelemetryDetailsExpanded ? '▼' : '▶'}
              </span>
              <h3>Telemetry & Sampling Details</h3>
            </button>
            <div hidden={!isTelemetryDetailsExpanded} className="jdr-collapsible-body">
              <div className="jdr-telemetry-details-grid">
                {finalSummary.steadyStateEfficiencyPercent != null && (
                  <div className="jdr-telemetry-detail-item">
                    <span className="jdr-detail-label">Steady-State Efficiency (10–90%)</span>
                    <span className="jdr-detail-val">{finalSummary.steadyStateEfficiencyPercent.toFixed(1)}%</span>
                    <span className="jdr-detail-desc">
                      {(finalSummary.occupancyGapClassification ?? 'nominal').replaceAll('_', ' ')}
                    </span>
                  </div>
                )}
                {finalSummary.workersSeen != null && finalSummary.expectedWorkers != null && (
                  <div className="jdr-telemetry-detail-item">
                    <span className="jdr-detail-label">Worker Participation</span>
                    <span className="jdr-detail-val">{finalSummary.workersSeen} / {finalSummary.expectedWorkers}</span>
                    <span className="jdr-detail-desc">Active workers participating in execution</span>
                  </div>
                )}
                {(finalSummary.readyTimelineNonemptyPercent != null || finalSummary.readyNonemptySamples != null) && (
                  <div className="jdr-telemetry-detail-item">
                    <span className="jdr-detail-label">Ready Queue Availability</span>
                    <span className="jdr-detail-val">
                      {finalSummary.readyTimelineNonemptyPercent != null
                        ? `${finalSummary.readyTimelineNonemptyPercent}% covered`
                        : 'Sampled'}
                    </span>
                    <span className="jdr-detail-desc">
                      {finalSummary.readyTimelineNonemptyPercent != null
                        ? `Ready tasks observed in ${finalSummary.readyTimelineNonemptyPercent}% of ${finalSummary.readyTimelineCoveredSeconds?.toFixed(1) ?? '0.0'}s time-sampled intervals`
                        : `Ready tasks observed in ${finalSummary.readyNonemptySamples?.toLocaleString()}/${finalSummary.readySampleCount?.toLocaleString()} completion checks`}
                    </span>
                  </div>
                )}
                {telemetry.quality && !telemetry.quality.isCompleteTaskSample && (
                  <div className="jdr-telemetry-detail-item">
                    <span className="jdr-detail-label">Task Sample Scope</span>
                    <span className="jdr-detail-val">
                      {telemetry.quality.loadedTaskCount?.toLocaleString() ?? '—'} / {telemetry.quality.totalTaskCount?.toLocaleString() ?? '—'}
                    </span>
                    <span className="jdr-detail-desc">Metrics scoped to loaded task sample</span>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}
        {Object.keys(telemetry.ledgerStats ?? {}).length > 0 && (
          <section className={`jdr-section jdr-collapsible-section ${!isLedgerTimingExpanded ? 'is-collapsed' : ''}`}>
            <button
              type="button"
              className="jdr-section-toggle"
              onClick={() => setIsLedgerTimingExpanded((prev) => !prev)}
              aria-expanded={isLedgerTimingExpanded}
            >
              <span className="jdr-accordion-chevron" aria-hidden="true">
                {isLedgerTimingExpanded ? '▼' : '▶'}
              </span>
              <h3>Ledger Checkpoint Timing</h3>
              <span className="jdr-toggle-count">
                ({Object.keys(telemetry.ledgerStats ?? {}).filter(([name]) => !name.endsWith('_execution') && !name.endsWith('_admission')).length} stages)
              </span>
            </button>
            <div hidden={!isLedgerTimingExpanded} className="jdr-collapsible-body">
              <table className="jdr-proxy-table"><thead><tr><th>Stage</th><th>Calls</th><th>Mean total wait</th><th>Mean SQL call</th><th>Mean admission and dispatch</th><th>Mean batch queue wait</th><th>Mean thread wait</th><th>Mean event-loop resume</th></tr></thead>
                <tbody>{Object.entries(telemetry.ledgerStats ?? {}).filter(([name]) => !name.endsWith('_execution') && !name.endsWith('_admission')).map(([name, stats]) => {
                  const count = Math.max(1, stats.count);
                  const threadWait = telemetry.ledgerStats?.[`${name}_thread_wait_admission`];
                  const batchWait = telemetry.ledgerStats?.[`${name}_batch_wait_admission`];
                  const resume = telemetry.ledgerStats?.[`${name}_resume_admission`];
                  return <tr key={name}><td>{name.replaceAll('_', ' ')}</td><td>{stats.count}</td><td>{(stats.ms / count).toFixed(2)}ms</td>
                    <td>{((telemetry.ledgerStats?.[`${name}_execution`]?.ms ?? 0) / count).toFixed(2)}ms</td>
                    <td>{((telemetry.ledgerStats?.[`${name}_admission`]?.ms ?? 0) / count).toFixed(2)}ms</td>
                    <td>{batchWait ? `${(batchWait.ms / count).toFixed(2)}ms` : 'Unavailable'}</td>
                    <td>{threadWait ? `${(threadWait.ms / count).toFixed(2)}ms` : 'Unavailable'}</td>
                    <td>{resume ? `${(resume.ms / count).toFixed(2)}ms` : 'Unavailable'}</td></tr>;
                })}</tbody></table>
              <p>Batch queue wait, thread wait and event-loop resume subdivide admission and dispatch. Progress is inside handler time; writer preparation is inside writer admission; finish is inside terminal time. SQL call time includes connection checkout and commit. These timings are nested.</p>
            </div>
          </section>
        )}
        {Object.keys(telemetry.terminalStats ?? {}).length > 0 && (
          <section className={`jdr-section jdr-collapsible-section ${!isTerminalTimingExpanded ? 'is-collapsed' : ''}`}>
            <button
              type="button"
              className="jdr-section-toggle"
              onClick={() => setIsTerminalTimingExpanded((prev) => !prev)}
              aria-expanded={isTerminalTimingExpanded}
            >
              <span className="jdr-accordion-chevron" aria-hidden="true">
                {isTerminalTimingExpanded ? '▼' : '▶'}
              </span>
              <h3>Terminal State Timing Detail</h3>
              <span className="jdr-toggle-count">
                ({Object.keys(telemetry.terminalStats ?? {}).length} stages)
              </span>
            </button>
            <div hidden={!isTerminalTimingExpanded} className="jdr-collapsible-body">
              <table className="jdr-proxy-table"><thead><tr><th>Stage</th><th>Count</th><th>Mean</th></tr></thead>
                <tbody>{Object.entries(telemetry.terminalStats ?? {}).map(([name, stats]) => (
                  <tr key={name}><td>{name}</td><td>{stats.count}</td><td>{(stats.ms / Math.max(1, stats.count)).toFixed(2)}ms</td></tr>
                ))}</tbody></table>
              <p>Finish-lock wait and output persistence are nested within before counter; do not add them to phase totals.</p>
            </div>
          </section>
        )}
        {Object.keys(telemetry.guestAuthStats ?? {}).length > 0 && (
          <div className={`jdr-refill-trace jdr-collapsible-section ${!isGuestAuthExpanded ? 'is-collapsed' : ''}`}>
            <button
              type="button"
              className="jdr-section-toggle"
              onClick={() => setIsGuestAuthExpanded((prev) => !prev)}
              aria-expanded={isGuestAuthExpanded}
            >
              <span className="jdr-accordion-chevron" aria-hidden="true">
                {isGuestAuthExpanded ? '▼' : '▶'}
              </span>
              <div className="jdr-section-title" style={{ margin: 0 }}>Guest auth initialization detail</div>
            </button>
            <div hidden={!isGuestAuthExpanded} className="jdr-collapsible-body">
              <table><thead><tr><th>Observation</th><th>Count</th><th>Mean per observation</th></tr></thead>
                <tbody>{Object.entries(telemetry.guestAuthStats ?? {}).map(([name, stats]) => (
                  <tr key={name}><td>{name.replaceAll('_', ' ')}</td><td>{stats.count}</td>
                    <td>{(stats.count > 0 ? stats.ms / stats.count : 0).toFixed(2)} ms</td></tr>
                ))}</tbody>
              </table>
              <p>These spans are inside guest initialization; counters and nested timings are not additive.</p>
            </div>
          </div>
        )}

        {mpsRefillTrace.length > 0 && (
          <div className={`jdr-refill-trace jdr-collapsible-section ${!isMpsRefillExpanded ? 'is-collapsed' : ''}`}>
            <button
              type="button"
              className="jdr-section-toggle"
              onClick={() => setIsMpsRefillExpanded((prev) => !prev)}
              aria-expanded={isMpsRefillExpanded}
            >
              <span className="jdr-accordion-chevron" aria-hidden="true">
                {isMpsRefillExpanded ? '▼' : '▶'}
              </span>
              <span className="jdr-refill-trace-title">MPS refill stages</span>
              <span className="jdr-toggle-count jdr-refill-trace-count">Latest {mpsRefillTrace.length} trace events loaded · newest 16 shown</span>
            </button>
            <div className="jdr-refill-trace-body" hidden={!isMpsRefillExpanded}>
              <div className="jdr-refill-trace-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Observed at</th>
                      <th>Cycle</th>
                      <th>Stage</th>
                      <th>Since prior stage in cycle</th>
                      <th>Batch</th>
                      <th>Ready / active</th>
                      <th>Controls / stop reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentRefillEvents.map(({ event, elapsedSincePreviousMs }, index) => (
                      <tr key={`${event.timestamp_ms}-${event.stage}-${index}`}>
                        <td>{formatChartClock(event.timestamp_ms)}</td>
                        <td>{event.cycle ?? '—'}</td>
                        <td>{refillStageLabel(event.stage)}</td>
                        <td>{elapsedSincePreviousMs === null
                          ? '—'
                          : formatElapsedMs(elapsedSincePreviousMs)}</td>
                        <td>{refillBatchLabel(event)}</td>
                        <td>{event.ready.toLocaleString()} / {event.inflight.toLocaleString()}</td>
                        <td>{event.reason ?? (event.controls
                          ? Object.entries(event.controls).map(([key, value]) => `${key}: ${value}`).join(' · ')
                          : '—')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
        {/* ── Per-route upstream lookup timings ── */}
        <div className={`jdr-table-container jdr-collapsible-section ${!isRouteLookupExpanded ? 'is-collapsed' : ''}`} data-testid="route-lookup-attribution">
          <div className="jdr-table-header-row">
            <button
              type="button"
              className="jdr-table-header-toggle"
              onClick={() => setIsRouteLookupExpanded((prev) => !prev)}
              aria-expanded={isRouteLookupExpanded}
            >
              <div className="jdr-section-title" style={{ margin: 0 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span className="jdr-accordion-chevron" aria-hidden="true">
                    {isRouteLookupExpanded ? '▼' : '▶'}
                  </span>
                  <span>Per-Route User Lookup Timing</span>
                  <InfoTooltip
                    ariaLabel="Route lookup timing explanation"
                    content={
                      <div>
                        <p style={{ margin: '0 0 0.45rem' }}>
                          Route IDs are opaque labels; proxy hosts and credentials are omitted. The outcome cell shows found/no match/lookup error/timeout/lookup canceled/guest-init failure/guest-init canceled counts, with recorded/attempt coverage. Showing up to the {ROUTE_LOOKUP_DISPLAY_LIMIT} slowest routes by mean initial user lookup time.
                        </p>
                        {finalSummary.routeLookupStats == null && (
                          <p style={{ margin: 0, color: 'var(--color-text-secondary, #8b949e)', fontStyle: 'italic' }}>
                            Per-route timings are unavailable for this run or backend version.
                          </p>
                        )}
                      </div>
                    }
                  />
                </span>
                <span>
                  {finalSummary.routeLookupStats == null
                    ? 'Unavailable'
                    : `${routeLookupRows.length.toLocaleString()} route(s)`}
                </span>
              </div>
            </button>
          </div>
          <div className="jdr-table-wrapper" hidden={!isRouteLookupExpanded}>
            {routeLookupRows.length === 0 ? (
              <p className="jdr-chart-empty" style={{ margin: '0.5rem 0' }}>
                {finalSummary.routeLookupStats == null
                  ? 'Unavailable'
                  : 'No route-level lookup observations were recorded.'}
              </p>
            ) : (
              <table className="jdr-proxy-table">
                <thead>
                  <tr>
                    <th>Route ID</th>
                    <th>Primary / hedge / fallback</th>
                    <th>Deferred / healthy / retry</th>
                    <th>Route Attempts</th>
                    <th>Lookups</th>
                    <th>Outcomes (n; found/no match/error/timeout/lookup canceled/init fail/init canceled)</th>
                    <th>Mean Guest Init</th>
                    <th>Mean User Lookup</th>
                    <th>Mean Route Active</th>
                  </tr>
                </thead>
                <tbody>
                  {routeLookupRows.slice(0, ROUTE_LOOKUP_DISPLAY_LIMIT).map(([routeId, route]) => (
                    <tr key={routeId}>
                      <td><code>{routeId}</code></td>
                      <td>{[route.primary_selected_count, route.hedge_selected_count, route.fallback_selected_count].map(value => value ?? "Unavailable").join(" / ")}</td>
                      <td>{[route.deferred_selected_count, route.healthy_selected_count, route.retry_selected_count].map(value => value ?? "Unavailable").join(" / ")}</td>
                      <td>{route.route_attempts.toLocaleString()}</td>
                      <td>{route.lookup_observations.toLocaleString()}</td>
                      <td>{formatRouteLookupOutcomes(route)}</td>
                      <td>{route.mean_guest_init_ms.toFixed(2)}ms</td>
                      <td>{route.mean_lookup_ms != null ? `${route.mean_lookup_ms.toFixed(2)}ms` : 'Unavailable'}</td>
                      <td>{route.mean_route_active_ms.toFixed(2)}ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
      )}
    </div>
  );
}
