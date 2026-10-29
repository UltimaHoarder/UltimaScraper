import { backendUrl, getApiBaseUrl } from '../http';

export interface TaskSummary {
  task_type: string;
  content_type: string | null;
  status: string;
  username: string | null;
  site: string | null;
  auth_id: number | null;
  items_processed: number;
  items_total: number | null;
}

/** Free-form planner metadata; only some job payloads include it. */
export type JobMetadata = Record<string, unknown>;

export interface Job {
  deletion_progress?: { rows?: number; table?: string; completed_stages?: number; total_stages?: number; partitions_dropped?: number; error?: string } | null;
  job_id: string;
  execution_engine?: string | null;
  job_name: string;
  job_type?: string | null;
  site?: string | null;
  status: 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled' | 'deleting';
  priority?: number;
  worker_id?: string | null;
  created_at: string;
  updated_at: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  task_count: number;
  completed_tasks: number;
  failed_tasks: number;
  tasks?: TaskSummary[];
  task_stats?: TaskStats;
  error_stats?: JobErrorStats;
  created_by?: string;
  is_scheduled?: boolean;
  scheduled_for?: string | null;
  interval_seconds?: number | null;
  cron?: string | null;
  run_count?: number;
  last_ran_at?: string | null;
  last_activity_at?: string | null;
  materialization_status?: string | null;
  materialized_tasks?: number | null;
  materialization_total?: number | null;
  materialization_error?: string | null;
  metadata?: JobMetadata | null;
  args?: Record<string, unknown> | null;
  duration_seconds?: number | null;
}

export interface JobListResponse {
  jobs: Job[];
  total: number;
  page: number;
  page_size: number;
  available_types?: string[];
  available_owners?: string[];
}

export interface QueueStats {
  instance_id: string;
  distributed_mode: boolean;
  transitioning: boolean;
  local_queue_size: number;
  redis_queue_size: number;
  active_queue_type: string;
  recovery_interval: number;
  next_recovery_seconds: number | null;
  last_recovery_at: string | null;
}

export interface HealthResponse {
  status: string;
  instance_id: string;
  distributed_mode: boolean;
  transitioning: boolean;
  queue_type: string;
  queue_size: number;
  redis_connected: boolean;
}

export interface TaskPayload {
  task_type: string;
  params: Record<string, unknown>;
}

export interface JobScheduleRequest {
  scheduled_for?: string;
  interval_seconds?: number;
  cron?: string;
  start_immediately?: boolean;
}

export interface CreateJobRequest {
  job_name: string;
  tasks: TaskPayload[];
  created_by: string;
  schedule?: JobScheduleRequest;
  ignore_space_requirements?: boolean;
  save_as_template?: boolean;
  template_name?: string;
  template_description?: string;
}

export interface UpdateJobRequest {
  job_name?: string;
  schedule?: JobScheduleRequest;
  tasks?: TaskPayload[];
}

export interface CreateJobTemplateRequest {
  name: string;
  description?: string;
  created_by?: string;
}

export interface TemplateParameterPayload {
  name: string;
  type: string;
  required: boolean;
  default: unknown;
  description: string;
  choices: unknown[] | null;
}

export interface JobTemplateTaskPayload {
  name: string | null;
  task_type: string;
  site_name_template: string;
  user_id_template: string;
  content_type_template: string;
  payload_template: Record<string, unknown>;
  capabilities: string[];
  depends_on: string[];
  ip_lock_key_template: string | null;
  max_attempts: number | null;
  dedupe_override: boolean;
}

export interface JobTemplateResponse {
  template_id: string;
  name: string;
  description: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  default_priority: number;
  job_name_template: string | null;
  parameters: TemplateParameterPayload[];
  tasks: JobTemplateTaskPayload[];
}

export interface TemplateEntry {
  username: string;
  auth_id: number;
}

export interface InstantiateTemplateRequest {
  parameter_values: Record<string, unknown>;
  job_name?: string;
  created_by?: string;
  auth_id?: number;
  entries?: TemplateEntry[];
  schedule?: JobScheduleRequest;
  ignore_space_requirements?: boolean;
}

export interface TaskParameterOption {
  label: string;
  value: string;
}

export interface TaskParameter {
  name: string;
  label: string;
  param_type:
    | 'text'
    | 'number'
    | 'boolean'
    | 'select'
    | 'multiselect'
    | 'username'
    | 'user_id'
    | 'path';
  required: boolean;
  default: unknown;
  description: string;
  options: TaskParameterOption[];
  placeholder: string;
  min_value: number | null;
  max_value: number | null;
}

export interface TaskDefinition {
  task_id: string;
  name: string;
  category: string;
  description: string;
  parameters: TaskParameter[];
  keywords: string[];
}

export interface TaskRouteHop {
  hop_number: number;
  url: string | null;
  masked_url: string;
  is_direct: boolean;
  status: 'used' | 'failed' | 'untried' | 'pending';
  role_label: string;
  country?: string | null;
  country_code?: string | null;
  flag_emoji?: string | null;
  group?: string | null;
}

export interface TaskDetail {
  message?: string | null;
  task_id: string | null;
  task_type: string;
  status: string;
  site: string | null;
  username: string | null;
  content_type: string | null;
  payload?: Record<string, unknown> | null;
  worker_id?: string | null;
  started_at: string | null;
  completed_at: string | null;
  progress: number;
  items_processed: number;
  items_total: number | null;
  error: string | null;
  result?: Record<string, unknown> | null;
  proxy_url?: string | null;
  proxy_routes?: Array<string | null> | null;
  proxy_hop_used?: number | null;
  proxy_hops?: TaskRouteHop[] | null;
  duration?: number | null;
}

export interface TaskStats {
  total: number;
  ready: number;
  blocked: number;
  inflight: number;
  deferred: number;
  completed: number;
  failed: number;
  task_type_counts: Record<string, number>;
}

export interface MPSRefillTraceEvent {
  stage: string;
  cycle: number;
  timestamp_ms: number;
  ready: number;
  inflight: number;
  completed: number;
  failed: number;
  window_end: number;
  task_count?: number | null;
  ready_added?: number | null;
  archived_tasks?: number | null;
  admitted_tasks?: number | null;
  archive_ms?: number | null;
  window_accounting_ms?: number | null;
  refill_ms?: number | null;
  pass_ms?: number | null;
  window_start?: number | null;
  reason?: string | null;
  controls?: Record<string, number | string | boolean | null> | null;
}

export interface JobRuntimeSample {
  cursor: string;
  timestamp_ms: number;
  total: number;
  ready: number;
  inflight: number;
  completed: number;
  failed: number;
}

export interface JobRuntimeSamplesPage {
  samples: JobRuntimeSample[];
  next_after_id: string | null;
  has_more: boolean;
}

export interface JobErrorStats {
  total: number;
  groups: Record<string, number>;
}

export interface JobRouteLookupStat {
  route_attempts: number;
  lookup_observations: number;
  lookup_found_count?: number | null;
  lookup_not_found_count?: number | null;
  lookup_error_count?: number | null;
  lookup_timeout_count?: number | null;
  lookup_cancelled_count?: number | null;
  guest_init_failure_count?: number | null;
  guest_init_cancelled_count?: number | null;
  primary_selected_count?: number | null;
  hedge_selected_count?: number | null;
  fallback_selected_count?: number | null;
  deferred_selected_count?: number | null;
  healthy_selected_count?: number | null;
  retry_selected_count?: number | null;

  mean_route_active_ms: number;
  mean_guest_init_ms: number;
  mean_lookup_ms: number | null;
}

export interface JobRuntimeTelemetry {
  version: number;
  scope: 'full_job_aggregate' | string;
  task_count: number;
  succeeded_tasks: number;
  failed_tasks: number;
  first_started_at: string | null;
  last_finished_at: string | null;
  active_window_ms: number;
  task_duration_sum_ms: number;
  mean_task_duration_ms: number | null;
  mean_queue_wait_ms: number | null;
  mean_setup_ms: number | null;
  setup_subphases?: Record<string, { mean_ms: number; count: number; mean_ms_per_observation?: number }> | null;
  mean_handler_ms: number | null;
  mean_handler_exclusive_ms: number | null;
  guest_auth_stats?: Record<string, { ms: number; count: number }>;
  terminal_stats?: Record<string, { ms: number; count: number }>;
  ledger_stats?: Record<string, { ms: number; count: number }>;
  mean_handler_guest_init_ms?: number | null;
  handler_guest_init_count?: number;
  mean_handler_initial_lookup_ms?: number | null;
  handler_initial_lookup_count?: number;
  mean_handler_refresh_api_ms?: number | null;
  handler_refresh_api_count?: number;
  mean_handler_fallback_retry_ms?: number | null;
  handler_fallback_retry_count?: number;
  mean_handler_serialization_ms?: number | null;
  handler_serialization_count?: number;
  mean_writer_ms: number | null;
  mean_post_ms: number | null;
  mean_release_ms: number | null;
  mean_claim_wait_ms: number | null;
  mean_writer_admission_ms: number | null;
  mean_writer_admission_serialization_ms?: number | null;
  mean_writer_admission_capacity_wait_ms?: number | null;
  mean_writer_admission_redis_ms?: number | null;
  mean_writer_admission_overhead_detail_ms?: number | null;
  mean_writer_queue_ms: number | null;
  mean_writer_execution_ms: number | null;
  mean_writer_commit_ms: number | null;
  mean_writer_overhead_ms: number | null;
  mean_writer_batch_peer_work_ms?: number | null;
  mean_writer_delivery_ms: number | null;
  mean_writer_result_publication_ms?: number | null;
  mean_writer_result_observation_ms?: number | null;
  mean_writer_result_delivery_residual_ms?: number | null;
  writer_result_delivery_split_coverage_ratio?: number | null;
  writer_result_cache_hits?: number;
  writer_receipt_fallbacks?: number;
  writer_result_cache_hit_ratio?: number | null;
  writer_split_missing_reasons?: Record<string, number>;
  writer_operation_stats?: Record<string, {
    count: number;
    mean_batch_commands: number;
    mean_batch_wall_ms: number;
    receipt_phases_count?: number;
    mean_receipt_lock_ms?: number;
    mean_receipt_read_ms?: number;
    mean_write_fence_ms?: number;
  }>;
  writer_domain_stats?: Record<string, {
    count: number;
    mean_batch_commands: number;
    mean_batch_wall_ms: number;
    receipt_phases_count?: number;
    mean_receipt_lock_ms?: number;
    mean_receipt_read_ms?: number;
    mean_write_fence_ms?: number;
  }>;
  writer_timed_submits: number;
  writer_timing_coverage_ratio: number | null;
  mean_writer_connection_checkout_ms: number | null;
  mean_writer_receipt_lookup_ms: number | null;
  mean_writer_receipt_finalize_ms: number | null;
  mean_writer_payload_ms: number | null;
  mean_writer_user_row_ms: number | null;
  mean_writer_alias_ms: number | null;
  mean_writer_authority_ms: number | null;
  writer_authority_rows_examined?: number;
  writer_authority_rows_skipped?: number;
  writer_authority_rows_upserted?: number;
  mean_writer_profile_ms: number | null;
  mean_writer_social_ms: number | null;
  mean_writer_flush_ms: number | null;
  mean_writer_queue_commands_at_start: number | null;
  max_writer_queue_commands_at_start: number;
  mean_writer_queue_bytes_at_start: number | null;
  max_writer_queue_bytes_at_start: number;
  mean_writer_active_lanes: number | null;
  max_writer_active_lanes: number;
  mean_writer_batch_commands: number | null;
  mean_writer_batch_fill_ratio?: number | null;
  mean_writer_lane_idle_ms?: number | null;
  mean_writer_lane_predecessor_wait_ms?: number | null;
  mean_writer_refill_wait_ms?: number | null;
  writer_configured_concurrency: number;
  writer_configured_batch_size: number;
  writer_window_commands?: number;
  writer_queue_max_commands: number;
  writer_queue_max_bytes: number;
  writer_refill_min_commands: number;
  writer_refill_min_commands_per_lane?: number;
  max_worker_completion_gap_ms: number;
  ready_queue_recovery_count: number;
  ready_queue_recovered_tasks: number;
  time_weighted_inflight: number | null;
  route_attempts: number;
  route_active_sum_ms: number;
  route_lookup_stats?: Record<string, JobRouteLookupStat> | null;
  time_weighted_active_routes: number | null;
  steady_task_count: number;
  steady_window_ms: number;
  steady_throughput: number | null;
  steady_mean_task_duration_ms: number | null;
  ramp_window_ms: number | null;
  drain_window_ms: number | null;
  ready_nonempty_ratio: number | null;
  ready_nonempty_samples?: number;
  ready_sample_count?: number;
  mean_ready_depth: number | null;
  max_ready_depth: number;
  workers_seen: number;
  expected_workers: number;
  time_weighted_participating_workers: number | null;
  time_weighted_effective_worker_capacity: number | null;
}

export interface JobDetail {
  updated_at?: string | null;
  job_id: string;
  execution_engine?: string | null;
  job_name: string | null;
  job_type: string | null;
  status: string;
  site: string | null;
  priority: number;
  worker_id: string | null;
  retries: number;
  max_retries: number;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  result_success: boolean | null;
  result_message: string | null;
  result_error: string | null;
  args: Record<string, unknown> | null;
  metadata?: JobMetadata | null;
  duration_seconds?: number | null;
  tasks: TaskDetail[];
  task_stats?: TaskStats;
  task_stats_observed_at_ms?: number | null;
  mps_refill_trace?: MPSRefillTraceEvent[];
  error_stats?: JobErrorStats;
  run_count?: number;
  last_ran_at?: string | null;
  last_activity_at?: string | null;
  materialization_status?: string | null;
  materialized_tasks?: number | null;
  materialization_total?: number | null;
  materialization_error?: string | null;
  runtime_telemetry?: JobRuntimeTelemetry | null;
}

export interface TaskPageResponse {
  tasks: TaskDetail[];
  next_cursor: string | null;
  has_more: boolean;
  scanned_count: number;
  offset: number;
  limit: number;
}

export interface ActiveTaskDetail {
  job_id: string;
  job_name: string;
  job_status: string;
  job_total_tasks?: number | null;
  task_id: string | null;
  task_type: string;
  status: string;
  site: string | null;
  username: string | null;
  content_type: string | null;
  worker_id?: string | null;
  started_at: string | null;
  completed_at: string | null;
  progress: number;
  items_processed: number;
  items_total: number | null;
  items_scraped?: number | null;
  items_saved?: number | null;
  bytes_written?: number | null;
  total_bytes?: number | null;
  speed_bps?: number | null;
  avg_speed_bps?: number | null;
  error: string | null;
}

export interface ActiveTaskListResponse {
  tasks: ActiveTaskDetail[];
  total: number;
}

export interface TaskQueryOptions {
  cursor?: string;
  offset?: number;
  limit?: number;
  state?: string;
  task_type?: string;
  error_only?: boolean;
}

export type RetryJobResponse = Job;

export interface PrioritizeJobResponse {
  job_id: string;
  rescored: number;
  priority: number;
}

export interface CancelJobResponse {
  job_id: string;
  status: string;
}

export interface DeleteJobsRequest {
  job_ids?: string[];
  older_than_hours?: number;
}

export interface DeleteJobFailure {
  job_id: string;
  error: string;
}

export interface DeleteJobsResponse {
  queued?: number;
  requested: number;
  deleted: number;
  failed: number;
  failures: DeleteJobFailure[];
}

export function streamJobTasksFromSource(
  jobId: string,
  onTask: (task: TaskDetail) => void,
  onDone?: () => void,
  onError?: (err: Event) => void,
  options: TaskQueryOptions = {},
  baseUrl: string = getApiBaseUrl(),
): () => void {
  const params = new URLSearchParams();
  if (options.cursor) params.set('cursor', options.cursor);
  if (typeof options.limit === 'number') params.set('batch_size', String(options.limit));
  if (options.state) params.set('state', options.state);
  if (options.task_type) params.set('task_type', options.task_type);
  if (options.error_only) params.set('error_only', 'true');
  const query = params.toString();
  const url = backendUrl(
    `${baseUrl}/api/v1/jobs/${jobId}/tasks/stream${query ? `?${query}` : ''}`,
  );
  const eventSource = new EventSource(url);

  eventSource.onmessage = (event) => {
    if (event.data === '[DONE]') {
      eventSource.close();
      onDone?.();
      return;
    }
    try {
      onTask(JSON.parse(event.data) as TaskDetail);
    } catch (error) {
      console.error('Failed to parse task from stream:', error);
    }
  };

  eventSource.onerror = (error: Event) => {
    console.error('EventSource error:', error);
    eventSource.close();
    onError?.(error);
  };

  return () => {
    eventSource.close();
  };
}
