import type { SubscriptionInfo } from '../../../api/types/subscriptions';

export const SUBSCRIPTION_SORT_OPTIONS = [
  { value: 'id', label: 'ID' },
  { value: 'created_at', label: 'Created' },
  { value: 'expires_at', label: 'Expires At' },
  { value: 'username', label: 'Name' },
  { value: 'price', label: 'Price' },
  { value: 'post_count', label: 'Post Count' },
];

export { formatCompactNumber as formatNumber, formatPrice } from '../../../shared/lib/format';

export function getSubscriptionKey(sub: SubscriptionInfo) {
  return `${sub.site}-${sub.id}`;
}
