// @vitest-environment node
import { describe, expect, it, beforeEach } from 'vitest';
import {
  getPersistedVolume,
  setPersistedVolume,
  getPersistedMuted,
  setPersistedMuted,
} from '../../src/components/videoPlayerStorage';

function createMockStorage(): Storage {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    length: store.size,
  };
}

describe('VideoPlayer volume persistence', () => {
  beforeEach(() => {
    setPersistedVolume(1.0);
    setPersistedMuted(false);
  });

  it('saves and retrieves volume level via memory fallback', () => {
    setPersistedVolume(0.65);
    expect(getPersistedVolume()).toBe(0.65);
  });

  it('clamps volume level strictly between 0 and 1', () => {
    setPersistedVolume(1.5);
    expect(getPersistedVolume()).toBe(1.0);

    setPersistedVolume(-0.2);
    expect(getPersistedVolume()).toBe(0);
  });

  it('saves and retrieves muted state via memory fallback', () => {
    setPersistedMuted(true);
    expect(getPersistedMuted()).toBe(true);

    setPersistedMuted(false);
    expect(getPersistedMuted()).toBe(false);
  });

  it('interacts correctly with localStorage when window.localStorage is present', () => {
    const mockLocalStorage = createMockStorage();
    Object.defineProperty(globalThis, 'window', {
      value: { localStorage: mockLocalStorage },
      writable: true,
      configurable: true,
    });

    setPersistedVolume(0.42);
    expect(mockLocalStorage.getItem('usr_video_player_volume')).toBe('0.42');
    expect(getPersistedVolume()).toBe(0.42);

    setPersistedMuted(true);
    expect(mockLocalStorage.getItem('usr_video_player_muted')).toBe('true');
    expect(getPersistedMuted()).toBe(true);

    setPersistedMuted(false);
    expect(mockLocalStorage.getItem('usr_video_player_muted')).toBe('false');
    expect(getPersistedMuted()).toBe(false);
  });
});
