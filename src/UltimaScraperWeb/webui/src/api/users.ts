import { createHttpClient } from './http';
import type {
  UserInfo,
  DetailedUserResponse,
  EligibleAuthsResponse,
  HistoUserInfoResponse,
  IgnoreToggleResponse,
  UserAliasDeleteResponse,
  UserAliasResponse,
  UserBrowserResponse,
  UserIdentifierResolutionResponse,
  UserProfileRefreshResponse,
  UsernameDirectorySearchResponse,
  UsersListQuery,
  UsersListResponse,
  UserUpdateRequest,
  UserUpdateResponse,
  WatchToggleResponse,
} from './types/users';

const http = createHttpClient();

export async function getUsersList(query: UsersListQuery): Promise<UsersListResponse> {
  const params = new URLSearchParams();
  if (query.site) params.append('site', query.site);
  if (query.search) params.append('search', query.search);
  if (query.searchDescription) params.append('search_description', query.searchDescription);
  if (query.activeOnly) params.append('active_only', 'true');
  if (query.favoriteOnly) params.append('favorite_only', 'true');
  query.sex?.forEach((value) => params.append('sex', String(value)));
  query.gender?.forEach((value) => params.append('gender', String(value)));
  query.profileType?.forEach((value) => params.append('profile_type', String(value)));
  query.sexualContent?.forEach((value) => params.append('sexual_content', String(value)));
  if (query.subscribedOnly) params.append('subscribed_only', 'true');
  if (query.excludeSubscribed) params.append('exclude_subscribed', 'true');
  if (query.minPrice) params.append('min_price', query.minPrice);
  if (query.maxPrice) params.append('max_price', query.maxPrice);
  if (query.minPostCount) params.append('min_post_count', query.minPostCount);
  if (query.maxPostCount) params.append('max_post_count', query.maxPostCount);
  if (query.minImageCount) params.append('min_image_count', query.minImageCount);
  if (query.maxImageCount) params.append('max_image_count', query.maxImageCount);
  if (query.minVideoCount) params.append('min_video_count', query.minVideoCount);
  if (query.maxVideoCount) params.append('max_video_count', query.maxVideoCount);
  if (query.performerOnly) params.append('performer_only', 'true');
  if (query.excludePerformers) params.append('exclude_performers', 'true');
  if (query.sortBy) params.append('sort_by', query.sortBy);
  if (query.sortOrder) params.append('sort_order', query.sortOrder);
  if (query.limit !== undefined) params.append('limit', String(query.limit));
  if (query.offset !== undefined) params.append('offset', String(query.offset));
  if (query.includeStats !== undefined) params.append('include_stats', String(query.includeStats));
  if (query.statsOnly) params.append('stats_only', 'true');

  // Cold description searches can outlast the 60s default; the backend cancels at 90s.
  const response = await http.get<UsersListResponse>(`/api/v1/users/?${params.toString()}`,
    { timeout: 120_000 });
  return response.data;
}

export async function browseUsers(
  site?: string,
  search?: string,
  activeOnly?: boolean,
  performerOnly?: boolean,
  page?: number,
  pageSize?: number,
): Promise<UserBrowserResponse> {
  const params: Record<string, string> = {};
  if (site) params.site = site;
  if (search) params.search = search;
  if (activeOnly) params.active_only = 'true';
  if (performerOnly) params.performer_only = 'true';
  if (page) params.page = page.toString();
  if (pageSize) params.page_size = pageSize.toString();
  const response = await http.get<UserBrowserResponse>('/api/v1/database/users', { params });
  return response.data;
}

export async function resolveUserIdentifier(
  identifier: string,
  site: string,
  page = 1,
  pageSize = 20,
): Promise<UserIdentifierResolutionResponse> {
  const response = await http.get<UserIdentifierResolutionResponse>('/api/v1/users/resolve', {
    timeout: 30_000,
    params: { identifier, site, page, page_size: pageSize },
  });
  return response.data;
}

export async function searchUsernameDirectories(
  username: string | null,
  site: string,
  userId?: number | null,
): Promise<UsernameDirectorySearchResponse> {
  const response = await http.get<UsernameDirectorySearchResponse>('/api/v1/files/users/search', {
    params: { username: username || undefined, user_id: userId ?? undefined, site },
  });
  return response.data;
}

export async function getUserProfile(
  userId: number,
  site: string,
): Promise<DetailedUserResponse> {
  const response = await http.get<DetailedUserResponse>(`/api/v1/users/${userId}`, {
    timeout: 30_000,
    params: { site },
  });
  return response.data;
}

export async function refreshUserProfile(
  userId: number,
  site: string,
): Promise<UserProfileRefreshResponse> {
  const response = await http.post<UserProfileRefreshResponse>(
    `/api/v1/users/${userId}/refresh`,
    undefined,
    { params: { site } },
  );
  return response.data;
}

export async function getUserHistory(
  userId: number,
  site: string,
): Promise<HistoUserInfoResponse> {
  const response = await http.get<HistoUserInfoResponse>(
    `/api/v1/database/users/${userId}/history`,
    { params: { site } },
  );
  return response.data;
}

export async function getUserAliases(
  userId: number,
  site: string,
): Promise<UserAliasResponse> {
  const response = await http.get<UserAliasResponse>(
    `/api/v1/database/users/${userId}/aliases`,
    { params: { site } },
  );
  return response.data;
}

export async function deleteUserAlias(
  userId: number,
  site: string,
  aliasId: number,
): Promise<UserAliasDeleteResponse> {
  const response = await http.delete<UserAliasDeleteResponse>(
    `/api/v1/database/users/${userId}/aliases/${aliasId}`,
    { params: { site } },
  );
  return response.data;
}

export async function updateUser(
  userId: number,
  site: string,
  payload: UserUpdateRequest,
): Promise<UserUpdateResponse> {
  const response = await http.patch<UserUpdateResponse>(`/api/v1/users/${userId}`, payload, {
    params: { site },
  });
  return response.data;
}

export async function getEligibleAuths(
  userId: number,
  site: string,
): Promise<EligibleAuthsResponse> {
  const response = await http.get<EligibleAuthsResponse>(
    `/api/v1/users/${userId}/eligible-auths`,
    { params: { site } },
  );
  return response.data;
}

export async function addToWatchList(
  userId: number,
  site: string,
): Promise<WatchToggleResponse> {
  const response = await http.put<WatchToggleResponse>(`/api/v1/webhooks/watch/${userId}`, null, {
    params: { site },
  });
  return response.data;
}

export async function removeFromWatchList(
  userId: number,
  site: string,
): Promise<WatchToggleResponse> {
  const response = await http.delete<WatchToggleResponse>(`/api/v1/webhooks/watch/${userId}`, {
    params: { site },
  });
  return response.data;
}

export async function addToIgnoreList(
  userId: number,
  site: string,
): Promise<IgnoreToggleResponse> {
  const response = await http.put<IgnoreToggleResponse>(
    `/api/v1/webhooks/watch/ignore/${userId}`,
    null,
    { params: { site } },
  );
  return response.data;
}

export async function removeFromIgnoreList(
  userId: number,
  site: string,
): Promise<IgnoreToggleResponse> {
  const response = await http.delete<IgnoreToggleResponse>(
    `/api/v1/webhooks/watch/ignore/${userId}`,
    { params: { site } },
  );
  return response.data;
}

export async function getUserCards(keys: { site: string; user_id: number }[]): Promise<{ users: UserInfo[] }> {
  const response = await http.post<{ users: UserInfo[] }>('/api/v1/users/cards', { keys });
  return response.data;
}
