import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// findBy*/waitFor default to 1s. Under parallel workers a full workspace can
// take longer to render, so the default failed different tests on each run
// without any assertion being wrong. Waits still resolve as soon as they pass.
configure({ asyncUtilTimeout: 5_000 });

class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

const localStorageMock = new MemoryStorage();
const sessionStorageMock = new MemoryStorage();

const cssMock = {
  supports: () => false,
  escape: (str: string) => str,
};

if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'localStorage', {
    value: localStorageMock,
    writable: true,
  });
  Object.defineProperty(window, 'sessionStorage', {
    value: sessionStorageMock,
    writable: true,
  });
  if (!window.CSS) {
    Object.defineProperty(window, 'CSS', {
      value: cssMock,
      writable: true,
    });
  } else if (typeof window.CSS.supports !== 'function') {
    window.CSS.supports = () => false;
  }
}
if (typeof globalThis !== 'undefined') {
  Object.defineProperty(globalThis, 'localStorage', {
    value: localStorageMock,
    writable: true,
  });
  Object.defineProperty(globalThis, 'sessionStorage', {
    value: sessionStorageMock,
    writable: true,
  });
  if (!(globalThis as { CSS?: unknown }).CSS) {
    Object.defineProperty(globalThis, 'CSS', {
      value: cssMock,
      writable: true,
    });
  }
}

if (typeof window !== 'undefined' && typeof window.HTMLMediaElement !== 'undefined') {
  window.HTMLMediaElement.prototype.load = () => {};
  window.HTMLMediaElement.prototype.play = async () => {};
  window.HTMLMediaElement.prototype.pause = () => {};
}

afterEach(() => {
  cleanup();
  try {
    localStorageMock.clear();
    sessionStorageMock.clear();
  } catch {
    // Ignored
  }
  vi.restoreAllMocks();
});

