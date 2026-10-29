import { useState } from 'react';
import type { UsersMockModel } from './usersMockModel';
import { formatBytes, getFreshnessStatus } from './usersMockModel';

export function DossierConcept({ model }: { model: UsersMockModel }) {
  const { visibleUsers, selectedUser, selectedId, setSelectedId, toggleFavorite, toggleWatch, toggleSubscribe, dispatchScrape } = model;
  const [activeTab, setActiveTab] = useState<'overview' | 'media' | 'taxonomy' | 'history'>('overview');

  const freshness = getFreshnessStatus(selectedUser);
  const isWatched = model.watchedKeys.has(selectedUser.id);
  const isIgnored = model.ignoredKeys.has(selectedUser.id);

  return (
    <div className="um-dossier-layout">
      {/* Left Pane: Creator Directory List */}
      <aside className="um-dossier-sidebar" aria-label="Creator Directory">
        <div className="um-dossier-sidebar-header">
          <span className="um-eyebrow">Roster Directory</span>
          <span className="um-mono">{visibleUsers.length} creators</span>
        </div>
        <div className="um-dossier-list" role="list">
          {visibleUsers.map((user) => {
            const isSelected = user.id === selectedId;
            const userFreshness = getFreshnessStatus(user);
            return (
              <button
                type="button"
                key={user.id}
                className={`um-dossier-item ${isSelected ? 'active' : ''}`}
                onClick={() => setSelectedId(user.id)}
                aria-current={isSelected ? 'true' : undefined}
              >
                <div className="um-avatar-wrap">
                  <img src={user.avatar_url ?? ''} alt="" className="um-avatar" />
                  <span className={`um-site-dot um-site-dot--${user.site}`} />
                </div>
                <div className="um-dossier-item-info">
                  <div className="um-dossier-item-top">
                    <strong className="um-dossier-item-name">{user.name || user.username}</strong>
                    <span className="um-price-badge">{user.price === 0 ? 'Free' : `$${user.price.toFixed(2)}`}</span>
                  </div>
                  <div className="um-dossier-item-sub">
                    <span className="um-handle">@{user.username}</span>
                    <span className={`um-fresh-pill um-fresh-pill--${userFreshness}`}>{userFreshness}</span>
                  </div>
                </div>
              </button>
            );
          })}
          {visibleUsers.length === 0 && (
            <div className="um-empty-state">No creators match current filters</div>
          )}
        </div>
      </aside>

      {/* Right Pane: Dossier Detail Workspace */}
      <main className="um-dossier-workspace" aria-label="Creator Dossier">
        {/* Profile Banner & Hero */}
        <section className="um-dossier-hero">
          <div className="um-hero-banner" style={{ backgroundImage: `url(${selectedUser.header_url})` }}>
            <div className="um-hero-overlay" />
            <div className="um-hero-site-tag">
              <span className={`um-badge um-badge--${selectedUser.site}`}>{selectedUser.site.toUpperCase()}</span>
              {selectedUser.is_subscribed && <span className="um-badge um-badge--sub">Subscribed</span>}
              {isWatched && <span className="um-badge um-badge--watched">Watched</span>}
            </div>
          </div>

          <div className="um-hero-body">
            <div className="um-hero-avatar-row">
              <div className="um-hero-avatar-box">
                <img src={selectedUser.avatar_url ?? ''} alt={selectedUser.username} className="um-hero-avatar" />
                {selectedUser.verified && <span className="um-verified-badge" title="Verified Creator">✓</span>}
              </div>
              <div className="um-hero-names">
                <h2>{selectedUser.name || selectedUser.username}</h2>
                <div className="um-hero-handle-row">
                  <span className="um-hero-handle">@{selectedUser.username}</span>
                  <span className="um-id-tag">ID: {selectedUser.user_id}</span>
                </div>
              </div>
              <div className="um-hero-actions">
                <button
                  type="button"
                  className={`um-action-btn ${selectedUser.favorite ? 'active' : ''}`}
                  onClick={() => toggleFavorite(selectedUser.id)}
                  title={selectedUser.favorite ? 'Remove favorite' : 'Favorite creator'}
                  aria-label={selectedUser.favorite ? 'Remove favorite' : 'Favorite creator'}
                >
                  ★
                </button>
                <button
                  type="button"
                  className={`um-action-btn ${isWatched ? 'active' : ''}`}
                  onClick={() => toggleWatch(selectedUser.id)}
                  title="Watch updates"
                >
                  🔔 {isWatched ? 'Watching' : 'Watch'}
                </button>
                <button
                  type="button"
                  className="um-action-btn um-action-btn--primary"
                  onClick={() => dispatchScrape(selectedUser.id)}
                >
                  ⚡ Trigger Scrape
                </button>
              </div>
            </div>

            {selectedUser.description && (
              <p className="um-hero-bio">{selectedUser.description}</p>
            )}

            {/* Quick Metrics Bar */}
            <div className="um-stat-grid">
              <div className="um-stat-card">
                <span className="um-stat-label">Total Posts</span>
                <strong className="um-stat-val">{selectedUser.post_count.toLocaleString()}</strong>
              </div>
              <div className="um-stat-card">
                <span className="um-stat-label">Photos</span>
                <strong className="um-stat-val">{selectedUser.image_count.toLocaleString()}</strong>
              </div>
              <div className="um-stat-card">
                <span className="um-stat-label">Videos</span>
                <strong className="um-stat-val">{selectedUser.video_count.toLocaleString()}</strong>
              </div>
              <div className="um-stat-card">
                <span className="um-stat-label">Archived Size</span>
                <strong className="um-stat-val">{formatBytes(selectedUser.storage_bytes)}</strong>
              </div>
              <div className="um-stat-card">
                <span className="um-stat-label">Rate / Mo</span>
                <strong className="um-stat-val">{selectedUser.price === 0 ? 'Free' : `$${selectedUser.price.toFixed(2)}`}</strong>
              </div>
            </div>
          </div>
        </section>

        {/* Section Tabs */}
        <nav className="um-dossier-tabs" aria-label="Dossier Sections">
          <button
            type="button"
            className={activeTab === 'overview' ? 'active' : ''}
            onClick={() => setActiveTab('overview')}
          >
            Vault Breakdown
          </button>
          <button
            type="button"
            className={activeTab === 'taxonomy' ? 'active' : ''}
            onClick={() => setActiveTab('taxonomy')}
          >
            Identity & Tags
          </button>
          <button
            type="button"
            className={activeTab === 'history' ? 'active' : ''}
            onClick={() => setActiveTab('history')}
          >
            Audit & Sync History
          </button>
        </nav>

        {/* Tab Content */}
        <section className="um-tab-body">
          {activeTab === 'overview' && (
            <div className="um-panel-grid">
              <div className="um-panel">
                <h3>Asset Vault Telemetry</h3>
                <div className="um-vault-meter">
                  <div
                    className="um-vault-bar um-vault-bar--photos"
                    style={{ width: `${(selectedUser.image_count / (selectedUser.media_count || 1)) * 100}%` }}
                    title={`Photos: ${selectedUser.image_count}`}
                  />
                  <div
                    className="um-vault-bar um-vault-bar--videos"
                    style={{ width: `${(selectedUser.video_count / (selectedUser.media_count || 1)) * 100}%` }}
                    title={`Videos: ${selectedUser.video_count}`}
                  />
                </div>
                <div className="um-vault-legend">
                  <span><span className="dot dot-photo" /> {selectedUser.image_count} Photos ({Math.round((selectedUser.image_count / (selectedUser.media_count || 1)) * 100)}%)</span>
                  <span><span className="dot dot-video" /> {selectedUser.video_count} Videos ({Math.round((selectedUser.video_count / (selectedUser.media_count || 1)) * 100)}%)</span>
                </div>
                <div className="um-detail-list">
                  <div><span>Archive Status:</span> <strong>{freshness.toUpperCase()}</strong></div>
                  <div><span>Unscraped Posts:</span> <strong>{selectedUser.unscraped_posts ?? 0} pending</strong></div>
                  <div><span>Estimated Disk Footprint:</span> <strong>{formatBytes(selectedUser.storage_bytes)}</strong></div>
                </div>
              </div>

              <div className="um-panel">
                <h3>Account Operational Flags</h3>
                <div className="um-flag-list">
                  <label className="um-flag-row">
                    <input
                      type="checkbox"
                      checked={selectedUser.is_subscribed}
                      onChange={() => toggleSubscribe(selectedUser.id)}
                    />
                    <span>Active Subscription (Token access valid)</span>
                  </label>
                  <label className="um-flag-row">
                    <input
                      type="checkbox"
                      checked={isWatched}
                      onChange={() => toggleWatch(selectedUser.id)}
                    />
                    <span>Real-Time Webhook Watch (Receive live post alerts)</span>
                  </label>
                  <label className="um-flag-row">
                    <input
                      type="checkbox"
                      checked={isIgnored}
                      onChange={() => model.toggleIgnore(selectedUser.id)}
                    />
                    <span>Ignore in Mass Scrapes (Excluded from automated runs)</span>
                  </label>
                  <label className="um-flag-row">
                    <input
                      type="checkbox"
                      checked={!!selectedUser.ai_assisted}
                      readOnly
                    />
                    <span>AI-Generated / Synthetic Content Marker</span>
                  </label>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'taxonomy' && (
            <div className="um-panel">
              <h3>Classification Taxonomy</h3>
              <p className="um-muted-text">Identified characteristics and metadata classification tags.</p>
              <div className="um-tag-cloud">
                <span className="um-tag um-tag--accent">Profile Type: {selectedUser.profile_type === 1 ? 'Couple' : selectedUser.profile_type === 2 ? 'Group' : 'Solo'}</span>
                <span className="um-tag um-tag--accent">Content: {selectedUser.sexual_content === 1 ? 'Lesbian' : selectedUser.sexual_content === 2 ? 'Gay' : selectedUser.sexual_content === 3 ? 'Bisexual' : selectedUser.sexual_content === 4 ? 'Trans/Queer' : 'Heterosexual'}</span>
                <span className="um-tag">Gender: {selectedUser.gender === 1 ? 'Man' : selectedUser.gender === 2 ? 'Non-Binary' : 'Woman'}</span>
                {selectedUser.ai_assisted && <span className="um-tag um-tag--warn">AI-Assisted</span>}
                {selectedUser.tags?.map((t) => (
                  <span key={t} className="um-tag">{t}</span>
                ))}
              </div>
              <div className="um-confidence-box">
                <span>Model Classification Confidence:</span>
                <strong>{Math.round((selectedUser.confidence ?? 0.9) * 100)}%</strong>
              </div>
            </div>
          )}

          {activeTab === 'history' && (
            <div className="um-panel">
              <h3>Ingestion Audit Timeline</h3>
              <ul className="um-timeline">
                <li>
                  <span className="um-timeline-time">Today, 04:15</span>
                  <div>
                    <strong>Roster Health Check</strong>
                    <p>API verification completed. Creator account active on {selectedUser.site}.</p>
                  </div>
                </li>
                <li>
                  <span className="um-timeline-time">{selectedUser.downloaded_at ? new Date(selectedUser.downloaded_at).toLocaleDateString() : 'Never'}</span>
                  <div>
                    <strong>Latest Download Run</strong>
                    <p>{selectedUser.downloaded_at ? `Archived media assets successfully.` : 'No media archives on disk.'}</p>
                  </div>
                </li>
              </ul>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
