import type { Job } from './jobs';

export type MPSProxyMode = 'none' | 'unassigned_only' | 'all' | 'custom';

export interface MPSBatchRecommendation {
  batch_size: number;
  label: string;
  reason: string;
}

export interface MPSAnalyzeRequest {
  site: string;
  start_id?: number | null;
  end_id?: number | null;
  ignore_missing_ids?: boolean;
  include_invalid?: boolean;
  invalid_last_checked_older_than_hours?: number | null;
  include_existing_users?: boolean;
  existing_last_checked_older_than_hours?: number | null;
  candidate_offset?: number;
  batch_size?: number | null;
  missing_preview_limit?: number;
  range_preview_limit?: number;
  bounded?: boolean;
  density_resolution?: number;
  routes?: number;
}

export interface MPSMissingRange {
  start_id: number;
  end_id: number;
  count: number;
}

export interface MPSDensityBucket {
  start_id: number;
  end_id: number;
  missing_count: number | null;
  invalid_count: number | null;
  existing_count: number | null;
  candidate_count: number | null;
  is_exact: boolean;
}

export interface MPSDensePocket {
  start_id: number;
  end_id: number;
  candidate_count: number;
  density_percentage: number;
  missing_count: number;
  invalid_count: number;
  existing_count: number;
}

export interface MPSAnalyzeResponse {
  site: string;
  database_min_id: number | null;
  database_max_id: number | null;
  start_id: number;
  end_id: number;
  range_size: number;
  existing_user_count: number;
  invalid_user_count: number;
  invalid_table_ready: boolean;
  invalid_eligible_count: number;
  existing_eligible_count: number;
  missing_count: number;
  candidate_count: number;
  missing_range_count: number;
  missing_range_count_exact?: boolean;
  missing_ranges_truncated: boolean;
  missing_ranges: MPSMissingRange[];
  missing_ids_preview: number[];
  frontier_range?: MPSMissingRange | null;
  candidate_ranges_preview: MPSMissingRange[];
  candidate_ids_preview: number[];
  candidate_preview_truncated: boolean;
  candidate_range_count?: number | null;
  candidate_ranges_truncated?: boolean;
  density_resolution?: number;
  density_buckets?: MPSDensityBucket[];
  density_is_exact?: boolean;
  dense_pockets?: MPSDensePocket[];
  candidate_offset: number;
  planned_batch_size: number | null;
  planned_candidate_count: number;
  remaining_candidate_count: number;
  next_candidate_offset: number | null;
  has_next_batch: boolean;
  recommended_batch_size: number | null;
  adaptive_batch_size?: number | null;
  batch_recommendations: MPSBatchRecommendation[];
  warnings: string[];
  requires_confirmation: boolean;
  population_estimate?: number | null;
  population_confidence_interval?: [number, number] | null;
  highest_id_confidence_interval?: [number, number] | null;
  density_estimate?: number | null;
  adaptive_discovery_performed?: boolean;
}

export interface MPSSiteBoundsResponse {
  site: string;
  database_min_id: number | null;
  database_max_id: number | null;
}

export interface MPSBoundaryDiscoveryRequest {
  site: string;
  min_id?: number;
  max_id_ceiling?: number;
  max_probes?: number;
  probe_multiplier?: number;
  samples_per_step?: number;
  refinement_steps?: number;
  confidence_level?: number;
  target_margin_of_error?: number;
}

export interface MPSProbeObservation {
  user_id: number;
  is_valid: boolean;
  phase: string;
  timestamp?: number;
}

export interface MPSBoundaryDiscoveryResponse {
  site: string;
  discovered_start_id: number;
  discovered_end_id: number;
  highest_observed_id: number | null;
  lowest_observed_id: number | null;
  estimated_total_users: number;
  population_confidence_interval: [number, number];
  estimated_density: number;
  density_margin_of_error: number;
  confidence_level: number;
  highest_id_confidence_interval: [number, number];
  total_probes_used: number;
  valid_probes_count: number;
  warnings: string[];
  observations?: MPSProbeObservation[];
}

export interface MPSCreateJobRequest {
  site: string;
  start_id?: number | null;
  end_id?: number | null;
  ignore_missing_ids?: boolean;
  include_invalid?: boolean;
  invalid_last_checked_older_than_hours?: number | null;
  include_existing_users?: boolean;
  existing_last_checked_older_than_hours?: number | null;
  candidate_offset?: number;
  max_profiles?: number | null;
  use_proxies?: boolean;
  proxy_mode?: MPSProxyMode;
  proxy_urls?: string[] | null;
  include_direct_connection?: boolean;
  max_route_hops?: number;
  conclusive_miss_threshold?: number;
  job_name?: string | null;
  created_by?: string;
  /** Analyzed candidate total; display-only remaining count for finite batches. */
  candidate_count_hint?: number | null;
}

export interface MPSCreateJobResponse {
  job: Job;
  candidate_offset: number;
  selected_profiles: number;
  total_missing_in_range: number;
  total_invalid_eligible_in_range: number;
  total_existing_eligible_in_range: number;
  total_candidates_in_range: number;
  remaining_candidate_count: number;
  next_candidate_offset: number | null;
  has_next_batch: boolean;
  recommended_batch_size: number | null;
  adaptive_batch_size?: number | null;
  next_batch_size: number | null;
  batch_recommendations: MPSBatchRecommendation[];
  warnings: string[];
  proxies_configured: number;
  proxies_used: number;
  direct_connection_included: boolean;
  proxy_mode: MPSProxyMode;
  proxy_urls_preview?: string[];
}

export interface MPSProxyPreviewRequest {
  site: string;
  use_proxies?: boolean;
  proxy_mode?: MPSProxyMode;
  proxy_urls?: string[] | null;
  include_direct_connection?: boolean;
}

export interface MPSProxyPreviewResponse {
  site: string;
  use_proxies: boolean;
  proxy_mode: MPSProxyMode;
  proxies_configured: number;
  proxies_used: number;
  direct_connection_included: boolean;
  proxy_urls: string[];
  proxy_capacity?: number;
}
