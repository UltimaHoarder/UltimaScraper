import { useEffect, useCallback, useSyncExternalStore } from 'react';

export interface WebUIPreferences {
  compactMode: boolean;
  telemetryPollRate: number; // in milliseconds (e.g. 1000, 3000, 10000)
  toastDuration: number; // in milliseconds (e.g. 3000, 5000, 8000)
  autoFailover: boolean;
  confirmDestructiveActions: boolean;
  enableSoundCues: boolean;
  // Turns on plugins and the design lab mocks.
  devMode: boolean;
}

export const DEFAULT_PREFERENCES: WebUIPreferences = {
  compactMode: false,
  telemetryPollRate: 3000,
  toastDuration: 4000,
  autoFailover: true,
  confirmDestructiveActions: true,
  enableSoundCues: false,
  devMode: false,
};

const STORAGE_KEY = 'usr_webui_preferences';

function readRaw(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function parsePreferences(raw: string | null): WebUIPreferences {
  if (!raw) return DEFAULT_PREFERENCES;
  try {
    const parsed = JSON.parse(raw) as Partial<WebUIPreferences>;
    return { ...DEFAULT_PREFERENCES, ...parsed };
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

// Every reader shares one parsed copy, re-parsed only when storage changes, so
// a change in Settings reaches the navigation and plugin host straight away.
let cached: { raw: string | null; value: WebUIPreferences } | null = null;
const listeners = new Set<() => void>();

function getPreferences(): WebUIPreferences {
  const raw = readRaw();
  if (cached?.raw !== raw) cached = { raw, value: parsePreferences(raw) };
  return cached.value;
}

function notify() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Another tab changed the preferences.
  window.addEventListener('storage', listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', listener);
  };
}

export function useDevMode(): boolean {
  return useSyncExternalStore(subscribe, () => getPreferences().devMode);
}

export function useWebUIPreferences() {
  const preferences = useSyncExternalStore(subscribe, getPreferences);

  useEffect(() => {
    // Apply compact density attribute to document element for global CSS hooks
    if (preferences.compactMode) {
      document.documentElement.dataset.density = 'compact';
    } else {
      delete document.documentElement.dataset.density;
    }
  }, [preferences.compactMode]);

  const updatePreferences = useCallback((patch: Partial<WebUIPreferences>) => {
    const next = { ...getPreferences(), ...patch };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Storage might be unavailable/full; keep the change for this page.
      cached = { raw: readRaw(), value: next };
    }
    notify();
  }, []);

  const resetPreferences = useCallback(() => {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore
    }
    cached = { raw: readRaw(), value: DEFAULT_PREFERENCES };
    notify();
  }, []);

  return {
    preferences,
    updatePreferences,
    resetPreferences,
  };
}
