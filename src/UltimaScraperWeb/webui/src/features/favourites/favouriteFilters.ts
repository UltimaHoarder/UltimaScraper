import type { FavouriteAdvancedFilters, FavouriteItem } from '../../api/favourites';
import { SEX_FILTER_OPTIONS, GENDER_FILTER_OPTIONS, PROFILE_TYPE_FILTER_OPTIONS, SEXUAL_CONTENT_FILTER_OPTIONS, parseIntListParam, type UserFilterMap } from '../users/lib/usersUtils';

const identity = {
  sex: SEX_FILTER_OPTIONS, gender: GENDER_FILTER_OPTIONS,
  profile_type: PROFILE_TYPE_FILTER_OPTIONS, sexual_content: SEXUAL_CONTENT_FILTER_OPTIONS,
};
export const ranges = ['price', 'post_count', 'image_count', 'video_count'] as const;
export const availability: FavouriteItem['availability'][] = ['available', 'inactive', 'deleted', 'expired', 'unavailable'];
export const noUserFilters: UserFilterMap = { performer: 'none', subscribed: 'none' };
export const keys = ['availability', 'active_only', 'performer', 'subscribed', ...Object.keys(identity), ...ranges.flatMap(name => ['min_' + name, 'max_' + name])];

export function parseFavouriteFilters(params: URLSearchParams): FavouriteAdvancedFilters {
  const result: Record<string, unknown> = {};
  const status = params.get('availability');
  if (availability.includes(status as FavouriteItem['availability'])) result.availability = status;
  if (params.get('active_only') === 'true') result.active_only = true;
  for (const key of ['performer', 'subscribed']) {
    const value = params.get(key);
    if (value === 'include' || value === 'exclude') result[key] = value;
  }
  for (const [key, options] of Object.entries(identity)) {
    const values = parseIntListParam(params.get(key), options.map(option => option.value));
    if (values.length) result[key] = values;
  }
  for (const name of ranges) for (const bound of ['min', 'max']) {
    const key = bound + '_' + name;
    const value = params.get(key);
    if (value?.trim() && Number.isFinite(Number(value)) && Number(value) >= 0 && (name === 'price' || Number.isSafeInteger(Number(value)))) result[key] = Number(value);
  }
  return result;
}

