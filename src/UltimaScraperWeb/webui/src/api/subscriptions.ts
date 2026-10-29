import { createHttpClient } from './http';
import type { SubscriptionListResponse, SubscriptionStats } from './types/subscriptions';

const http = createHttpClient();

export async function getSubscriptions(
  site?: string,
  search?: string,
  activeOnly?: boolean,
  authId?: number,
  limit?: number,
  offset?: number,
  orderBy?: string,
  orderDir?: string,
  sex?: number[],
): Promise<SubscriptionListResponse> {
  const params = new URLSearchParams();
  if (site) params.append('site', site);
  if (search) params.append('search', search);
  if (activeOnly) params.append('active_only', 'true');
  if (authId !== undefined) params.append('auth_id', authId.toString());
  if (sex && sex.length) {
    sex.forEach((value) => params.append('sex', value.toString()));
  }
  if (limit !== undefined) params.append('limit', limit.toString());
  if (offset !== undefined) params.append('offset', offset.toString());
  if (orderBy) params.append('order_by', orderBy);
  if (orderDir) params.append('order_dir', orderDir);
  const response = await http.get<SubscriptionListResponse>('/api/v1/subscriptions/', {
    params,
  });
  return response.data;
}

export async function getSubscriptionStats(): Promise<SubscriptionStats[]> {
  const response = await http.get<SubscriptionStats[]>('/api/v1/subscriptions/stats');
  return response.data;
}
