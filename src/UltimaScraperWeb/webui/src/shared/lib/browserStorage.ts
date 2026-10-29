/**
 * Best-effort Web Storage access.
 *
 * Storage can be missing or throw on access (privacy modes, blocked site data,
 * exceeded quota). Persisted values are conveniences, so failures degrade to
 * "nothing stored" instead of breaking rendering or startup.
 */
type StorageArea = 'local' | 'session';

function storageFor(area: StorageArea): Storage | null {
  try {
    if (typeof window === 'undefined') return null;
    return area === 'local' ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readStorage(key: string, area: StorageArea = 'local'): string | null {
  try {
    return storageFor(area)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

/** Returns whether the value was stored. */
export function writeStorage(key: string, value: string, area: StorageArea = 'local'): boolean {
  try {
    const storage = storageFor(area);
    if (!storage) return false;
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function removeStorage(key: string, area: StorageArea = 'local'): void {
  try {
    storageFor(area)?.removeItem(key);
  } catch {
    // Nothing to clean up when storage is unavailable.
  }
}
