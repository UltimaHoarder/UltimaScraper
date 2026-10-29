import { Fragment, useState, type ReactNode } from 'react';
import type { WebhookMessage } from '../../../hooks/useWebhookStream';
import { categoryLabels, siteLabels, type CategoryFilter } from '../lib/webhooksUtils';
import type { WebhookRoute, WebhooksWorkspaceModel } from '../lib/webhooksWorkspaceModel';
export type Area = 'overview' | 'messages' | 'config' | 'watch';

export function Icon({ name }: { name: 'signal' | 'message' | 'route' | 'people' | 'search' | 'arrow' }) {
  const paths = {
    signal: 'M3 12h4l3-8 4 16 3-8h4',
    message: 'M5 4h14v12H9l-4 4V4z M9 8h6 M9 12h4',
    route: 'M5 5v8a5 5 0 0 0 5 5h8 M15 14l4 4-4 4 M5 2v6 M2 5h6',
    people: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M19 8a3 3 0 0 1 0 6 M22 21v-2a4 4 0 0 0-3-4 M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8',
    search: 'M10 3a7 7 0 1 1 0 14 7 7 0 0 1 0-14 M15 15l6 6',
    arrow: 'M5 12h14 M13 6l6 6-6 6',
  };
  return <svg className="wh-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

export function Tag({ children, tone = 'muted' }: { children: ReactNode; tone?: 'accent' | 'warning' | 'muted' }) {
  return <span className={`wh-tag wh-tag--${tone}`}>{children}</span>;
}

export function Panel({ title, children, action, className = '' }: { title: string; children: ReactNode; action?: ReactNode; className?: string }) {
  return <section className={`wh-panel ${className}`}><header className="wh-panel-head"><h3>{title}</h3>{action}</header>{children}</section>;
}

export function Search({ label, placeholder, value, onChange }: { label: string; placeholder: string; value: string; onChange: (value: string) => void }) {
  return <label className="wh-search"><Icon name="search" /><input aria-label={label} placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

function EventTitle({ message }: { message: WebhookMessage }) {
  return <>{message.event.split('_').join(' ').replace(/^./, (letter) => letter.toUpperCase())}</>;
}

function CategoryFilters({ model, vertical = false }: { model: WebhooksWorkspaceModel; vertical?: boolean }) {
  return <div className={`wh-categories ${vertical ? 'wh-categories--vertical' : ''}`} aria-label="Message categories">{(['all', 'backend', 'usapi', 'system'] as CategoryFilter[]).map((category) => <button type="button" key={category} aria-pressed={model.category === category} onClick={() => model.setCategory(category)}><span>{category === 'usapi' ? 'Sites' : category === 'all' ? 'All sources' : categoryLabels[category]}</span><small>{model.messages.filter((item) => category === 'all' || item.category === category).length}</small></button>)}</div>;
}

function EventControls({ model }: { model: WebhooksWorkspaceModel }) {
  return <div className="wh-event-controls"><Search label="Search messages" placeholder="Search messages…" value={model.query} onChange={model.setQuery} /><label className="wh-check"><input type="checkbox" checked={model.showAll} onChange={(event) => model.setShowAll(event.target.checked)} />Include runtime events</label>{model.toggleUpdates && <button type="button" className="wh-btn wh-btn--quiet" aria-pressed={model.updatesPaused} onClick={model.toggleUpdates}>{model.updatesPaused ? 'Resume updates' : 'Pause updates'}</button>}<button type="button" className="wh-btn wh-btn--quiet" disabled={!model.messages.length} onClick={model.clearMessages}>Clear</button></div>;
}

function PayloadBody({ message }: { message: WebhookMessage }) {
  const [format, setFormat] = useState<'summary' | 'json'>('summary');
  const fields = Object.entries(message.payload).filter(([key]) => !['type', 'event'].includes(key));
  return <div className="wh-payload-body"><div className="wh-payload-tabs" role="group" aria-label="Payload format"><button type="button" aria-pressed={format === 'summary'} onClick={() => setFormat('summary')}>Details</button><button type="button" aria-pressed={format === 'json'} onClick={() => setFormat('json')}>Raw JSON</button></div>{format === 'summary' ? <dl className="wh-definition">{fields.map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl> : <pre className="wh-json">{JSON.stringify(message.payload, null, 2)}</pre>}</div>;
}

function Payload({ model }: { model: WebhooksWorkspaceModel }) {
  const message = model.selectedMessage;
  return <Panel title="Message details" className="wh-payload-panel" action={<Tag>{message?.id ?? 'No selection'}</Tag>}>{message ? <><div className="wh-payload-meta"><Tag tone="accent">{categoryLabels[message.category]}</Tag><h4><EventTitle message={message} /></h4><time>{message.receivedAt.slice(0, 10)} · {message.receivedAt.slice(11, 19)} UTC</time></div><PayloadBody key={message.id} message={message} /><p className="wh-footnote">Incoming event data{model.isPreview ? ' · sample' : ''}</p></> : <div className="wh-empty"><Icon name="message" /><strong>No message selected</strong><span>Choose an event from the list.</span></div>}</Panel>;
}

export function Events({ model, timeline = false, limit, onInspect }: { model: WebhooksWorkspaceModel; timeline?: boolean; limit?: number; onInspect?: () => void }) {
  const [page, setPage] = useState(0);
  const pageSize = 100;
  const paged = !limit && model.filteredMessages.length > pageSize;
  const lastPage = Math.max(0, Math.ceil(model.filteredMessages.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  const offset = limit ? 0 : currentPage * pageSize;
  const visibleMessages = model.filteredMessages.slice(offset, limit ?? offset + pageSize);
  function changePage(nextPage: number) {
    if (model.toggleUpdates && !model.updatesPaused) model.toggleUpdates();
    setPage(nextPage);
  }
  if (!model.filteredMessages.length) return <div className="wh-empty"><Icon name="message" /><strong>{model.messages.length ? 'No matching messages' : model.isPreview ? 'Your preview is clear' : model.connected ? 'Listening for events' : 'Event stream offline'}</strong><span>{model.messages.length ? 'Try a different search or source.' : model.isPreview ? 'Reset the sample data to bring the messages back.' : 'Incoming events will appear here when available.'}</span>{model.resetFilters && (model.query.trim() || model.category !== 'all' || !model.showAll) && <button type="button" className="wh-btn" onClick={model.resetFilters}>Reset filters</button>}</div>;
  return <><div className={timeline ? 'wh-timeline' : 'wh-event-list'}>{visibleMessages.map((message) => <article key={message.id} className={`wh-event wh-event--${message.category} ${model.selectedMessage?.id === message.id ? 'is-selected' : ''}`}><button type="button" className="wh-event-select" aria-label={`Inspect ${message.event} ${message.id}`} aria-pressed={model.selectedMessage?.id === message.id} onClick={() => { model.setSelectedMessageId(message.id); onInspect?.(); }}><span className="wh-event-icon"><Icon name={message.category === 'usapi' ? 'message' : 'signal'} /></span><span className="wh-event-copy"><strong><EventTitle message={message} /></strong><span>{typeof message.payload.site === 'string' ? `${message.payload.site === 'onlyfans' ? 'OnlyFans' : message.payload.site === 'fansly' ? 'Fansly' : message.payload.site} · ` : ''}{typeof message.payload.username === 'string' ? `@${message.payload.username}` : message.eventType?.replaceAll('_', ' ') || categoryLabels[message.category]}</span></span><time>{new Date(message.receivedAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })}<small>UTC</small></time><span className="wh-event-arrow" aria-hidden="true">›</span></button>{!limit && model.selectedMessage?.id === message.id && <div className={timeline ? 'wh-journal-payload' : 'wh-inline-payload'}><PayloadBody key={message.id} message={message} /></div>}</article>)}</div>{paged && <nav className="wh-event-pages" aria-label="Journal pages"><button type="button" className="wh-btn wh-btn--quiet" disabled={currentPage === 0} onClick={() => changePage(currentPage - 1)}>Newer events</button><span>{offset + 1}–{Math.min(offset + pageSize, model.filteredMessages.length)} of {model.filteredMessages.length}</span><button type="button" className="wh-btn wh-btn--quiet" disabled={currentPage === lastPage} onClick={() => changePage(currentPage + 1)}>Older events</button></nav>}</>;
}

function RouteCards({ model }: { model: WebhooksWorkspaceModel }) {
  return <div className="wh-route-cards">{model.routes.map((route) => <button type="button" key={route.id} className={`wh-route-card ${model.selectedRoute?.id === route.id ? 'is-selected' : ''}`} aria-pressed={model.selectedRoute?.id === route.id} onClick={() => model.setSelectedRouteId(route.id)}><span className={`wh-site-mark wh-site-mark--${route.site}`}>{route.site === 'onlyfans' ? 'OF' : 'FY'}</span><span><strong>{siteLabels[route.site]}</strong><small>{route.kind}</small></span><span className={`wh-state-dot ${route.active ? 'is-active' : ''}`} /><span className="wh-sr-only">{route.active ? 'Active' : 'Inactive'}</span></button>)}</div>;
}

function RouteStatus({ route }: { route: WebhookRoute }) {
  return <Tag tone={route.active ? 'accent' : 'muted'}><span className="wh-dot" />{route.active ? 'Active' : 'Inactive'}</Tag>;
}

function RouteDetail({ model }: { model: WebhooksWorkspaceModel }) {
  const route = model.selectedRoute;
  if (!route) return <Panel title="Hook details"><p className="wh-footnote">No hook configuration available.</p></Panel>;
  return <Panel title="Hook details" action={<RouteStatus route={route} />}><div className="wh-route-identity"><span className={`wh-site-mark wh-site-mark--${route.site}`}>{route.site === 'onlyfans' ? 'OF' : 'FY'}</span><div><h4>{siteLabels[route.site]}</h4><span>{route.kind} webhook</span></div></div><dl className="wh-definition"><div><dt>Destination</dt><dd><code>{route.url || 'No endpoint configured'}</code></dd></div><div><dt>Hidden information</dt><dd>{route.hide_info.length ? route.hide_info.map((field) => <Tag key={field}>{field}</Tag>) : 'No fields hidden'}</dd></div></dl><p className="wh-footnote">Read-only configuration. Active does not confirm delivery.</p></Panel>;
}

function AddWatch({ model }: { model: WebhooksWorkspaceModel }) {
  return <details className="wh-add-watch"><summary><span>＋ Add a user</span><small>{model.isPreview ? 'Search the sample directory' : 'Search users'}</small></summary><div className="wh-add-body"><div className="wh-watch-controls"><select aria-label="Site to search for users" value={model.addSite} onChange={(event) => model.setAddSite(event.target.value)}><option value="onlyfans">OnlyFans</option><option value="fansly">Fansly</option></select><Search label="Search users to watch" placeholder={model.isPreview ? model.addSite === 'onlyfans' ? 'Try olive or luna…' : 'Try atlas…' : 'Search users…'} value={model.addQuery} onChange={model.setAddQuery} /></div>{model.searchLoading && <p className="wh-footnote">Searching users…</p>}{model.searchError && <p className="wh-footnote" role="alert">{model.searchError}</p>}{!model.isPreview && model.addQuery.trim().length < 2 && <p className="wh-footnote">Enter at least two characters.</p>}{model.candidates.map((person) => <div className="wh-search-result" key={`${person.site}-${person.id}`}><strong>@{person.username || person.id}</strong><button type="button" className="wh-btn wh-btn--primary" disabled={model.addPending} onClick={() => model.watch(person)}>Watch @{person.username || person.id}</button></div>)}{model.addQuery.trim().length >= (model.isPreview ? 1 : 2) && !model.candidates.length && !model.searchLoading && !model.searchError && <p className="wh-footnote">{model.isPreview ? 'No unwatched sample users match your search.' : 'No unwatched users match your search.'}</p>}</div></details>;
}

function WatchRoster({ model, cards = false }: { model: WebhooksWorkspaceModel; cards?: boolean }) {
  return <div className={cards ? 'wh-people-grid' : 'wh-watch-list'}>{model.filteredUsers.map((person) => <article className="wh-person" key={`${person.site}-${person.id}`}><span className={`wh-avatar wh-avatar--${person.site}`}>{person.username?.slice(0, 2).toUpperCase()}</span><div className="wh-person-copy"><strong>@{person.username || person.id}</strong><span>{person.site === 'onlyfans' ? 'OnlyFans' : 'Fansly'} · #{person.id}</span><small><span>Last download</span>{person.downloaded_at ? `${person.downloaded_at.slice(0, 10)} · ${person.downloaded_at.slice(11, 16)} UTC` : 'Not downloaded yet'}</small></div><button type="button" className="wh-btn wh-btn--quiet" aria-label={`Unwatch ${person.username || person.id}`} disabled={model.removePending} onClick={() => model.unwatch(person)}>Unwatch</button></article>)}{!model.filteredUsers.length && <div className="wh-empty"><Icon name="people" /><strong>No users found</strong><span>Adjust your filters or add {model.isPreview ? 'a sample user' : 'a user'}.</span></div>}</div>;
}

export function WatchWorkspace({ model, studio }: { model: WebhooksWorkspaceModel; studio?: boolean }) {
  return <div className={studio ? 'wh-studio-layout' : 'wh-watch-workspace'}><Panel title="Watched users" action={<Tag>{model.totalUsers ?? model.users.length} users</Tag>}><div className="wh-watch-controls"><Search label="Search watched users" placeholder="Find a watched user…" value={model.watchQuery} onChange={model.setWatchQuery} /><select aria-label="Filter watched users by site" value={model.watchSite} onChange={(event) => model.setWatchSite(event.target.value)}><option value="all">All sites</option><option value="onlyfans">OnlyFans</option><option value="fansly">Fansly</option></select><button type="button" className="wh-btn" disabled={model.pausePending || model.watchStatusUnavailable} onClick={model.togglePaused}>{model.paused ? 'Resume watch list' : 'Pause watch list'}</button></div><>{model.watchListLoading ? <div className="wh-empty" role="status">Loading watched users…</div> : <WatchRoster model={model} cards={studio} />}</>{model.hasMoreUsers && <div className="wh-footnote"><button type="button" className="wh-btn" onClick={model.loadMoreUsers}>Load more users</button></div>}<AddWatch model={model} /></Panel>{studio && <aside className="wh-studio-aside"><Panel title="Watch status"><div className="wh-watch-summary"><Icon name="people" /><strong>{model.paused ? 'Watching is paused' : 'Your watch list is running'}</strong><p>{model.paused ? 'Resume processing when you are ready. Your watched users remain on the list.' : 'A single place for the creators you want to keep watching.'}</p><div><span>OnlyFans</span><strong>{model.users.filter((user) => user.site === 'onlyfans').length}</strong></div><div><span>Fansly</span><strong>{model.users.filter((user) => user.site === 'fansly').length}</strong></div></div></Panel><div className="wh-note"><strong>About the preview</strong><p>Watch actions change sample data in this browser session. Reset restores the original roster.</p></div></aside>}</div>;
}

export function RouteWorkspace({ model }: { model: WebhooksWorkspaceModel }) {
  return (
    <div className="wh-register-layout">
      <Panel title="Hook configuration" action={<Tag>{model.routes.filter((route) => route.active).length} of {model.routes.length} active</Tag>}>
        <div className="wh-table-scroll">
          <table className="wh-route-table">
            <thead><tr><th>Site & hook</th><th>Status</th><th>Destination</th><th>Inspect</th></tr></thead>
            <tbody>{model.routes.map((route) => (
              <Fragment key={route.id}>
                <tr className={model.selectedRoute?.id === route.id ? 'is-selected' : ''}>
                  <td><div className="wh-table-site"><span className={`wh-site-mark wh-site-mark--${route.site}`}>{route.site === 'onlyfans' ? 'OF' : 'FY'}</span><span><strong>{siteLabels[route.site]}</strong><small>{route.kind}</small></span></div></td>
                  <td><RouteStatus route={route} /></td>
                  <td><code>{route.url || 'Not configured'}</code></td>
                  <td><button type="button" className="wh-btn wh-btn--quiet" aria-label={`Inspect ${siteLabels[route.site]} ${route.kind} hook`} aria-pressed={model.selectedRoute?.id === route.id} onClick={() => model.setSelectedRouteId(route.id)}><Icon name="arrow" /></button></td>
                </tr>
                {model.selectedRoute?.id === route.id && <tr className="wh-mobile-route-detail"><td colSpan={4}><RouteDetail model={model} /></td></tr>}
              </Fragment>
            ))}</tbody>
          </table>
        </div>
        <p className="wh-footnote">Destinations and hidden fields are displayed as configuration.</p>
      </Panel>
      <RouteDetail model={model} />
    </div>
  );
}

export function MessageWorkspace({ model, concept }: { model: WebhooksWorkspaceModel; concept: { id: string } }) {
  if (concept.id === 'journal') return <div className="wh-journal-layout"><aside className="wh-journal-sidebar"><span className="wh-section-label">Sources</span><CategoryFilters model={model} vertical /><div className="wh-note"><strong>{model.isPreview ? '12 October 2026' : 'Recent events'}</strong><p>Newest first. {model.isPreview ? 'Sample timestamps' : 'Timestamps'} are shown in UTC.</p></div></aside><Panel title="Event journal" action={<Tag>{model.filteredMessages.length} visible</Tag>}><EventControls model={model} />{model.updatesPaused && <p className="wh-footnote" role="status">Updates paused. The stream continues in the background.</p>}<Events key={`${model.category}:${model.query}:${model.showAll}`} model={model} timeline /></Panel></div>;
  return <div className={concept.id === 'console' ? 'wh-console-grid' : 'wh-message-layout'}>{concept.id === 'console' && <aside className="wh-console-routes"><Panel title="Site hooks"><RouteCards model={model} /></Panel><RouteDetail model={model} /></aside>}<Panel title="Incoming messages" action={<Tag>{model.filteredMessages.length} visible</Tag>}><CategoryFilters model={model} /><EventControls model={model} /><Events key={`${model.category}:${model.query}:${model.showAll}`} model={model} /></Panel><Payload model={model} /></div>;
}

export function Overview({ model, navigate }: { model: WebhooksWorkspaceModel; navigate: (area: Area) => void }) {
  return <div className="wh-overview"><div className="wh-metrics"><button type="button" onClick={() => navigate('config')}><span className="wh-metric-icon"><Icon name="route" /></span><span><small>Active hooks</small><strong>{model.routes.filter((route) => route.active).length} <em>of {model.routes.length} {model.hookCountLabel ?? 'configured'}</em></strong></span><Icon name="arrow" /></button><button type="button" onClick={() => navigate('messages')}><span className="wh-metric-icon"><Icon name="message" /></span><span><small>{model.isPreview ? 'Sample messages' : 'Retained messages'}</small><strong>{model.messages.length} <em>across {new Set(model.messages.map((message) => message.category)).size} sources</em></strong></span><Icon name="arrow" /></button><button type="button" onClick={() => navigate('watch')}><span className="wh-metric-icon"><Icon name="people" /></span><span><small>Watched users</small><strong>{model.totalUsers ?? model.users.length} <em>{model.paused ? 'processing paused' : 'processing enabled'}</em></strong></span><Icon name="arrow" /></button></div><div className="wh-overview-grid"><Panel title="Recent messages" action={<button type="button" className="wh-text-btn" onClick={() => navigate('messages')}>View messages <span>→</span></button>}><Events model={model} limit={3} onInspect={() => navigate('messages')} /><p className="wh-footnote">Latest matching {model.isPreview ? 'sample' : 'retained'} messages · UTC</p></Panel><Panel title="Site hooks" action={<button type="button" className="wh-text-btn" onClick={() => navigate('config')}>View configuration <span>→</span></button>}><div className="wh-site-overview">{(['onlyfans', 'fansly'] as const).map((site) => <div key={site}><span className={`wh-site-mark wh-site-mark--${site}`}>{site === 'onlyfans' ? 'OF' : 'FY'}</span><div><strong>{siteLabels[site]}</strong><span>{model.routes.filter((route) => route.site === site && route.active).length} of {model.routes.filter((route) => route.site === site).length} hooks active</span></div><Tag tone="accent">Configured</Tag></div>)}</div><p className="wh-footnote">{model.hookCountLabel === 'available' ? 'Selected hooks and routing rules for each site.' : 'Auth and download hooks for each site.'}</p></Panel></div><div className="wh-overview-watch"><div><Icon name="people" /><span><strong>Your watch list</strong><small>{model.totalUsers ?? model.users.length} creators · {model.paused ? 'Paused' : 'Processing enabled'}</small></span></div><div className="wh-avatar-stack">{model.users.slice(0, 5).map((person) => <span className={`wh-avatar wh-avatar--${person.site}`} key={`${person.site}-${person.id}`} title={`@${person.username}`}>{person.username?.slice(0, 2).toUpperCase()}</span>)}</div><button type="button" className="wh-btn" onClick={() => navigate('watch')}>Manage watch list →</button></div></div>;
}

