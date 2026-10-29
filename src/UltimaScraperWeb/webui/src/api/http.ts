import axios, { type AxiosInstance } from 'axios';

import { reportServedBy } from './failover';

/*
 * The page is always served by, or through, the WebUI server
 * (ultima_webui_server). It signs the browser in and adds each backend's admin
 * token itself, so the page holds no token and reaches the backend it shows
 * through /b/{connection}.
 */

const LEGACY_ADMIN_TOKEN_KEY = 'usr_admin_token';
const PROTECTED_PATH_PREFIX = '/api/v1';
const CONNECTION_PATH = /^\/b\/([^/]+)/;

/** The connection in a /b/{connection}/... path, if any. */
export function connectionIdFromPath(pathname: string): string | null {
  const match = CONNECTION_PATH.exec(pathname);
  return match ? decodeURIComponent(match[1]) : null;
}

let scopedConnectionId: string | null = null;

/** Sets a fallback connection ID when BackendScope is mounted outside /b/{id} (e.g. inline in /setup). */
export function setScopedConnectionId(connectionId: string | null): void {
  scopedConnectionId = connectionId;
}

/** The backend connection in the page's /b/{connection} path, or the active BackendScope fallback. */
export function getActiveConnectionId(): string | null {
  if (typeof window === 'undefined') return scopedConnectionId;
  const path = window.location.pathname;
  const pathId = connectionIdFromPath(path);
  if (pathId) return pathId;
  if (scopedConnectionId) return scopedConnectionId;
  if (path === '/connections' || path.startsWith('/connections/') || path === '/setup' || path.startsWith('/setup/')) {
    return null;
  }
  return 'default';
}

const LOCATION_CHANGE_EVENT = 'usr:location-change';

/**
 * Moves to another WebUI page without reloading, e.g. to another backend's
 * /b/{connection}/. Components that depend on the path subscribe with
 * subscribeToLocation; React Router inside one backend handles its own routes.
 */
export function navigateTo(path: string, { replace = false }: { replace?: boolean } = {}): void {
  if (replace) window.history.replaceState(null, '', path);
  else window.history.pushState(null, '', path);
  window.dispatchEvent(new Event(LOCATION_CHANGE_EVENT));
}

/** Called after navigateTo and on back/forward. */
export function subscribeToLocation(listener: () => void): () => void {
  window.addEventListener('popstate', listener);
  window.addEventListener(LOCATION_CHANGE_EVENT, listener);
  return () => {
    window.removeEventListener('popstate', listener);
    window.removeEventListener(LOCATION_CHANGE_EVENT, listener);
  };
}

/** A storage key for data that belongs to the active backend, not the browser. */
export function connectionScopedKey(key: string): string {
  const connectionId = getActiveConnectionId();
  return !connectionId || connectionId === 'default' ? key : `${key}@${connectionId}`;
}

/** The /b/{connection} path prefix of the active backend ('' when none or local default). */
export function getConnectionBasePath(): string {
  const connectionId = getActiveConnectionId();
  return connectionId && connectionId !== 'default' ? `/b/${encodeURIComponent(connectionId)}` : '';
}

function isAbsoluteUrl(url: string): boolean {
  return /^[a-zA-Z][a-zA-Z\d+.-]*:/.test(url);
}

/** A root-relative backend path such as /api/v1/... routed to the active backend. */
export function apiUrl(path: string): string {
  return path.startsWith('/') ? `${getConnectionBasePath()}${path}` : path;
}

/**
 * A root-relative app route (e.g. /users/1) kept on the active backend's page.
 * Only for plain links and window.location; router links use the basename.
 */
export function appUrl(path: string): string {
  return path.startsWith('/') ? `${getConnectionBasePath()}${path}` : path;
}

/** Resolves a backend path against the active backend, keeping its /b/ prefix. */
export function resolveApiUrl(path: string): URL {
  return new URL(apiUrl(path), window.location.origin);
}

/** A URL for media, sockets or downloads: backend paths go to the active backend. */
export function backendUrl(url: string): string {
  return isAbsoluteUrl(url) ? url : apiUrl(url);
}

/**
 * A URL a backend returned, such as /api/v1/media/stream/..., made to reach
 * that backend. Other URLs (CDNs, app assets) are returned unchanged.
 */
export function backendResourceUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (isAbsoluteUrl(url)) return url;
  const { pathname } = new URL(url, window.location.origin);
  const isBackendPath = pathname === PROTECTED_PATH_PREFIX || pathname.startsWith(`${PROTECTED_PATH_PREFIX}/`);
  return isBackendPath ? apiUrl(url) : url;
}

export function getApiBaseUrl(): string {
  if (typeof window === 'undefined') return 'http://localhost';
  return `${window.location.origin}${getConnectionBasePath()}`;
}

export function getWebSocketBaseUrl(): string {
  return getApiBaseUrl().replace(/^http/, 'ws');
}

/**
 * The WebUI once kept the backend's admin token in the browser. The server
 * holds it now; remove any copy an older WebUI saved.
 */
export function forgetTokenFromBeforeWebUIServer(): void {
  for (const area of ['localStorage', 'sessionStorage'] as const) {
    try {
      window[area].removeItem(LEGACY_ADMIN_TOKEN_KEY);
    } catch {
      // Storage is unavailable, so nothing is saved either.
    }
  }
}

export function createHttpClient(baseURL?: string): AxiosInstance {
  const client = axios.create({
    baseURL: baseURL ?? getApiBaseUrl(),
    timeout: 60000,
    headers: {
      'Content-Type': 'application/json',
    },
  });

  client.interceptors.request.use(
    (config) => {
      // Clients are created when their module loads; resolve the backend per
      // request so it follows the page's /b/{connection}.
      if (baseURL === undefined) {
        config.baseURL = getApiBaseUrl();
      }
      console.log(
        '[API] Request:',
        config.method?.toUpperCase(),
        `${config.baseURL ?? ''}${config.url ?? ''}`,
      );
      return config;
    },
    (error) => {
      console.error('[API] Request error:', error);
      return Promise.reject(error);
    },
  );

  client.interceptors.response.use(
    (response) => {
      console.log('[API] Response:', response.status, response.config.url);
      // Another cluster member answered while the open backend is down; an
      // answer without the header means the open backend is back.
      const servedBy = response.headers['x-usr-served-by'];
      reportServedBy(typeof servedBy === 'string' && servedBy ? servedBy : null);
      return response;
    },
    (error) => {
      if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === 'string' && detail.trim()) {
          error.message = detail.trim();
        }
      }
      console.error('[API] Response error:', error.message, error.config?.url);
      return Promise.reject(error);
    },
  );

  return client;
}
