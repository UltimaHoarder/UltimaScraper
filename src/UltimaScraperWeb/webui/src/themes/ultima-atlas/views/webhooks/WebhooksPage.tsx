import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { WatchedUserInfo } from '../../../../api/types/webhooks';
import type { WebhookMessage } from '../../../../hooks/useWebhookStream';
import { useWebhooksPageController } from '../../../../features/webhooks/hooks/useWebhooksPageController';
import { filterWebhookMessages, type SiteKey } from '../../../../features/webhooks/lib/webhooksUtils';
import type { WebhookRoute, WebhooksWorkspaceModel } from '../../../../features/webhooks/lib/webhooksWorkspaceModel';
import { Icon, Tag, Overview, MessageWorkspace, WatchWorkspace, type Area } from '../../../../features/webhooks/components/WebhooksDesignWorkspace';
import { WebhookConfigurationEditor } from '../../../../features/webhooks/components/WebhookConfigurationEditor';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import type { WebhooksResponse } from '../../../../api/types/webhooks';
import '../../../../features/webhooks/components/WebhooksDesignWorkspace.css';
import './WebhooksPage.css';

function errorMessage(error: unknown) { return error instanceof Error ? error.message : 'Please try again.'; }

export function WebhooksPage() {
  const c = useWebhooksPageController('messages');
  const queryClient = useQueryClient();
  const [selectedRouteId, setSelectedRouteId] = useState('');
  const [selectedMessageId, setSelectedMessageId] = useState('');
  const [heldMessages, setHeldMessages] = useState<WebhookMessage[] | null>(null);
  const [removedUser, setRemovedUser] = useState<WatchedUserInfo | null>(null);
  const [notice, setNotice] = useState('');
  const configuration = c.webhooksQuery.data?.configuration;
  const routes: WebhookRoute[] = configuration ? (['onlyfans', 'fansly'] as const).flatMap((site) => configuration.catalog.filter((hook) => hook.sites.includes(site)).map((hook) => {
    const routing = configuration.sites[site];
    const rules = routing.rules.filter((rule) => rule.hooks.includes(hook.id));
    const destinations = routing.destinations.filter((destination) => rules.some((rule) => rule.destination_ids.includes(destination.id)));
    return { id: `${site}-${hook.id}`, site, kind: hook.label, active: rules.some((rule) => rule.active), url: destinations.map((destination) => destination.url).join(', ') || null, hide_info: [...new Set(rules.flatMap((rule) => rule.hide_info))] };
  })) : c.webhooksQuery.data?.sites ? (Object.entries(c.webhooksQuery.data.sites) as [SiteKey, NonNullable<typeof c.webhooksQuery.data>['sites'][SiteKey]][]).flatMap(([site, hooks]) => ([{ ...hooks.auth, id: `${site}-auth`, site, kind: 'Auth' }, { ...hooks.download, id: `${site}-download`, site, kind: 'Download' }] as WebhookRoute[])) : [];
  const messages = heldMessages ?? c.messages;
  const filteredMessages = [...filterWebhookMessages(messages, c.categoryFilter, c.showAllEvents, c.filterText)].sort((a, b) => Date.parse(b.receivedAt) - Date.parse(a.receivedAt));
  const users = (c.activeTab === 'overview' ? c.overviewWatchQuery : c.watchListQuery).data?.users ?? [];
  const selectedMessage = filteredMessages.find((message) => message.id === selectedMessageId) ?? filteredMessages[0];
  const mutationError = c.addToWatchMutation.error || c.removeFromWatchMutation.error || c.pauseWatchesMutation.error || c.resumeWatchesMutation.error;
  function navigate(area: Area) { c.setActiveTab(area === 'watch' ? 'watchlist' : area); }
  const model: WebhooksWorkspaceModel = {
    routes, hookCountLabel: configuration ? 'available' : 'configured', selectedRoute: routes.find((route) => route.id === selectedRouteId) ?? routes[0], setSelectedRouteId,
    messages, filteredMessages, selectedMessage, setSelectedMessageId,
    category: c.categoryFilter, setCategory: c.setCategoryFilter, query: c.filterText, setQuery: c.setFilterText,
    showAll: c.showAllEvents, setShowAll: c.setShowAllEvents,
    resetFilters: () => { c.setFilterText(''); c.setCategoryFilter('all'); c.setShowAllEvents(true); },
    clearMessages: () => { c.clearMessages(); if (heldMessages !== null) setHeldMessages([]); },
    users, filteredUsers: users, totalUsers: c.watchStatsQuery.data?.total_watched,
    paused: c.watchStatsQuery.data?.paused ?? false, connected: c.isConnected,
    watchSite: c.watchSiteFilter ?? 'all', setWatchSite: (site) => c.setWatchSiteFilter(site === 'all' ? undefined : site),
    watchQuery: c.watchSearch, setWatchQuery: c.setWatchSearch,
    addQuery: c.addSearch, setAddQuery: c.setAddSearch, addSite: c.addSite, setAddSite: c.setAddSite,
    candidates: (c.userSearchQuery.data?.users ?? []).filter((person) => !users.some((user) => user.site === c.addSite && user.id === person.id)).map((person) => ({ id: person.id, site: c.addSite, username: person.username, watched: false, downloaded_at: null, created_at: null })),
    watch: (person) => c.addToWatchMutation.mutate({ userId: person.id, site: person.site }, { onSuccess: () => { c.setAddSearch(''); setNotice(`@${person.username || person.id} added to the watch list.`); } }),
    unwatch: (person) => c.removeFromWatchMutation.mutate({ userId: person.id, site: person.site }, { onSuccess: () => { setRemovedUser(person); setNotice(`@${person.username || person.id} removed from the watch list.`); } }),
    togglePaused: () => c.watchStatsQuery.data?.paused ? c.resumeWatchesMutation.mutate() : c.pauseWatchesMutation.mutate(),
    addPending: c.addToWatchMutation.isPending, removePending: c.removeFromWatchMutation.isPending,
    pausePending: c.pauseWatchesMutation.isPending || c.resumeWatchesMutation.isPending,
    watchStatusUnavailable: !c.watchStatsQuery.data,
    watchListLoading: c.watchListQuery.isLoading,
    searchLoading: c.userSearchQuery.isFetching, searchError: c.userSearchQuery.error ? errorMessage(c.userSearchQuery.error) : c.userSearchQuery.data?.error,
    hasMoreUsers: users.length < (c.watchListQuery.data?.total ?? users.length), loadMoreUsers: () => c.setWatchLimit((limit) => limit + 50),
    updatesPaused: heldMessages !== null, toggleUpdates: () => setHeldMessages(heldMessages === null ? [...c.messages] : null),
  };
  const watchQuery = c.activeTab === 'overview' ? c.overviewWatchQuery : c.watchListQuery;
  const configLoading = c.webhooksQuery.isLoading;
  const watchLoading = watchQuery.isLoading || c.watchStatsQuery.isLoading;
  const loadError = c.activeTab === 'config' ? c.webhooksQuery.error : c.activeTab === 'watchlist' ? watchQuery.error || c.watchStatsQuery.error : c.activeTab === 'overview' ? c.webhooksQuery.error || watchQuery.error || c.watchStatsQuery.error : null;
  const loading = c.activeTab === 'config' ? configLoading : c.activeTab === 'watchlist' ? c.watchStatsQuery.isLoading : c.activeTab === 'overview' ? configLoading || watchLoading : false;
  return (
    <div className="wh-lab wh-production">
      <section className="wh-stage wh-stage--journal" aria-label="Webhooks workspace">
        <WorkspacePageHeader
          eyebrow="Platform"
          title="Webhooks"
          subtitle="Your hooks, messages, and watched users."
          icon={<Icon name="signal" />}
          meta={<Tag tone={c.isConnected ? 'accent' : 'warning'}><span className="wh-dot" />{c.isConnected ? 'Stream connected' : 'Stream offline'}</Tag>}
        />
        <nav className="wh-workspace-nav" aria-label="Webhook workspace">
          {([{ id: 'overview', label: 'Overview', icon: 'signal' }, { id: 'messages', label: 'Messages', icon: 'message' }, { id: 'config', label: 'Configuration', icon: 'route' }, { id: 'watch', label: 'Watch list', icon: 'people' }] as const).map((item) => <button type="button" key={item.id} aria-pressed={c.activeTab === (item.id === 'watch' ? 'watchlist' : item.id)} onClick={() => navigate(item.id)}><Icon name={item.icon} />{item.label}{item.id === 'watch' && c.watchStatsQuery.data && <small>{c.watchStatsQuery.data.total_watched}</small>}</button>)}
        </nav>
        {!c.isConnected && <div className="wh-banner"><strong>Event stream offline</strong><span>Cached messages remain available.</span></div>}
        {model.paused && <div className="wh-banner"><strong>Watch processing paused</strong><span>Incoming messages remain available.</span></div>}
        <div className="wh-workspace-body">
          {loadError ? <div className="wh-empty" role="alert"><strong>{c.activeTab === 'config' ? 'Failed to load hook configuration' : 'Failed to load watch data'}</strong><span>{errorMessage(loadError)}</span><button type="button" className="wh-btn" onClick={() => { void c.webhooksQuery.refetch(); void watchQuery.refetch(); void c.watchStatsQuery.refetch(); }}>Retry</button></div> : loading ? <div className="wh-empty" role="status">Loading {c.activeTab === 'config' ? 'hook configuration' : 'watch data'}…</div> : <>
            {c.activeTab === 'overview' && <Overview model={model} navigate={navigate} />}
            {c.activeTab === 'messages' && <MessageWorkspace model={model} concept={{ id: 'journal' }} />}
            {c.activeTab === 'watchlist' && <WatchWorkspace model={model} />}
          </>}
          {c.webhooksQuery.data && <div hidden={c.activeTab !== 'config' || loading || Boolean(loadError)}><WebhookConfigurationEditor data={c.webhooksQuery.data} onSaved={(saved) => queryClient.setQueryData<WebhooksResponse>(['webhooks'], (current) => current ? { ...current, configuration: saved } : current)} onReload={async () => { const result = await c.webhooksQuery.refetch(); if (result.error) throw result.error; return result.data!; }} /></div>}
          {mutationError && <p className="wh-action-error" role="alert">Action failed: {errorMessage(mutationError)}</p>}
        </div>
      </section>
      {notice && <div className={`wh-preview-notice ${removedUser ? 'wh-preview-notice--action' : ''}`}><span role="status">{notice}</span>{removedUser && <button type="button" className="wh-text-btn" disabled={c.addToWatchMutation.isPending} onClick={() => c.addToWatchMutation.mutate({ userId: removedUser.id, site: removedUser.site }, { onSuccess: () => { setNotice(`@${removedUser.username || removedUser.id} restored to the watch list.`); setRemovedUser(null); } })}>Undo unwatch</button>}</div>}
    </div>
  );
}
export default WebhooksPage;
