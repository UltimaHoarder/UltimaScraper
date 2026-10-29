import { apiUrl, createHttpClient } from './http';
import type {
  AddNetworkProxyRequest,
  AuthAccount,
  BulkAddProxiesRequest,
  BulkAddProxiesResponse,
  BulkAssignGroupRequest,
  BulkAssignGroupResponse,
  BulkProxyDeleteRequest,
  BulkProxyDeleteResponse,
  BulkProxyEditRequest,
  BulkProxyEditResponse,
  BulkProxyStateRequest,
  BulkProxyStateResponse,
  BulkSyncProxiesRequest,
  BulkSyncProxiesResponse,
  BulkTestProxiesRequest,
  BulkTestProxiesResponse,
  GeolocationData,
  GroupSettingsResponse,
  GroupSettingsUpdateRequest,
  GroupSettingsUpdateResponse,
  NetworkProxy,
  ProxyAnalysisStreamEvent,
  ProxyAnalyzerResult,
  ProxyAssignmentRequest,
  ProxyMediaPoolResponse,
  ProxyTestResponse,
  UpdateNetworkProxyRequest,
  UpdateNetworkProxyResponse,
} from './types/network';

const http = createHttpClient();

async function getErrorMessage(response: Response, fallback: string) {
  const responseData = (await response.json().catch(() => null)) as
    | { detail?: string; message?: string }
    | null;

  return responseData?.detail || responseData?.message || fallback;
}

export async function listProxies(): Promise<NetworkProxy[]> {
  const response = await http.get<NetworkProxy[]>('/api/v1/proxies/');
  return response.data;
}

export async function getProxyAuths(proxyId: string): Promise<AuthAccount[]> {
  const response = await http.get<AuthAccount[]>(
    `/api/v1/proxies/${encodeURIComponent(proxyId)}/auths`,
  );
  return response.data;
}

export async function addProxy(request: AddNetworkProxyRequest): Promise<NetworkProxy> {
  const response = await http.post<NetworkProxy>('/api/v1/proxies/', request);
  return response.data;
}

export async function updateProxy(
  proxyUrl: string,
  request: UpdateNetworkProxyRequest,
): Promise<UpdateNetworkProxyResponse> {
  const response = await http.put<UpdateNetworkProxyResponse>(
    `/api/v1/proxies/${encodeURIComponent(proxyUrl)}`,
    request,
  );
  return response.data;
}

export async function deleteProxy(proxyUrl: string): Promise<unknown> {
  const response = await http.delete<unknown>(
    `/api/v1/proxies/${encodeURIComponent(proxyUrl)}`,
  );
  return response.data;
}

export async function assignProxy(request: ProxyAssignmentRequest): Promise<unknown> {
  const response = await http.post<unknown>('/api/v1/proxies/assign', request);
  return response.data;
}

export async function testProxy(request: AddNetworkProxyRequest): Promise<ProxyTestResponse> {
  const response = await http.post<ProxyTestResponse>('/api/v1/proxies/test', request);
  return response.data;
}

export async function getProxyMediaPool(): Promise<ProxyMediaPoolResponse> {
  const response = await http.get<ProxyMediaPoolResponse>('/api/v1/proxies/media-pool');
  return response.data;
}

export async function getProxyGeolocation(proxyUrl: string): Promise<GeolocationData> {
  const response = await http.post<GeolocationData>(
    `/api/v1/proxies/${encodeURIComponent(proxyUrl)}/geolocation`,
  );
  return response.data;
}

export async function updateProxySettings(
  endpoint: string,
  request: UpdateNetworkProxyRequest,
): Promise<unknown> {
  const response = await http.put<unknown>(endpoint, request);
  return response.data;
}

export async function bulkAddProxies(
  request: BulkAddProxiesRequest,
): Promise<BulkAddProxiesResponse> {
  const response = await http.post<BulkAddProxiesResponse>(
    '/api/v1/proxies/bulk',
    request,
  );
  return response.data;
}

export async function bulkSyncProxies(
  request: BulkSyncProxiesRequest,
): Promise<BulkSyncProxiesResponse> {
  const response = await http.post<BulkSyncProxiesResponse>(
    '/api/v1/proxies/bulk-sync',
    request,
  );
  return response.data;
}

export async function bulkTestProxies(
  request: BulkTestProxiesRequest,
): Promise<BulkTestProxiesResponse> {
  const response = await http.post<BulkTestProxiesResponse>(
    '/api/v1/proxies/bulk-test',
    request,
  );
  return response.data;
}

export async function bulkAssignGroup(
  request: BulkAssignGroupRequest,
): Promise<BulkAssignGroupResponse> {
  const response = await http.put<BulkAssignGroupResponse>(
    '/api/v1/proxies/bulk-group',
    request,
  );
  return response.data;
}

export async function updateGroupSettings(
  groupName: string,
  request: GroupSettingsUpdateRequest,
): Promise<GroupSettingsUpdateResponse> {
  const response = await http.put<GroupSettingsUpdateResponse>(
    `/api/v1/proxies/groups/${encodeURIComponent(groupName)}/settings`,
    request,
  );
  return response.data;
}

export async function getGroupSettings(groupName: string): Promise<GroupSettingsResponse> {
  const response = await http.get<GroupSettingsResponse>(
    `/api/v1/proxies/groups/${encodeURIComponent(groupName)}/settings`,
  );
  return response.data;
}

export async function bulkUpdateProxyState(
  request: BulkProxyStateRequest,
): Promise<BulkProxyStateResponse> {
  const response = await http.put<BulkProxyStateResponse>(
    '/api/v1/proxies/bulk-state',
    request,
  );
  return response.data;
}

export async function bulkDeleteProxies(
  request: BulkProxyDeleteRequest,
): Promise<BulkProxyDeleteResponse> {
  const response = await http.delete<BulkProxyDeleteResponse>(
    '/api/v1/proxies/bulk-delete',
    { data: request },
  );
  return response.data;
}

export async function bulkEditProxies(
  request: BulkProxyEditRequest,
): Promise<BulkProxyEditResponse> {
  const response = await http.put<BulkProxyEditResponse>(
    '/api/v1/proxies/bulk-edit',
    request,
  );
  return response.data;
}

export async function analyzeProxyLevel(options: {
  proxy: NetworkProxy;
  concurrencyLevel: number;
  requestCount: number;
  useLiveCdn: boolean;
  signal: AbortSignal;
  onWarmup?: (ip: string | undefined) => void;
  onProgress?: (event: ProxyAnalysisStreamEvent) => void;
  onResult?: (result: ProxyAnalyzerResult) => void;
  onComplete?: (event: ProxyAnalysisStreamEvent) => void;
}): Promise<boolean> {
  const {
    proxy,
    concurrencyLevel,
    requestCount,
    useLiveCdn,
    signal,
    onWarmup,
    onProgress,
    onResult,
    onComplete,
  } = options;

  const response = await fetch(apiUrl(`/api/v1/proxies/${encodeURIComponent(proxy.url)}/analyze-stream`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({
      concurrency_levels: [concurrencyLevel],
      timeout_seconds: 10,
      auto_ramp: false,
      max_connections: proxy.max_connections > 0 ? proxy.max_connections : 64,
      test_connection_scaling: true,
      connection_levels: [1, 2, 4, 8, 16, 32, 64],
      adaptive_connections: true,
      stress_requests: requestCount,
      mode: 'range',
      use_live_cdn: useLiveCdn,
    }),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response, 'Performance analysis failed'));
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let hadResults = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split('\n\n');
    buffer = frames.pop() || '';

    for (const frame of frames) {
      if (!frame.startsWith('data: ')) {
        continue;
      }

      try {
        const event = JSON.parse(frame.slice(6)) as ProxyAnalysisStreamEvent;

        if (event.type === 'warmup') {
          onWarmup?.(event.ip);
          continue;
        }

        if (event.type === 'progress') {
          onProgress?.(event);
          continue;
        }

        if (event.type === 'result' && event.result) {
          hadResults = true;
          onResult?.(event.result);
          continue;
        }

        if (event.type === 'complete') {
          onComplete?.(event);
        }
      } catch {
        // Ignore malformed SSE frames.
      }
    }
  }

  return hadResults;
}
