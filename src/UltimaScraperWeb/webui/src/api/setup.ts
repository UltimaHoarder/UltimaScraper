import { createHttpClient } from './http';
import type {
  DatabaseConnectionRequest,
  DatabaseConnectionResponse,
  FilesystemListing,
  InitialSetupRequest,
  InitialSetupResponse,
  RedisConnectionRequest,
  RedisConnectionResponse,
  SetupStatusResponse,
  StartupMigrationActionResponse,
  StartupMigrationApplyRequest,
  StartupMigrationPreviewResponse,
} from './types/setup';

const http = createHttpClient();

export async function getSetupStatus(): Promise<SetupStatusResponse> {
  const response = await http.get<SetupStatusResponse>('/api/v1/setup/status');
  return response.data;
}

export async function testDatabaseConnection(
  request: DatabaseConnectionRequest,
): Promise<DatabaseConnectionResponse> {
  const response = await http.post<DatabaseConnectionResponse>(
    '/api/v1/setup/test-database',
    request,
  );
  return response.data;
}

// Prepares the schema too, which can take a while on a new database.
const DATABASE_PREPARE_TIMEOUT_MS = 330_000;

export async function testConfiguredDatabase(): Promise<DatabaseConnectionResponse> {
  const response = await http.post<DatabaseConnectionResponse>(
    '/api/v1/setup/test-configured-database',
    undefined,
    { timeout: DATABASE_PREPARE_TIMEOUT_MS },
  );
  return response.data;
}

export async function testConfiguredRedis(): Promise<RedisConnectionResponse> {
  const response = await http.post<RedisConnectionResponse>('/api/v1/setup/test-configured-redis');
  return response.data;
}

export async function browseFilesystem(
  path: string,
  includeFiles: boolean,
): Promise<FilesystemListing> {
  const response = await http.get<FilesystemListing>('/api/v1/system/filesystem', {
    params: { path, include_files: includeFiles },
  });
  return response.data;
}

export async function testSetupRedisConnection(
  request: RedisConnectionRequest,
): Promise<RedisConnectionResponse> {
  const response = await http.post<RedisConnectionResponse>('/api/v1/setup/test-redis', request);
  return response.data;
}

export async function completeSetup(
  request: InitialSetupRequest,
): Promise<InitialSetupResponse> {
  const response = await http.post<InitialSetupResponse>('/api/v1/setup/complete', request);
  return response.data;
}

export async function previewStartupMigration(): Promise<StartupMigrationPreviewResponse> {
  const response = await http.post<StartupMigrationPreviewResponse>(
    '/api/v1/setup/migrations/preview',
  );
  return response.data;
}

export async function applyStartupMigration(
  request: StartupMigrationApplyRequest,
): Promise<StartupMigrationActionResponse> {
  const response = await http.post<StartupMigrationActionResponse>(
    '/api/v1/setup/migrations/apply',
    request,
    // History migrations can take minutes; wait for the backend transaction result.
    { timeout: 0 },
  );
  return response.data;
}

export async function discardStartupMigration(): Promise<StartupMigrationActionResponse> {
  const response = await http.post<StartupMigrationActionResponse>(
    '/api/v1/setup/migrations/discard',
  );
  return response.data;
}

export async function regenerateStartupMigration(): Promise<StartupMigrationPreviewResponse> {
  const response = await http.post<StartupMigrationPreviewResponse>(
    '/api/v1/setup/migrations/regenerate',
  );
  return response.data;
}
