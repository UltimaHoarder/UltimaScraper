import { createHttpClient } from './http';
import type {
  SearchLoadoutMutationResponse,
  SearchLoadoutsResponse,
  SearchLoadoutType,
  SearchLoadoutUpsertRequest,
} from './types/loadouts';

const http = createHttpClient();

export async function getSearchLoadouts(
  type: SearchLoadoutType,
): Promise<SearchLoadoutsResponse> {
  const response = await http.get<SearchLoadoutsResponse>('/api/v1/search-loadouts/', {
    params: { type },
  });
  return response.data;
}

export async function saveSearchLoadout(
  type: SearchLoadoutType,
  name: string,
  payload: SearchLoadoutUpsertRequest,
): Promise<SearchLoadoutMutationResponse> {
  const response = await http.put<SearchLoadoutMutationResponse>(
    `/api/v1/search-loadouts/${encodeURIComponent(name)}`,
    payload,
    { params: { type } },
  );
  return response.data;
}

export async function setDefaultSearchLoadout(
  type: SearchLoadoutType,
  name: string,
): Promise<SearchLoadoutMutationResponse> {
  const response = await http.put<SearchLoadoutMutationResponse>(
    `/api/v1/search-loadouts/${encodeURIComponent(name)}/default`,
    {},
    { params: { type } },
  );
  return response.data;
}

export async function clearDefaultSearchLoadout(
  type: SearchLoadoutType,
): Promise<SearchLoadoutMutationResponse> {
  const response = await http.delete<SearchLoadoutMutationResponse>(
    '/api/v1/search-loadouts/default',
    { params: { type } },
  );
  return response.data;
}

export async function deleteSearchLoadout(
  type: SearchLoadoutType,
  name: string,
): Promise<SearchLoadoutMutationResponse> {
  const response = await http.delete<SearchLoadoutMutationResponse>(
    `/api/v1/search-loadouts/${encodeURIComponent(name)}`,
    { params: { type } },
  );
  return response.data;
}
