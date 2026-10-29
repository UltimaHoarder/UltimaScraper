import { useQuery } from '@tanstack/react-query';
import type { UserCardItem } from '../../components/users/UserCard';

export type CachedUserCard = UserCardItem & { authoritative?: boolean };
export const userCardKey = (site: string, userId: number) => ['user-card', site.toLowerCase(), userId] as const;
export const profileVersion = (item: Pick<UserCardItem, 'last_checked_at'>) => {
  const value = Date.parse(item.last_checked_at || '');
  return Number.isFinite(value) ? value : 0;
};
const profileFields = ['username', 'name', 'description', 'sex', 'gender', 'profile_type',
  'sexual_content', 'partner_sex', 'partner_gender', 'ai_assisted', 'verified', 'avatar_url',
  'header_url', 'price', 'post_count', 'image_count', 'video_count', 'last_checked_at'] as const;

/** Cached page data renders synchronously; completion hints update this shared observer. */
export function useCachedUserCard<T extends UserCardItem>(item: T, preserveAvailability = false): T {
  const { data } = useQuery<CachedUserCard>({ queryKey: userCardKey(item.site, item.user_id),
    enabled: false, initialData: item, gcTime: 5 * 60_000 });
  if (!data?.authoritative || profileVersion(data) < profileVersion(item)) return item;
  const merged = { ...item };
  for (const field of profileFields) {
    if (field in data) Object.assign(merged, { [field]: data[field] });
  }
  if (!preserveAvailability) merged.is_active = data.is_active;
  return merged;
}
