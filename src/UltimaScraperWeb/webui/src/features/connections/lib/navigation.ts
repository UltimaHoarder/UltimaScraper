import { useSyncExternalStore, type MouseEvent } from 'react';

import { navigateTo, subscribeToLocation } from '../../../api/http';
import { connectionHome } from '../../../api/webui';

const currentPath = () => window.location.pathname;

/** The page path, updated by navigateTo and back/forward. */
export function useLocationPath(): string {
  return useSyncExternalStore(subscribeToLocation, currentPath);
}

/**
 * Follows a link without reloading the page. Modified clicks (new tab,
 * new window) keep the browser's behaviour.
 */
export function followInApp(event: MouseEvent<HTMLAnchorElement> | null | undefined, path: string): void {
  if (event) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    event.preventDefault();
  }
  navigateTo(path);
}

/**
 * The same section on another backend: /b/nas/jobs/123 becomes /b/nas2/jobs,
 * and switching to local/default becomes /jobs.
 * Only the section is kept, since ids belong to the backend that issued them.
 */
export function sectionOnBackend(connectionId: string, pathname = currentPath()): string {
  const home = connectionHome(connectionId);
  const prefix = /^\/b\/[^/]+/.exec(pathname);
  if (prefix === null) {
    if (pathname === '/connections' || pathname.startsWith('/connections')) return home;
    if (connectionId === 'default') return pathname;
    const section = pathname.split('/').find(Boolean);
    return section ? `${home}${section}` : home;
  }
  const section = pathname.slice(prefix[0].length).split('/').find(Boolean);
  if (connectionId === 'default') {
    return section ? `/${section}` : '/';
  }
  return section ? `${home}${section}` : home;
}
