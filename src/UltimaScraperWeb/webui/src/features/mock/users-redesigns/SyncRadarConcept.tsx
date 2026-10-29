import type { UsersMockModel } from './usersMockModel';
import { formatBytes, getFreshnessStatus } from './usersMockModel';

export function SyncRadarConcept({ model }: { model: UsersMockModel }) {
  const { visibleUsers, dispatchScrape, watchedKeys, toggleWatch } = model;

  const overdueList = visibleUsers.filter((u) => getFreshnessStatus(u) === 'overdue');
  const neverList = visibleUsers.filter((u) => getFreshnessStatus(u) === 'unscraped');
  const watchedList = visibleUsers.filter((u) => watchedKeys.has(u.id));
  const freshList = visibleUsers.filter((u) => getFreshnessStatus(u) === 'fresh');

  const catchUpOverdue = () => {
    overdueList.forEach((u) => dispatchScrape(u.id));
  };

  const catchUpNever = () => {
    neverList.forEach((u) => dispatchScrape(u.id));
  };

  return (
    <div className="um-radar-layout">
      {/* Overview Top Stats */}
      <div className="um-radar-summary-strip">
        <div className="um-radar-metric">
          <span className="um-radar-metric-label">Overdue Archives</span>
          <strong className="um-radar-metric-val um-text-warn">{overdueList.length}</strong>
          <small>Stale by &gt; 7 days</small>
        </div>
        <div className="um-radar-metric">
          <span className="um-radar-metric-label">Pending Ingestion</span>
          <strong className="um-radar-metric-val">{neverList.length}</strong>
          <small>Never downloaded</small>
        </div>
        <div className="um-radar-metric">
          <span className="um-radar-metric-label">Live Watch Streams</span>
          <strong className="um-radar-metric-val um-text-accent">{watchedList.length}</strong>
          <small>Active webhook listeners</small>
        </div>
        <div className="um-radar-metric">
          <span className="um-radar-metric-label">Fresh & Synced</span>
          <strong className="um-radar-metric-val um-text-ok">{freshList.length}</strong>
          <small>Updated within 48h</small>
        </div>
      </div>

      {/* 4 Ingestion Swimlanes */}
      <div className="um-radar-lanes">
        {/* Lane 1: Overdue */}
        <section className="um-radar-lane um-radar-lane--warn">
          <header className="um-lane-header">
            <div>
              <h3>Overdue For Sync</h3>
              <span className="um-lane-badge">{overdueList.length}</span>
            </div>
            {overdueList.length > 0 && (
              <button
                type="button"
                className="um-btn um-btn--sm um-btn--warn"
                onClick={catchUpOverdue}
              >
                ⚡ Catch-up All ({overdueList.length})
              </button>
            )}
          </header>
          <div className="um-lane-content">
            {overdueList.map((user) => (
              <div key={user.id} className="um-radar-card">
                <img src={user.avatar_url ?? ''} alt="" className="um-avatar-sm" />
                <div className="um-radar-card-info">
                  <strong>{user.name || user.username}</strong>
                  <span className="um-handle-sm">@{user.username}</span>
                  <div className="um-radar-delta">
                    <span className="um-delta-pill">+{user.unscraped_posts ?? 0} new posts</span>
                    <small className="um-muted">
                      Last: {user.downloaded_at ? new Date(user.downloaded_at).toLocaleDateString() : 'Never'}
                    </small>
                  </div>
                </div>
                <button
                  type="button"
                  className="um-btn um-btn--sm um-btn--primary"
                  onClick={() => dispatchScrape(user.id)}
                >
                  Sync
                </button>
              </div>
            ))}
            {overdueList.length === 0 && (
              <div className="um-lane-empty">All archives are up to date! 🎉</div>
            )}
          </div>
        </section>

        {/* Lane 2: Never Ingested */}
        <section className="um-radar-lane">
          <header className="um-lane-header">
            <div>
              <h3>Never Scraped</h3>
              <span className="um-lane-badge">{neverList.length}</span>
            </div>
            {neverList.length > 0 && (
              <button
                type="button"
                className="um-btn um-btn--sm um-btn--primary"
                onClick={catchUpNever}
              >
                ⚡ Initial Ingest ({neverList.length})
              </button>
            )}
          </header>
          <div className="um-lane-content">
            {neverList.map((user) => (
              <div key={user.id} className="um-radar-card">
                <img src={user.avatar_url ?? ''} alt="" className="um-avatar-sm" />
                <div className="um-radar-card-info">
                  <strong>{user.name || user.username}</strong>
                  <span className="um-handle-sm">@{user.username}</span>
                  <div className="um-radar-delta">
                    <span className="um-delta-pill um-delta-pill--new">{user.post_count} posts to pull</span>
                    <small className="um-muted">{user.site}</small>
                  </div>
                </div>
                <button
                  type="button"
                  className="um-btn um-btn--sm um-btn--primary"
                  onClick={() => dispatchScrape(user.id)}
                >
                  Pull
                </button>
              </div>
            ))}
            {neverList.length === 0 && (
              <div className="um-lane-empty">No un-ingested creators.</div>
            )}
          </div>
        </section>

        {/* Lane 3: Live Watched */}
        <section className="um-radar-lane">
          <header className="um-lane-header">
            <div>
              <h3>Watched Streams</h3>
              <span className="um-lane-badge">{watchedList.length}</span>
            </div>
          </header>
          <div className="um-lane-content">
            {watchedList.map((user) => (
              <div key={user.id} className="um-radar-card">
                <img src={user.avatar_url ?? ''} alt="" className="um-avatar-sm" />
                <div className="um-radar-card-info">
                  <strong>{user.name || user.username}</strong>
                  <span className="um-handle-sm">@{user.username}</span>
                  <div className="um-radar-delta">
                    <span className="um-live-indicator">● Webhook Active</span>
                    <small className="um-muted">{formatBytes(user.storage_bytes)}</small>
                  </div>
                </div>
                <button
                  type="button"
                  className="um-btn um-btn--sm"
                  onClick={() => toggleWatch(user.id)}
                >
                  Unwatch
                </button>
              </div>
            ))}
            {watchedList.length === 0 && (
              <div className="um-lane-empty">No watched creators.</div>
            )}
          </div>
        </section>

        {/* Lane 4: Synced */}
        <section className="um-radar-lane um-radar-lane--ok">
          <header className="um-lane-header">
            <div>
              <h3>Fresh &amp; Synced</h3>
              <span className="um-lane-badge">{freshList.length}</span>
            </div>
          </header>
          <div className="um-lane-content">
            {freshList.map((user) => (
              <div key={user.id} className="um-radar-card">
                <img src={user.avatar_url ?? ''} alt="" className="um-avatar-sm" />
                <div className="um-radar-card-info">
                  <strong>{user.name || user.username}</strong>
                  <span className="um-handle-sm">@{user.username}</span>
                  <div className="um-radar-delta">
                    <span className="um-ok-pill">✓ Synced</span>
                    <small className="um-muted">{formatBytes(user.storage_bytes)}</small>
                  </div>
                </div>
                <button
                  type="button"
                  className="um-btn um-btn--sm um-btn--ghost"
                  onClick={() => dispatchScrape(user.id)}
                  title="Rescrape"
                >
                  ↺
                </button>
              </div>
            ))}
            {freshList.length === 0 && (
              <div className="um-lane-empty">No synced creators in this view.</div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
