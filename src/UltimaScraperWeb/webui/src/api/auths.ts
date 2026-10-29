import { createHttpClient } from './http';
import type {
  AddAuthFromCurlResponse,
  AgeVerificationResponse,
  AuthActionResponse,
  AuthBalanceResponse,
  AuthCredential,
  AuthEditRequest,
  AuthListResponse,
  AuthProxyTestResult,
  AuthStatusFilter,
  AuthTestResult,
  AuthUpdateResponse,
  ParsedCurlData,
} from './types/auths';
import { normalizeToAuthJson } from '../features/auths/lib/authsUtils';

const http = createHttpClient();

export async function getAuthList(
  site?: string,
  activeOnly?: boolean,
  username?: string,
  userId?: number,
  limit?: number,
  offset?: number,
  statusFilter?: AuthStatusFilter,
): Promise<AuthListResponse> {
  const params: Record<string, string> = {};
  if (site) params.site = site;
  if (activeOnly !== undefined) params.active_only = activeOnly ? 'true' : 'false';
  if (username) params.username = username;
  if (userId !== undefined) params.user_id = userId.toString();
  if (limit !== undefined) params.limit = limit.toString();
  if (offset !== undefined) params.offset = offset.toString();
  if (statusFilter) params.status_filter = statusFilter;
  const response = await http.get<AuthListResponse>('/api/v1/auths/', { params });
  return response.data;
}

export async function getAuthById(id: number, site: string): Promise<AuthCredential> {
  const response = await http.get<AuthCredential>(`/api/v1/auths/${id}`, {
    params: { site },
  });
  return response.data;
}

export async function toggleAuthStatus(
  id: number,
  site: string,
  active: boolean,
): Promise<AuthActionResponse> {
  const response = await http.patch<AuthActionResponse>(
    `/api/v1/auths/${id}/status`,
    { active },
    { params: { site } },
  );
  return response.data;
}

export async function updateAuth(
  id: number,
  site: string,
  data: AuthEditRequest,
): Promise<AuthUpdateResponse> {
  const response = await http.put<AuthUpdateResponse>(`/api/v1/auths/${id}`, data, {
    params: { site },
  });
  return response.data;
}

export async function testAuth(id: number, site: string): Promise<AuthTestResult> {
  const response = await http.post<AuthTestResult>(
    `/api/v1/auths/${id}/test`,
    {},
    { params: { site } },
  );
  return response.data;
}

export async function testAuthProxy(
  id: number,
  site: string,
): Promise<AuthProxyTestResult> {
  const response = await http.post<AuthProxyTestResult>(
    `/api/v1/auths/${id}/proxy-test`,
    {},
    { params: { site } },
  );
  return response.data;
}

export async function getAgeVerification(
  id: number,
  site: string,
): Promise<AgeVerificationResponse> {
  const response = await http.post<AgeVerificationResponse>(
    `/api/v1/auths/${id}/verify-age`,
    {},
    { params: { site } },
  );
  return response.data;
}

export async function getIdentityVerification(
  id: number,
  site: string,
): Promise<AgeVerificationResponse> {
  const response = await http.post<AgeVerificationResponse>(
    `/api/v1/auths/${id}/verify-identity`,
    {},
    { params: { site } },
  );
  return response.data;
}

export async function getAuthBalance(
  id: number,
  site: string,
): Promise<AuthBalanceResponse> {
  const response = await http.get<AuthBalanceResponse>(`/api/v1/auths/${id}/balance`, {
    params: { site },
  });
  return response.data;
}

export async function deleteAuth(
  id: number,
  site: string,
): Promise<AuthActionResponse> {
  const response = await http.delete<AuthActionResponse>(`/api/v1/auths/${id}`, {
    params: { site },
  });
  return response.data;
}

export async function parseCurl(
  curlCommand: string,
  site: string,
): Promise<ParsedCurlData> {
  const response = await http.post<ParsedCurlData>('/api/v1/curl/parse', {
    curl_command: curlCommand,
    site,
  });
  return response.data;
}

export async function parseAuthJson(
  authJson: string,
  site: string,
): Promise<ParsedCurlData> {
  const normalized = normalizeToAuthJson(authJson);
  const response = await http.post<ParsedCurlData>('/api/v1/curl/parse-json', {
    auth_json: normalized,
    site,
  });
  return response.data;
}

export async function addAuthFromCurl(
  curlCommand: string,
  site: string,
  inputType: 'curl' | 'json' = 'curl',
  proxyId?: string | null,
  emailNotificationsEnabled?: boolean | null,
): Promise<AddAuthFromCurlResponse> {
  const normalizedCommand =
    inputType === 'json' ? normalizeToAuthJson(curlCommand) : curlCommand;
  const response = await http.post<AddAuthFromCurlResponse>('/api/v1/curl/add-auth', {
    curl_command: normalizedCommand,
    site,
    input_type: inputType,
    proxy_id: proxyId ?? null,
    email_notifications_enabled: emailNotificationsEnabled ?? null,
  });
  return response.data;
}
