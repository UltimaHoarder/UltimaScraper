/**
 * The sites the backend scrapes, as it names them: the lower-case key the API
 * uses and the display name jobs take. Keep in step with the API's
 * ENABLED_SITES_LITERALS (LoyalFans has an archive but is switched off).
 */
export const SITES = [
  { key: 'onlyfans', label: 'OnlyFans', origin: 'https://onlyfans.com' },
  { key: 'fansly', label: 'Fansly', origin: 'https://fansly.com' },
  { key: 'privacy', label: 'Privacy', origin: 'https://privacy.com.br' },
  { key: 'darkfans', label: 'DarkFans', origin: 'https://darkfans.com' },
] as const;

export type SiteKey = (typeof SITES)[number]['key'];

const LABELS: Record<string, string> = {
  ...Object.fromEntries(SITES.map((site) => [site.key, site.label])),
  loyalfans: 'LoyalFans',
};

/** "OnlyFans" for "onlyfans" (any case); an unknown site comes back as given. */
export function siteLabel(site: string | null | undefined): string {
  const key = (site ?? '').trim().toLowerCase();
  return LABELS[key] ?? site ?? '';
}

/** A creator's page on the site itself, or null when the site is unknown. */
export function siteProfileUrl(site: string | null | undefined, username: string): string | null {
  const key = (site ?? '').trim().toLowerCase();
  const name = encodeURIComponent(username);
  switch (key) {
    case 'onlyfans':
    case 'fansly':
    case 'darkfans':
      return `${SITES.find((entry) => entry.key === key)!.origin}/${name}`;
    case 'privacy':
      return `https://privacy.com.br/profile/${name}`;
    default:
      return null;
  }
}
