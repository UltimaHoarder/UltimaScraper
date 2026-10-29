export interface SubscriptionCountdown {
  value: string;
  detail: string;
  tone: 'active' | 'expired' | 'neutral';
}

export interface UserOverviewVersionData {
  description: string;
  price: number;
  media_count: number;
  audio_count: number;
  stream_count: number;
  archived_post_count: number;
  favourited_count: number;
  subscribers_count: number;
  location: string | null;
  website: string | null;
  sex: number | null;
  join_date: string | null;
  last_checked_at: string | null;
  downloaded_at: string | null;
  first_downloaded_at: string | null;
  created_at: string | null;
}

export interface UserOverviewVersion {
  key: string;
  label: string;
  createdAt: string | null;
  data: UserOverviewVersionData;
}

export function decodeHtmlEntities(value: string): string {
  const doc = new DOMParser().parseFromString(value, 'text/html');
  return doc.documentElement.textContent || value;
}

export { formatBytes, formatCompactNumber as formatNumber, formatPrice } from '../../../shared/lib/format';

export function formatRelativeTime(isoDate: string | null): string {
  if (!isoDate) return 'Never';
  const date = new Date(isoDate);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);
  const diffDays = Math.floor(diffMs / 86_400_000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
  return `${Math.floor(diffDays / 365)}y ago`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatDuration(diffMs: number): string {
  const totalMinutes = Math.max(0, Math.floor(diffMs / 60_000));
  const days = Math.floor(totalMinutes / (60 * 24));
  const hours = Math.floor((totalMinutes % (60 * 24)) / 60);
  const minutes = totalMinutes % 60;

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m`;
  return '<1m';
}

export function getSubscriptionCountdown(
  expiresAt: string | null,
  isSubscribed: boolean,
  nowMs: number
): SubscriptionCountdown {
  if (!expiresAt) {
    return {
      value: 'N/A',
      detail: isSubscribed ? 'Subscription expiry unavailable' : 'No subscription expiry',
      tone: 'neutral',
    };
  }

  const expiresMs = new Date(expiresAt).getTime();
  if (Number.isNaN(expiresMs)) {
    return {
      value: 'Unknown',
      detail: 'Invalid expiry timestamp',
      tone: 'neutral',
    };
  }

  const diffMs = expiresMs - nowMs;
  if (diffMs <= 0) {
    return {
      value: `${formatDuration(Math.abs(diffMs))} ago`,
      detail: `Expired ${formatDateTime(expiresAt)}`,
      tone: 'expired',
    };
  }

  return {
    value: formatDuration(diffMs),
    detail: `Expires ${formatDateTime(expiresAt)}`,
    tone: 'active',
  };
}

export function sexLabel(sex: number | null): string {
  if (sex === 0) return 'Female';
  if (sex === 1) return 'Male';
  if (sex === 2) return 'Other';
  return '—';
}

export function genderLabel(gender: number | null): string {
  if (gender === 0) return 'Woman';
  if (gender === 1) return 'Man';
  if (gender === 2) return 'Other';
  return '—';
}

export function profileTypeLabel(profileType: number | null | undefined): string {
  if (profileType === 0) return 'Solo';
  if (profileType === 1) return 'Couple';
  if (profileType === 2) return 'Group';
  if (profileType === 3) return 'Other';
  return '—';
}

export function sexualContentLabel(sexualContent: number | null | undefined): string {
  if (sexualContent === 0) return 'Heterosexual (B/G)';
  if (sexualContent === 1) return 'Lesbian (G/G)';
  if (sexualContent === 2) return 'Gay (M/M)';
  if (sexualContent === 3) return 'Bisexual';
  if (sexualContent === 4) return 'Trans / Queer';
  if (sexualContent === 5) return 'Solo';
  if (sexualContent === 6) return 'Other';
  return '—';
}

export interface IdentityPreset {
  id: string;
  label: string;
  category: 'solo' | 'couple';
  profileType: number;
  sexualContent: number;
  sex: number;
  gender: number;
  partnerSex: number | null;
  partnerGender: number | null;
}

export const IDENTITY_PRESETS: IdentityPreset[] = [
  // Solo Presets
  {
    id: 'cis_woman',
    label: 'Cis Woman',
    category: 'solo',
    profileType: 0,
    sexualContent: 5,
    sex: 0,
    gender: 0,
    partnerSex: null,
    partnerGender: null,
  },
  {
    id: 'cis_man',
    label: 'Cis Man',
    category: 'solo',
    profileType: 0,
    sexualContent: 5,
    sex: 1,
    gender: 1,
    partnerSex: null,
    partnerGender: null,
  },
  {
    id: 'trans_woman',
    label: 'Trans Woman',
    category: 'solo',
    profileType: 0,
    sexualContent: 4,
    sex: 1,
    gender: 0,
    partnerSex: null,
    partnerGender: null,
  },
  {
    id: 'trans_man',
    label: 'Trans Man',
    category: 'solo',
    profileType: 0,
    sexualContent: 4,
    sex: 0,
    gender: 1,
    partnerSex: null,
    partnerGender: null,
  },
  // Couple Presets
  {
    id: 'straight_couple',
    label: 'Straight Couple (F/M)',
    category: 'couple',
    profileType: 1,
    sexualContent: 0,
    sex: 0,
    gender: 0,
    partnerSex: 1,
    partnerGender: 1,
  },
  {
    id: 'lesbian_couple',
    label: 'Lesbian Couple (F/F)',
    category: 'couple',
    profileType: 1,
    sexualContent: 1,
    sex: 0,
    gender: 0,
    partnerSex: 0,
    partnerGender: 0,
  },
  {
    id: 'gay_couple',
    label: 'Gay Couple (M/M)',
    category: 'couple',
    profileType: 1,
    sexualContent: 2,
    sex: 1,
    gender: 1,
    partnerSex: 1,
    partnerGender: 1,
  },
  {
    id: 'trans_couple',
    label: 'Trans / Queer Couple',
    category: 'couple',
    profileType: 1,
    sexualContent: 4,
    sex: 1,
    gender: 0,
    partnerSex: 0,
    partnerGender: 0,
  },
];

export function getSocialUrl(site: string, identifier: string): string | null {
  const normalizedSite = site.trim().toLowerCase();
  const normalizedIdentifier = identifier.trim().replace(/^@/, '');
  if (!normalizedIdentifier) return null;

  if (/^https?:\/\//i.test(identifier.trim())) {
    return identifier.trim();
  }
  if (normalizedSite === 'x' || normalizedSite === 'twitter') {
    return `https://x.com/${normalizedIdentifier}`;
  }
  if (normalizedSite === 'instagram') {
    return `https://www.instagram.com/${normalizedIdentifier}`;
  }
  if (normalizedSite === 'tiktok') {
    return `https://www.tiktok.com/@${normalizedIdentifier}`;
  }
  if (normalizedSite === 'youtube') {
    return `https://www.youtube.com/@${normalizedIdentifier}`;
  }
  if (normalizedSite === 'reddit') {
    return `https://www.reddit.com/user/${normalizedIdentifier}`;
  }
  if (normalizedSite === 'snapchat') {
    return `https://www.snapchat.com/add/${normalizedIdentifier}`;
  }
  if (normalizedSite === 'threads') {
    return `https://www.threads.net/@${normalizedIdentifier}`;
  }
  if (normalizedSite === 'facebook') {
    return `https://www.facebook.com/${normalizedIdentifier}`;
  }
  if (normalizedSite === 'twitch') {
    return `https://www.twitch.tv/${normalizedIdentifier}`;
  }
  if (normalizedSite === 'linktree') {
    return `https://linktr.ee/${normalizedIdentifier}`;
  }
  return null;
}

export const CONTENT_TYPES = [
  { value: '', label: 'All' },
  { value: 'post', label: 'Posts' },
  { value: 'story', label: 'Stories' },
  { value: 'message', label: 'Messages' },
  { value: 'mass_message', label: 'Mass Messages' },
];

export const PAID_CONTENT_TYPES = [
  { value: '', label: 'All' },
  { value: 'post', label: 'Posts' },
  { value: 'message', label: 'Messages' },
  { value: 'mass_message', label: 'Mass Messages' },
] as const;

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
