import { createHttpClient } from './http';
import type {
  ActivePluginWebUI,
  DelegatedJobSubmitRequest,
  DelegatedJobSubmitResponse,
  PluginCreateRequest,
  PluginCreateResponse,
  PluginManifestResponse,
  PluginManifestUpdateRequest,
  PluginManifestUpdateResponse,
  PluginMetadata,
  PluginPurgeResponse,
  PluginRecord,
  PluginSecretRecord,
  PluginSecretSetRequest,
  PluginSecretSetResponse,
  PluginSetupDescription,
  PluginSource,
  PluginInstallSource,
  PluginInstallPreview,
} from './types/plugins';

const http = createHttpClient();

export async function listPluginSources(): Promise<PluginSource[]> {
  return (await http.get<PluginSource[]>('/api/v1/plugins/sources')).data;
}

export async function preparePluginInstall(source: PluginInstallSource): Promise<PluginInstallPreview> {
  return (await http.post<PluginInstallPreview>('/api/v1/plugins/install/prepare', source, { timeout: 180_000 })).data;
}

export async function confirmPluginInstall(preview: PluginInstallPreview): Promise<PluginRecord> {
  return (await http.post<PluginRecord>('/api/v1/plugins/install/confirm', { plugin_id: preview.plugin_id, preview_token: preview.preview_token })).data;
}

export async function cancelPluginInstall(preview: PluginInstallPreview): Promise<void> {
  await http.post('/api/v1/plugins/install/cancel', { plugin_id: preview.plugin_id, preview_token: preview.preview_token });
}

export async function uninstallPlugin(pluginId: string, deleteData: boolean, confirmation: string): Promise<{ plugin_id: string; data_retained: boolean }> {
  return (await http.post(`/api/v1/plugins/${encodeURIComponent(pluginId)}/uninstall`, { delete_data: deleteData, confirmation })).data;
}

export async function getPluginSetup(pluginId: string): Promise<PluginSetupDescription> {
  return (await http.get<PluginSetupDescription>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/setup`)).data;
}

export async function savePluginSetup(pluginId: string, payload: { configuration: Record<string, unknown>; credentials: Record<string, string>; enable: boolean }): Promise<PluginRecord> {
  return (await http.post<PluginRecord>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/setup`, payload)).data;
}

export async function runPluginSchedule(pluginId: string, scheduleId: string): Promise<{ job_id: string; reused?: boolean }> {
  return (await http.post(`/api/v1/plugins/${encodeURIComponent(pluginId)}/schedules/${encodeURIComponent(scheduleId)}/run`)).data;
}

export async function listPlugins(): Promise<PluginRecord[]> {
  const response = await http.get<PluginRecord[]>('/api/v1/plugins');
  return response.data;
}

export async function getPluginMetadata(): Promise<PluginMetadata> {
  const response = await http.get<PluginMetadata>('/api/v1/plugins/metadata');
  return response.data;
}

export async function getPluginManifest(pluginId: string): Promise<PluginManifestResponse> {
  const response = await http.get<PluginManifestResponse>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/manifest`,
  );
  return response.data;
}

export async function listPluginSecrets(pluginId: string): Promise<PluginSecretRecord[]> {
  const response = await http.get<PluginSecretRecord[]>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/secrets`,
  );
  return response.data;
}

export async function setPluginSecret(
  pluginId: string,
  request: PluginSecretSetRequest,
): Promise<PluginSecretSetResponse> {
  const response = await http.post<PluginSecretSetResponse>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/secrets/set`,
    {
      plugin_id: pluginId,
      ...request,
    },
  );
  return response.data;
}

export async function submitDelegatedJob(
  pluginId: string,
  request: DelegatedJobSubmitRequest,
): Promise<DelegatedJobSubmitResponse> {
  const response = await http.post<DelegatedJobSubmitResponse>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/remote-delegation/submit`,
    {
      plugin_id: pluginId,
      ...request,
    },
  );
  return response.data;
}

export async function createPlugin(request: PluginCreateRequest): Promise<PluginCreateResponse> {
  const response = await http.post<PluginCreateResponse>('/api/v1/plugins', request);
  return response.data;
}

export async function updatePluginManifest(
  pluginId: string,
  request: PluginManifestUpdateRequest,
): Promise<PluginManifestUpdateResponse> {
  const response = await http.put<PluginManifestUpdateResponse>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/manifest`,
    request,
  );
  return response.data;
}

export async function enablePlugin(pluginId: string): Promise<PluginRecord> {
  const response = await http.post<PluginRecord>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/enable`,
  );
  return response.data;
}

export async function disablePlugin(pluginId: string): Promise<PluginRecord> {
  const response = await http.post<PluginRecord>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/disable`,
  );
  return response.data;
}

export async function approvePluginCapabilities(pluginId: string): Promise<PluginRecord> {
  const response = await http.post<PluginRecord>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/capabilities/approve`,
  );
  return response.data;
}

export async function reloadPlugin(pluginId: string): Promise<PluginRecord> {
  const response = await http.post<PluginRecord>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/reload`,
  );
  return response.data;
}

export async function purgePluginData(
  pluginId: string,
  confirmation: string,
): Promise<PluginPurgeResponse> {
  const response = await http.delete<PluginPurgeResponse>(
    `/api/v1/plugins/${encodeURIComponent(pluginId)}/data`,
    { data: { confirmation } },
  );
  return response.data;
}

export async function listActiveWebUI(): Promise<ActivePluginWebUI[]> {
  const response = await http.get<ActivePluginWebUI[]>('/api/v1/plugins/active-webui');
  return response.data;
}

export async function activatePluginPackage(pluginId: string, packageDigest: string, approvePermissions: boolean): Promise<PluginRecord> {
  const response = await http.post<PluginRecord>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/packages/activate`, {
    package_digest: packageDigest, approve_permissions: approvePermissions,
  });
  return response.data;
}

export async function rollbackPluginPackage(pluginId: string): Promise<PluginRecord> {
  return (await http.post<PluginRecord>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/packages/rollback`)).data;
}

export async function getPluginConfiguration(pluginId: string): Promise<Record<string, unknown>> {
  return (await http.get<Record<string, unknown>>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/configuration`)).data;
}

export async function setPluginConfiguration(pluginId: string, configuration: Record<string, unknown>): Promise<PluginRecord> {
  return (await http.put<PluginRecord>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/configuration`, configuration)).data;
}

export interface PluginSettings {
  schema: Record<string, unknown> | null;
  values: Record<string, unknown>;
  connections: { name: string; label: string }[];
}

export async function getPluginSettings(pluginId: string): Promise<PluginSettings> {
  return (await http.get<PluginSettings>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/settings`)).data;
}

export async function testPluginConnection(pluginId: string, target: string, configuration: Record<string, unknown>): Promise<{ reachable: boolean; status_code: number; message: string }> {
  return (await http.post<{ reachable: boolean; status_code: number; message: string }>(`/api/v1/plugins/${encodeURIComponent(pluginId)}/settings/test`, { target, configuration })).data;
}
