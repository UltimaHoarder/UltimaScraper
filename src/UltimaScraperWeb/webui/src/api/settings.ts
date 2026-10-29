import { createHttpClient } from './http';
import type {
  BackendInventoryPatchRequest,
  BackendInventoryRecord,
  BackendInventoryUpsertRequest,
  DBSettingPatchRequest,
  DBSettingRecord,
  DBSettingUpsertRequest,
  DeleteSettingResponse,
  RemoteSettingsResponse,
  RemoteUpdateResponse,
  SettingsResponse,
  SettingsUpdate,
  SyncAllResponse,
  TestRedisConnectionRequest,
  TestRedisConnectionResponse,
} from './types/settings';

const http = createHttpClient();

export function isProtectedSettingKey(key: string): boolean {
  return ['config', 'config_scope', 'hostname', 'network.config', 'drm.config'].includes(key)
    || /^(db|redis|download)\./.test(key);
}

export async function getSettings(): Promise<SettingsResponse> {
  const response = await http.get<SettingsResponse>('/api/v1/settings/');
  return response.data;
}

export function applicationSettingsPayload(settings: SettingsUpdate): Record<string, unknown> {
  const allowed = [
    'worker_pool', 'network', 'download_setup', 'metadata_setup', 'drm',
    'job_execution',
    'previews_directory', 'subtitles_directory', 'sites', 'infinite_loop',
    'exit_on_completion', 'expected_version', 'actor_backend_id', 'request_id',
  ] as const;
  const payload: Record<string, unknown> = {};
  for (const key of allowed) {
    if (key in settings) payload[key] = settings[key];
  }
  if (settings.backend) {
    const backend: Record<string, unknown> = { ...settings.backend };
    delete backend.backend_id;
    payload.backend = backend;
  }
  return payload;
}

export async function updateSettings(settings: SettingsUpdate): Promise<SettingsResponse> {
  const applicationPayload = applicationSettingsPayload(settings);
  const applicationKeys = Object.keys(applicationPayload).filter(
    (key) => !['expected_version', 'actor_backend_id', 'request_id'].includes(key),
  );

  let current: SettingsResponse | null = null;
  if (applicationKeys.length > 0 || !settings.redis) {
    const response = await http.put<SettingsResponse>('/api/v1/settings/', applicationPayload);
    current = response.data;
  }

  if (settings.redis) {
    const response = await http.put<SettingsResponse>(
      '/api/v1/settings/runtime/redis',
      settings.redis,
    );
    return response.data;
  }

  if (!current) {
    throw new Error('No settings changes were provided.');
  }
  return current;
}

export async function testSettingsRedisConnection(
  config: TestRedisConnectionRequest,
): Promise<TestRedisConnectionResponse> {
  const response = await http.post<TestRedisConnectionResponse>(
    '/api/v1/settings/test-redis',
    config,
  );
  return response.data;
}

export async function listDbSettings(params?: {
  backend?: string;
  key?: string;
  include_secrets?: boolean;
}): Promise<DBSettingRecord[]> {
  const response = await http.get<DBSettingRecord[]>('/api/v1/settings/db', { params });
  return response.data;
}

export async function upsertDbSetting(
  request: DBSettingUpsertRequest,
): Promise<DBSettingRecord> {
  const response = await http.put<DBSettingRecord>('/api/v1/settings/db', request);
  return response.data;
}

export async function patchDbSetting(
  settingId: number,
  request: DBSettingPatchRequest,
): Promise<DBSettingRecord> {
  const response = await http.patch<DBSettingRecord>(
    `/api/v1/settings/db/${settingId}`,
    request,
  );
  return response.data;
}

export async function deleteDbSetting(settingId: number): Promise<DeleteSettingResponse> {
  const response = await http.delete<DeleteSettingResponse>(`/api/v1/settings/db/${settingId}`);
  return response.data;
}

export async function listBackendInventory(
  hostname?: string,
): Promise<BackendInventoryRecord[]> {
  const response = await http.get<BackendInventoryRecord[]>('/api/v1/settings/db/backends', {
    params: hostname ? { hostname } : undefined,
  });
  return response.data;
}

export async function upsertBackendInventory(
  request: BackendInventoryUpsertRequest,
): Promise<BackendInventoryRecord> {
  const response = await http.put<BackendInventoryRecord>(
    '/api/v1/settings/db/backends',
    request,
  );
  return response.data;
}

export async function patchBackendInventory(
  backendId: number,
  request: BackendInventoryPatchRequest,
): Promise<BackendInventoryRecord> {
  const response = await http.patch<BackendInventoryRecord>(
    `/api/v1/settings/db/backends/${backendId}`,
    request,
  );
  return response.data;
}

export async function deleteBackendInventory(
  backendId: number,
): Promise<DeleteSettingResponse> {
  const response = await http.delete<DeleteSettingResponse>(
    `/api/v1/settings/db/backends/${backendId}`,
  );
  return response.data;
}

export async function getRemoteSettings(
  backendId: string,
): Promise<RemoteSettingsResponse> {
  const response = await http.get<RemoteSettingsResponse>(`/api/v1/settings/${backendId}`);
  return response.data;
}

export async function updateRemoteSettings(
  backendId: string,
  settings: SettingsUpdate,
): Promise<RemoteUpdateResponse> {
  const response = await http.put<RemoteUpdateResponse>(
    `/api/v1/settings/${backendId}`,
    applicationSettingsPayload(settings),
  );
  return response.data;
}

export async function syncSettingsToAll(
  settings: SettingsUpdate,
): Promise<SyncAllResponse> {
  const response = await http.put<SyncAllResponse>('/api/v1/settings/sync-all', applicationSettingsPayload(settings));
  return response.data;
}
