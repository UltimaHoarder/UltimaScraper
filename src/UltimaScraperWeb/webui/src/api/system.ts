import { createHttpClient } from './http';
import type { SystemBootstrapResponse } from './types/bootstrap';
import type {
  AddDirectoryRequest,
  AddDirectoryResponse,
  AllBackendsResponse,
  BackendStatusResponse,
  DatabaseAnalyzeRequest,
  DatabaseAnalyzeResponse,
  DatabaseOverviewResponse,
  DatabaseReindexRequest,
  DatabaseReindexResponse,
  DatabaseVacuumRequest,
  DatabaseVacuumResponse,
  DirectoryConfigRequest,
  DirectoryConfigResponse,
  DrivesResponse,
  RemoveDirectoryRequest,
  RemoveDirectoryResponse,
  RuntimePowerAction,
  RuntimePowerResponse,
  RuntimeServiceTarget,
} from './types/system';

const http = createHttpClient();

export async function getSystemBootstrap(): Promise<SystemBootstrapResponse> {
  const response = await http.get<SystemBootstrapResponse>('/api/v1/system/bootstrap', {
    timeout: 15000,
  });
  return response.data;
}

export async function getDrives(): Promise<DrivesResponse> {
  const response = await http.get<DrivesResponse>('/api/v1/system/drives');
  return response.data;
}

export async function getBackendStatus(): Promise<BackendStatusResponse> {
  const response = await http.get<BackendStatusResponse>('/api/v1/system/backend', {
    timeout: 15000,
  });
  return response.data;
}

export async function getAllBackends(): Promise<AllBackendsResponse> {
  const response = await http.get<AllBackendsResponse>('/api/v1/system/backends');
  return response.data;
}

export async function addDirectory(
  request: AddDirectoryRequest,
): Promise<AddDirectoryResponse> {
  const response = await http.post<AddDirectoryResponse>(
    '/api/v1/system/drives/add-directory',
    request,
  );
  return response.data;
}

export async function removeDirectory(
  request: RemoveDirectoryRequest,
): Promise<RemoveDirectoryResponse> {
  const response = await http.post<RemoveDirectoryResponse>(
    '/api/v1/system/drives/remove-directory',
    request,
  );
  return response.data;
}

export async function getDirectoryConfig(
  directoryPath: string,
  setupType: 'download' | 'metadata',
  targetBackendId?: string,
): Promise<DirectoryConfigResponse> {
  const response = await http.get<DirectoryConfigResponse>(
    '/api/v1/system/drives/directory-config',
    {
      params: {
        directory_path: directoryPath,
        setup_type: setupType,
        target_backend_id: targetBackendId,
      },
    },
  );
  return response.data;
}

export async function updateDirectoryConfig(
  request: DirectoryConfigRequest,
): Promise<DirectoryConfigResponse> {
  const response = await http.post<DirectoryConfigResponse>(
    '/api/v1/system/drives/directory-config',
    request,
  );
  return response.data;
}

/** Restart or stop this instance's launcher and every service it supervises. */
export async function controlRuntimePower(
  action: RuntimePowerAction,
  targets?: RuntimeServiceTarget[],
): Promise<RuntimePowerResponse> {
  const response = await http.post<RuntimePowerResponse>('/api/v1/system/runtime/power', {
    action,
    targets,
  });
  return response.data;
}

export async function getDatabaseOverview(): Promise<DatabaseOverviewResponse> {
  const response = await http.get<DatabaseOverviewResponse>('/api/v1/system/database');
  return response.data;
}

export async function vacuumDatabase(
  request: DatabaseVacuumRequest,
): Promise<DatabaseVacuumResponse> {
  const response = await http.post<DatabaseVacuumResponse>(
    '/api/v1/system/database/vacuum',
    request,
    { timeout: 0 },
  );
  return response.data;
}

export async function analyzeDatabase(
  request: DatabaseAnalyzeRequest,
): Promise<DatabaseAnalyzeResponse> {
  const response = await http.post<DatabaseAnalyzeResponse>(
    '/api/v1/system/database/analyze',
    request,
    { timeout: 0 },
  );
  return response.data;
}

export async function reindexDatabase(
  request: DatabaseReindexRequest,
): Promise<DatabaseReindexResponse> {
  const response = await http.post<DatabaseReindexResponse>(
    '/api/v1/system/database/reindex',
    request,
    { timeout: 0 },
  );
  return response.data;
}

export async function cancelDatabaseOperation(
  site?: string,
  tableName?: string,
): Promise<{ success: boolean; message: string; cancelled_count: number }> {
  const response = await http.post<{ success: boolean; message: string; cancelled_count: number }>(
    '/api/v1/system/database/cancel',
    { site, table_name: tableName },
  );
  return response.data;
}
