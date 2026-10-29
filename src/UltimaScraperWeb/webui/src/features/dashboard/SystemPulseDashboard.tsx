import {
  memo,
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { connectionScopedKey, getWebSocketBaseUrl } from '../../api/http';
import { getActiveTasks, getHealth, getJobs, getQueueStats } from '../../api/jobs';
import { listProxies } from '../../api/network';
import { getBackendStatus } from '../../api/system';
import type { Job } from '../../api/types/jobs';
import type { NetworkProxy } from '../../api/types/network';
import type { WorkerInfo } from '../../api/types/system';
import { useWebSocket, type WebSocketEvent } from '../../hooks/useWebSocket';
import {
  buildActiveTaskState,
  buildJobCompletionSamples,
  formatBytesPerSecond,
  type ActiveTaskState,
  type JobCompletionSample,
} from './lib/dashboardUtils';
import { chartPath } from './lib/dashboardChartUtils';
import './SystemPulseDashboard.css';

const JobDetailsModal = lazy(() =>
  import('../jobs/components/JobDetailsModal').then((module) => ({
    default: module.JobDetailsModal,
  })),
);

type PulseRange = '15 min' | '1 hour' | '24 hours';
type PulseTone = 'accent' | 'info' | 'warning' | 'danger' | 'neutral';
type PulseSeverity = 'critical' | 'warning' | 'info' | 'success';

interface PulseSample {
  timestamp: number;
  activeJobs: number;
  queuedJobs: number;
  itemRate: number;
  successRate: number;
  workerLoad: number;
  writeRate: number;
}

interface PulseEvent {
  id: string;
  timestamp: number;
  severity: PulseSeverity;
  source: string;
  title: string;
  detail: string;
}

interface ProxyRegion {
  name: string;
  routes: number;
  assignments: number;
  capacity: number;
}

interface PulseMetric {
  label: string;
  value: string;
  detail: string;
  tone: PulseTone;
  samples: number[];
}

const RANGE_OPTIONS: PulseRange[] = ['15 min', '1 hour', '24 hours'];
const RANGE_DURATION: Record<PulseRange, number> = {
  '15 min': 15 * 60 * 1000,
  '1 hour': 60 * 60 * 1000,
  '24 hours': 24 * 60 * 60 * 1000,
};
const SAVED_RANGE_KEY = 'usr_system_pulse_range';
const HISTORY_RETENTION_MS = RANGE_DURATION['24 hours'];
const HISTORY_STORAGE_KEY = 'usr_system_pulse_samples';
const SAMPLE_BUCKET_MS = 15 * 1000;
const MAX_STORED_SAMPLES = Math.ceil(HISTORY_RETENTION_MS / SAMPLE_BUCKET_MS) + 1;
const MAX_RENDER_SAMPLES = 360;

function clamp(value: number, minimum = 0, maximum = 100): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function isPulseSample(value: unknown): value is PulseSample {
  if (!value || typeof value !== 'object') return false;
  const sample = value as Partial<PulseSample>;
  return (
    Number.isFinite(sample.timestamp) &&
    Number.isFinite(sample.activeJobs) &&
    Number.isFinite(sample.queuedJobs) &&
    Number.isFinite(sample.itemRate) &&
    Number.isFinite(sample.successRate) &&
    Number.isFinite(sample.workerLoad) &&
    Number.isFinite(sample.writeRate)
  );
}

function readStoredSamples(): PulseSample[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(connectionScopedKey(HISTORY_STORAGE_KEY));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const cutoff = Date.now() - HISTORY_RETENTION_MS;
    return parsed
      .filter(isPulseSample)
      .filter((sample) => sample.timestamp >= cutoff)
      .sort((left, right) => left.timestamp - right.timestamp)
      .slice(-MAX_STORED_SAMPLES);
  } catch {
    return [];
  }
}

function mergePulseSample(previous: PulseSample[], sample: PulseSample): PulseSample[] {
  const cutoff = sample.timestamp - HISTORY_RETENTION_MS;
  const retained = previous.filter((candidate) => candidate.timestamp >= cutoff);
  const bucketTimestamp = Math.floor(sample.timestamp / SAMPLE_BUCKET_MS) * SAMPLE_BUCKET_MS;
  const existingIndex = retained.findIndex(
    (candidate) => candidate.timestamp === bucketTimestamp,
  );

  if (existingIndex >= 0) {
    const existing = retained[existingIndex];
    retained[existingIndex] = {
      ...sample,
      timestamp: bucketTimestamp,
      // Preserve short-lived bursts between dashboard polls.
      itemRate: Math.max(existing.itemRate, sample.itemRate),
      writeRate: Math.max(existing.writeRate, sample.writeRate),
    };
  } else {
    retained.push({ ...sample, timestamp: bucketTimestamp });
  }

  return retained
    .sort((left, right) => left.timestamp - right.timestamp)
    .slice(-MAX_STORED_SAMPLES);
}

function downsamplePulseSamples(
  source: PulseSample[],
  maximum = MAX_RENDER_SAMPLES,
): PulseSample[] {
  if (source.length <= maximum) return source;

  return Array.from({ length: maximum }, (_, index) => {
    const start = Math.floor((index * source.length) / maximum);
    const end = Math.max(start + 1, Math.floor(((index + 1) * source.length) / maximum));
    const bucket = source.slice(start, end);
    const latest = bucket.at(-1) ?? source[start];
    return {
      ...latest,
      // Preserve short-lived rate/error peaks when reducing a long history.
      itemRate: Math.max(...bucket.map((sample) => sample.itemRate)),
      successRate: Math.min(...bucket.map((sample) => sample.successRate)),
      writeRate: Math.max(...bucket.map((sample) => sample.writeRate)),
    };
  });
}

function throughputAxisBounds(values: number[]): { minimum: number; maximum: number } {
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (finiteValues.length === 0) return { minimum: 0, maximum: 1 };

  const dataMinimum = Math.min(...finiteValues);
  const dataMaximum = Math.max(...finiteValues);
  const spread = Math.max(dataMaximum - dataMinimum, 1);
  const includesIdlePeriod = dataMinimum <= 0 || dataMinimum <= dataMaximum * 0.2;
  const minimum = includesIdlePeriod
    ? 0
    : Math.max(0, dataMinimum - spread * 0.1);
  const maximum = Math.max(minimum + 1, dataMaximum + spread * 0.1);
  return { minimum, maximum };
}

function readSavedRange(): PulseRange {
  if (typeof window === 'undefined') return '1 hour';
  try {
    const value = window.localStorage.getItem(SAVED_RANGE_KEY);
    return RANGE_OPTIONS.includes(value as PulseRange) ? (value as PulseRange) : '1 hour';
  } catch {
    return '1 hour';
  }
}

function jobProgress(job: Job): number {
  if (job.task_count <= 0) return job.status === 'completed' ? 100 : 0;
  return clamp(((job.completed_tasks + job.failed_tasks) / job.task_count) * 100);
}

function labelJobStatus(status: Job['status']): string {
  return status === 'pending' ? 'queued' : status;
}

function formatCompactRate(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0';
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k`;
  if (value >= 100) return value.toFixed(0);
  if (value >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return '—';
  if (value >= 99.95) return '100%';
  return `${value.toFixed(value >= 10 ? 1 : 2)}%`;
}

function formatClock(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return '—';
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp);
}

function miniTrendPoints(values: number[]): string {
  const series = values.length > 1 ? values : [values[0] ?? 0, values[0] ?? 0];
  const minimum = Math.min(...series);
  const maximum = Math.max(...series);
  const span = maximum - minimum;
  return series
    .map((value, index) => {
      const x = (index / Math.max(series.length - 1, 1)) * 120;
      const normalized = span > 0 ? (value - minimum) / span : 0.5;
      const y = 28 - normalized * 22;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

function humanizeEventName(value: string): string {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function eventString(event: WebSocketEvent, key: string): string | null {
  const value = event[key];
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return null;
}

function eventSeverity(eventName: string, level: string | null): PulseSeverity {
  const normalized = `${eventName} ${level ?? ''}`.toLowerCase();
  if (/critical|fatal|error|failed|failure|cancelled/.test(normalized)) return 'critical';
  if (/warn|degraded|retry|timeout|transition/.test(normalized)) return 'warning';
  if (/complete|completed|success|ready|connected/.test(normalized)) return 'success';
  return 'info';
}

function mapWebSocketEvent(event: WebSocketEvent): PulseEvent | null {
  const eventName = eventString(event, 'event') ?? eventString(event, 'type');
  if (!eventName || eventName === 'pong' || eventName === 'ack') return null;

  const timestampText = eventString(event, 'timestamp');
  const parsedTimestamp = timestampText ? Date.parse(timestampText) : Number.NaN;
  const timestamp = Number.isFinite(parsedTimestamp) ? parsedTimestamp : Date.now();
  const level = eventString(event, 'level');
  const source =
    eventString(event, 'source') ??
    eventString(event, 'worker_id') ??
    eventString(event, 'job_id') ??
    eventString(event, 'category') ??
    'system';

  if (eventName === 'log') {
    const message = eventString(event, 'message');
    if (!message) return null;
    const category = eventString(event, 'category') ?? 'system';
    const origin = eventString(event, 'function') ?? eventString(event, 'module');
    return {
      id: `${timestamp}:${source}:${message}`,
      timestamp,
      severity: eventSeverity(eventName, level),
      source,
      title: message,
      detail: origin ? `${category} · ${origin}` : category,
    };
  }

  const message = eventString(event, 'message');
  const taskType = eventString(event, 'task_type');
  const username = eventString(event, 'username');
  const detail = [message, taskType && humanizeEventName(taskType), username && `@${username}`]
    .filter(Boolean)
    .join(' · ');
  return {
    id: `${timestamp}:${source}:${eventName}:${detail}`,
    timestamp,
    severity: eventSeverity(eventName, level),
    source,
    title: humanizeEventName(eventName),
    detail: detail || 'Live backend event',
  };
}

function proxyRegionName(proxy: NetworkProxy): string {
  const location = proxy.geolocation;
  if (location?.country && location.region) return `${location.country} · ${location.region}`;
  return location?.country ?? location?.continent ?? 'Unresolved region';
}

function groupProxyRegions(proxies: NetworkProxy[]): ProxyRegion[] {
  const regions = new Map<string, ProxyRegion>();
  for (const proxy of proxies) {
    const name = proxyRegionName(proxy);
    const region = regions.get(name) ?? {
      name,
      routes: 0,
      assignments: 0,
      capacity: 0,
    };
    region.routes += 1;
    region.assignments += proxy.assigned_auths.length;
    region.capacity += Math.max(0, proxy.max_connections);
    regions.set(name, region);
  }
  return [...regions.values()].sort(
    (left, right) => right.capacity - left.capacity || right.routes - left.routes,
  );
}

function SectionHeading({
  eyebrow,
  title,
  aside,
}: {
  eyebrow: string;
  title: string;
  aside?: ReactNode;
}) {
  return (
    <header className="system-pulse__section-heading">
      <div>
        <span>{eyebrow}</span>
        <h2>{title}</h2>
      </div>
      {aside}
    </header>
  );
}

const MiniTrend = memo(function MiniTrend({
  values,
  tone,
}: {
  values: number[];
  tone: PulseTone;
}) {
  const points = miniTrendPoints(values);
  return (
    <svg
      className={`system-pulse__mini-trend is-${tone}`}
      viewBox="0 0 120 32"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={`system-pulse-trend-${tone}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="currentColor" stopOpacity=".24" />
          <stop offset="1" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon
        points={`0,32 ${points} 120,32`}
        fill={`url(#system-pulse-trend-${tone})`}
      />
      <polyline points={points} fill="none" vectorEffect="non-scaling-stroke" />
    </svg>
  );
});

function StatusPill({ tone, children, title }: { tone: PulseTone; children: ReactNode; title?: string }) {
  return <span className={`system-pulse__status is-${tone}`} title={title}>{children}</span>;
}

function EmptyState({ children }: { children: ReactNode }) {
  return <p className="system-pulse__empty">{children}</p>;
}

function WorkerRow({ worker }: { worker: WorkerInfo }) {
  const statusValue = worker.status === 'busy' ? 100 : 0;
  return (
    <Link to="/system" className="system-pulse__worker-row">
      <span>
        <b>{worker.worker_id}</b>
        <small>{worker.current_job ?? 'No active job'}</small>
      </span>
      <div>
        <i aria-hidden="true">
          <em
            className={`is-${worker.status}`}
            style={{ width: `${statusValue}%` } as CSSProperties}
          />
        </i>
        <small>{worker.status}</small>
      </div>
      <strong>
        {worker.jobs_completed.toLocaleString()}
        <small>done</small>
      </strong>
    </Link>
  );
}

export interface DashboardPipelineProps {
  backendId?: string;
  workers?: number;
  activeWorkers?: number;
  routes?: number;
  distributed?: boolean;
  redisConnected?: boolean;
}

/** Theme-supplied parts that switch the dashboard to its Atlas presentation. */
export interface AtlasDashboardParts {
  Overview: ComponentType;
  Pipeline: ComponentType<DashboardPipelineProps>;
  WorkerArray: ComponentType<{ workers: WorkerInfo[] }>;
}

export function SystemPulseDashboard({ atlasParts }: { atlasParts?: AtlasDashboardParts }) {
  const atlas = atlasParts !== undefined;
  const queryClient = useQueryClient();
  const [range, setRange] = useState<PulseRange>(readSavedRange);
  const [saved, setSaved] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [eventsPaused, setEventsPaused] = useState(false);
  const [events, setEvents] = useState<PulseEvent[]>([]);
  const [samples, setSamples] = useState<PulseSample[]>(readStoredSamples);
  const [mpsCompletionSamples, setMpsCompletionSamples] = useState<
    Record<string, JobCompletionSample>
  >({});
  const [activeTaskState, setActiveTaskState] = useState<ActiveTaskState>({
    activeTasks: [],
    stageSpeedSamples: {},
  });
  const eventsPausedRef = useRef(false);
  const refreshTimerRef = useRef<number | null>(null);
  const pendingRefreshesRef = useRef<Set<string>>(new Set());
  const persistedHistorySignatureRef = useRef<string | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedJob) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault();
        setSelectedJob(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedJob]);

  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) window.clearTimeout(refreshTimerRef.current);
    };
  }, []);

  const scheduleRefresh = useCallback(
    (...keys: string[]) => {
      for (const key of keys) pendingRefreshesRef.current.add(key);
      if (refreshTimerRef.current) return;
      refreshTimerRef.current = window.setTimeout(() => {
        refreshTimerRef.current = null;
        const pendingKeys = [...pendingRefreshesRef.current];
        pendingRefreshesRef.current.clear();
        for (const key of pendingKeys) {
          void queryClient.invalidateQueries({ queryKey: [key] });
        }
      }, 500);
    },
    [queryClient],
  );

  const handleWebSocketMessage = useCallback(
    (event: WebSocketEvent) => {
      const eventName = eventString(event, 'event') ?? eventString(event, 'type') ?? '';
      if (/progress/.test(eventName)) {
        scheduleRefresh('pulse-active-tasks');
      } else if (/job|task|worker|queue|settings/.test(eventName)) {
        scheduleRefresh(
          'pulse-active-tasks',
          'pulse-jobs',
          'pulse-queue-stats',
          'pulse-backend-status',
        );
      }

      if (eventsPausedRef.current) return;
      const mapped = mapWebSocketEvent(event);
      if (!mapped) return;
      setEvents((previous) => {
        if (previous.some((candidate) => candidate.id === mapped.id)) return previous;
        return [mapped, ...previous].slice(0, 40);
      });
    },
    [scheduleRefresh],
  );

  const { isConnected: wsConnected } = useWebSocket({
    url: `${getWebSocketBaseUrl()}/ws/events`,
    topics: ['jobs', 'system'],
    onMessage: handleWebSocketMessage,
  });

  const queueQuery = useQuery({
    queryKey: ['pulse-queue-stats'],
    queryFn: getQueueStats,
    refetchInterval: 10000,
    retry: 0,
  });
  const healthQuery = useQuery({
    queryKey: ['pulse-health'],
    queryFn: getHealth,
    refetchInterval: 15000,
    retry: 0,
  });
  const backendQuery = useQuery({
    queryKey: ['pulse-backend-status'],
    queryFn: getBackendStatus,
    refetchInterval: 5000,
    retry: 0,
  });
  const jobsQuery = useQuery({
    queryKey: ['pulse-jobs'],
    queryFn: () => getJobs(undefined, 1, 200, undefined, false),
    refetchInterval: wsConnected ? 6000 : 4000,
    refetchIntervalInBackground: true,
    retry: 0,
  });

  const allJobs = useMemo(() => jobsQuery.data?.jobs ?? [], [jobsQuery.data?.jobs]);
  const mpsJobs = useMemo(
    () => allJobs.filter((job) => job.created_by === 'webui_mps'),
    [allJobs],
  );
  const mpsJobIds = useMemo(() => new Set(mpsJobs.map((job) => job.job_id)), [mpsJobs]);

  useEffect(() => {
    if (jobsQuery.dataUpdatedAt <= 0) return;
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setMpsCompletionSamples((previous) =>
        buildJobCompletionSamples(mpsJobs, jobsQuery.dataUpdatedAt, previous),
      );
    });
    return () => {
      active = false;
    };
  }, [mpsJobs, jobsQuery.dataUpdatedAt]);

  const persistedActiveJobs = useMemo(
    () =>
      allJobs
        .filter((job) => job.status === 'running' || job.status === 'pending')
        .filter((job) => {
          const id = job.job_id.toLowerCase();
          return id !== 'api' && !id.startsWith('api-') && !id.startsWith('test-');
        })
        .sort((left, right) => {
          if (left.status === 'running' && right.status !== 'running') return -1;
          if (right.status === 'running' && left.status !== 'running') return 1;
          return Date.parse(right.created_at) - Date.parse(left.created_at);
        }),
    [allJobs],
  );
  const heavyQueue = (queueQuery.data?.redis_queue_size ?? 0) >= 50000;
  const activeTasksQuery = useQuery({
    queryKey: ['pulse-active-tasks', heavyQueue],
    queryFn: () => getActiveTasks(heavyQueue ? 60 : 120, heavyQueue ? 120 : 250),
    refetchInterval: persistedActiveJobs.length > 0 ? (wsConnected ? 4000 : 2500) : 10000,
    refetchIntervalInBackground: true,
    retry: 0,
  });
  const proxiesQuery = useQuery({
    queryKey: ['pulse-proxies'],
    queryFn: listProxies,
    refetchInterval: 60000,
    retry: 0,
  });

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setActiveTaskState((previous) =>
        buildActiveTaskState(
          activeTasksQuery.data?.tasks ?? [],
          activeTasksQuery.dataUpdatedAt,
          previous.stageSpeedSamples,
        ),
      );
    });
    return () => {
      active = false;
    };
  }, [activeTasksQuery.data?.tasks, activeTasksQuery.dataUpdatedAt]);

  const activeTasks = activeTaskState.activeTasks;
  const activeTaskSnapshotTimestamp = activeTasksQuery.dataUpdatedAt || now;
  const activeJobs = useMemo(() => {
    const knownJobIds = new Set(allJobs.map((job) => job.job_id));
    const virtualJobs = new Map<string, Job>();

    for (const task of activeTasks) {
      if (knownJobIds.has(task.job_id)) continue;
      const jobId = task.job_id.toLowerCase();
      if (jobId === 'api' || jobId.startsWith('api-') || jobId.startsWith('test-')) {
        continue;
      }

      const status = (task.job_status ?? task.status).toLowerCase();
      if (status !== 'running' && status !== 'pending') continue;
      const hintedTaskCount =
        typeof task.job_total_tasks === 'number' && task.job_total_tasks > 0
          ? task.job_total_tasks
          : null;
      const existing = virtualJobs.get(task.job_id);
      if (existing) {
        existing.status =
          existing.status === 'running' || status === 'running' ? 'running' : 'pending';
        existing.task_count = hintedTaskCount
          ? Math.max(existing.task_count, hintedTaskCount)
          : existing.task_count + 1;
        if (task.status.toLowerCase() === 'completed') existing.completed_tasks += 1;
        if (task.status.toLowerCase() === 'failed') existing.failed_tasks += 1;
        continue;
      }

      virtualJobs.set(task.job_id, {
        job_id: task.job_id,
        job_name: task.job_name || task.job_id,
        status: status === 'running' ? 'running' : 'pending',
        created_at:
          task.started_at ??
          new Date(activeTaskSnapshotTimestamp).toISOString(),
        updated_at: null,
        task_count: hintedTaskCount ?? 1,
        completed_tasks: task.status.toLowerCase() === 'completed' ? 1 : 0,
        failed_tasks: task.status.toLowerCase() === 'failed' ? 1 : 0,
        tasks: [],
      });
    }

    return [...persistedActiveJobs, ...virtualJobs.values()].sort((left, right) => {
      if (left.status === 'running' && right.status !== 'running') return -1;
      if (right.status === 'running' && left.status !== 'running') return 1;
      return Date.parse(right.created_at) - Date.parse(left.created_at);
    });
  }, [activeTaskSnapshotTimestamp, activeTasks, allJobs, persistedActiveJobs]);
  const runningJobCount = activeJobs.filter((job) => job.status === 'running').length;
  const runningTasks = activeTasks.filter((task) => task.status === 'running').length;
  // Each MPS completion represents one profile check, including not-found
  // profiles. Active-task polling can miss the entire lifetime of that check.
  const itemRate = mpsJobs.reduce(
    (total, job) => total + (mpsCompletionSamples[job.job_id]?.rate ?? 0),
    0,
  ) + activeTasks.reduce(
    (total, task) => total + (mpsJobIds.has(task.job_id) ? 0 : finiteNumber(task.speed)),
    0,
  );
  const completedTasks = allJobs.reduce(
    (total, job) => total + Math.max(0, finiteNumber(job.completed_tasks)),
    0,
  );
  const failedTasks = allJobs.reduce(
    (total, job) => total + Math.max(0, finiteNumber(job.failed_tasks)),
    0,
  );
  const terminalTasks = completedTasks + failedTasks;
  const successRate = terminalTasks > 0 ? (completedTasks / terminalTasks) * 100 : 100;
  const workerCount = backendQuery.data?.worker_count ?? 0;
  const activeWorkers = backendQuery.data?.active_workers ?? 0;
  const workerLoad = workerCount > 0 ? clamp((activeWorkers / workerCount) * 100) : 0;
  const writeRate = (() => {
    const disks = backendQuery.data?.system_stats?.disks ?? [];
    const seenDevices = new Set<string>();
    return disks.reduce((total, disk) => {
      if (seenDevices.has(disk.device)) return total;
      seenDevices.add(disk.device);
      return total + Math.max(0, finiteNumber(disk.write_bytes_per_sec));
    }, 0);
  })();
  const queuedJobs =
    backendQuery.data?.pending_jobs ?? allJobs.filter((job) => job.status === 'pending').length;
  const sampleTimestamp = Math.max(
    queueQuery.dataUpdatedAt,
    backendQuery.dataUpdatedAt,
    jobsQuery.dataUpdatedAt,
    activeTasksQuery.dataUpdatedAt,
  );

  useEffect(() => {
    if (sampleTimestamp <= 0) return;
    const sample: PulseSample = {
      timestamp: sampleTimestamp,
      activeJobs: runningJobCount,
      queuedJobs,
      itemRate,
      successRate,
      workerLoad,
      writeRate,
    };
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      setSamples((previous) => {
        return mergePulseSample(previous, sample);
      });
    });
    return () => {
      active = false;
    };
  }, [
    runningJobCount,
    itemRate,
    queuedJobs,
    sampleTimestamp,
    successRate,
    workerLoad,
    writeRate,
  ]);

  useEffect(() => {
    const newestTimestamp = samples.at(-1)?.timestamp ?? 0;
    const signature = `${samples.length}:${newestTimestamp}`;
    if (persistedHistorySignatureRef.current === signature) return;
    persistedHistorySignatureRef.current = signature;
    try {
      window.localStorage.setItem(connectionScopedKey(HISTORY_STORAGE_KEY), JSON.stringify(samples));
    } catch {
      // Historical telemetry is best-effort and must not affect the dashboard.
    }
  }, [samples]);

  const effectiveSelectedJobId =
    selectedJob && activeJobs.some((job) => job.job_id === selectedJob.job_id)
      ? selectedJob.job_id
      : activeJobs[0]?.job_id ?? null;
  const selectedJobDetails = selectedJob
    ? allJobs.find((job) => job.job_id === selectedJob.job_id)
      ?? activeJobs.find((job) => job.job_id === selectedJob.job_id)
      ?? selectedJob
    : null;

  const historyNow = Math.floor(now / SAMPLE_BUCKET_MS) * SAMPLE_BUCKET_MS;
  const rangeSamples = useMemo(() => {
    const cutoff = historyNow - RANGE_DURATION[range];
    return samples.filter((sample) => sample.timestamp >= cutoff);
  }, [historyNow, range, samples]);
  const visibleRangeSamples = useMemo(
    () => downsamplePulseSamples(rangeSamples),
    [rangeSamples],
  );
  const activeQueueType = queueQuery.data?.active_queue_type;
  const hasSystemStats = Boolean(backendQuery.data?.system_stats);
  const hasJobs = Boolean(jobsQuery.data || activeTasksQuery.data);
  const hasRateSources = Boolean(jobsQuery.data && activeTasksQuery.data);

  const metrics = useMemo<PulseMetric[]>(() => [
    {
      label: 'Active jobs',
      value: atlas && !hasJobs ? '--' : `${runningJobCount}`,
      detail: `${runningTasks} ${runningTasks === 1 ? 'task' : 'tasks'}`,
      tone: runningJobCount > 0 ? 'info' : 'neutral',
      samples: visibleRangeSamples.map((sample) => sample.activeJobs),
    },
    {
      label: 'Queued jobs',
      value: atlas && !backendQuery.data && !jobsQuery.data ? '--' : `${queuedJobs}`,
      detail: activeQueueType || 'pending',
      tone: queuedJobs > 0 ? 'warning' : 'accent',
      samples: visibleRangeSamples.map((sample) => sample.queuedJobs),
    },
    {
      label: 'Items / sec',
      value: atlas && !hasRateSources ? '--' : formatCompactRate(itemRate),
      detail: 'aggregate',
      tone: 'accent',
      samples: visibleRangeSamples.map((sample) => sample.itemRate),
    },
    {
      label: 'Success rate',
      value: atlas && !jobsQuery.data ? '--' : formatPercent(successRate),
      detail: `${failedTasks.toLocaleString()} failed`,
      tone: successRate < 95 ? 'danger' : successRate < 99 ? 'warning' : 'accent',
      samples: visibleRangeSamples.map((sample) => sample.successRate),
    },
    {
      label: 'Worker load',
      value: workerCount > 0 ? formatPercent(workerLoad) : '—',
      detail: `${activeWorkers}/${workerCount} busy`,
      tone: workerCount === 0 ? 'warning' : workerLoad >= 90 ? 'warning' : 'info',
      samples: visibleRangeSamples.map((sample) => sample.workerLoad),
    },
    {
      label: 'Write throughput',
      value: hasSystemStats ? formatBytesPerSecond(writeRate) : '—',
      detail: hasSystemStats ? 'disk I/O' : 'pending',
      tone: hasSystemStats ? 'accent' : 'neutral',
      samples: visibleRangeSamples.map((sample) => sample.writeRate),
    },
  ], [
    atlas,
    hasJobs,
    hasRateSources,
    backendQuery.data,
    jobsQuery.data,
    activeQueueType,
    activeWorkers,
    failedTasks,
    hasSystemStats,
    itemRate,
    queuedJobs,
    runningJobCount,
    runningTasks,
    successRate,
    visibleRangeSamples,
    workerCount,
    workerLoad,
    writeRate,
  ]);

  const proxyRegions = useMemo(
    () => groupProxyRegions(proxiesQuery.data ?? []),
    [proxiesQuery.data],
  );
  const totalProxyCapacity = proxyRegions.reduce((total, region) => total + region.capacity, 0);
  const totalProxyAssignments = proxyRegions.reduce(
    (total, region) => total + region.assignments,
    0,
  );

  const derivedJobEvents = useMemo<PulseEvent[]>(
    () =>
      [...allJobs]
        .sort((left, right) => {
          const leftTime = Date.parse(left.updated_at ?? left.created_at);
          const rightTime = Date.parse(right.updated_at ?? right.created_at);
          return rightTime - leftTime;
        })
        .slice(0, 8)
        .map((job) => {
          const timestamp = Date.parse(job.updated_at ?? job.created_at);
          const severity: PulseSeverity =
            job.status === 'failed' || job.status === 'cancelled'
              ? 'critical'
              : job.status === 'completed'
                ? 'success'
                : job.status === 'pending'
                  ? 'warning'
                  : 'info';
          return {
            id: `job:${job.job_id}:${job.status}:${timestamp}`,
            timestamp: Number.isFinite(timestamp) ? timestamp : 0,
            severity,
            source: job.job_id,
            title: `${job.job_name || job.job_id} ${labelJobStatus(job.status)}`,
            detail: `${job.completed_tasks.toLocaleString()} completed · ${job.failed_tasks.toLocaleString()} failed · ${job.task_count.toLocaleString()} total`,
          };
        }),
    [allJobs],
  );
  const visibleEvents = useMemo(
    () => [...events, ...derivedJobEvents].sort((a, b) => b.timestamp - a.timestamp).slice(0, 4),
    [derivedJobEvents, events],
  );

  const attentionSignals = useMemo(() => {
    const signals: string[] = [];
    if (queueQuery.data?.transitioning) signals.push('Queue transition');
    if (
      backendQuery.data?.distributed_mode &&
      backendQuery.data.redis_connected === false
    ) {
      signals.push('Redis disconnected');
    }
    if (runningJobCount > 0 && backendQuery.data && workerCount === 0) {
      signals.push('No workers online');
    }
    if (healthQuery.data && !['healthy', 'ok'].includes(healthQuery.data.status.toLowerCase())) {
      signals.push(`Backend ${healthQuery.data.status}`);
    }
    const failedJobs = allJobs.filter((job) => job.status === 'failed').length;
    if (failedJobs > 0) {
      signals.push(`${failedJobs} failed ${failedJobs === 1 ? 'job' : 'jobs'}`);
    }
    if (queueQuery.isError || backendQuery.isError || jobsQuery.isError) {
      signals.push('Dashboard source unavailable');
    }
    if (atlas && (healthQuery.isError || activeTasksQuery.isError || proxiesQuery.isError)) {
      signals.push('Telemetry source unavailable');
    }
    return signals;
  }, [
    atlas,
    healthQuery.isError,
    activeTasksQuery.isError,
    proxiesQuery.isError,
    runningJobCount,
    allJobs,
    backendQuery.data,
    backendQuery.isError,
    healthQuery.data,
    jobsQuery.isError,
    queueQuery.data?.transitioning,
    queueQuery.isError,
    workerCount,
  ]);

  const latestUpdate = Math.max(
    queueQuery.dataUpdatedAt,
    healthQuery.dataUpdatedAt,
    backendQuery.dataUpdatedAt,
    jobsQuery.dataUpdatedAt,
    activeTasksQuery.dataUpdatedAt,
    proxiesQuery.dataUpdatedAt,
  );
  const updateAgeSeconds = latestUpdate > 0 ? Math.max(0, Math.floor((now - latestUpdate) / 1000)) : null;
  const chartNow = historyNow;
  const throughputValues = rangeSamples.map((sample) => sample.itemRate);
  const throughputAxis = throughputAxisBounds(throughputValues);
  const chartStart = chartNow - RANGE_DURATION[range];
  const throughputLine = chartPath(
    visibleRangeSamples.map((sample) => ({ timestamp: sample.timestamp, value: sample.itemRate })),
    640,
    180,
    throughputAxis.maximum,
    chartStart,
    chartNow,
    throughputAxis.minimum,
  );
  const errorLine = chartPath(
    visibleRangeSamples.map((sample) => ({
      timestamp: sample.timestamp,
      value: Math.max(0, 100 - sample.successRate),
    })),
    640,
    180,
    100,
    chartStart,
    chartNow,
  );
  const chartLabels = Array.from({ length: 5 }, (_, index) => {
    const timestamp = now - RANGE_DURATION[range] + (RANGE_DURATION[range] * index) / 4;
    return new Intl.DateTimeFormat(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    }).format(timestamp);
  });
  const systemCpu = backendQuery.data?.system_stats?.cpu_percent;
  const systemMemory = backendQuery.data?.system_stats?.memory_percent;

  const saveView = () => {
    try {
      window.localStorage.setItem(SAVED_RANGE_KEY, range);
      setSaved(true);
    } catch {
      setSaved(false);
    }
  };

  const toggleEvents = () => {
    setEventsPaused((previous) => {
      const next = !previous;
      eventsPausedRef.current = next;
      return next;
    });
  };

  return (
    <section
      className={`system-pulse${atlas ? ' atlas-dashboard' : ''}`}
      data-pulse-range={range}
      aria-labelledby="system-pulse-title"
    >
      {atlasParts && <atlasParts.Overview />}
      <header className="system-pulse__topbar">
        <div className="system-pulse__title">
          <span>{atlas ? '02 // SYSTEM STATUS' : 'Live system overview'}</span>
          {atlas ? <h2 id="system-pulse-title">System telemetry</h2> : <h1 id="system-pulse-title">System pulse</h1>}
          <small>
            {wsConnected ? 'Live event stream' : 'Polling fallback'} ·{' '}
            {updateAgeSeconds == null ? 'waiting for data' : `updated ${updateAgeSeconds}s ago`}
          </small>
        </div>
        <div className="system-pulse__ranges" role="group" aria-label="Dashboard time range">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              className={range === option ? 'is-active' : ''}
              aria-pressed={range === option}
              onClick={() => {
                setRange(option);
                setSaved(false);
              }}
            >
              {option}
            </button>
          ))}
        </div>
        <div className="system-pulse__topbar-actions">
          {atlas && <time className="atlas-live-clock" dateTime={new Date(now).toISOString()}>{new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(now)}</time>}
          <StatusPill
            tone={attentionSignals.length > 0 ? 'warning' : atlas && !healthQuery.data ? 'neutral' : 'accent'}
            title={attentionSignals.join(' / ') || undefined}
          >
            {attentionSignals.length > 0
              ? `${attentionSignals.length} active ${attentionSignals.length === 1 ? 'alert' : 'alerts'}`
              : atlas && !healthQuery.data ? 'Awaiting health data' : 'Systems nominal'}
          </StatusPill>
          <button type="button" className="system-pulse__save" onClick={saveView}>
            {saved ? 'View saved' : 'Save view'}
          </button>
          <span className="system-pulse__save-feedback" role="status" aria-live="polite">
            {saved ? `${range} is now the default range` : ''}
          </span>
        </div>
      </header>

      {atlas && attentionSignals.length > 0 && <aside className="atlas-incidents" aria-label="System attention signals">
        <strong>ATTENTION</strong><span>{attentionSignals.join(' / ')}</span><Link to="/logs">System record →</Link>
      </aside>}

      <section className="system-pulse__kpis" aria-label="Live operational metrics">
        {metrics.map((metric) => (
          <article key={metric.label} className={`is-${metric.tone}`}>
            <header>
              <span>{metric.label}</span>
              <b>{metric.detail}</b>
            </header>
            <strong>{metric.value}</strong>
            <MiniTrend values={metric.samples} tone={metric.tone} />
          </article>
        ))}
      </section>

      <div className="system-pulse__grid">
        <section className="system-pulse__panel system-pulse__throughput">
          <SectionHeading
            eyebrow={`Processing throughput · ${range}`}
            title="Scraping activity"
            aside={
              <div className="system-pulse__legend" aria-label="Chart legend">
                <span className="is-primary">Items/s</span>
                <span className="is-error">Failure %</span>
              </div>
            }
          />
          <div className="system-pulse__chart-wrap">
            <div className="system-pulse__chart-axis" aria-hidden="true">
              <span>{formatCompactRate(throughputAxis.maximum)}</span>
              <span>{formatCompactRate(throughputAxis.minimum + (throughputAxis.maximum - throughputAxis.minimum) * 0.66)}</span>
              <span>{formatCompactRate(throughputAxis.minimum + (throughputAxis.maximum - throughputAxis.minimum) * 0.33)}</span>
              <span>{formatCompactRate(throughputAxis.minimum)}</span>
            </div>
            <div className="system-pulse__chart-canvas">
              <svg
                className="system-pulse__chart"
                viewBox="0 0 640 180"
                preserveAspectRatio="none"
                role="img"
                aria-label={`Items per second and failure rate over ${range}`}
              >
                <defs>
                  <linearGradient id="system-pulse-area" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" stopColor={atlas ? '#24aac3' : '#67e6b1'} stopOpacity=".27" />
                    <stop offset="1" stopColor={atlas ? '#24aac3' : '#67e6b1'} stopOpacity="0" />
                  </linearGradient>
                </defs>
                <g className="grid">
                  <path d="M0 20H640M0 60H640M0 100H640M0 140H640M80 0V180M160 0V180M240 0V180M320 0V180M400 0V180M480 0V180M560 0V180" />
                </g>
                <path className="area" d={`${throughputLine} L640 180 L0 180Z`} />
                <path className="line" d={throughputLine} />
                <path className="errors" d={errorLine} />
              </svg>
              {rangeSamples.length < 2 && (
                <p>
                  {itemRate > 0
                    ? 'Building live history…'
                    : 'No scraping activity in this window'}
                </p>
              )}
            </div>
          </div>
          <footer>{chartLabels.map((label, index) => <span key={`${label}-${index}`}>{label}</span>)}</footer>
        </section>

        {atlasParts && <atlasParts.Pipeline
          backendId={backendQuery.data?.backend_id}
          workers={backendQuery.data?.worker_count}
          activeWorkers={backendQuery.data?.active_workers}
          routes={proxiesQuery.data?.length}
          distributed={backendQuery.data?.distributed_mode}
          redisConnected={backendQuery.data?.redis_connected}
        />}

        <section
          className="system-pulse__panel system-pulse__jobs"
        >
          <SectionHeading
            eyebrow={`${activeJobs.filter((job) => job.status === 'running').length} executing · ${queuedJobs} queued`}
            title="Active jobs"
            aside={<Link to="/jobs">View all →</Link>}
          />
          <div className="system-pulse__job-list">
            {activeJobs.length === 0 ? (
              <EmptyState>No active jobs. The queue is clear.</EmptyState>
            ) : (
              activeJobs.slice(0, 4).map((job) => {
                const progress = jobProgress(job);
                const selected = effectiveSelectedJobId === job.job_id;
                return (
                  <button
                    type="button"
                    className={`system-pulse__job ${selected ? 'is-selected' : ''}`}
                    aria-pressed={selected}
                    aria-haspopup="dialog"
                    key={job.job_id}
                    onClick={() => setSelectedJob(job)}
                  >
                    <span className="system-pulse__job-topline">
                      <StatusPill tone={job.status === 'pending' ? 'warning' : 'info'}>
                        {labelJobStatus(job.status)}
                      </StatusPill>
                      <code>{job.job_id}</code>
                      <time dateTime={job.created_at}>
                        {formatClock(job.created_at)}
                      </time>
                    </span>
                    <span className="system-pulse__job-title">
                      <b>{job.job_name || job.job_id}</b>
                      <small>{job.site || job.job_type || 'General workload'}</small>
                    </span>
                    <span
                      className="system-pulse__meter"
                      role="progressbar"
                      aria-label={`${job.job_name || job.job_id} progress`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(progress)}
                    >
                      <i style={{ width: `${progress}%` }} />
                      <em>{Math.round(progress)}%</em>
                    </span>
                    <span className="system-pulse__job-meta">
                      <small>{job.completed_tasks.toLocaleString()} completed</small>
                      <small>{job.failed_tasks.toLocaleString()} failed</small>
                      <small>{job.worker_id || 'Awaiting worker'}</small>
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </section>

        <section className="system-pulse__panel system-pulse__workers">
          <SectionHeading
            eyebrow={`${activeWorkers} busy · ${Math.max(workerCount - activeWorkers, 0)} available`}
            title={atlas ? 'Worker array' : 'Worker utilization'}
            aside={
              <span>
                CPU {systemCpu == null ? '—' : formatPercent(systemCpu)} · MEM{' '}
                {systemMemory == null ? '—' : formatPercent(systemMemory)}
              </span>
            }
          />
          <div className="system-pulse__worker-list">
            {(backendQuery.data?.workers ?? []).length === 0 ? (
              <EmptyState>No worker heartbeats are currently available.</EmptyState>
            ) : atlasParts ? <atlasParts.WorkerArray workers={backendQuery.data?.workers ?? []} /> : (
              (backendQuery.data?.workers ?? []).slice(0, 8).map((worker) => (
                <WorkerRow key={worker.worker_id} worker={worker} />
              ))
            )}
          </div>
        </section>

        <section className="system-pulse__panel system-pulse__network">
          <SectionHeading
            eyebrow={`${(proxiesQuery.data ?? []).length} configured · ${totalProxyAssignments} assignments`}
            title={atlas ? 'Route network / Proxies' : 'Proxy fabric'}
            aside={atlas ? <Link to="/network">Manage proxies →</Link> : <span>{totalProxyCapacity.toLocaleString()} connection slots</span>}
          />
          <div className="system-pulse__network-list">
            {proxiesQuery.isError ? (
              <EmptyState>Proxy inventory is unavailable.</EmptyState>
            ) : proxyRegions.length === 0 ? (
              <EmptyState>No proxy routes are configured.</EmptyState>
            ) : (
              proxyRegions.slice(0, 6).map((region) => {
                const share = totalProxyCapacity > 0
                  ? (region.capacity / totalProxyCapacity) * 100
                  : (region.routes / Math.max(proxiesQuery.data?.length ?? 1, 1)) * 100;
                return (
                  <div key={region.name}>
                    <span>
                      <b>{region.name}</b>
                      <small>{region.capacity.toLocaleString()} connection slots</small>
                    </span>
                    <span
                      className="system-pulse__proxy-meter"
                      role="progressbar"
                      aria-label={`${region.name} share of proxy capacity`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(share)}
                    >
                      <i style={{ width: `${clamp(share)}%` }} />
                    </span>
                    <em>
                      {region.routes}
                      <small>+{region.assignments}</small>
                    </em>
                  </div>
                );
              })
            )}
          </div>
        </section>

        <section className="system-pulse__panel system-pulse__events">
          <SectionHeading
            eyebrow={eventsPaused ? 'Stream held at operator request' : 'Correlated system stream'}
            title="Recent events"
            aside={
              <button type="button" onClick={toggleEvents}>
                {eventsPaused ? 'Resume' : 'Pause'}
              </button>
            }
          />
          <div className="system-pulse__event-list">
            {visibleEvents.length === 0 ? (
              <EmptyState>Waiting for the first backend event.</EmptyState>
            ) : (
              visibleEvents.map((event) => (
                <article key={event.id}>
                  <time dateTime={new Date(event.timestamp).toISOString()}>
                    {new Intl.DateTimeFormat(undefined, {
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                    }).format(event.timestamp)}
                  </time>
                  <i className={`is-${event.severity}`} aria-hidden="true" />
                  <span>
                    <b>{event.title}</b>
                    <small>{event.source} · {event.detail}</small>
                  </span>
                </article>
              ))
            )}
          </div>
        </section>
      </div>
      {selectedJobDetails && createPortal(
        <Suspense fallback={null}>
          <JobDetailsModal
            key={selectedJobDetails.job_id}
            job={selectedJobDetails}
            onClose={() => setSelectedJob(null)}
          />
        </Suspense>,
        document.body,
      )}
    </section>
  );
}
