export interface PluginRecord {
  plugin_id: string;
  display_name: string;
  plugin_version: string;
  status: 'enabled' | 'disabled' | 'invalid' | 'missing';
  capabilities: string[];
  loaded_at: string;
  enabled_at: string | null;
  disabled_at: string | null;
  last_error: string | null;
  revision: number;
  manifest_schema_version?: number | null;
  usr_compatibility?: string | null;
  requested_capabilities?: string[];
  granted_capabilities?: string[];
  pending_capabilities?: string[];
  preflight_ready?: boolean;
  health_status?: 'healthy' | 'starting' | 'disabled' | 'approval_required' | 'incompatible' | 'invalid' | 'missing';
  health_message?: string;
  pending_scopes?: string[];
  runtime_storage?: 'postgresql' | 'sqlite';
  sdk_version?: string;
  delivery_queue?: { pending: number; oldest_pending_at: string | null; counts: Record<string, number> };
  active_package?: { digest: string; previous_digest: string | null } | null;
  ui_mode?: 'native' | 'sandbox' | 'declarative';
  has_settings?: boolean;
  setup_required?: boolean;
  setup_ready?: boolean;
  schedules?: PluginScheduleStatus[];
}

export interface PluginScheduleStatus {
  schedule_id: string;
  task_type: string;
  next_at?: string;
  job_id?: string;
  blocked_by_job?: string;
  last_result?: { job_id?: string; status?: string; [key: string]: unknown };
}

export interface PluginSetupDescription {
  required: boolean;
  ready: boolean;
  schema: Record<string, unknown> | null;
  values: Record<string, unknown>;
  credentials: { name: string; title: string; description: string; required: boolean; configured: boolean }[];
}

export interface PluginSource {
  source_id: string;
  plugin_id: string;
  display_name: string;
  plugin_version: string;
  revision: string;
  installed: boolean;
  data_retained: boolean;
}

export type PluginInstallSource = { kind: 'local'; source_id: string } | { kind: 'git'; url: string; revision?: string };
export interface PluginInstallPreview {
  plugin_id: string;
  display_name: string;
  plugin_version: string;
  preview_token: string;
  package_digest: string;
  requested_capabilities: string[];
  requested_scopes: Partial<PluginAccessScopes>;
  source: { kind: 'git' | 'local'; source_id: string; url?: string | null; revision: string; dirty: boolean };
}

export interface PluginPreflightCheck {
  name: string;
  status: 'passed' | 'failed' | 'approval_required';
  message: string;
}

export interface PluginPreflightResponse {
  plugin_id: string;
  ready: boolean;
  summary: string;
  usr_version?: string;
  compatibility?: string;
  requested_capabilities?: string[];
  granted_capabilities?: string[];
  pending_capabilities?: string[];
  checks: PluginPreflightCheck[];
}

export interface PluginCreateRequest {
  configuration_schema?: Record<string, unknown>;
  manifest_schema_version?: 1 | 2;
  sdk?: {
    compatibility?: string;
    configuration_schema?: Record<string, unknown>;
    access?: Partial<PluginAccessScopes>;
    ui?: PluginUIContribution[];
    setup?: { credentials: { name: string; title: string; description?: string; required?: boolean }[]; validation_service?: string; validation_query?: Record<string, unknown> };
    http_services?: { service_id: string; url: string; credential?: string; auth_scheme?: 'Token' | 'Bearer'; query_schema?: Record<string, unknown>; timeout_seconds?: number; response_limit_bytes?: number }[];
    schedules?: { schedule_id: string; task_type: string; interval_setting: string }[];
  };
  webui?: PluginWebUIConfig;
  plugin_id: string;
  plugin_version: string;
  display_name: string;
  description?: string;
  usr_compatibility?: string;
  capabilities?: string[];
  task_types?: TaskTypeDefinition[];
  event_subscriptions?: EventSubscriptionDefinition[];
  callbacks?: CallbackDefinition[];
  outbound_deliveries?: OutboundDeliveryDefinition[];
  operational_policy?: OperationalPolicyDefinition;
  remote_delegation?: RemoteDelegationDefinition | null;
}

export interface PluginCreateResponse extends PluginRecord {
  creation_status: string;
  reload_succeeded: boolean;
}

export interface PluginManifestResponse {
  plugin_id: string;
  manifest_yaml: string;
  status: PluginRecord['status'];
  revision: number;
}

export interface PluginManifestUpdateRequest {
  manifest_yaml: string;
}

export interface PluginManifestUpdateResponse extends PluginRecord {
  reload_succeeded: boolean;
  manifest_yaml: string;
  staged_package?: PluginStagedPackage;
}

export interface PluginSecretRecord {
  plugin_id: string;
  scope_kind: string;
  scope_name: string;
  has_secret: boolean;
  has_grace_secret: boolean;
  created_at: string;
  rotated_at: string | null;
}

export interface PluginSecretSetRequest {
  scope_kind: string;
  scope_name: string;
  raw_secret: string;
}

export interface PluginSecretSetResponse {
  status: string;
  note: string;
}

export interface DelegatedJobSubmitRequest {
  payload: Record<string, unknown>;
  idempotency_key?: string;
}

export interface DelegatedJobSubmitResponse {
  correlation_id: string;
  plugin_id: string;
  integration_id: string;
  status: string;
  external_job_id: string | null;
  http_status_code: number | null;
  response_body: Record<string, unknown> | null;
  last_error: string | null;
  retry_count: number;
  payload_hash: string;
  message_id: string | null;
}

export interface TaskFieldDefinition {
  name: string;
  field_type: 'string' | 'integer' | 'float' | 'boolean' | 'list' | 'object';
  required?: boolean;
  description?: string;
  allowed_values?: (string | number | boolean)[];
  min_value?: number;
  max_value?: number;
  min_length?: number;
  max_length?: number;
}

export interface TaskResultFieldDefinition {
  name: string;
  field_type: 'string' | 'integer' | 'float' | 'boolean' | 'list' | 'object';
  description?: string;
}

export interface TaskTypeDefinition {
  task_type: string;
  description?: string;
  payload_fields?: TaskFieldDefinition[];
  result_fields?: TaskResultFieldDefinition[];
  max_priority?: number;
  handler?: { kind: 'http' | 'process'; url?: string; command?: string[]; auth_scope?: string; timeout_seconds?: number; response_limit_bytes?: number };
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
}

export interface EventSubscriptionDefinition {
  event_family: string;
  event_types?: string[];
  delivery_target: string;
}

export interface CallbackDefinition {
  handler_id: string;
  description?: string;
  auth_method?: 'hmac' | 'bearer';
  payload_fields?: TaskFieldDefinition[];
}

export interface OutboundDeliveryDefinition {
  target_name: string;
  url: string;
  url_setting?: string;
  description?: string;
}

export interface DeliveryRetryPolicyDefinition {
  max_retries?: number;
  initial_backoff_seconds?: number;
  max_backoff_seconds?: number;
  backoff_multiplier?: number;
}

export interface OperationalPolicyDefinition {
  max_pending_deliveries?: number;
  delivery_concurrency?: number;
  task_concurrency?: number;
  retry_policy?: DeliveryRetryPolicyDefinition;
  state_quota_bytes?: number;
  replay_on_enable?: boolean;
  allow_private_networks?: boolean;
  allow_insecure_http?: boolean;
  allowed_outbound_domains?: string[];
}

export interface PluginMetadata {
  manifest_schema_version: number;
  capabilities: string[];
  event_families: string[];
}

export interface PluginPurgeResponse {
  plugin_id: string;
  status: 'purged';
  deleted_records: number;
  deleted_by_store: Record<string, number>;
  manifest_retained: boolean;
}

// ── Remote Delegation types ──────────────────────────────────────────────

export type RemoteDelegationRole = 'submitter' | 'executor' | 'bidirectional';
export type RemoteAuthMethod = 'api_key' | 'bearer' | 'hmac';
export type RemoteHttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface RemoteAuthConfigDefinition {
  method?: RemoteAuthMethod;
  header_name?: string;
}

export interface RemoteCorrelationConfigDefinition {
  local_id_field?: string;
  remote_id_field?: string;
  submitter_id_field?: string;
}

export interface RemoteResponseMappingDefinition {
  external_job_id_path?: string;
  remote_status_path?: string;
  error_path?: string;
}

export interface DeclarativeValueMappingDefinition {
  source_path?: string;
  literal?: unknown;
}

export type RemoteMappingValue =
  | DeclarativeValueMappingDefinition
  | string
  | number
  | boolean
  | null
  | RemoteMappingObject
  | RemoteMappingValue[];

export interface RemoteMappingObject {
  [key: string]: RemoteMappingValue;
}

export interface RemoteRequestMappingDefinition {
  path_params?: Record<string, RemoteMappingValue>;
  query?: Record<string, RemoteMappingValue>;
  headers?: Record<string, RemoteMappingValue>;
  body?: Record<string, RemoteMappingValue>;
}

export interface RemoteHttpOperationDefinition {
  transport?: 'http';
  method?: RemoteHttpMethod;
  endpoint: string;
  auth_scope?: string;
  request_mapping?: RemoteRequestMappingDefinition;
  response_mapping?: RemoteResponseMappingDefinition;
}

export interface RemoteOperationsDefinition {
  submission?: RemoteHttpOperationDefinition;
  claim?: RemoteHttpOperationDefinition;
  heartbeat?: RemoteHttpOperationDefinition;
  progress?: RemoteHttpOperationDefinition;
  complete?: RemoteHttpOperationDefinition;
  fail?: RemoteHttpOperationDefinition;
  cancel?: RemoteHttpOperationDefinition;
  poll?: RemoteHttpOperationDefinition;
}

export interface RemoteInboundCallbackExtractDefinition {
  lifecycle_event: RemoteMappingValue;
  correlation_id?: RemoteMappingValue;
  external_job_id?: RemoteMappingValue;
  remote_status?: RemoteMappingValue;
  progress?: RemoteMappingValue;
  result?: RemoteMappingValue;
  error?: RemoteMappingValue;
}

export interface RemoteInboundCallbackDefinition {
  handler_id: string;
  extract: RemoteInboundCallbackExtractDefinition;
}

export interface RemoteExecutorTaskMatchDefinition {
  job_type?: string;
  kind?: string;
}

export interface RemoteExecutorTaskBindingDefinition {
  remote_match: RemoteExecutorTaskMatchDefinition;
  local_task_type: string;
  payload_mapping?: Record<string, RemoteMappingValue>;
  defaults?: Record<string, RemoteMappingValue>;
  overrides?: Record<string, RemoteMappingValue>;
  task_alias?: RemoteMappingValue;
  depends_on_aliases?: RemoteMappingValue;
}

export interface RemoteExecutorMappingDefinition {
  remote_job_type_path?: string;
  remote_payload_path?: string;
  remote_tasks_path?: string;
  local_job_name_template?: string;
  task_bindings?: RemoteExecutorTaskBindingDefinition[];
}

export interface RemoteAuthExportDefinition {
  site_path?: string;
  auth_id_path?: string;
  runtime_key?: string;
}

export interface RemoteAuthImportDefinition {
  bundle_path?: string;
  site_path?: string;
  username_path?: string;
  user_id_path?: string;
  runtime_key?: string;
}

export interface RemoteCallbackConfigDefinition {
  inbound?: RemoteInboundCallbackDefinition[];
}

export interface RemoteCallbackRegistrationDefinition {
  endpoint?: string;
  method?: 'POST' | 'PUT';
  auth_scope?: string;
  lifecycle_events?: string[];
  payload_mapping?: Record<string, RemoteMappingValue>;
}

export interface RemoteWebSocketReconnectPolicyDefinition {
  initial_backoff_seconds?: number;
  max_backoff_seconds?: number;
  max_retries?: number;
}

export interface RemoteWebSocketEnvelopeMappingDefinition {
  message_id_field?: string;
  message_type_field?: string;
  plugin_id_field?: string;
  correlation_id_field?: string;
  external_job_id_field?: string;
  action_field?: string;
  payload_field?: string;
  timestamp_field?: string;
}

export interface RemoteWebSocketConfigDefinition {
  url: string;
  auth?: RemoteAuthConfigDefinition;
  reconnect_policy?: RemoteWebSocketReconnectPolicyDefinition;
  heartbeat_interval_seconds?: number;
  message_envelope_mapping?: RemoteWebSocketEnvelopeMappingDefinition;
}

export interface RemoteDelegationDefinition {
  integration_id: string;
  role: RemoteDelegationRole;
  description?: string;
  external_system_url?: string;
  auth?: RemoteAuthConfigDefinition;
  auth_scopes?: Record<string, RemoteAuthConfigDefinition>;
  correlation?: RemoteCorrelationConfigDefinition;
  operations?: RemoteOperationsDefinition;
  auth_export?: RemoteAuthExportDefinition;
  auth_import?: RemoteAuthImportDefinition;
  executor_mapping?: RemoteExecutorMappingDefinition;
  callback_registration?: RemoteCallbackRegistrationDefinition;
  websocket?: RemoteWebSocketConfigDefinition | null;
  callbacks?: RemoteCallbackConfigDefinition;
}

export interface PluginWebUIConfig {
  mode?: 'native' | 'sandbox';
  entry: string;
  styles?: string[];
}

export interface ActivePluginWebUI {
  plugin_id: string;
  display_name: string;
  plugin_version: string;
  entry: string;
  styles: string[];
  package_digest?: string;
  sdk_version?: string;
  mode?: 'native' | 'sandbox' | 'declarative';
  access?: PluginAccessScopes | null;
  contributions?: PluginUIContribution[];
}

export interface PluginAccessScopes {
  profile_fields: string[];
  task_types: string[];
  outbound_domains: string[];
  state_keys?: string[];
  http_services?: string[];
  proxy_sources?: string[];
  propose_profile_changes: boolean;
}

export interface PluginUIContribution {
  contribution_id: string;
  slot: import('../../features/plugins/lib/pluginHost').PluginSlotName;
  kind: 'badge' | 'action' | 'panel' | 'page';
  title: string;
  text: string;
  order: number;
  task_type: string | null;
}

export interface PluginStagedPackage {
  plugin_id: string;
  package_digest: string;
  plugin_version: string;
  previous_version: string | null;
  added_capabilities: string[];
  requested_capabilities: string[];
  requested_scopes: PluginAccessScopes;
  scope_changes: boolean;
  status: 'staged';
}
