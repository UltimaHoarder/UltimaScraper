import { useEffect, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { favouriteKey, getFavouritesStatus, type FavouriteKey, type FavouriteState } from '../../api/favourites';
import { getWebSocketBaseUrl } from '../../api/http';
import { useWebSocket } from '../../hooks/useWebSocket';
import { invalidateFavouriteViews } from './favouritesCache';
import { FavouritesEnabledContext } from './favouritesContext';

function FavouriteEvents() {
  const client = useQueryClient();
  useWebSocket({ url: `${getWebSocketBaseUrl()}/ws/events`, topics: ['favourites'], onMessage: event => {
    if (event.type === 'resync') {
      void client.invalidateQueries({ queryKey: ['favourite-state'] });
      invalidateFavouriteViews(client);
    } else if (event.type === 'favourite_changed' && typeof event.site === 'string' && typeof event.entity_id === 'number') {
      const key = { site: event.site, entity_type: event.entity_type, entity_id: event.entity_id } as FavouriteKey;
      if (!client.getQueryData<FavouriteState>(favouriteKey(key))?.pending) {
        void client.invalidateQueries({ queryKey: favouriteKey(key), exact: true });
        invalidateFavouriteViews(client, key);
      }
    }
  } });
  useEffect(() => {
    const refresh = () => {
      void client.invalidateQueries({ queryKey: ['favourite-state'], refetchType: 'active' });
      invalidateFavouriteViews(client);
    };
    window.addEventListener('focus', refresh);
    return () => window.removeEventListener('focus', refresh);
  }, [client]);
  return null;
}

export function FavouritesProvider({ children }: { children: ReactNode }) {
  const status = useQuery({ queryKey: ['favourites-status'], queryFn: getFavouritesStatus, staleTime: 60_000, retry: false });
  const enabled = status.isPending ? undefined : status.data?.enabled === true;
  return <FavouritesEnabledContext.Provider value={enabled}>{enabled && <FavouriteEvents />}{children}</FavouritesEnabledContext.Provider>;
}
