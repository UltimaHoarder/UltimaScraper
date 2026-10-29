import { afterEach, describe, expect, it, vi } from 'vitest';

import { loadStoredThemeId, persistThemeId } from '../../src/app/theme/theme-storage';
import {
  hasMigrationCheckForStartup,
  recordMigrationCheckForStartup,
} from '../../src/app/bootstrap/startupMigrationState';
import { readStorage, removeStorage, writeStorage } from '../../src/shared/lib/browserStorage';

function blockStorage() {
  const denied = () => {
    throw new DOMException('Storage is disabled', 'SecurityError');
  };
  for (const storage of [window.localStorage, window.sessionStorage]) {
    vi.spyOn(storage, 'getItem').mockImplementation(denied);
    vi.spyOn(storage, 'setItem').mockImplementation(denied);
    vi.spyOn(storage, 'removeItem').mockImplementation(denied);
  }
}

describe('browserStorage', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    sessionStorage.clear();
  });

  it('round-trips values in local and session storage', () => {
    expect(writeStorage('key', 'local-value')).toBe(true);
    expect(writeStorage('key', 'session-value', 'session')).toBe(true);

    expect(readStorage('key')).toBe('local-value');
    expect(readStorage('key', 'session')).toBe('session-value');

    removeStorage('key');
    expect(readStorage('key')).toBeNull();
  });

  it('degrades to empty storage when access throws', () => {
    blockStorage();

    expect(readStorage('key')).toBeNull();
    expect(writeStorage('key', 'value')).toBe(false);
    expect(() => removeStorage('key')).not.toThrow();
  });

  it('keeps theme and startup bookkeeping usable when storage is blocked', () => {
    blockStorage();

    expect(loadStoredThemeId('ultima-atlas')).toBe('ultima-atlas');
    expect(() => persistThemeId('ultima-atlas')).not.toThrow();
    expect(() => recordMigrationCheckForStartup('startup-1')).not.toThrow();
    expect(hasMigrationCheckForStartup('startup-1')).toBe(false);
  });
});
