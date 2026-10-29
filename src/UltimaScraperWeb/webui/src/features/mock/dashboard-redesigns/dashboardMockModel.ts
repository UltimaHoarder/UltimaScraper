import { useState, useEffect, useMemo } from 'react';

export type DashboardTimeRange = '15 min' | '1 hour' | '24 hours';
export type DashboardScenarioId = 'nominal' | 'surge' | 'degraded';
export type JobStatus = 'running' | 'queued' | 'completed' | 'failed' | 'paused';
export type WorkerState = 'busy' | 'idle' | 'warning' | 'offline';
export type EventSeverity = 'info' | 'success' | 'warning' | 'critical';

export interface MockDashboardJob {
  id: string;
  name: string;
  site: 'OnlyFans' | 'Fansly' | 'LoyalFans';
  type: 'Creator Sync' | 'Mass Profile Scrape' | 'Vault Backfill' | 'Media Re-encode';
  status: JobStatus;
  totalTasks: number;
  completedTasks: number;
  failedTasks: number;
  itemsPerSec: number;
  writeMbPerSec: number;
  workerId: string;
  startedAt: string;
  etaMinutes: number;
  currentStage: 'Discovering' | 'Authenticating' | 'Downloading' | 'Checksumming';
}

export interface MockWorkerNode {
  id: string;
  name: string;
  region: string;
  state: WorkerState;
  cpuPercent: number;
  memPercent: number;
  activeJobId: string | null;
  tasksCompleted: number;
  throughputMb: number;
  latencyMs: number;
  uptimeHours: number;
}

export interface MockProxyRegion {
  id: string;
  name: string;
  countryCode: string;
  routes: number;
  activeAssignments: number;
  maxCapacity: number;
  latencyMs: number;
  successRate: number;
  throttledCount: number;
}

export interface MockStorageMount {
  id: string;
  label: string;
  path: string;
  tier: 'hot' | 'warm' | 'cold';
  usedTb: number;
  totalTb: number;
  writeMbPerSec: number;
  freeSpaceGb: number;
  minWatermarkGb: number;
  overflowActive: boolean;
}

export interface MockSystemEvent {
  id: string;
  timestamp: string;
  severity: EventSeverity;
  source: string;
  category: 'job' | 'worker' | 'proxy' | 'storage' | 'redis';
  title: string;
  detail: string;
  acknowledged?: boolean;
}

export interface MockTelemetrySample {
  timeLabel: string;
  itemsPerSec: number;
  writeMbPerSec: number;
  failureRate: number;
  workerLoad: number;
  queueDepth: number;
}

export interface MockIncidentAlert {
  id: string;
  severity: 'warning' | 'critical';
  title: string;
  subsystem: 'Redis Broker' | 'Proxy Pool' | 'Storage Spillway' | 'Worker Fleet';
  diagnosis: string;
  remediationLabel: string;
  resolved: boolean;
}

const INITIAL_JOBS: MockDashboardJob[] = [
  {
    id: 'job-9482a',
    name: 'VIP Creator Delta Sync (Batch 04)',
    site: 'OnlyFans',
    type: 'Creator Sync',
    status: 'running',
    totalTasks: 1240,
    completedTasks: 892,
    failedTasks: 4,
    itemsPerSec: 42.8,
    writeMbPerSec: 184.5,
    workerId: 'worker-eu-01',
    startedAt: '02:41',
    etaMinutes: 6,
    currentStage: 'Downloading',
  },
  {
    id: 'job-9485c',
    name: 'MPS Range 1,400,000 – 1,450,000',
    site: 'Fansly',
    type: 'Mass Profile Scrape',
    status: 'running',
    totalTasks: 50000,
    completedTasks: 31450,
    failedTasks: 18,
    itemsPerSec: 128.4,
    writeMbPerSec: 32.0,
    workerId: 'worker-us-02',
    startedAt: '01:55',
    etaMinutes: 14,
    currentStage: 'Discovering',
  },
  {
    id: 'job-9489f',
    name: 'Content Mentions Backfill (@luna_archive)',
    site: 'OnlyFans',
    type: 'Vault Backfill',
    status: 'running',
    totalTasks: 480,
    completedTasks: 412,
    failedTasks: 0,
    itemsPerSec: 19.2,
    writeMbPerSec: 96.4,
    workerId: 'worker-eu-02',
    startedAt: '02:58',
    etaMinutes: 2,
    currentStage: 'Checksumming',
  },
  {
    id: 'job-9491b',
    name: 'Scheduled Subscription Catch-up',
    site: 'LoyalFans',
    type: 'Creator Sync',
    status: 'queued',
    totalTasks: 860,
    completedTasks: 0,
    failedTasks: 0,
    itemsPerSec: 0,
    writeMbPerSec: 0,
    workerId: 'Awaiting slot',
    startedAt: '03:04',
    etaMinutes: 22,
    currentStage: 'Authenticating',
  },
  {
    id: 'job-9479x',
    name: 'AV1 Hardware Re-encode Queue',
    site: 'OnlyFans',
    type: 'Media Re-encode',
    status: 'failed',
    totalTasks: 320,
    completedTasks: 198,
    failedTasks: 24,
    itemsPerSec: 0,
    writeMbPerSec: 0,
    workerId: 'worker-de-04',
    startedAt: '01:10',
    etaMinutes: 0,
    currentStage: 'Downloading',
  },
];

const INITIAL_WORKERS: MockWorkerNode[] = [
  { id: 'worker-eu-01', name: 'ams-nvme-core-01', region: 'NL · Amsterdam', state: 'busy', cpuPercent: 78, memPercent: 64, activeJobId: 'job-9482a', tasksCompleted: 14820, throughputMb: 184.5, latencyMs: 11, uptimeHours: 412 },
  { id: 'worker-eu-02', name: 'ams-nvme-core-02', region: 'NL · Amsterdam', state: 'busy', cpuPercent: 62, memPercent: 58, activeJobId: 'job-9489f', tasksCompleted: 12910, throughputMb: 96.4, latencyMs: 14, uptimeHours: 412 },
  { id: 'worker-us-01', name: 'ash-edge-scraper-01', region: 'US · Ashburn', state: 'busy', cpuPercent: 84, memPercent: 71, activeJobId: 'job-9485c', tasksCompleted: 29400, throughputMb: 112.0, latencyMs: 28, uptimeHours: 196 },
  { id: 'worker-us-02', name: 'ash-edge-scraper-02', region: 'US · Ashburn', state: 'busy', cpuPercent: 71, memPercent: 66, activeJobId: 'job-9485c', tasksCompleted: 27150, throughputMb: 88.2, latencyMs: 31, uptimeHours: 196 },
  { id: 'worker-de-03', name: 'fra-storage-node-03', region: 'DE · Frankfurt', state: 'idle', cpuPercent: 14, memPercent: 38, activeJobId: null, tasksCompleted: 9840, throughputMb: 0, latencyMs: 9, uptimeHours: 640 },
  { id: 'worker-de-04', name: 'fra-transcode-04', region: 'DE · Frankfurt', state: 'warning', cpuPercent: 94, memPercent: 89, activeJobId: 'job-9479x', tasksCompleted: 6120, throughputMb: 14.2, latencyMs: 84, uptimeHours: 88 },
  { id: 'worker-sg-01', name: 'sin-apac-relay-01', region: 'SG · Singapore', state: 'idle', cpuPercent: 9, memPercent: 29, activeJobId: null, tasksCompleted: 5430, throughputMb: 0, latencyMs: 62, uptimeHours: 310 },
  { id: 'worker-uk-01', name: 'lon-standby-01', region: 'UK · London', state: 'offline', cpuPercent: 0, memPercent: 0, activeJobId: null, tasksCompleted: 4110, throughputMb: 0, latencyMs: 0, uptimeHours: 0 },
];

const INITIAL_PROXIES: MockProxyRegion[] = [
  { id: 'reg-us-east', name: 'United States · Virginia', countryCode: 'US', routes: 48, activeAssignments: 36, maxCapacity: 240, latencyMs: 24, successRate: 99.6, throttledCount: 0 },
  { id: 'reg-nl-ams', name: 'Netherlands · North Holland', countryCode: 'NL', routes: 36, activeAssignments: 28, maxCapacity: 180, latencyMs: 12, successRate: 99.9, throttledCount: 0 },
  { id: 'reg-de-fra', name: 'Germany · Hesse', countryCode: 'DE', routes: 32, activeAssignments: 22, maxCapacity: 160, latencyMs: 15, successRate: 98.4, throttledCount: 2 },
  { id: 'reg-uk-lon', name: 'United Kingdom · London', countryCode: 'GB', routes: 20, activeAssignments: 14, maxCapacity: 100, latencyMs: 19, successRate: 99.2, throttledCount: 0 },
  { id: 'reg-sg-sin', name: 'Singapore · Central', countryCode: 'SG', routes: 14, activeAssignments: 6, maxCapacity: 70, latencyMs: 58, successRate: 97.8, throttledCount: 1 },
];

const INITIAL_MOUNTS: MockStorageMount[] = [
  { id: 'mnt-fast', label: 'NVMe Fast Cache', path: '/mnt/storage_fast', tier: 'hot', usedTb: 1.32, totalTb: 2.0, writeMbPerSec: 280.9, freeSpaceGb: 680, minWatermarkGb: 50, overflowActive: false },
  { id: 'mnt-frankfurt', label: 'Frankfurt Satellite Staging', path: '/mnt/worker_frankfurt', tier: 'warm', usedTb: 3.79, totalTb: 4.0, writeMbPerSec: 46.2, freeSpaceGb: 210, minWatermarkGb: 250, overflowActive: true },
  { id: 'mnt-archive', label: 'ZFS Bulk Archive Pool', path: '/media/archive_pool', tier: 'cold', usedTb: 84.48, totalTb: 96.0, writeMbPerSec: 112.4, freeSpaceGb: 11520, minWatermarkGb: 500, overflowActive: false },
];

const INITIAL_EVENTS: MockSystemEvent[] = [
  { id: 'ev-1', timestamp: '03:08:14', severity: 'info', source: 'worker-eu-01', category: 'job', title: 'Checkpoint committed for @luna_archive', detail: '412 media items verified · SHA-256 manifest updated' },
  { id: 'ev-2', timestamp: '03:07:52', severity: 'warning', source: 'reg-de-fra', category: 'proxy', title: 'HTTP 429 rate-limit backoff on 2 Frankfurt routes', detail: 'Auto-rotated session auth-of-09 to NL · Amsterdam pool' },
  { id: 'ev-3', timestamp: '03:06:30', severity: 'success', source: 'worker-us-02', category: 'job', title: 'MPS refill batch 62 completed', detail: '500 candidate IDs scanned · 38 active creators queued' },
  { id: 'ev-4', timestamp: '03:05:11', severity: 'critical', source: 'worker-de-04', category: 'storage', title: 'Frankfurt mount crossed 250 GB watermark', detail: 'Overflow spillway engaged → routing new writes to /media/archive_pool' },
  { id: 'ev-5', timestamp: '03:03:45', severity: 'info', source: 'redis-primary', category: 'redis', title: 'Distributed claim lease sweep finished', detail: '0 orphaned tasks · queue latency 1.4ms' },
  { id: 'ev-6', timestamp: '03:01:19', severity: 'critical', source: 'job-9479x', category: 'job', title: 'AV1 Hardware Re-encode task error threshold reached', detail: 'NVENC session limit exceeded on fra-transcode-04 (24 failed tasks)' },
];

const INITIAL_INCIDENTS: MockIncidentAlert[] = [
  {
    id: 'inc-spillway',
    severity: 'warning',
    title: 'Frankfurt Satellite Mount (/mnt/worker_frankfurt) below 250 GB reserve',
    subsystem: 'Storage Spillway',
    diagnosis: 'Free space at 210 GB (94.8% used). Overflow routing is actively diverting writes to ZFS Bulk Archive.',
    remediationLabel: 'Flush Staging to Cold Archive',
    resolved: false,
  },
  {
    id: 'inc-transcode',
    severity: 'critical',
    title: 'Worker fra-transcode-04 reporting high memory & NVENC errors',
    subsystem: 'Worker Fleet',
    diagnosis: 'Job job-9479x stalled with 24 failed tasks due to concurrent hardware encoder contention.',
    remediationLabel: 'Requeue Failed Tasks on EU-01',
    resolved: false,
  },
];

const INITIAL_SAMPLES: MockTelemetrySample[] = [
  { timeLabel: '02:10', itemsPerSec: 94, writeMbPerSec: 165, failureRate: 0.4, workerLoad: 58, queueDepth: 1420 },
  { timeLabel: '02:20', itemsPerSec: 118, writeMbPerSec: 210, failureRate: 0.3, workerLoad: 66, queueDepth: 1890 },
  { timeLabel: '02:30', itemsPerSec: 145, writeMbPerSec: 248, failureRate: 0.5, workerLoad: 74, queueDepth: 2340 },
  { timeLabel: '02:40', itemsPerSec: 162, writeMbPerSec: 295, failureRate: 0.8, workerLoad: 82, queueDepth: 2110 },
  { timeLabel: '02:50', itemsPerSec: 210, writeMbPerSec: 360, failureRate: 1.9, workerLoad: 88, queueDepth: 1750 },
  { timeLabel: '03:00', itemsPerSec: 184, writeMbPerSec: 318, failureRate: 1.1, workerLoad: 79, queueDepth: 1290 },
  { timeLabel: '03:08', itemsPerSec: 190.4, writeMbPerSec: 312.9, failureRate: 0.6, workerLoad: 75, queueDepth: 860 },
];

export function useDashboardMockModel() {
  const [range, setRange] = useState<DashboardTimeRange>('1 hour');
  const [scenario, setScenario] = useState<DashboardScenarioId>('nominal');
  const [liveStream, setLiveStream] = useState<boolean>(true);
  const [eventsPaused, setEventsPaused] = useState<boolean>(false);
  const [jobs, setJobs] = useState<MockDashboardJob[]>(INITIAL_JOBS);
  const [workers, setWorkers] = useState<MockWorkerNode[]>(INITIAL_WORKERS);
  const [proxies, setProxies] = useState<MockProxyRegion[]>(INITIAL_PROXIES);
  const [mounts, setMounts] = useState<MockStorageMount[]>(INITIAL_MOUNTS);
  const [events, setEvents] = useState<MockSystemEvent[]>(INITIAL_EVENTS);
  const [incidents, setIncidents] = useState<MockIncidentAlert[]>(INITIAL_INCIDENTS);
  const [samples, setSamples] = useState<MockTelemetrySample[]>(INITIAL_SAMPLES);
  const [selectedJobId, setSelectedJobId] = useState<string>(INITIAL_JOBS[0].id);
  const [selectedWorkerId, setSelectedWorkerId] = useState<string>(INITIAL_WORKERS[0].id);
  const [eventFilter, setEventFilter] = useState<'all' | EventSeverity>('all');
  const [notice, setNotice] = useState<string | null>(null);

  const showNotice = (msg: string) => {
    setNotice(msg);
  };

  useEffect(() => {
    if (!liveStream) return;
    const timer = window.setInterval(() => {
      setSamples((prev) => {
        const last = prev[prev.length - 1];
        const multiplier = scenario === 'surge' ? 1.35 : scenario === 'degraded' ? 0.65 : 1;
        const nextItems = Math.max(24, Number(((last.itemsPerSec + (Math.random() - 0.48) * 18) * multiplier).toFixed(1)));
        const nextWrite = Math.max(40, Number(((last.writeMbPerSec + (Math.random() - 0.48) * 28) * multiplier).toFixed(1)));
        const nextFail = scenario === 'degraded' ? Number((3.2 + Math.random() * 2.5).toFixed(1)) : Number(Math.max(0.1, last.failureRate + (Math.random() - 0.5) * 0.3).toFixed(1));
        const now = new Date();
        const label = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
        return [
          ...prev.slice(1),
          {
            timeLabel: label,
            itemsPerSec: nextItems,
            writeMbPerSec: nextWrite,
            failureRate: nextFail,
            workerLoad: Math.min(98, Math.max(35, Math.round(last.workerLoad + (Math.random() - 0.5) * 6))),
            queueDepth: Math.max(120, Math.round(last.queueDepth + (Math.random() - 0.52) * 90)),
          },
        ];
      });
    }, 2400);
    return () => window.clearInterval(timer);
  }, [liveStream, scenario]);

  const applyScenario = (nextScenario: DashboardScenarioId) => {
    setScenario(nextScenario);
    if (nextScenario === 'nominal') {
      setJobs(INITIAL_JOBS);
      setWorkers(INITIAL_WORKERS);
      setIncidents(INITIAL_INCIDENTS);
      showNotice('Switched to Nominal Operations preset · balanced fleet load');
    } else if (nextScenario === 'surge') {
      setJobs((prev) =>
        prev.map((j) =>
          j.status === 'running'
            ? { ...j, itemsPerSec: Number((j.itemsPerSec * 1.6).toFixed(1)), writeMbPerSec: Number((j.writeMbPerSec * 1.45).toFixed(1)) }
            : j.status === 'queued'
              ? { ...j, status: 'running', itemsPerSec: 84.2, writeMbPerSec: 142.0, workerId: 'worker-de-03' }
              : j
        )
      );
      setWorkers((prev) =>
        prev.map((w) => (w.state === 'idle' ? { ...w, state: 'busy', cpuPercent: 88, memPercent: 76, throughputMb: 142.0 } : w))
      );
      showNotice('Switched to High-Throughput Surge preset · 6/8 workers saturated');
    } else {
      setWorkers((prev) =>
        prev.map((w, idx) => (idx === 1 || idx === 5 ? { ...w, state: 'warning', cpuPercent: 96, latencyMs: 145 } : w))
      );
      setIncidents([
        ...INITIAL_INCIDENTS,
        {
          id: 'inc-redis-lag',
          severity: 'critical',
          title: 'Redis Broker stream lag spike (420ms claim latency)',
          subsystem: 'Redis Broker',
          diagnosis: 'High MPS discovery burst queuing 50,000+ ephemeral keys on primary broker.',
          remediationLabel: 'Throttle MPS Concurrency & Compact Stream',
          resolved: false,
        },
      ]);
      showNotice('Switched to Degraded Incident preset · 3 active subsystem alerts');
    }
  };

  const selectedJob = useMemo(
    () => jobs.find((j) => j.id === selectedJobId) ?? jobs[0],
    [jobs, selectedJobId]
  );

  const selectedWorker = useMemo(
    () => workers.find((w) => w.id === selectedWorkerId) ?? workers[0],
    [workers, selectedWorkerId]
  );

  const filteredEvents = useMemo(
    () => (eventFilter === 'all' ? events : events.filter((e) => e.severity === eventFilter)),
    [events, eventFilter]
  );

  const kpis = useMemo(() => {
    const runningJobs = jobs.filter((j) => j.status === 'running').length;
    const queuedJobs = jobs.filter((j) => j.status === 'queued').length;
    const totalItemsPerSec = jobs.reduce((acc, j) => acc + (j.status === 'running' ? j.itemsPerSec : 0), 0);
    const totalWriteMb = mounts.reduce((acc, m) => acc + m.writeMbPerSec, 0);
    const busyWorkers = workers.filter((w) => w.state === 'busy' || w.state === 'warning').length;
    const onlineWorkers = workers.filter((w) => w.state !== 'offline').length;
    const totalCompleted = jobs.reduce((acc, j) => acc + j.completedTasks, 0);
    const totalFailed = jobs.reduce((acc, j) => acc + j.failedTasks, 0);
    const successRate = totalCompleted + totalFailed > 0 ? ((totalCompleted / (totalCompleted + totalFailed)) * 100) : 100;
    const unresolvedIncidents = incidents.filter((i) => !i.resolved).length;

    return {
      runningJobs,
      queuedJobs,
      totalItemsPerSec: Number(totalItemsPerSec.toFixed(1)),
      totalWriteMb: Number(totalWriteMb.toFixed(1)),
      busyWorkers,
      onlineWorkers,
      totalWorkers: workers.length,
      workerUtilization: Math.round((busyWorkers / Math.max(onlineWorkers, 1)) * 100),
      successRate: Number(successRate.toFixed(2)),
      totalFailed,
      unresolvedIncidents,
    };
  }, [jobs, mounts, workers, incidents]);

  const toggleJobPause = (jobId: string) => {
    setJobs((prev) =>
      prev.map((j) => {
        if (j.id !== jobId) return j;
        const nextStatus: JobStatus = j.status === 'running' ? 'paused' : 'running';
        showNotice(`Job ${j.id} (${j.name}) ${nextStatus === 'paused' ? 'paused' : 'resumed'}`);
        return { ...j, status: nextStatus };
      })
    );
  };

  const retryFailedJob = (jobId: string) => {
    setJobs((prev) =>
      prev.map((j) => {
        if (j.id !== jobId) return j;
        showNotice(`Requeued ${j.failedTasks} failed tasks for ${j.name}`);
        return { ...j, status: 'running', failedTasks: 0, itemsPerSec: 34.5, writeMbPerSec: 78.0 };
      })
    );
  };

  const resolveIncident = (incidentId: string) => {
    setIncidents((prev) =>
      prev.map((inc) => {
        if (inc.id !== incidentId) return inc;
        showNotice(`Executed remediation: ${inc.remediationLabel}`);
        return { ...inc, resolved: true };
      })
    );
  };

  const rotateThrottledProxies = (regionId: string) => {
    setProxies((prev) =>
      prev.map((p) => {
        if (p.id !== regionId) return p;
        showNotice(`Rotated throttled sessions in ${p.name} · 100% route health restored`);
        return { ...p, throttledCount: 0, successRate: 99.9 };
      })
    );
  };

  const rebalanceOverflowMount = (mountId: string) => {
    setMounts((prev) =>
      prev.map((m) => {
        if (m.id !== mountId) return m;
        showNotice(`Flushed 180 GB from ${m.path} to cold archive · spillway cleared`);
        return { ...m, usedTb: Number((m.usedTb - 0.18).toFixed(2)), freeSpaceGb: m.freeSpaceGb + 180, overflowActive: false };
      })
    );
  };

  const drainWorker = (workerId: string) => {
    setWorkers((prev) =>
      prev.map((w) => {
        if (w.id !== workerId) return w;
        const nextState: WorkerState = w.state === 'idle' ? 'busy' : 'idle';
        showNotice(`Worker ${w.name} transitioned to ${nextState.toUpperCase()}`);
        return { ...w, state: nextState, cpuPercent: nextState === 'idle' ? 8 : 68, activeJobId: nextState === 'idle' ? null : 'job-9482a' };
      })
    );
  };

  const reset = () => {
    setRange('1 hour');
    setScenario('nominal');
    setLiveStream(true);
    setEventsPaused(false);
    setJobs(INITIAL_JOBS);
    setWorkers(INITIAL_WORKERS);
    setProxies(INITIAL_PROXIES);
    setMounts(INITIAL_MOUNTS);
    setEvents(INITIAL_EVENTS);
    setIncidents(INITIAL_INCIDENTS);
    setSamples(INITIAL_SAMPLES);
    setSelectedJobId(INITIAL_JOBS[0].id);
    setSelectedWorkerId(INITIAL_WORKERS[0].id);
    setEventFilter('all');
    setNotice('Dashboard preview reset to baseline telemetry');
  };

  return {
    range,
    setRange,
    scenario,
    applyScenario,
    liveStream,
    setLiveStream,
    eventsPaused,
    setEventsPaused,
    jobs,
    workers,
    proxies,
    mounts,
    events,
     filteredEvents,
    eventFilter,
    setEventFilter,
    incidents,
    samples,
    selectedJob,
    selectedJobId,
    setSelectedJobId,
    selectedWorker,
    selectedWorkerId,
    setSelectedWorkerId,
    kpis,
    notice,
    showNotice,
    toggleJobPause,
    retryFailedJob,
    resolveIncident,
    rotateThrottledProxies,
    rebalanceOverflowMount,
    drainWorker,
    reset,
  };
}

export type DashboardMockModel = ReturnType<typeof useDashboardMockModel>;
