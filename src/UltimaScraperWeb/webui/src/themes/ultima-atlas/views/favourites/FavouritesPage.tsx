import { useEffect, useMemo, useRef, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { getFavouriteCounts, getFavourites, type FavouriteFilters, type FavouriteType } from '../../../../api/favourites';
import type { UserInfo } from '../../../../api/types/users';
import type { ContentLibraryItem } from '../../../../api/types/content';
import { UsersRosterCard } from '../../../../features/users/components/UsersRosterCard';
import { UsersAuthPickerModal } from '../../../../features/users/components/UsersAuthPickerModal';
import { UsersEditModal } from '../../../../features/users/components/UsersEditModal';
import { useFavouriteUserActions } from '../../../../features/favourites/useFavouriteUserActions';
import { ImageLightbox } from '../../../../shared/ui/ImageLightbox';
import { ContentCard } from '../../../../components/content/ContentCard';
import { parseFavouriteFilters } from '../../../../features/favourites/favouriteFilters';
import { FavouritesFilters } from '../../../../features/favourites/FavouritesFilters';
import { FavouriteButton } from '../../../../features/favourites/FavouriteButton';
import '../../../../features/users/components/UsersHeader.css';
import '../../../../features/users/components/UsersToolbar.css';
import '../../../../features/favourites/favourites.css';
import '../users/UsersPage.css';
import '../content/ContentLibraryBase.css';

const tabs: { type?: FavouriteType; label: string }[] = [
  { type: 'user', label: 'Users' }, { type: 'post', label: 'Posts' },
  { type: 'story', label: 'Stories' }, { type: 'message', label: 'Messages' }, { label: 'All' },
];

function favouriteDateDetails(createdAt: string, source: string) {
  const provenance = source === 'user_downloaded_at' ? 'Inherited user download date' : source === 'user_join_date'
    ? 'Inherited user join date; original favourite date is unknown' : source === 'migration_fallback'
    ? 'Migration fallback; historical favourite date is unknown' : 'Date added to favourites';
  return `${new Date(createdAt).toLocaleString()} · ${provenance}`;
}

export function FavouritesPage() {
  const navigate = useNavigate();
  const actions = useFavouriteUserActions();
  const [params, setParams] = useSearchParams();
  const selected = params.get('type') ?? 'user';
  const type = tabs.find(tab => tab.type === selected)?.type;
  const search = params.get('q') ?? '';
  const [draftSearch, setDraftSearch] = useState({ source: search, value: search });
  const input = draftSearch.source === search ? draftSearch.value : search;
  useEffect(() => {
    if (input.trim() === search) return;
    const timer = setTimeout(() => setParams(previous => {
      const next = new URLSearchParams(previous);
      if (input.trim()) next.set('q', input.trim()); else next.delete('q');
      return next;
    }, { replace: true }), 250);
    return () => clearTimeout(timer);
  }, [input, search, setParams]);
  const site = params.get('site') || undefined;
  const order = params.get('order') === 'asc' ? 'asc' : 'desc';
  const filters = useMemo<FavouriteFilters>(() => ({ site, entity_type: type, search, order, ...parseFavouriteFilters(params) }), [site, type, search, order, params]);
  const query = useInfiniteQuery({
    queryKey: ['favourites-list', filters],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => getFavourites(filters, pageParam, signal),
    getNextPageParam: page => page.has_more && page.next_cursor ? page.next_cursor : undefined,
    staleTime: 30_000,
  });
  const items = useMemo(() => {
    const seen = new Set<string>();
    return (query.data?.pages.flatMap(page => page.items) ?? []).filter(item => {
      const key = item.site + ':' + item.entity_type + ':' + item.entity_id;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    });
  }, [query.data]);
  const countFilters = useMemo(() => {
    const values = { ...filters };
    delete values.entity_type;
    const { order, ...result } = values;
    void order;
    return result;
  }, [filters]);
  const counts = useQuery({ queryKey: ['favourites-counts', countFilters], queryFn: ({ signal }) => getFavouriteCounts(countFilters, signal), staleTime: 30_000 });
  const setFilter = (key: string, value: string) => setParams(previous => {
    const next = new URLSearchParams(previous); if (value) next.set(key, value); else next.delete(key); return next;
  });
  const { hasNextPage, isFetching, isFetchNextPageError, fetchNextPage } = query;
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!items.length || !hasNextPage || isFetching || isFetchNextPageError || typeof IntersectionObserver === 'undefined' || !sentinel.current) return;
    const main = document.querySelector('.main-content');
    const root = main instanceof HTMLElement && ['auto', 'scroll'].includes(getComputedStyle(main).overflowY) ? main : null;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) void fetchNextPage({ cancelRefetch: false });
    }, { root, rootMargin: '0px 0px 40% 0px', threshold: 0 });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [items.length, hasNextPage, isFetching, isFetchNextPageError, fetchNextPage]);
  return (
    <div className="users-page favourites-page ultimur-users-v2">
      {actions.notice && <div className={`toast toast-${actions.notice.error ? 'error' : 'success'}`} role={actions.notice.error ? 'alert' : 'status'}>
        <span className="toast-message">{actions.notice.message}</span>
        <button className="toast-close" aria-label="Dismiss notification" onClick={() => actions.setNotice(null)}>×</button>
      </div>}
      <UsersAuthPickerModal isOpen={Boolean(actions.authTarget)} targetUser={actions.authTarget}
        eligibleAuths={actions.auths} isCreatingJob={actions.create.isPending} onClose={actions.closeAuth} onSelectAuth={actions.selectAuth} />
      <UsersEditModal isOpen={Boolean(actions.editTarget)} targetUser={actions.editTarget}
        editName={actions.editName} editAlias={actions.editAlias} editDescription={actions.editDescription}
        {...actions.identityFields} isSaving={actions.edit.isPending} onClose={actions.closeEdit}
        onEditNameChange={actions.setEditName} onEditAliasChange={actions.setEditAlias}
        onEditDescriptionChange={actions.setEditDescription} onSave={actions.saveEdit} />
      <ImageLightbox imageUrl={actions.lightbox.url} alt={actions.lightbox.alt} onClose={actions.closeLightbox} />
      <section className="users-workspace-stage" aria-label="Favourites workspace header">
        <header className="users-workspace-header">
          <div className="users-workspace-title">
            <span className="users-workspace-symbol" aria-hidden="true">⭐</span>
            <div>
              <h1 className="users-workspace-heading">Favourites</h1>
              <p className="users-workspace-subtitle">Browse favourited creators and saved content bookmarks</p>
            </div>
          </div>
          <div className="users-workspace-meta">
            <div className="users-header-status">
              <span className="users-dot users-dot--live" />
              <span>{counts.data?.total ?? items.length ?? 0} Favourites in Roster</span>
            </div>
          </div>
        </header>

        <div className="users-metrics">
          <div className="users-metric-tile">
            <span>Total Favourites</span>
            <strong>{String(counts.data?.total ?? items.length ?? 0).padStart(2, '0')}</strong>
            <small>Across all categories</small>
          </div>
          <div className="users-metric-tile">
            <span>Creators</span>
            <strong className="users-metric-accent">
              {String(counts.data?.by_type.user ?? 0).padStart(2, '0')}
            </strong>
            <small>Favourited users</small>
          </div>
          <div className="users-metric-tile">
            <span>Posts &amp; Stories</span>
            <strong>
              {String((counts.data?.by_type.post ?? 0) + (counts.data?.by_type.story ?? 0)).padStart(2, '0')}
            </strong>
            <small>Saved content</small>
          </div>
          <div className="users-metric-tile">
            <span>Messages</span>
            <strong>
              {String(counts.data?.by_type.message ?? 0).padStart(2, '0')}
            </strong>
            <small>Direct message archives</small>
          </div>
        </div>

        <div className="favourites-tabs" role="tablist" aria-label="Favourite type">
          {tabs.map(tab => (
            <button
              key={tab.type ?? 'all'}
              type="button"
              role="tab"
              aria-selected={type === tab.type}
              className={type === tab.type ? 'btn-primary' : 'btn-secondary'}
              onClick={() => setFilter('type', tab.type ?? 'all')}
            >
              {tab.label}{counts.data && ` (${tab.type ? counts.data.by_type[tab.type] : counts.data.total})`}
            </button>
          ))}
        </div>

        <div className="users-toolbar favourites-toolbar" role="toolbar" aria-label="Favourites query controls">
          <label className="users-toolbar__search" title="Search favourites">
            <span className="users-toolbar__icon" aria-hidden="true">🔍</span>
            <input
              type="search"
              aria-label="Search favourites"
              placeholder="Search favourites"
              value={input}
              onChange={event => setDraftSearch({ source: search, value: event.target.value })}
            />
            {input ? (
              <button
                type="button"
                className="users-toolbar__clear"
                onClick={() => setDraftSearch({ source: search, value: '' })}
                aria-label="Clear favourites search"
              >
                ×
              </button>
            ) : null}
          </label>
          <select
            aria-label="Favourite site"
            className="users-toolbar__select"
            value={site ?? ''}
            onChange={event => setFilter('site', event.target.value)}
          >
            <option value="">All sites</option>
            <option value="onlyfans">OnlyFans</option>
            <option value="fansly">Fansly</option>
            <option value="loyalfans">LoyalFans</option>
          </select>
          <select
            aria-label="Favourite order"
            className="users-toolbar__select"
            value={order}
            onChange={event => setFilter('order', event.target.value)}
          >
            <option value="desc">Newest first</option>
            <option value="asc">Oldest first</option>
          </select>
          <FavouritesFilters params={params} onApply={setParams} />
          <span className="users-toolbar__count">
            {items.length ?? 0} visible
          </span>
        </div>

        <div className="users-workspace-body">
          {query.isPending && <p role="status">Loading favourites…</p>}
          {query.error && !query.isFetchNextPageError && (
            <p role="alert">
              {query.error.message}{' '}
              <button type="button" onClick={() => void query.refetch()}>Retry</button>
            </p>
          )}
          {query.data && items.length === 0 && <p>No favourites found.</p>}
          <div className="user-card-grid-container">
            <div className={type === 'user' ? 'users-grid user-card-grid favourites-users-grid' : 'favourites-grid'} role="tabpanel" aria-label={tabs.find(tab => tab.type === type)?.label ?? 'All'}>
              {items.map(item => (
                <article className="favourite-entry" key={`${item.site}:${item.entity_type}:${item.id}`}>
                  {item.entity_type === 'user' && item.entity ? (
                    <UsersRosterCard
                      item={item.entity as UserInfo}
                      profileUrl={`/users/${item.entity_id}?site=${item.site}`}
                      isSelected={false}
                      isCreatingJob={actions.create.isPending || actions.resolvingAuth}
                      isWatched={actions.watched.has(actions.key(item.entity as UserInfo))}
                      isWatchPending={actions.watch.isPending}
                      isIgnored={actions.ignored.has(actions.key(item.entity as UserInfo))}
                      isIgnorePending={actions.ignore.isPending}
                      onSelect={() => navigate(`/users/${item.entity_id}?site=${item.site}`)}
                      onScrape={user => void actions.scrape(user)}
                      onView={() => navigate(`/users/${item.entity_id}?site=${item.site}`)}
                      onWatchToggle={user => { if (!actions.watch.isPending) actions.watch.mutate(user); }}
                      onIgnoreToggle={user => { if (!actions.ignore.isPending) actions.ignore.mutate(user); }}
                      onOpenLightbox={actions.openLightbox}
                      isSubscribePending={actions.subscribe.isPending}
                      isUpdatePending={actions.edit.isPending}
                      onSubscribeUser={user => { if (!actions.subscribe.isPending) actions.subscribe.mutate(user); }}
                      onEditUser={actions.openEdit}
                      favouriteDetails={favouriteDateDetails(item.created_at, item.created_at_source)}
                    />
                  ) : item.entity ? (
                    <ContentCard item={item.entity as ContentLibraryItem} highlightText={search} />
                  ) : (
                    <div className="card">{item.site} · {item.entity_type} {item.entity_id} <FavouriteButton entity={item} initialFavorite /></div>
                  )}
                  {(item.entity_type !== 'user' || !item.entity) && <div className="favourite-entry-meta">
                    <time dateTime={item.created_at} title={item.created_at_source === 'user_downloaded_at' ? 'Inherited user download date' : item.created_at_source === 'user_join_date' ? 'Inherited user join date; original favourite date is unknown' : item.created_at_source === 'migration_fallback' ? 'Migration fallback; historical favourite date is unknown' : 'Date added to favourites'}>
                      {new Date(item.created_at).toLocaleString()}{item.created_at_source === 'user_downloaded_at' ? ' · downloaded' : item.created_at_source === 'user_join_date' ? ' · joined' : item.created_at_source === 'migration_fallback' ? ' · migrated' : ''}
                    </time>
                    {item.availability !== 'available' && <span className="favourite-availability">{item.availability}</span>}
                  </div>}
                </article>
              ))}
            </div>
          </div>

          <div ref={sentinel} className="users-scroll-sentinel" aria-hidden="true" />
          {query.isFetchNextPageError && <p role="alert">Could not load more favourites. Your loaded favourites are still visible.</p>}
          {query.hasNextPage && <div className="load-more-container">
            <button type="button" className="load-more-btn" disabled={query.isFetching}
              onClick={() => void query.fetchNextPage({ cancelRefetch: false })}>
              {query.isFetchingNextPage ? 'Loading…' : query.isFetchNextPageError ? 'Retry loading more' : 'Load More (50)'}
            </button>
          </div>}
          {!query.hasNextPage && query.data && items.length > 0 && <div className="users-end" role="status">All favourites loaded</div>}

        </div>
      </section>
    </div>
  );
}
