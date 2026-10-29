import type {
  RemoteAuthMethod,
  RemoteHttpMethod,
  RemoteHttpOperationDefinition,
  RemoteInboundCallbackDefinition,
  RemoteDelegationRole,
} from '../../../api/types/plugins';

export const DEFAULT_PLUGIN_CAPABILITIES = [
  'auth.credentials.export',
  'auth.credentials.import',
  'events.read',
  'jobs.submit',
  'jobs.schedule',
  'http.request',
  'proxies.sync',
  'remote.callbacks.receive',
  'remote.jobs.execute',
  'remote.jobs.submit',
  'remote.sessions.connect',
  'webhooks.register',
  'workers.status.read',
] as const;

export const DEFAULT_EVENT_FAMILIES = [
  'delivery.lifecycle',
  'job.lifecycle',
  'plugin.lifecycle',
  'system.alerts',
  'worker.health',
] as const;

export const FIELD_TYPES = ['string', 'integer', 'float', 'boolean', 'list', 'object'] as const;
export const REMOTE_ROLES: RemoteDelegationRole[] = ['submitter', 'executor', 'bidirectional'];
export const REMOTE_AUTH_METHODS: RemoteAuthMethod[] = ['api_key', 'bearer', 'hmac'];
export const REMOTE_HTTP_METHODS: RemoteHttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
export const REMOTE_LIFECYCLE_EVENTS = ['claimed', 'progress', 'completed', 'failed', 'cancelled'] as const;

export function createHttpOperation(
  method: RemoteHttpMethod = 'POST',
  endpoint = '',
): RemoteHttpOperationDefinition {
  return {
    transport: 'http',
    method,
    endpoint,
    request_mapping: {
      path_params: {},
      query: {},
      headers: {},
      body: {},
    },
    response_mapping: {
      external_job_id_path: 'job.id',
      remote_status_path: 'job.status',
    },
  };
}

export function createInboundCallbackMapping(): RemoteInboundCallbackDefinition {
  return {
    handler_id: '',
    extract: {
      lifecycle_event: { literal: 'progress' },
      correlation_id: { source_path: 'callback.body.correlation_id' },
      external_job_id: { source_path: 'callback.body.external_job_id' },
      remote_status: { source_path: 'callback.body.remote_status' },
      progress: { source_path: 'callback.body.progress' },
      result: { source_path: 'callback.body.result' },
      error: { source_path: 'callback.body.error' },
    },
  };
}

export function getMappingSourcePath(value: unknown): string {
  if (value && typeof value === 'object' && 'source_path' in value) {
    const sourcePath = (value as { source_path?: unknown }).source_path;
    return typeof sourcePath === 'string' ? sourcePath : '';
  }
  return '';
}

export function getMappingLiteral(value: unknown): string {
  if (value && typeof value === 'object' && 'literal' in value) {
    const literal = (value as { literal?: unknown }).literal;
    return typeof literal === 'string' ? literal : '';
  }
  return '';
}
