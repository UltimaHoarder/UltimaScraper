import { formatPrice as formatUsd } from '../../../shared/lib/format';

export const ORDERS_LIVE_REFRESH_MS = 5000;

export const statusOrder: Record<string, number> = {
  running: 0,
  pending: 1,
  incomplete: 2,
  completed: 3,
  failed: 4,
};

export function formatPrice(price: number | null) {
  if (price === null || Number.isNaN(price)) {
    return '—';
  }
  return formatUsd(price);
}

export function formatDate(value: string | null) {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day} ${hour}:${minute}`;
}
