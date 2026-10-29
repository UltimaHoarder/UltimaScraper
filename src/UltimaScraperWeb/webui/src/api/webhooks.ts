import { createHttpClient } from './http';
import type {
  WatchListResponse,
  WatchPauseResponse,
  WatchStatsResponse,
  WebhooksResponse,
  WebhookConfiguration,
  WebhookSite,
  SiteWebhookRouting,
} from './types/webhooks';

const http = createHttpClient();

export async function getWebhooks(): Promise<WebhooksResponse> {
  const response = await http.get<WebhooksResponse>('/api/v1/webhooks/');
  return response.data;
}

export async function saveWebhookConfiguration(site: WebhookSite, routing: SiteWebhookRouting, expectedVersion: number): Promise<WebhookConfiguration> {
  const response = await http.put<WebhookConfiguration>(`/api/v1/webhooks/configuration/${site}`, {
    expected_version: expectedVersion,
    routing,
  });
  return response.data;
}

export async function getWatchList(
  site?: string,
  search?: string,
  limit?: number,
  offset?: number,
): Promise<WatchListResponse> {
  const response = await http.get<WatchListResponse>('/api/v1/webhooks/watch/', {
    params: { site, search, limit, offset },
  });
  return response.data;
}

export async function getWatchStats(): Promise<WatchStatsResponse> {
  const response = await http.get<WatchStatsResponse>('/api/v1/webhooks/watch/stats');
  return response.data;
}

export async function pauseWatches(): Promise<WatchPauseResponse> {
  const response = await http.post<WatchPauseResponse>('/api/v1/webhooks/watch/pause');
  return response.data;
}

export async function resumeWatches(): Promise<WatchPauseResponse> {
  const response = await http.post<WatchPauseResponse>('/api/v1/webhooks/watch/resume');
  return response.data;
}
