import type { SearchLoadoutItem } from '../../../api/types/loadouts';

export const CONTENT_TYPES = [
  { value: '', label: 'All' },
  { value: 'post', label: 'Posts' },
  { value: 'story', label: 'Stories' },
  { value: 'message', label: 'Messages' },
  { value: 'mass_message', label: 'Mass Messages' },
];

export const SORT_OPTIONS = [
  { value: 'created_at', label: 'Date' },
  { value: 'price', label: 'Price' },
  { value: 'media_count', label: 'Media Count' },
  { value: 'expires_at', label: 'Expiry' },
  { value: 'user_id', label: 'User ID' },
  { value: 'id', label: 'Content ID' },
];

export const PAGE_SIZE = 30;

export const ADVANCED_FILTER_OPTIONS = [
  { key: 'purchased', label: 'Purchased' },
  { key: 'locked', label: 'Locked' },
  { key: 'free', label: 'Free' },
  { key: 'has_media', label: 'Has Media' },
  { key: 'no_media', label: 'No Media' },
  { key: 'archived', label: 'Archived' },
  { key: 'deleted', label: 'Deleted' },
  { key: 'expiring', label: 'Has Expiry' },
  { key: 'text', label: 'Has Text' },
] as const;

export type AdvancedFilterKey =
  | (typeof ADVANCED_FILTER_OPTIONS)[number]['key']
  | 'has_video'
  | 'has_photo'
  | 'has_audio';
export type AdvancedFilterState = 'none' | 'include' | 'exclude';
export type AdvancedFilterMap = Record<AdvancedFilterKey, AdvancedFilterState>;

export const DEFAULT_ADVANCED_FILTERS: AdvancedFilterMap = {
  purchased: 'none',
  locked: 'none',
  free: 'none',
  has_media: 'none',
  no_media: 'none',
  has_video: 'none',
  has_photo: 'none',
  has_audio: 'none',
  archived: 'none',
  deleted: 'none',
  expiring: 'none',
  text: 'none',
};

export function applyContentLoadoutState(loadout: SearchLoadoutItem) {
  const identifier = loadout.identifier || '';
  const filters = loadout.filters || {};
  const rawAdvanced = filters.advanced_filters;
  const nextAdvanced: AdvancedFilterMap = { ...DEFAULT_ADVANCED_FILTERS };

  if (rawAdvanced && typeof rawAdvanced === 'object') {
    for (const key of Object.keys(DEFAULT_ADVANCED_FILTERS) as AdvancedFilterKey[]) {
      const value = (rawAdvanced as Record<string, unknown>)[key];
      if (value === 'include' || value === 'exclude' || value === 'none') {
        nextAdvanced[key] = value;
      }
    }
  }

  const rawExcluded = filters.exclude_user_ids;
  let excludedUserIds: number[] = [];
  if (Array.isArray(rawExcluded)) {
    excludedUserIds = rawExcluded.map(Number).filter((id) => !isNaN(id) && id > 0);
  } else if (typeof rawExcluded === 'string') {
    excludedUserIds = rawExcluded
      .split(',')
      .map(Number)
      .filter((id) => !isNaN(id) && id > 0);
  }

  return {
    identifier,
    site: loadout.site || '',
    contentType: typeof filters.content_type === 'string' ? filters.content_type : '',
    sortBy: typeof filters.sort_by === 'string' ? filters.sort_by : 'created_at',
    order: filters.order === 'asc' ? ('asc' as const) : ('desc' as const),
    advancedFilters: nextAdvanced,
    excludedUserIds,
  };
}

export function buildAutoLoadoutName(options: {
  site: string;
  search: string;
  searchInput: string;
}) {
  const normalize = (value: string, maxLength: number) =>
    value.trim().replace(/\s+/g, ' ').slice(0, maxLength);

  const siteValue = normalize(options.site || 'all', 24) || 'all';
  const identifierValue = normalize(options.search || options.searchInput, 36);
  const parts = [`site:${siteValue}`];

  if (identifierValue) {
    parts.push(`identifier:${identifierValue}`);
  }

  return parts.join(' | ');
}
