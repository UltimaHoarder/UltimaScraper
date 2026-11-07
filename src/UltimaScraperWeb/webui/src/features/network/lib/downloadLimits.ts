import type { DownloadLimits } from '../hooks/useNetworkDownloadLimits';

export const DOWNLOAD_LIMIT_KEYS = [
  'max_concurrency',
  'per_domain_concurrency',
  'head_concurrency',
] as const satisfies readonly (keyof DownloadLimits)[];

export type DownloadLimitsDraft = Record<keyof DownloadLimits, string>;

export function toDownloadLimitsDraft(limits: DownloadLimits): DownloadLimitsDraft {
  return {
    max_concurrency: String(limits.max_concurrency),
    per_domain_concurrency: String(limits.per_domain_concurrency),
    head_concurrency: String(limits.head_concurrency),
  };
}

/** The draft as limits, or null while any field isn't a whole number of at least 1. */
export function parseDownloadLimits(draft: DownloadLimitsDraft): DownloadLimits | null {
  const values = DOWNLOAD_LIMIT_KEYS.map((key) => {
    const raw = draft[key].trim();
    return /^\d+$/.test(raw) ? Number(raw) : Number.NaN;
  });
  if (values.some((value) => !Number.isSafeInteger(value) || value < 1)) {
    return null;
  }
  const [max_concurrency, per_domain_concurrency, head_concurrency] = values;
  return { max_concurrency, per_domain_concurrency, head_concurrency };
}
