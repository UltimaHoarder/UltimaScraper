import { createHttpClient } from './http';
import type { UserInfo } from './types/users';
import type { ContentLibraryItem } from './types/content';

export type FavouriteType = 'user' | 'post' | 'story' | 'message';
export interface FavouriteKey { site: string; entity_type: FavouriteType; entity_id: number }
export interface FavouriteState extends FavouriteKey {
  favourited: boolean;
  favourite_id: number | null;
  created_at: string | null;
  created_at_source: string | null;
  pending?: boolean;
}
export interface FavouriteItem extends FavouriteKey {
  id: number;
  created_at: string;
  created_at_source: string;
  availability: 'available' | 'inactive' | 'deleted' | 'expired' | 'unavailable';
  entity: UserInfo | ContentLibraryItem | null;
}
export interface FavouritePage { items: FavouriteItem[]; has_more: boolean; next_cursor: string | null }
export interface FavouriteAdvancedFilters {
  availability?: FavouriteItem['availability'];
  active_only?: boolean;
  performer?: 'include' | 'exclude';
  subscribed?: 'include' | 'exclude';
  sex?: number[]; gender?: number[]; profile_type?: number[]; sexual_content?: number[];
  min_price?: number; max_price?: number;
  min_post_count?: number; max_post_count?: number;
  min_image_count?: number; max_image_count?: number;
  min_video_count?: number; max_video_count?: number;
}
export interface FavouriteFilters extends FavouriteAdvancedFilters { site?: string; entity_type?: FavouriteType; search: string; order: 'asc' | 'desc' }
export interface FavouriteCounts { total: number; by_type: Record<FavouriteType, number> }
const http = createHttpClient();
const base = '/api/v1/favourites';
export const favouriteKey = (key: FavouriteKey) => ['favourite-state', key.site, key.entity_type, key.entity_id] as const;
export const getFavouritesStatus = async () => (await http.get<{ enabled: boolean }>(`${base}/status`)).data;
export const getFavouriteStates = async (keys: FavouriteKey[]) => (await http.post<{states: FavouriteState[]}>(`${base}/states`, { keys })).data.states;
export const setFavourite = async (key: FavouriteKey, desired: boolean) => {
  const path = `${base}/${encodeURIComponent(key.site)}/${key.entity_type}/${key.entity_id}`;
  return (desired ? await http.put<FavouriteState>(path) : await http.delete<FavouriteState>(path)).data;
};
export const getFavourites = async (filters: FavouriteFilters, cursor: string | null, signal?: AbortSignal) =>
  (await http.get<FavouritePage>(base, { params: { ...filters, cursor, limit: 50 }, paramsSerializer: { indexes: null }, signal })).data;
export const getFavouriteCounts = async (filters: Omit<FavouriteFilters, 'order' | 'entity_type'>, signal?: AbortSignal) =>
  (await http.get<FavouriteCounts>(`${base}/counts`, { params: filters, paramsSerializer: { indexes: null }, signal })).data;
