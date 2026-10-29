import { useCallback, useEffect, useRef, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getUserCards } from '../../api/users';
import { getWebSocketBaseUrl } from '../../api/http';
import { useWebSocket } from '../../hooks/useWebSocket';
import { profileVersion, userCardKey, type CachedUserCard } from './useCachedUserCard';

export function UserCardsProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const queued = useRef(new Map<string, { site: string; user_id: number }>());
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const inFlight = useRef(false);
  const flush = useCallback(async () => {
    if (inFlight.current || !queued.current.size) return;
    inFlight.current = true;
    try {
      while (queued.current.size) {
        const keys = [...queued.current.values()].slice(0, 200);
        keys.forEach(key => queued.current.delete(`${key.site}:${key.user_id}`));
        try {
          const response = await getUserCards(keys);
          response.users.forEach(user => client.setQueryData<CachedUserCard>(userCardKey(user.site, user.user_id), previous =>
            previous && profileVersion(previous) > profileVersion(user) ? previous : { ...user, authoritative: true }));
        } catch { /* Keep the cached card; focus or reconnect retries authoritative reads. */ }
      }
    } finally { inFlight.current = false; }
  }, [client]);
  const refresh = useCallback((site?: string, userId?: number) => {
    client.getQueryCache().findAll({ queryKey: ['user-card'] }).forEach(query => {
      if (!query.getObserversCount()) return;
      const [, cardSite, cardId] = query.queryKey as ReturnType<typeof userCardKey>;
      if (site && (site.toLowerCase() !== cardSite || userId !== cardId)) return;
      queued.current.set(`${cardSite}:${cardId}`, { site: cardSite, user_id: cardId });
    });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { void flush(); }, 25);
  }, [client, flush]);
  useWebSocket({ url: `${getWebSocketBaseUrl()}/ws/events`, topics: ['profiles'], onMessage: event => {
    if (event.type === 'resync') refresh();
    if (event.type === 'user_profile_updated' && typeof event.site === 'string' && typeof event.user_id === 'number') {
      refresh(event.site, event.user_id);
    }
  } });
  useEffect(() => {
    const focus = () => refresh();
    window.addEventListener('focus', focus);
    return () => { window.removeEventListener('focus', focus); clearTimeout(timer.current); };
  }, [refresh]);
  return children;
}
