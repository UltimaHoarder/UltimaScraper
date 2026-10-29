export interface SetupStatusResponse {
  is_configured: boolean;
  has_config: boolean;
  has_database: boolean;
  data_directory: string;
  startup_id: string;
  /** BACKEND_ID pinned by the deployment; setup cannot choose another. */
  backend_id?: string | null;
  /** host:port of the Redis the deployment configures, if any. */
  redis_target?: string | null;
}

export interface FilesystemEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

export interface FilesystemListing {
  path: string;
  parent: string | null;
  writable: boolean;
  entries: FilesystemEntry[];
  truncated: boolean;
}

export interface SSHConnection {
  username?: string | null;
  private_key_filepath?: string | null;
  private_key_password?: string | null;
  host?: string | null;
  port: number;
  active: boolean;
}

export interface DatabaseConnectionRequest {
  host: string;
  port: number;
  name: string;
  username: string;
  password: string;
  ssh?: SSHConnection;
}

export interface DatabaseConnectionResponse {
  success: boolean;
  message: string;
  latency_ms: number | null;
}

export interface RedisConnectionRequest {
  host: string;
  port: number;
  db: number;
  password?: string;
  enabled: boolean;
}

export interface RedisConnectionResponse {
  success: boolean;
  message: string;
  latency_ms: number | null;
}

export interface DRMConfig {
  device_client_blob_filepath?: string | null;
  device_private_key_filepath?: string | null;
}

export const STAGING_USAGES = ['downloads', 'merge', 'drm'] as const;

export type StagingUsage = (typeof STAGING_USAGES)[number];

export const STAGING_POLICIES = ['drm_only', 'prefer'] as const;

export type StagingPolicy = (typeof STAGING_POLICIES)[number];

export const STAGING_POLICY_LABELS: Record<StagingPolicy, string> = {
  drm_only: 'Use this staging directory only for DRM items',
  prefer: 'Prefer this directory, in list order, while the item fits',
};

export interface StagingDirectory {
  path: string;
  usage: StagingUsage[];
  policy: StagingPolicy[];
  /** Headroom never handed to staged files (keeps RAM free on tmpfs). */
  min_free_bytes?: number;
}

/** A proxy added in setup, as the network page's form describes it. */
export interface SetupProxy {
  url: string;
  username?: string | null;
  password?: string | null;
  max_connections: number;
  group?: string | null;
}

export interface NetworkConfig {
  max_connections: number;
  proxies: SetupProxy[];
  proxy_fallback: boolean;
}

export interface SetupAuthRequest {
  site: string;
  curl_command: string;
  proxy_id?: string | null;
}

export interface InitialSetupRequest {
  database?: DatabaseConnectionRequest | null;
  redis?: RedisConnectionRequest | null;
  drm?: DRMConfig | null;
  network?: NetworkConfig | null;
  auths?: SetupAuthRequest[];
  download_directories?: string[];
  staging_directories?: StagingDirectory[];
  hostname?: string | null;
}

export interface InitialSetupResponse {
  success: boolean;
  message: string;
  is_configured: boolean;
  /** Accounts that could not be added; setup itself still completed. */
  auth_errors?: string[];
}

export interface StartupMigrationPreviewResponse {
  status: 'ready' | 'no_changes' | 'requires_database' | 'completed' | 'error';
  outcome?: 'checked' | 'applied' | 'skipped' | null;
  message: string;
  preview_id: string | null;
  revision: string | null;
  filename: string | null;
  diff: string | null;
  has_changes: boolean;
  can_apply: boolean;
  output: string[];
}

export interface StartupMigrationApplyRequest {
  preview_id?: string | null;
}

export interface StartupMigrationActionResponse {
  success: boolean;
  message: string;
  output: string[];
}
