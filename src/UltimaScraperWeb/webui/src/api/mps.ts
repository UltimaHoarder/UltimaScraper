import { backendUrl, createHttpClient, getApiBaseUrl } from './http';
import type {
  MPSAnalyzeRequest,
  MPSAnalyzeResponse,
  MPSBoundaryDiscoveryRequest,
  MPSBoundaryDiscoveryResponse,
  MPSCreateJobRequest,
  MPSCreateJobResponse,
  MPSProxyPreviewRequest,
  MPSProxyPreviewResponse,
  MPSSiteBoundsResponse,
} from './types/mps';

const http = createHttpClient();

export async function getSiteBounds(site: string): Promise<MPSSiteBoundsResponse> {
  const response = await http.get<MPSSiteBoundsResponse>('/api/v1/mps/site-bounds', {
    params: { site },
  });
  return response.data;
}

export async function analyzeMps(
  request: MPSAnalyzeRequest,
): Promise<MPSAnalyzeResponse> {
  const response = await http.post<MPSAnalyzeResponse>('/api/v1/mps/analyze', request, {
    timeout: 0,
  });
  return response.data;
}

export async function createMpsJob(
  request: MPSCreateJobRequest,
): Promise<MPSCreateJobResponse> {
  const response = await http.post<MPSCreateJobResponse>('/api/v1/mps/create-job', request, {
    timeout: 0,
  });
  return response.data;
}

export async function previewMpsProxies(
  request: MPSProxyPreviewRequest,
): Promise<MPSProxyPreviewResponse> {
  const response = await http.post<MPSProxyPreviewResponse>(
    '/api/v1/mps/proxy-preview',
    request,
  );
  return response.data;
}

export async function discoverBounds(
  request: MPSBoundaryDiscoveryRequest,
): Promise<MPSBoundaryDiscoveryResponse> {
  const response = await http.post<MPSBoundaryDiscoveryResponse>(
    '/api/v1/mps/discover-bounds',
    request,
    { timeout: 0 },
  );
  return response.data;
}

export function getDiscoverBoundsStreamUrl(
  params: MPSBoundaryDiscoveryRequest,
  baseUrl: string = getApiBaseUrl(),
): string {
  const search = new URLSearchParams();
  search.set('site', params.site);
  if (params.min_id !== undefined && params.min_id !== null) {
    search.set('min_id', String(params.min_id));
  }
  if (params.max_id_ceiling !== undefined) {
    search.set('max_id_ceiling', String(params.max_id_ceiling));
  }
  if (params.max_probes !== undefined) {
    search.set('max_probes', String(params.max_probes));
  }
  if (params.probe_multiplier !== undefined) {
    search.set('probe_multiplier', String(params.probe_multiplier));
  }
  if (params.confidence_level !== undefined) {
    search.set('confidence_level', String(params.confidence_level));
  }
  if (params.target_margin_of_error !== undefined) {
    search.set('target_margin_of_error', String(params.target_margin_of_error));
  }
  const cleanBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
  const path = `${cleanBase}/api/v1/mps/discover-bounds/stream?${search.toString()}`;
  return backendUrl(path);
}
