import type { SearchLoadoutItem } from '../../../api/types/loadouts';
import type { UserInfo, UsersListResponse } from '../../../api/types/users';
import { formatCompactNumber, formatPrice } from '../../../shared/lib/format';
import { stripHtml } from '../../../utils/sanitize';
import {
  type IdentityPreset,
  sexLabel,
  sexualContentLabel,
} from '../../user-profile/lib/userProfileUtils';

export const USERS_SORT_OPTIONS = [
  { value: 'username', label: 'Name' },
  { value: 'price', label: 'Price' },
  { value: 'post_count', label: 'Post Count' },
  { value: 'last_checked_at', label: 'Recently Checked' },
  { value: 'created_at', label: 'Created' },
  { value: 'id', label: 'ID' },
];

const FAVORITE_USERS_SORT_OPTIONS = USERS_SORT_OPTIONS.filter(
  (option) => option.value !== 'created_at'
);

export interface UsersPageProps {
  title?: string;
  subtitle?: string;
  icon?: React.ReactNode;
  favoriteOnly?: boolean;
}

export type { UserInfo, UsersListResponse };

export interface UsersStats {
  total: number;
  active: number;
  inactive: number;
  free: number;
  paid: number;
  avgPrice: string;
}

export const USER_FILTER_OPTIONS = [
  { key: 'performer', label: 'Performer' },
  { key: 'subscribed', label: 'Subscribed' },
] as const;

export type UserFilterKey = (typeof USER_FILTER_OPTIONS)[number]['key'];
export type UserFilterState = 'none' | 'include' | 'exclude';
export type UserFilterMap = Record<UserFilterKey, UserFilterState>;

export const DEFAULT_USER_FILTERS: UserFilterMap = {
  performer: 'include',
  subscribed: 'none',
};

export const SEX_FILTER_OPTIONS = [
  { value: -1, label: 'Unset' },
  { value: 0, label: 'Female' },
  { value: 1, label: 'Male' },
  { value: 2, label: 'Other' },
] as const;

export const GENDER_FILTER_OPTIONS = [
  { value: -1, label: 'Unset' },
  { value: 0, label: 'Woman' },
  { value: 1, label: 'Man' },
  { value: 2, label: 'Other' },
] as const;

export const PROFILE_TYPE_FILTER_OPTIONS = [
  { value: -1, label: 'Unset' },
  { value: 0, label: 'Solo' },
  { value: 1, label: 'Couple' },
  { value: 2, label: 'Group' },
  { value: 3, label: 'Other' },
] as const;

export const SEXUAL_CONTENT_FILTER_OPTIONS = [
  { value: -1, label: 'Unset' },
  { value: 0, label: 'Heterosexual (B/G)' },
  { value: 1, label: 'Lesbian (G/G)' },
  { value: 2, label: 'Gay (M/M)' },
  { value: 3, label: 'Bisexual' },
  { value: 4, label: 'Trans / Queer' },
  { value: 5, label: 'Solo' },
  { value: 6, label: 'Other' },
] as const;

export type { IdentityPreset };
export { formatCompactNumber as formatUserNumber, formatPrice as formatUserPrice };

export function userIdentityLabel(user: {
  sex?: number | null;
  gender?: number | null;
  partner_sex?: number | null;
  partner_gender?: number | null;
  profile_type?: number | null;
  sexual_content?: number | null;
}): string {
  if (user.sexual_content === 4) {
    if (user.gender === 0 || (user.sex === 1 && user.gender === 0)) {
      return '🏳️‍⚧️ Trans Woman';
    }
    if (user.gender === 1 || (user.sex === 0 && user.gender === 1)) {
      return '🏳️‍⚧️ Trans Man';
    }
    const s = sexLabel(user.sex ?? null);
    return s && s !== '—' ? `🏳️‍⚧️ Trans (${s})` : '🏳️‍⚧️ Trans';
  }
  if (user.sex === 1 && user.gender === 0) {
    return '🏳️‍⚧️ Trans Woman';
  }
  if (user.sex === 0 && user.gender === 1) {
    return '🏳️‍⚧️ Trans Man';
  }
  if (user.profile_type === 1) {
    if (user.sexual_content !== null && user.sexual_content !== undefined) {
      const label = sexualContentLabel(user.sexual_content);
      if (label !== '—') {
        return `Couple · ${label}`;
      }
    }
    if (user.partner_sex !== null && user.partner_sex !== undefined) {
      return `Couple (${sexLabel(user.sex ?? null)} & ${sexLabel(user.partner_sex)})`;
    }
    return 'Couple';
  }
  if (user.profile_type === 2) {
    return 'Group';
  }
  return sexLabel(user.sex ?? null);
}

export function parseBooleanParam(value: string | null, fallback: boolean): boolean {
  if (value === null) {
    return fallback;
  }
  return value === 'true' || value === '1';
}

export function parseIntListParam(value: string | null, allowed: number[]): number[] {
  if (!value) {
    return [];
  }

  const allowedSet = new Set(allowed);
  return value
    .split(',')
    .map((item) => Number(item))
    .filter((item) => Number.isInteger(item) && allowedSet.has(item));
}

export function buildUsersStats(
  usersData: UsersListResponse | undefined
): UsersStats | null {
  if (!usersData?.success || usersData.total == null) {
    return null;
  }

  return {
    total: usersData.total ?? 0,
    active: usersData.active ?? 0,
    inactive: usersData.inactive ?? 0,
    free: usersData.free ?? 0,
    paid: usersData.paid ?? 0,
    avgPrice: Number(usersData.avg_price ?? 0).toFixed(2),
  };
}

export function getUserDescription(user: UserInfo): string {
  if (!user.description) {
    return '';
  }
  return stripHtml(user.description).trim();
}

export function buildUsersLoadoutName(options: {
  selectedSite: string;
  searchQuery: string;
  searchTerm: string;
  searchDescriptionQuery: string;
  searchDescriptionTerm: string;
}) {
  const normalize = (value: string, maxLength: number) =>
    value.trim().replace(/\s+/g, ' ').slice(0, maxLength);

  const siteValue = normalize(options.selectedSite || 'all', 24) || 'all';
  const identifierValue = normalize(options.searchQuery || options.searchTerm, 36);
  const descriptionValue = normalize(
    options.searchDescriptionQuery || options.searchDescriptionTerm,
    36
  );
  const parts = [`site:${siteValue}`];

  if (identifierValue) {
    parts.push(`identifier:${identifierValue}`);
  }
  if (descriptionValue) {
    parts.push(`description:${descriptionValue}`);
  }

  return parts.join(' | ');
}

export function getUsersSortOptions(favoriteOnly = false) {
  return favoriteOnly ? FAVORITE_USERS_SORT_OPTIONS : USERS_SORT_OPTIONS;
}

export function normalizeUsersSortBy(
  sortBy: string | null | undefined,
  favoriteOnly = false
) {
  const sortOptions = getUsersSortOptions(favoriteOnly);
  return typeof sortBy === 'string' && sortOptions.some((option) => option.value === sortBy)
    ? sortBy
    : 'id';
}

export function applyUsersLoadoutState(
  loadout: SearchLoadoutItem,
  favoriteOnly = false
) {
  const identifier = loadout.identifier || '';
  const description = loadout.description || '';
  const siteValue = loadout.site || '';
  const filters = loadout.filters || {};
  const nextSex = Array.isArray(filters.sex)
    ? filters.sex
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && [-1, 0, 1, 2].includes(value))
    : [];
  const nextGender = Array.isArray(filters.gender)
    ? filters.gender
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && [-1, 0, 1, 2].includes(value))
    : [];

  const performerFilter: UserFilterState =
    filters.performer_filter === 'exclude' || filters.performer_filter === 'none'
      ? filters.performer_filter
      : 'include';
  const subscribedFilter: UserFilterState =
    filters.subscribed_filter === 'include' || filters.subscribed_filter === 'exclude'
      ? filters.subscribed_filter
      : 'none';
  const sortByValue = normalizeUsersSortBy(
    typeof filters.sort_by === 'string' ? filters.sort_by : null,
    favoriteOnly
  );
  const sortOrderValue: 'asc' | 'desc' = filters.sort_order === 'asc' ? 'asc' : 'desc';

  return {
    identifier,
    description,
    siteValue,
    nextSex,
    nextGender,
    performerFilter,
    subscribedFilter,
    sortByValue,
    sortOrderValue,
    minPrice: typeof filters.min_price === 'string' ? filters.min_price : '',
    maxPrice: typeof filters.max_price === 'string' ? filters.max_price : '',
    minPostCount:
      typeof filters.min_post_count === 'string' ? filters.min_post_count : '',
    maxPostCount:
      typeof filters.max_post_count === 'string' ? filters.max_post_count : '',
    minImageCount:
      typeof filters.min_image_count === 'string' ? filters.min_image_count : '',
    maxImageCount:
      typeof filters.max_image_count === 'string' ? filters.max_image_count : '',
    minVideoCount:
      typeof filters.min_video_count === 'string' ? filters.min_video_count : '',
    maxVideoCount:
      typeof filters.max_video_count === 'string' ? filters.max_video_count : '',
    activeOnly: typeof filters.active_only === 'boolean' ? filters.active_only : true,
  };
}
