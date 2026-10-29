import type { DRMConfig, StagingDirectory } from './setup';
import type { StorageConfigPropagation } from './system';

export interface RedisSettings {
  host: string;
  port: number;
  db: number;
  password: string | null;
  enabled: boolean;
  completed_job_retention_seconds?: number;
}

export interface BackendSettings {
  backend_id: string | null;
  execution_mode: 'local' | 'distributed' | 'redis_metrics';
  /** Also serve HTTPS for other machines (WebUIs joining the cluster). Read at startup. */
  share_https?: boolean;
  https_port?: number;
  /** The address other machines reach this host at; empty detects its LAN address. */
  advertise_host?: string | null;
}

export interface JobExecutionSettings {
  window_max_tasks: number | null;
  refill_ready_threshold: number | null;
  event_retention_hours: number;
  task_history_retention_days: number;
  receipt_retention_minutes: number;
  terminal_reconcile_interval_seconds: number;
  terminal_reconcile_min_age_seconds: number;
  terminal_reconcile_batch_size: number;
  completed_job_retention_seconds: number;
  completed_job_retention_batch_size: number;
  task_archive_batch_size?: number;
  mps_replacement_batch_size?: number;
  ledger_planner_batch?: number;
}

export interface WorkerPoolSettings {
  enabled: boolean;
  size: number;
  sites: string[];
  max_claimed_jobs: number;
  /** Null derives per-worker slots from proxy capacity. */
  task_concurrency?: number | null;
  /** Null uses the ledger batch size. */
  claim_batch_size?: number | null;
}

export interface DownloadConcurrencySettings {
  max_concurrency: number;
  per_domain_concurrency: number;
  head_concurrency: number;
  buffer_size_bytes: number;
}

export interface ProxySettings {
  url: string;
  username: string | null;
  password: string | null;
  enabled: boolean;
  max_connections: number;
  downloads: DownloadConcurrencySettings | null;
  guest_lookup_timeout?: number | null;
}

export interface NetworkSettings {
  max_connections: number;
  proxies: ProxySettings[];
  proxy_fallback: boolean;
  guest_route_rate_limit: number;
  guest_session_pool: boolean;
  guest_lookup_timeout?: number;
  guest_route_timeout?: number;
  downloads: DownloadConcurrencySettings;
}

export interface DriveSettings {
  minimum_space: number;
  store: boolean;
  scan_existing: boolean;
  overflow: boolean;
  directories: string[];
}

export interface DownloadSetupSettings {
  drives: DriveSettings[];
  alt_directory_formats: string[];
  site_directory_aliases?: Record<string, string[]>;
  staging_directories: StagingDirectory[];
  directory_format: string;
  filename_format: string;
  text_length: number;
  date_format: string;
  overwrite_files: boolean;
}

export interface MetadataSetupSettings {
  drives: DriveSettings[];
  directory_format: string;
}

export interface SiteSettings {
  blacklists: string[];
}

export interface SiteApiSettings {
  onlyfans: SiteSettings;
  fansly: SiteSettings;
}

export interface SettingsResponse {
  hostname: string;
  infinite_loop?: boolean;
  exit_on_completion?: boolean;
  configuration_source?: string;
  runtime_readonly_fields?: string[];
  runtime_restart_required?: boolean;
  worker_pool: WorkerPoolSettings;
  backend: BackendSettings;
  job_execution: JobExecutionSettings;
  redis: RedisSettings;
  network: NetworkSettings;
  download_setup: DownloadSetupSettings;
  metadata_setup: MetadataSetupSettings;
  previews_directory: string | null;
  subtitles_directory: string | null;
  drm: DRMConfig;
  sites: SiteApiSettings;
  config_path: string | null;
  is_configured: boolean;
  config_scope?: string | null;
  config_version?: number | null;
  config_updated_at?: string | null;
  storage_propagation?: StorageConfigPropagation | null;
}

export interface SettingsUpdate extends Partial<SettingsResponse> {
  expected_version?: number;
  actor_backend_id?: number | null;
  request_id?: string | null;
}

export interface SettingsConflictDetail {
  message: string;
  current?: SettingsResponse | Record<string, unknown> | null;
  current_version?: number | null;
  current_updated_at?: string | null;
  attempted_patch?: Record<string, unknown>;
  conflicting_fields?: string[];
}

export interface TestRedisConnectionRequest {
  host: string;
  port: number;
  db: number;
  password: string | null;
}

export interface TestRedisConnectionResponse {
  success: boolean;
  message: string;
  latency_ms: number | null;
}

export interface DBSettingRecord {
  id: number;
  backend: string;
  key: string;
  value: string;
  is_secret: boolean;
  description?: string | null;
  version: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DBSettingUpsertRequest {
  backend: string;
  key: string;
  value: string;
  is_secret?: boolean;
  description?: string | null;
  expected_version?: number;
  actor_backend_id?: number | null;
  request_id?: string | null;
}

export interface DBSettingPatchRequest {
  backend?: string;
  key?: string;
  value?: string;
  is_secret?: boolean;
  description?: string | null;
  expected_version?: number;
  actor_backend_id?: number | null;
  request_id?: string | null;
}

export interface DeleteSettingResponse {
  success: boolean;
  id: number;
}

export interface BackendInventoryRecord {
  id: number;
  backend_name: string;
  hostname: string;
  local_ip?: string | null;
  settings_id: number;
  settings_scope?: string | null;
  settings_key?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface BackendInventoryUpsertRequest {
  backend_name: string;
  hostname: string;
  local_ip?: string | null;
  settings_id: number;
}

export interface BackendInventoryPatchRequest {
  backend_name?: string;
  hostname?: string;
  local_ip?: string | null;
  settings_id?: number;
}

export interface RemoteSettingsResponse {
  backend_id: string;
  settings: SettingsResponse | null;
  error: string | null;
}

export interface RemoteUpdateResponse {
  backend_id: string;
  success: boolean;
  message: string;
}

export interface SyncAllResponse {
  success: boolean;
  message: string;
  backends_updated: string[];
  backends_failed: string[];
}
