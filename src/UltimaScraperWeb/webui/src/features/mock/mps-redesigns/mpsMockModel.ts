import { useMemo, useState } from 'react';

export type MockSite = 'OnlyFans' | 'Fansly' | 'LoyalFans';
export type MockProxyMode = 'none' | 'unassigned_only' | 'all' | 'custom';

export interface MockMpsConfig {
  site: MockSite;
  startId: number;
  endId: number;
  includeMissing: boolean;
  includeInvalid: boolean;
  includeExisting: boolean;
  recheckDays: number;
  batchSize: number;
  proxyMode: MockProxyMode;
  includeDirect: boolean;
  maxRouteHops: number;
  missThreshold: number;
  jobName: string;
}

export interface MockProxyRoute {
  id: string;
  label: string;
  region: string;
  latencyMs: number;
  assigned: boolean;
  healthy: boolean;
}

export interface MockRange {
  startId: number;
  endId: number;
  count: number;
}

export interface MockBucket {
  startId: number;
  endId: number;
  missing: number;
  invalid: number;
  existing: number;
  total: number;
}

export interface MockMpsDerived {
  rangeSize: number;
  missing: number;
  invalidTotal: number;
  invalidEligible: number;
  existingTotal: number;
  existingEligible: number;
  candidates: number;
  selected: number;
  batches: number;
  rangeCount: number;
  averageRange: number;
  routes: MockProxyRoute[];
  routeCount: number;
  profilesPerRoute: number;
  minutesPerBatch: number;
  minutesTotal: number;
  ranges: MockRange[];
  warnings: string[];
  sourceCount: number;
}

export interface MockMpsModel {
  config: MockMpsConfig;
  derived: MockMpsDerived;
  update: (patch: Partial<MockMpsConfig>) => void;
  setSite: (site: MockSite) => void;
  reset: () => void;
}

export const MOCK_SITES: readonly MockSite[] = ['OnlyFans', 'Fansly', 'LoyalFans'];

export const SITE_PROFILES: Record<
  MockSite,
  { minId: number; maxId: number; missingRate: number; invalidRate: number; existingRate: number; seed: number }
> = {
  OnlyFans: { minId: 1, maxId: 412_000_000, missingRate: 0.028, invalidRate: 0.012, existingRate: 0.064, seed: 7 },
  Fansly: { minId: 1, maxId: 96_000_000, missingRate: 0.041, invalidRate: 0.009, existingRate: 0.048, seed: 13 },
  LoyalFans: { minId: 1, maxId: 18_500_000, missingRate: 0.062, invalidRate: 0.017, existingRate: 0.09, seed: 29 },
};

export const PROXY_MODE_LABELS: Record<MockProxyMode, string> = {
  none: 'Direct only',
  unassigned_only: 'Unassigned proxies',
  all: 'All healthy proxies',
  custom: 'Custom list',
};

export const MOCK_PROXIES: readonly MockProxyRoute[] = [
  { id: 'px-01', label: 'res-ams-01', region: 'NL', latencyMs: 84, assigned: false, healthy: true },
  { id: 'px-02', label: 'res-ams-02', region: 'NL', latencyMs: 91, assigned: true, healthy: true },
  { id: 'px-03', label: 'dc-fra-11', region: 'DE', latencyMs: 46, assigned: false, healthy: true },
  { id: 'px-04', label: 'dc-fra-12', region: 'DE', latencyMs: 52, assigned: false, healthy: true },
  { id: 'px-05', label: 'res-lon-04', region: 'GB', latencyMs: 73, assigned: true, healthy: true },
  { id: 'px-06', label: 'res-lon-05', region: 'GB', latencyMs: 69, assigned: false, healthy: true },
  { id: 'px-07', label: 'mob-nyc-02', region: 'US', latencyMs: 132, assigned: false, healthy: true },
  { id: 'px-08', label: 'mob-nyc-03', region: 'US', latencyMs: 148, assigned: true, healthy: true },
  { id: 'px-09', label: 'dc-lax-07', region: 'US', latencyMs: 118, assigned: false, healthy: false },
  { id: 'px-10', label: 'dc-lax-08', region: 'US', latencyMs: 109, assigned: false, healthy: true },
  { id: 'px-11', label: 'res-sgp-01', region: 'SG', latencyMs: 211, assigned: true, healthy: true },
  { id: 'px-12', label: 'res-syd-02', region: 'AU', latencyMs: 236, assigned: false, healthy: true },
  { id: 'px-13', label: 'dc-waw-03', region: 'PL', latencyMs: 58, assigned: false, healthy: true },
  { id: 'px-14', label: 'dc-waw-04', region: 'PL', latencyMs: 61, assigned: true, healthy: true },
];

export const DIRECT_ROUTE: MockProxyRoute = {
  id: 'direct',
  label: 'Direct (raw IP)',
  region: '—',
  latencyMs: 38,
  assigned: false,
  healthy: true,
};

/** Profiles a single lookup route resolves per minute in the mock throughput model. */
const PROFILES_PER_ROUTE_MINUTE = 42;

export function defaultConfig(site: MockSite = 'OnlyFans'): MockMpsConfig {
  const bounds = SITE_PROFILES[site];
  const span = Math.round((bounds.maxId - bounds.minId) * 0.03);
  return {
    site,
    startId: bounds.maxId - span,
    endId: bounds.maxId,
    includeMissing: true,
    includeInvalid: false,
    includeExisting: false,
    recheckDays: 7,
    batchSize: 5_000,
    proxyMode: 'unassigned_only',
    includeDirect: false,
    maxRouteHops: 3,
    missThreshold: 3,
    jobName: '',
  };
}

export function fmt(value: number): string {
  return Math.round(value).toLocaleString();
}

const compactFormatter = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

export function compact(value: number): string {
  return compactFormatter.format(value);
}

export function formatMinutes(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes <= 0) return '—';
  if (minutes < 1) return '<1 min';
  if (minutes < 90) return `${Math.round(minutes)} min`;
  const hours = minutes / 60;
  if (hours < 48) return `${hours.toFixed(1)} h`;
  return `${(hours / 24).toFixed(1)} d`;
}

/** Smooth deterministic noise in [0, 1] so the ID-space map stays stable while zooming. */
export function densityAt(site: MockSite, id: number): number {
  const { seed, maxId } = SITE_PROFILES[site];
  const x = (id / maxId) * 40;
  const value =
    0.5 +
    0.26 * Math.sin(x * 1.7 + seed) +
    0.16 * Math.sin(x * 5.3 + seed * 2.1) +
    0.08 * Math.sin(x * 17.9 + seed * 0.7);
  return Math.min(1, Math.max(0.02, value));
}

function recheckEligibility(days: number): number {
  if (days <= 0) return 1;
  return Math.max(0.08, 1 - Math.log10(1 + days) / 2.2);
}

export function selectRoutes(mode: MockProxyMode, includeDirect: boolean): MockProxyRoute[] {
  const healthy = MOCK_PROXIES.filter((proxy) => proxy.healthy);
  let routes: MockProxyRoute[];
  switch (mode) {
    case 'none':
      routes = [];
      break;
    case 'unassigned_only':
      routes = healthy.filter((proxy) => !proxy.assigned);
      break;
    case 'all':
      routes = healthy;
      break;
    case 'custom':
      routes = healthy.slice(2, 6);
      break;
  }
  return includeDirect || mode === 'none' ? [DIRECT_ROUTE, ...routes] : routes;
}

export function bucketize(config: MockMpsConfig, viewStart: number, viewEnd: number, count: number): MockBucket[] {
  const profile = SITE_PROFILES[config.site];
  const eligibility = recheckEligibility(config.recheckDays);
  const width = Math.max(1, (viewEnd - viewStart + 1) / count);
  return Array.from({ length: count }, (_, index) => {
    const startId = Math.round(viewStart + index * width);
    const endId = Math.round(viewStart + (index + 1) * width) - 1;
    const size = endId - startId + 1;
    const density = densityAt(config.site, (startId + endId) / 2);
    const missing = Math.round(size * profile.missingRate * density * 2);
    const invalid = Math.round(size * profile.invalidRate * (1.2 - density) * eligibility);
    const existing = Math.round(size * profile.existingRate * (0.4 + density * 0.6) * eligibility);
    return { startId, endId, missing, invalid, existing, total: missing + invalid + existing };
  });
}

export function deriveMock(config: MockMpsConfig): MockMpsDerived {
  const profile = SITE_PROFILES[config.site];
  const rangeSize = Math.max(0, config.endId - config.startId + 1);
  const eligibility = recheckEligibility(config.recheckDays);

  const missing = Math.round(rangeSize * profile.missingRate);
  const invalidTotal = Math.round(rangeSize * profile.invalidRate);
  const invalidEligible = Math.round(invalidTotal * eligibility);
  const existingTotal = Math.round(rangeSize * profile.existingRate);
  const existingEligible = Math.round(existingTotal * eligibility);

  const candidates =
    (config.includeMissing ? missing : 0) +
    (config.includeInvalid ? invalidEligible : 0) +
    (config.includeExisting ? existingEligible : 0);
  const batchSize = Math.max(1, config.batchSize);
  const selected = Math.min(batchSize, candidates);
  const batches = candidates > 0 ? Math.ceil(candidates / batchSize) : 0;
  const rangeCount = candidates > 0 ? Math.max(1, Math.round(candidates / 46)) : 0;
  const averageRange = rangeCount > 0 ? Math.round(candidates / rangeCount) : 0;

  const routes = selectRoutes(config.proxyMode, config.includeDirect);
  const routeCount = routes.length;
  const profilesPerRoute = routeCount > 0 ? selected / routeCount : selected;
  const throughput = Math.max(1, routeCount) * PROFILES_PER_ROUTE_MINUTE;

  const ranges: MockRange[] = [];
  if (candidates > 0 && rangeSize > 0) {
    const step = rangeSize / 10;
    for (let index = 0; index < 10; index += 1) {
      const anchor = config.startId + Math.round(step * index + step * densityAt(config.site, config.startId + step * index) * 0.6);
      const span = Math.max(1, Math.round(step * 0.08 * (0.5 + densityAt(config.site, anchor))));
      const endId = Math.min(config.endId, anchor + span);
      ranges.push({ startId: anchor, endId, count: Math.max(1, Math.round((endId - anchor) * profile.missingRate * 3)) });
    }
  }

  const warnings: string[] = [];
  if (!config.includeMissing && !config.includeInvalid && !config.includeExisting) {
    warnings.push('No candidate source is selected.');
  }
  if (config.proxyMode === 'none' && selected >= 2_500) {
    warnings.push(`Only the direct connection is selected for ${fmt(selected)} queued profiles. Consider smaller batches or enabling proxies.`);
  } else if (profilesPerRoute >= 1_000) {
    warnings.push(`About ${fmt(profilesPerRoute)} profiles per lookup route. Reduce the batch or increase proxy coverage.`);
  }
  if (config.includeExisting && config.recheckDays < 1) {
    warnings.push('Existing profiles have no cooldown — every stored profile in range will be re-fetched.');
  }

  return {
    rangeSize,
    missing,
    invalidTotal,
    invalidEligible,
    existingTotal,
    existingEligible,
    candidates,
    selected,
    batches,
    rangeCount,
    averageRange,
    routes,
    routeCount,
    profilesPerRoute,
    minutesPerBatch: selected / throughput,
    minutesTotal: candidates / throughput,
    ranges,
    warnings,
    sourceCount: [config.includeMissing, config.includeInvalid, config.includeExisting].filter(Boolean).length,
  };
}

export function useMockMpsModel(): MockMpsModel {
  const [config, setConfig] = useState<MockMpsConfig>(() => defaultConfig());
  const derived = useMemo(() => deriveMock(config), [config]);

  return {
    config,
    derived,
    update: (patch) => setConfig((current) => ({ ...current, ...patch })),
    setSite: (site) => setConfig((current) => ({ ...defaultConfig(site), batchSize: current.batchSize, proxyMode: current.proxyMode })),
    reset: () => setConfig(defaultConfig()),
  };
}

export function describeSources(config: MockMpsConfig): string {
  const parts = [
    config.includeMissing ? 'new / missing IDs' : null,
    config.includeInvalid ? 'previously not-found' : null,
    config.includeExisting ? 'existing profiles' : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(' + ') : 'no sources';
}

export function jobLabel(config: MockMpsConfig): string {
  return config.jobName.trim() || `MPS ${config.site} ${compact(config.startId)}–${compact(config.endId)}`;
}

export interface ConceptProps {
  model: MockMpsModel;
  onLaunch: (summary: string) => void;
}
