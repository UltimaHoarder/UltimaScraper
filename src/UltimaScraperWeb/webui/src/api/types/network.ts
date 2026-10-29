export interface GeolocationData {
  ip: string;
  success: boolean;
  type?: string;
  continent?: string;
  continent_code?: string;
  country?: string;
  country_code?: string;
  region?: string;
  region_code?: string;
  city?: string;
  latitude?: number;
  longitude?: number;
  is_eu?: boolean;
  postal?: string;
  calling_code?: string;
  capital?: string;
  borders?: string;
  flag?: {
    img?: string;
    emoji?: string;
    emoji_unicode?: string;
  };
  connection?: {
    asn?: number;
    org?: string;
    isp?: string;
    domain?: string;
  };
  timezone?: {
    id?: string;
    abbr?: string;
    is_dst?: boolean;
    offset?: number;
    utc?: string;
    current_time?: string;
  };
}

export interface NetworkProxy {
  id: string;
  url: string;
  username: string | null;
  enabled?: boolean;
  max_connections: number;
  group?: string | null;
  assigned_auths: number[];
  active_assigned_count?: number;
  geolocation?: GeolocationData | null;
  guest_lookup_timeout?: number | null;
}

export interface AuthAccount {
  id: number;
  site: string;
  username: string | null;
  status: string;
  active: boolean;
}

export interface ProxyAnalyzerResult {
  concurrency: number;
  max_connections: number;
  requests: number;
  successes: number;
  errors: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  max_latency_ms: number;
  min_latency_ms: number;
  jitter_ms: number;
  avg_ttfb_ms: number;
  throughput_mbps: number;
  efficiency_score: number;
  status_counts: Record<string, number>;
  head_status_counts: Record<string, number> | null;
  download_status_counts: Record<string, number> | null;
  proxy_ip: string | null;
  ip_consistent: boolean;
  geolocation: GeolocationData | null;
}

export interface ProxyAnalyzerResponse {
  success: boolean;
  message: string;
  results: ProxyAnalyzerResult[];
  recommended_concurrency: number | null;
  recommended_connections: number | null;
  best_configs: Record<number, { connections: number; efficiency: number }>;
  warmup_ip: string | null;
  warmup_latency_ms: number | null;
}

export type AnalyzerTab =
  | 'results'
  | 'settings'
  | 'compare'
  | 'media-pool'
  | 'geolocation';

export type ProxyTestStatus = 'idle' | 'testing' | 'success' | 'error';

export interface AnalyzerErrorDetail {
  endpoint: string;
  errors: Record<string, number>;
}

export interface AddNetworkProxyRequest {
  url: string;
  username?: string;
  password?: string;
  enabled?: boolean;
  max_connections?: number;
  group?: string | null;
  guest_lookup_timeout?: number | null;
}

export interface UpdateNetworkProxyRequest {
  username?: string;
  password?: string;
  enabled?: boolean;
  max_connections?: number;
  max_concurrency?: number | null;
  group?: string | null;
  guest_lookup_timeout?: number | null;
}

export interface UpdateNetworkProxyResponse {
  status: string;
  message: string;
  username: string | null;
  password: string;
  enabled: boolean;
  max_connections: number;
  max_concurrency: number;
  group?: string | null;
  guest_lookup_timeout?: number | null;
}

export interface BulkProxyItem {
  url: string;
  username?: string | null;
  password?: string | null;
  enabled?: boolean;
  max_connections?: number;
  group?: string | null;
}

export interface BulkAddProxiesRequest {
  proxies?: BulkProxyItem[];
  raw_text?: string | null;
  default_group?: string | null;
  overwrite?: boolean;
}

export interface BulkAddProxiesResponse {
  status: string;
  added: NetworkProxy[];
  updated: NetworkProxy[];
  skipped: string[];
  errors: string[];
}

export interface BulkSyncProxiesRequest {
  proxies?: BulkProxyItem[];
  raw_text?: string | null;
  default_group?: string | null;
  target_group?: string | null;
}

export interface BulkSyncProxiesResponse {
  status: string;
  added: NetworkProxy[];
  kept: NetworkProxy[];
  deleted: string[];
  errors: string[];
  message: string;
  target_group?: string | null;
}

export interface BulkTestItem {
  url: string;
  username?: string | null;
  password?: string | null;
}

export interface BulkTestProxiesRequest {
  proxies: BulkTestItem[];
  timeout_seconds?: number;
  concurrency?: number;
}

export interface BulkTestItemResult {
  url: string;
  success: boolean;
  message: string;
  latency_ms?: number | null;
}

export interface BulkTestProxiesResponse {
  results: BulkTestItemResult[];
}

export interface BulkAssignGroupRequest {
  proxy_urls: string[];
  group?: string | null;
}

export interface BulkAssignGroupResponse {
  status: string;
  message: string;
  updated_count: number;
  group?: string | null;
}

export interface GroupSettingsUpdateRequest {
  max_connections?: number | null;
  max_concurrency?: number | null;
  enabled?: boolean | null;
  /** Stored on the group; null clears it. A proxy's own timeout still wins. */
  guest_lookup_timeout?: number | null;
}

export interface GroupSettingsResponse {
  group: string;
  guest_lookup_timeout: number | null;
}

export interface GroupSettingsUpdateResponse {
  status: string;
  message: string;
  updated_count: number;
  group: string;
  max_connections?: number | null;
  max_concurrency?: number | null;
  enabled?: boolean | null;
  guest_lookup_timeout?: number | null;
}

export interface BulkProxyStateRequest {
  proxy_urls: string[];
  enabled: boolean;
}

export interface BulkProxyStateResponse {
  status: string;
  message: string;
  updated_count: number;
  enabled: boolean;
}

export interface BulkProxyDeleteRequest {
  proxy_urls: string[];
}

export interface BulkProxyDeleteResponse {
  status: string;
  message: string;
  deleted_count: number;
}

export interface BulkProxyEditRequest {
  proxy_urls: string[];
  max_connections?: number | null;
  max_concurrency?: number | null;
  guest_lookup_timeout?: number | null;
}

export interface BulkProxyEditResponse {
  status: string;
  message: string;
  updated_count: number;
  max_connections?: number | null;
  max_concurrency?: number | null;
  guest_lookup_timeout?: number | null;
}

export interface ProxyAssignmentRequest {
  auth_id: number;
  proxy_url: string | null;
}

export interface ProxyTestResponse {
  success: boolean;
  message: string;
  latency_ms?: number | null;
}

export interface ProxyMediaPoolResponse {
  success: boolean;
  urls: string[];
  message: string | null;
}

export interface ProxyAnalysisStreamEvent {
  type?: string;
  ip?: string;
  concurrency?: number;
  connections?: number;
  requests?: number;
  result?: ProxyAnalyzerResult;
  recommended_concurrency?: number | null;
  recommended_connections?: number | null;
}

export const DIRECT_CONNECTION_PROXY: NetworkProxy = {
  id: 'direct',
  url: 'direct',
  username: null,
  enabled: true,
  max_connections: -1,
  assigned_auths: [],
};
