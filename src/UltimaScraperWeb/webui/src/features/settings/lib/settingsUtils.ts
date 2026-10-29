import type { SettingsResponse } from '../../../api/types/settings';

export type WebUISettingsTab =
  | 'security'
  | 'connections'
  | 'appearance'
  | 'developer'
  | 'about';

export type SettingsTab =
  | WebUISettingsTab
  | 'general'
  | 'network'
  | 'redis'
  | 'directories'
  | 'sites'
  | 'database';

export type TopLevelSettingsKey =
  | keyof SettingsResponse
  | 'infinite_loop'
  | 'exit_on_completion';

export type MergeChoice = 'local' | 'remote';

export interface ConflictModalState {
  current: SettingsResponse;
  currentVersion: number | null;
  currentUpdatedAt: string | null;
  attemptedPatch: Record<string, unknown>;
  conflictingFields: string[];
}

export interface ConflictLeafEntry {
  path: string;
  pathParts: string[];
  topField: string;
  localValue: unknown;
  remoteValue: unknown;
  isConflict: boolean;
}

export const RESERVED_CONFLICT_FIELDS = new Set([
  'expected_version',
  'actor_backend_id',
  'request_id',
]);

export const WEBUI_TAB_META: Record<WebUISettingsTab, { label: string; description: string }> = {
  security: { label: 'Security & Access', description: 'WebUI password, active sessions and credentials' },
  connections: { label: 'Fleet Connections', description: 'Active scraper backends and auto-failover' },
  appearance: { label: 'Appearance & UI', description: 'Theme selection, visual density and telemetry polling' },
  developer: { label: 'Developer', description: 'Developer mode for plugins and mocks' },
  about: { label: 'About & Diagnostics', description: 'System versions, connected cluster and local state' },
};

export const TAB_META: Record<SettingsTab, { label: string; description: string }> = {
  security: { label: 'Security & Access', description: 'WebUI password, active sessions and credentials' },
  connections: { label: 'Fleet Connections', description: 'Active scraper backends and auto-failover' },
  appearance: { label: 'Appearance & UI', description: 'Theme selection, visual density and telemetry polling' },
  developer: { label: 'Developer', description: 'Developer mode for plugins and mocks' },
  about: { label: 'About & Diagnostics', description: 'System versions, connected cluster and local state' },
  general: { label: 'General', description: 'Identity and runtime behavior' },
  network: { label: 'Network', description: 'Workers and transfer throughput' },
  redis: { label: 'Redis', description: 'Distributed mode and queue behavior' },
  directories: { label: 'Directories', description: 'Download and metadata paths' },
  sites: { label: 'Sites', description: 'Per-platform scraping rules' },
  database: { label: 'Database', description: 'Direct row editing and backend mapping' },
};

export const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export const deepClone = <T,>(value: T): T => {
  if (value === undefined || value === null) return value;
  try {
    return JSON.parse(JSON.stringify(value)) as T;
  } catch {
    return value;
  }
};

export const mergePlainObjects = (
  base: Record<string, unknown>,
  patch: Record<string, unknown>,
): Record<string, unknown> => {
  const next: Record<string, unknown> = { ...deepClone(base) };
  for (const [key, value] of Object.entries(patch)) {
    const currentValue = next[key];
    if (isPlainObject(value) && isPlainObject(currentValue)) {
      next[key] = mergePlainObjects(currentValue, value);
      continue;
    }
    next[key] = deepClone(value);
  }
  return next;
};

export const setNestedObjectValue = (
  target: Record<string, unknown>,
  pathParts: string[],
  value: unknown,
) => {
  if (pathParts.length === 0) return;
  let cursor: Record<string, unknown> = target;
  for (let i = 0; i < pathParts.length - 1; i += 1) {
    const key = pathParts[i];
    const next = cursor[key];
    if (!isPlainObject(next)) {
      cursor[key] = {};
    }
    cursor = cursor[key] as Record<string, unknown>;
  }
  cursor[pathParts[pathParts.length - 1]] = value;
};

const valuesEqual = (left: unknown, right: unknown): boolean => {
  if (left === right) return true;
  try {
    return JSON.stringify(left) === JSON.stringify(right);
  } catch {
    return false;
  }
};

export function buildConflictLeafEntries(
  attemptedPatch: Record<string, unknown>,
  currentState: Record<string, unknown>,
  conflictingFields: string[],
): ConflictLeafEntry[] {
  const conflictTop = new Set(conflictingFields);
  const entries: ConflictLeafEntry[] = [];

  const walk = (
    localValue: unknown,
    remoteValue: unknown,
    pathParts: string[],
    topField: string,
  ) => {
    if (isPlainObject(localValue)) {
      const keys = Object.keys(localValue);
      if (keys.length === 0) {
        const path = pathParts.join('.');
        entries.push({
          path,
          pathParts,
          topField,
          localValue,
          remoteValue,
          isConflict: conflictTop.has(topField) && !valuesEqual(localValue, remoteValue),
        });
        return;
      }

      const remoteObject = isPlainObject(remoteValue) ? remoteValue : {};
      for (const key of keys) {
        walk(localValue[key], remoteObject[key], [...pathParts, key], topField);
      }
      return;
    }

    const path = pathParts.join('.');
    entries.push({
      path,
      pathParts,
      topField,
      localValue,
      remoteValue,
      isConflict: conflictTop.has(topField) && !valuesEqual(localValue, remoteValue),
    });
  };

  for (const [field, value] of Object.entries(attemptedPatch)) {
    if (RESERVED_CONFLICT_FIELDS.has(field)) continue;
    walk(value, currentState[field], [field], field);
  }

  return entries;
}

export function formatJson(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return 'null';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
