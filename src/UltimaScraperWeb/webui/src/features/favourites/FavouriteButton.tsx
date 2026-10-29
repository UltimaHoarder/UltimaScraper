import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';
import { favouriteKey, setFavourite, type FavouriteKey, type FavouritePage, type FavouriteState } from '../../api/favourites';
import { invalidateFavouriteViews, loadFavouriteState, patchFavouriteProjections } from './favouritesCache';
import { useFavouritesEnabled } from './favouritesContext';
import './favourites.css';

type FavouriteList = FavouritePage | InfiniteData<FavouritePage>;
const pagesOf = (list: FavouriteList) => 'pages' in list ? list.pages : [list];
const sameEntity = (item: FavouriteKey, entity: FavouriteKey) => item.site === entity.site && item.entity_type === entity.entity_type && item.entity_id === entity.entity_id;
const mapPages = (list: FavouriteList, update: (page: FavouritePage, index: number) => FavouritePage): FavouriteList =>
  'pages' in list ? { ...list, pages: list.pages.map(update) } : update(list, 0);

interface Props { entity: FavouriteKey; initialFavorite?: boolean; fallback?: ReactNode; className?: string; details?: string; displayLabel?: string }

function ActiveFavouriteButton({ entity, initialFavorite, className, details, displayLabel }: Props) {
  const client = useQueryClient();
  const key = favouriteKey(entity);
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({ queryKey: key, queryFn: () => loadFavouriteState(client, entity), staleTime: 30_000, retry: false,
    initialData: initialFavorite === undefined ? undefined : { ...entity, favourited: initialFavorite, favourite_id: null, created_at: null, created_at_source: null },
  });
  const mutation = useMutation({ mutationFn: (desired: boolean) => setFavourite(entity, desired),
    onMutate: async desired => {
      await client.cancelQueries({ queryKey: key, exact: true });
      const current = client.getQueryData<FavouriteState>(key);
      const previous = current && { ...current, pending: false };
      await client.cancelQueries({ queryKey: ['favourites-list'] });
      const lists = client.getQueriesData<FavouriteList>({ queryKey: ['favourites-list'] });
      client.setQueryData(key, { ...previous, ...entity, favourited: desired, pending: true });
      patchFavouriteProjections(client, entity, desired);
      if (!desired) client.setQueriesData<FavouriteList>({ queryKey: ['favourites-list'] }, list => list && mapPages(list, page => ({
        ...page, items: page.items.filter(item => !sameEntity(item, entity)),
      })));
      setError(null);
      return { previous, lists };
    },
    onSuccess: state => { client.setQueryData(key, state); patchFavouriteProjections(client, entity, state.favourited); },
    onError: (failure: Error, _desired, context) => {
      client.setQueryData(key, context?.previous);
      if (context?.previous) patchFavouriteProjections(client, entity, context.previous.favourited);
      // Restore only this record; a different simultaneous removal must not
      // be overwritten by an entire old page snapshot.
      context?.lists.forEach(([listKey, before]) => {
        if (!before) return;
        const beforePages = pagesOf(before);
        const index = beforePages.findIndex(page => page.items.some(item => sameEntity(item, entity)));
        if (index < 0) return;
        const record = beforePages[index].items.find(item => sameEntity(item, entity))!;
        client.setQueryData<FavouriteList>(listKey, current => {
          if (!current || pagesOf(current).some(page => page.items.some(item => sameEntity(item, record)))) return current;
          return mapPages(current, (page, pageIndex) => pageIndex !== index ? page : ({
            ...page, items: [...page.items, record].sort((a, b) => beforePages[index].items.findIndex(item => sameEntity(item, a)) - beforePages[index].items.findIndex(item => sameEntity(item, b))),
          }));
        });
      });
      setError(failure.message);
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: key, exact: true });
      invalidateFavouriteViews(client, entity);
    },
  });
  const state = query.data;
  const pending = mutation.isPending || state?.pending;
  const label = state?.favourited ? 'Remove favourite' : 'Add favourite';
  return <span className="favourite-control">
    <button type="button" className={`favourite-button ${state?.favourited ? 'is-favourite' : ''} ${className ?? ''}`}
      aria-label={`${label} ${entity.entity_type} ${entity.entity_id}`} aria-pressed={state?.favourited ?? false}
      title={error ?? query.error?.message ?? (details ? `${label} · ${details}` : label)} disabled={!state || Boolean(pending)}
      onClick={event => {
        event.stopPropagation();
        if (client.getQueryData<FavouriteState>(key)?.pending) return;
        // Mark synchronously: a second copy of the control cannot submit in
        // the gap before React Query runs the optimistic callback.
        client.setQueryData(key, { ...state, pending: true });
        mutation.mutate(!state?.favourited);
      }}>{displayLabel ?? (state?.favourited ? '★' : '☆')}</button>
    {(error || query.error) && <span className="favourite-error" role="alert">{error ?? query.error?.message}</span>}
  </span>;
}

export function FavouriteButton(props: Props) {
  const enabled = useFavouritesEnabled();
  return enabled ? <ActiveFavouriteButton {...props} /> : <>{props.fallback ?? null}</>;
}
