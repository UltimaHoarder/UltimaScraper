export interface DriveInfo {
  path: string;
  device: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  percent_used: number;
  is_configured: boolean;
  directory_count: number;
  configured_directories: string[];
  is_available?: boolean;
}

export interface DrivesResponse {
  backend_id: string;
  drives: DriveInfo[];
}

export type StoragePropagationStatus =
  | 'acknowledged'
  | 'partial'
  | 'pending'
  | 'no_workers'
  | 'local_only';

export interface StorageConfigPropagation {
  status: StoragePropagationStatus;
  target_backend_id: string;
  settings_scope: string;
  config_version: number;
  revision: string;
  request_id: string;
  expected_workers: string[];
  acknowledged_workers: string[];
  failed_workers: string[];
  message: string;
}

export interface AddDirectoryRequest {
  drive_path: string;
  directory_path: string;
  setup_type: 'download' | 'metadata';
  target_backend_id?: string;
  expected_version?: number;
}

export interface AddDirectoryResponse {
  success: boolean;
  message: string;
  directory_path: string | null;
  propagation?: StorageConfigPropagation | null;
}

export interface RemoveDirectoryRequest {
  directory_path: string;
  setup_type: 'download' | 'metadata';
  target_backend_id?: string;
  expected_version?: number;
}

export interface RemoveDirectoryResponse {
  success: boolean;
  message: string;
  propagation?: StorageConfigPropagation | null;
}

export interface DirectoryConfigInfo {
  path: string;
  setup_type: 'download' | 'metadata';
  minimum_space: number;
  store: boolean;
  scan_existing: boolean;
  overflow: boolean;
}

export interface DirectoryConfigRequest {
  directory_path: string;
  setup_type: 'download' | 'metadata';
  minimum_space?: number;
  store?: boolean;
  scan_existing?: boolean;
  overflow?: boolean;
  target_backend_id?: string;
  expected_version?: number;
}

export interface DirectoryConfigResponse {
  success: boolean;
  message: string;
  config: DirectoryConfigInfo | null;
  propagation?: StorageConfigPropagation | null;
}

export interface WorkerInfo {
  worker_id: string;
  status: 'idle' | 'busy' | 'offline';
  current_job: string | null;
  jobs_completed: number;
}

export interface BackendDiskStats {
  device: string;
  mount_point: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  percent_used: number;
  read_bytes_per_sec: number;
  write_bytes_per_sec: number;
}

export interface BackendSystemStats {
  timestamp: string;
  cpu_percent: number;
  cpu_count: number;
  memory_total: number;
  memory_used: number;
  memory_free: number;
  memory_percent: number;
  disks: BackendDiskStats[];
}

export interface BackendStatusResponse {
  backend_id: string;
  distributed_mode: boolean;
  redis_connected: boolean;
  worker_count: number;
  active_workers: number;
  pending_jobs: number;
  workers: WorkerInfo[];
  system_stats?: BackendSystemStats | null;
  max_workers?: number | null;
}

export interface RemoteBackendDrive {
  path: string;
  device: string;
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  percent_used: number;
  configured_directories: string[];
}

export interface RemoteBackendWorker {
  worker_id: string;
  status: string;
  current_job: string | null;
  jobs_completed: number;
}

export interface RemoteBackendInfo {
  backend_id: string;
  hostname: string;
  status: string;
  last_seen: string;
  max_workers: number;
  version: string;
  drives: RemoteBackendDrive[];
  workers: RemoteBackendWorker[];
  active_workers: number;
  pending_jobs: number;
  /** Shared by every backend on the same database. */
  cluster_id?: string | null;
  /** Where other machines reach this backend (USR_PUBLIC_API_URL). */
  api_url?: string | null;
  /** The machine's network address (for SSH), when the backend knows it. */
  address?: string | null;
}

export interface AllBackendsResponse {
  success: boolean;
  local_backend_id: string;
  local_hostname: string;
  backends: RemoteBackendInfo[];
  total_backends: number;
}

export type RuntimePowerAction = 'restart' | 'shutdown';

export type RuntimeServiceTarget =
  | 'api'
  | 'database_writer'
  | 'worker_pool'
  | 'plugins'
  | 'webui';

export interface RuntimePowerRequest {
  action: RuntimePowerAction;
  targets?: RuntimeServiceTarget[];
}

export interface RuntimePowerResponse {
  action: RuntimePowerAction;
  status: 'accepted';
  supervisor_pid: number;
  targets?: RuntimeServiceTarget[];
}

export interface DatabaseTableOverview {
  table_name: string;
  live_tuples: number;
  dead_tuples: number;
  total_bytes: number;
  table_bytes: number;
  index_bytes: number;
  last_vacuum: string | null;
  last_autovacuum: string | null;
  last_analyze: string | null;
  last_autoanalyze: string | null;
}

export interface DatabaseOverview {
  site: string;
  database_name: string;
  schema_name: string;
  host: string;
  port: number | null;
  is_connected: boolean;
  status: 'healthy' | 'warning' | 'offline';
  total_size_bytes: number;
  total_size_pretty: string;
  table_count: number;
  total_live_tuples: number;
  /** True when row counts are PostgreSQL estimates rather than exact counts. */
  row_counts_estimated?: boolean;
  total_dead_tuples: number;
  bloat_percent: number;
  last_vacuum: string | null;
  last_analyze: string | null;
  tables: DatabaseTableOverview[];
}

export interface DatabaseActiveOperation {
  id: string;
  operation_type: 'vacuum' | 'analyze' | 'reindex';
  site: string;
  table_name?: string | null;
  current_table?: string | null;
  tables_completed: number;
  tables_total: number;
  phase?: string | null;
  progress_percent?: number | null;
  heap_blks_total?: number | null;
  heap_blks_scanned?: number | null;
  heap_blks_vacuumed?: number | null;
  started_at: string;
  duration_seconds: number;
  status: 'running' | 'completed' | 'failed';
  message?: string | null;
}

export interface DatabaseOverviewResponse {
  success: boolean;
  backend_id: string;
  databases: DatabaseOverview[];
  total_databases: number;
  total_size_bytes: number;
  server_version: string | null;
  active_operations?: DatabaseActiveOperation[];
}

export interface DatabaseVacuumRequest {
  site?: string;
  table_name?: string;
  full?: boolean;
  analyze?: boolean;
  freeze?: boolean;
}

export interface DatabaseVacuumResponse {
  success: boolean;
  message: string;
  site: string;
  table_name: string | null;
  mode: string;
  duration_seconds: number;
  size_before_bytes?: number | null;
  size_after_bytes?: number | null;
}

export interface DatabaseAnalyzeRequest {
  site?: string;
  table_name?: string;
}

export interface DatabaseAnalyzeResponse {
  success: boolean;
  message: string;
  site: string;
  table_name: string | null;
  duration_seconds: number;
}

export interface DatabaseReindexRequest {
  site?: string;
  table_name?: string;
  concurrently?: boolean;
}

export interface DatabaseReindexResponse {
  success: boolean;
  message: string;
  site: string;
  table_name: string | null;
  duration_seconds: number;
}
