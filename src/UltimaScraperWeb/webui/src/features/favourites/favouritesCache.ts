import type { QueryClient } from '@tanstack/react-query';
import { favouriteKey, getFavouriteStates, type FavouriteKey, type FavouriteState } from '../../api/favourites';

const buckets = new WeakMap<QueryClient, Map<string, { key: FavouriteKey; resolve: (state: FavouriteState) => void; reject: (error: unknown) => void }>>();

/** Coalesce visible controls into bounded batch checks, never one HTTP call per card. */
export function loadFavouriteState(client: QueryClient, key: FavouriteKey): Promise<FavouriteState> {
  let bucket = buckets.get(client);
  if (!bucket) {
    bucket = new Map();
    buckets.set(client, bucket);
    setTimeout(() => {
      buckets.delete(client);
      const entries = [...bucket!.values()];
      for (let offset = 0; offset < entries.length; offset += 200) {
        const page = entries.slice(offset, offset + 200);
        void getFavouriteStates(page.map(entry => entry.key)).then(states => {
          const lookup = new Map(states.map(state => [JSON.stringify(favouriteKey(state)), state]));
          page.forEach(entry => {
            const state = lookup.get(JSON.stringify(favouriteKey(entry.key)));
            if (state) entry.resolve(state); else entry.reject(new Error('Missing favourite state'));
          });
        }).catch(error => page.forEach(entry => entry.reject(error)));
      }
    }, 0);
  }
  return new Promise((resolve, reject) => bucket!.set(JSON.stringify(favouriteKey(key)), { key, resolve, reject }));
}

export function invalidateFavouriteViews(client: QueryClient, key?: FavouriteKey) {
  const names = new Set(['favourites-list', 'favourites-counts', ...(key?.entity_type === 'user' ? ['users-list', 'users-stats', 'user-profile', 'subscriptions'] : [])]);
  const matchesSite = (site: unknown) => !site || site === 'all' || site === key?.site;
  void client.invalidateQueries({ predicate: query => {
    const [name, filter, site] = query.queryKey;
    if (!names.has(String(name))) return false;
    if (!key) return true;
    if (name === 'favourites-list') {
      const filters = filter as { site?: string; entity_type?: string };
      return matchesSite(filters.site) && (!filters.entity_type || filters.entity_type === key.entity_type);
    }
    if (name === 'favourites-counts') return matchesSite(filter && typeof filter === 'object' ? (filter as {site?: string}).site : filter);
    if (name === 'user-profile') return Number(filter) === key.entity_id && matchesSite(site);
    if (name === 'users-list' || name === 'users-stats') return matchesSite(site);
    if (name === 'subscriptions') return matchesSite(filter);
    return true;
  } });
}

/** Update existing projections without adding a second favourite authority. */
export function patchFavouriteProjections(client: QueryClient, key: FavouriteKey, desired: boolean) {
  const names = new Set(key.entity_type === 'user' ? ['users-list', 'user-profile', 'subscriptions'] : ['content-library']);
  const patch = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(patch);
    if (!value || typeof value !== 'object') return value;
    const object = value as Record<string, unknown>;
    const matches = object.site === key.site && (object.user_id === key.entity_id || object.id === key.entity_id) &&
      (key.entity_type === 'user' ? 'favorite' in object && !('content_type' in object) : object.content_type === key.entity_type && object.id === key.entity_id);
    return Object.fromEntries(Object.entries(object).map(([name, child]) => [name, name === 'favorite' && matches ? desired : patch(child)]));
  };
  client.setQueriesData({ predicate: query => names.has(String(query.queryKey[0])) }, patch);
}
