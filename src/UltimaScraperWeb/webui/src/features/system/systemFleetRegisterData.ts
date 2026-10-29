import type {
  BackendStatusResponse,
  DriveInfo,
  RemoteBackendDrive,
  RemoteBackendInfo,
  RemoteBackendWorker,
} from '../../api/types/system';

export type RegisterHealth = 'healthy' | 'warning' | 'offline';
export type RegisterWorkerState = 'running' | 'idle' | 'offline' | 'warning';

export interface RegisterWorker {
  workerId: string;
  status: RegisterWorkerState;
  currentJob: string | null;
  jobsCompleted: number;
}

export interface RegisterMount {
  id: string;
  backendId: string;
  path: string;
  device: string;
  totalBytes: number;
  usedBytes: number;
  freeBytes: number;
  percentUsed: number;
  configuredDirectories: string[];
  isAvailable: boolean;
  isConfigured: boolean;
}

export interface RegisterBackend {
  backendId: string;
  label: string;
  hostname: string;
  status: string;
  version: string;
  maxWorkers: number;
  activeWorkers: number;
  pendingJobs: number;
  lastSeen: string;
  heartbeatAge: number | null;
  health: RegisterHealth;
  isLocal: boolean;
  clusterId?: string | null;
  apiUrl?: string | null;
  /** The machine's network address, when its backend reports one. */
  address?: string | null;
  workers: RegisterWorker[];
  mounts: RegisterMount[];
}

function normalizeWorkerState(status: string): RegisterWorkerState {
  const normalized = status.toLowerCase();
  if (normalized === 'busy' || normalized === 'running') return 'running';
  if (normalized === 'idle' || normalized === 'online') return 'idle';
  if (normalized === 'offline' || normalized === 'stopped') return 'offline';
  return 'warning';
}

function heartbeatAge(lastSeen: string, now: number): number | null {
  const timestamp = Date.parse(lastSeen);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, Math.floor((now - timestamp) / 1000));
}

function getBackendHealth(
  status: string,
  age: number | null,
  isLocal: boolean,
  redisConnected: boolean | undefined,
): RegisterHealth {
  if (isLocal && redisConnected === false) return 'warning';
  const normalized = status.toLowerCase();
  if (normalized === 'offline' || (age !== null && age > 60)) return 'offline';
  if (normalized !== 'online' || (!isLocal && age !== null && age > 30) || age === null) {
    return 'warning';
  }
  return 'healthy';
}

function toRegisterWorker(worker: RemoteBackendWorker): RegisterWorker {
  return {
    workerId: worker.worker_id,
    status: normalizeWorkerState(worker.status),
    currentJob: worker.current_job,
    jobsCompleted: worker.jobs_completed,
  };
}

function toRegisterMount(
  drive: RemoteBackendDrive | DriveInfo,
  backendId: string,
  index: number,
): RegisterMount {
  const configuredDirectories = drive.configured_directories ?? [];
  const isAvailable = 'is_available' in drive ? drive.is_available !== false : true;
  const isConfigured = 'is_configured' in drive
    ? drive.is_configured
    : configuredDirectories.length > 0;

  return {
    id: `${backendId}:${drive.path}:${index}`,
    backendId,
    path: drive.path,
    device: drive.device,
    totalBytes: drive.total_bytes,
    usedBytes: drive.used_bytes,
    freeBytes: drive.free_bytes,
    percentUsed: drive.percent_used,
    configuredDirectories,
    isAvailable,
    isConfigured,
  };
}

export function buildRegisterBackends(
  localStatus: BackendStatusResponse | undefined,
  cluster: { local_backend_id: string; local_hostname: string; backends: RemoteBackendInfo[] } | undefined,
  localDrives: DriveInfo[],
  now: number,
): RegisterBackend[] {
  const remoteRows = (cluster?.backends ?? []).map((backend) => {
    const age = heartbeatAge(backend.last_seen, now);
    return {
      backendId: backend.backend_id,
      label: backend.hostname && !/^[0-9a-f]{12}$/i.test(backend.hostname) ? backend.hostname : backend.backend_id,
      hostname: backend.hostname || 'Hostname unavailable',
      status: backend.status,
      version: backend.version || 'Version unavailable',
      maxWorkers: backend.max_workers,
      activeWorkers: backend.active_workers,
      pendingJobs: backend.pending_jobs,
      lastSeen: backend.last_seen,
      heartbeatAge: age,
      health: getBackendHealth(backend.status, age, false, localStatus?.redis_connected),
      isLocal: false,
      clusterId: backend.cluster_id ?? null,
      apiUrl: backend.api_url ?? null,
      address: backend.address ?? null,
      workers: backend.workers.map(toRegisterWorker),
      mounts: backend.drives.map((drive, index) => toRegisterMount(drive, backend.backend_id, index)),
    } satisfies RegisterBackend;
  });

  const localBackendId = localStatus?.backend_id ?? cluster?.local_backend_id;
  if (!localBackendId) return remoteRows;

  const registeredLocal = remoteRows.find((backend) => backend.backendId === localBackendId);
  const localLastSeen = registeredLocal?.lastSeen ?? new Date(now).toISOString();
  const localAge = heartbeatAge(localLastSeen, now);
  const localWorkers = localStatus?.workers.map((worker) => toRegisterWorker(worker))
    ?? registeredLocal?.workers
    ?? [];
  const localMounts = localDrives.length > 0
    ? localDrives.map((drive, index) => toRegisterMount(drive, localBackendId, index))
    : registeredLocal?.mounts ?? [];
  const localRow: RegisterBackend = {
    backendId: localBackendId,
    label: registeredLocal?.label ?? cluster?.local_hostname ?? localBackendId,
    hostname: registeredLocal?.hostname ?? cluster?.local_hostname ?? 'Local host',
    status: localStatus?.redis_connected === false ? 'degraded' : registeredLocal?.status ?? 'online',
    version: registeredLocal?.version ?? 'Current process',
    maxWorkers: registeredLocal?.maxWorkers || localStatus?.worker_count || localWorkers.length,
    activeWorkers: localStatus?.active_workers ?? registeredLocal?.activeWorkers ?? 0,
    pendingJobs: localStatus?.pending_jobs ?? registeredLocal?.pendingJobs ?? 0,
    lastSeen: localLastSeen,
    heartbeatAge: localAge,
    health: getBackendHealth(
      localStatus?.redis_connected === false ? 'degraded' : registeredLocal?.status ?? 'online',
      localAge,
      true,
      localStatus?.redis_connected,
    ),
    isLocal: true,
    clusterId: registeredLocal?.clusterId ?? null,
    apiUrl: registeredLocal?.apiUrl ?? null,
    address: registeredLocal?.address ?? null,
    workers: localWorkers,
    mounts: localMounts,
  };

  return [localRow, ...remoteRows.filter((backend) => backend.backendId !== localBackendId)];
}
