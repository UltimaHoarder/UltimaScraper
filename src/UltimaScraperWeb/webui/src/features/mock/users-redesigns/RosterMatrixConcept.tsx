import { useState } from 'react';
import type { UsersMockModel } from './usersMockModel';
import { formatBytes, getFreshnessStatus } from './usersMockModel';

export function RosterMatrixConcept({ model }: { model: UsersMockModel }) {
  const {
    visibleUsers,
    selectedUserIds,
    toggleSelect,
    selectAll,
    clearSelection,
    toggleFavorite,
    toggleWatch,
    toggleIgnore,
    dispatchScrape,
    bulkScrape,
    bulkWatch,
    bulkIgnore,
    watchedKeys,
    ignoredKeys,
    bulkSetIdentity,
  } = model;

  const [identityPresetModal, setIdentityPresetModal] = useState(false);

  const allSelected = visibleUsers.length > 0 && selectedUserIds.size === visibleUsers.length;
  const hasSelection = selectedUserIds.size > 0;

  return (
    <div className="um-matrix-layout">
      {/* Sticky Batch Operations Bar */}
      {hasSelection && (
        <aside className="um-batch-bar" role="toolbar" aria-label="Batch operations">
          <div className="um-batch-summary">
            <span className="um-batch-count">{selectedUserIds.size}</span>
            <span>creators selected</span>
          </div>
          <div className="um-batch-actions">
            <button
              type="button"
              className="um-btn um-btn--primary"
              onClick={bulkScrape}
              title="Scrape selected creators"
            >
              ⚡ Scrape Selected
            </button>
            <button
              type="button"
              className="um-btn"
              onClick={() => bulkWatch(true)}
              title="Add selected to watch list"
            >
              🔔 Watch
            </button>
            <button
              type="button"
              className="um-btn"
              onClick={() => bulkWatch(false)}
              title="Remove selected from watch list"
            >
              🔕 Unwatch
            </button>
            <button
              type="button"
              className="um-btn"
              onClick={() => setIdentityPresetModal(true)}
              title="Apply taxonomy tags"
            >
              🏷️ Set Identity
            </button>
            <button
              type="button"
              className="um-btn um-btn--danger"
              onClick={() => bulkIgnore(true)}
              title="Ignore in future scans"
            >
              🚫 Ignore
            </button>
            <button
              type="button"
              className="um-btn um-btn--ghost"
              onClick={clearSelection}
              title="Deselect all"
            >
              ✕ Clear
            </button>
          </div>
        </aside>
      )}

      {/* Identity Preset Modal */}
      {identityPresetModal && (
        <div className="um-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div className="um-modal">
            <h3 id="modal-title">Bulk Apply Taxonomy Preset</h3>
            <p className="um-modal-desc">
              Apply common classification presets to {selectedUserIds.size} selected creators simultaneously.
            </p>
            <div className="um-preset-grid">
              <button
                type="button"
                className="um-preset-btn"
                onClick={() => {
                  bulkSetIdentity({ profile_type: 0, gender: 0, sexual_content: 0 });
                  setIdentityPresetModal(false);
                }}
              >
                <strong>Solo Woman (Hetero)</strong>
                <small>Female / Solo / Heterosexual</small>
              </button>
              <button
                type="button"
                className="um-preset-btn"
                onClick={() => {
                  bulkSetIdentity({ profile_type: 1, sexual_content: 3 });
                  setIdentityPresetModal(false);
                }}
              >
                <strong>Couple (Bisexual)</strong>
                <small>Couple / Bi content</small>
              </button>
              <button
                type="button"
                className="um-preset-btn"
                onClick={() => {
                  bulkSetIdentity({ profile_type: 0, gender: 1, sexual_content: 2 });
                  setIdentityPresetModal(false);
                }}
              >
                <strong>Gay Male Solo</strong>
                <small>Male / Solo / M-M</small>
              </button>
              <button
                type="button"
                className="um-preset-btn"
                onClick={() => {
                  bulkSetIdentity({ profile_type: 0, ai_assisted: true });
                  setIdentityPresetModal(false);
                }}
              >
                <strong>AI-Assisted Synth</strong>
                <small>Flag as synthetic content</small>
              </button>
            </div>
            <div className="um-modal-footer">
              <button
                type="button"
                className="um-btn um-btn--ghost"
                onClick={() => setIdentityPresetModal(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tabular Matrix */}
      <div className="um-table-container">
        <table className="um-matrix-table" aria-label="Roster Matrix">
          <thead>
            <tr>
              <th className="um-th-select">
                <input
                  type="checkbox"
                  aria-label="Select all visible creators"
                  checked={allSelected}
                  onChange={selectAll}
                />
              </th>
              <th>Creator</th>
              <th>Platform</th>
              <th>Rate</th>
              <th>Media Breakdown</th>
              <th>Disk Size</th>
              <th>Freshness</th>
              <th>Flags</th>
              <th className="um-th-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {visibleUsers.map((user) => {
              const isSelected = selectedUserIds.has(user.id);
              const freshness = getFreshnessStatus(user);
              const isWatched = watchedKeys.has(user.id);
              const isIgnored = ignoredKeys.has(user.id);

              return (
                <tr key={user.id} className={isSelected ? 'um-row-selected' : ''}>
                  <td className="um-td-select">
                    <input
                      type="checkbox"
                      aria-label={`Select ${user.username}`}
                      checked={isSelected}
                      onChange={() => toggleSelect(user.id)}
                    />
                  </td>
                  <td>
                    <div className="um-creator-cell">
                      <img src={user.avatar_url ?? ''} alt="" className="um-avatar-sm" />
                      <div>
                        <div className="um-creator-name-row">
                          <strong>{user.name || user.username}</strong>
                          {user.verified && <span className="um-check-mini">✓</span>}
                        </div>
                        <span className="um-handle-sm">@{user.username}</span>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className={`um-site-pill um-site-pill--${user.site}`}>
                      {user.site}
                    </span>
                  </td>
                  <td className="um-mono">
                    {user.price === 0 ? <span className="um-text-accent">FREE</span> : `$${user.price.toFixed(2)}`}
                  </td>
                  <td>
                    <div className="um-media-cell">
                      <span title="Photos">📷 {user.image_count.toLocaleString()}</span>
                      <span title="Videos">🎬 {user.video_count.toLocaleString()}</span>
                      <small className="um-muted">({user.post_count} posts)</small>
                    </div>
                  </td>
                  <td className="um-mono um-muted">
                    {formatBytes(user.storage_bytes)}
                  </td>
                  <td>
                    <span className={`um-status-pill um-status-pill--${freshness}`}>
                      {freshness === 'fresh' ? '● Synced' : freshness === 'overdue' ? '▲ Overdue' : '○ Never'}
                    </span>
                  </td>
                  <td>
                    <div className="um-flags-cell">
                      <button
                        type="button"
                        className={`um-flag-icon ${user.favorite ? 'active' : ''}`}
                        onClick={() => toggleFavorite(user.id)}
                        title={user.favorite ? 'Favorited' : 'Favorite'}
                      >
                        ★
                      </button>
                      <button
                        type="button"
                        className={`um-flag-icon ${isWatched ? 'active' : ''}`}
                        onClick={() => toggleWatch(user.id)}
                        title={isWatched ? 'Watched' : 'Watch'}
                      >
                        🔔
                      </button>
                      <button
                        type="button"
                        className={`um-flag-icon ${isIgnored ? 'active' : ''}`}
                        onClick={() => toggleIgnore(user.id)}
                        title={isIgnored ? 'Ignored' : 'Ignore'}
                      >
                        🚫
                      </button>
                    </div>
                  </td>
                  <td className="um-td-actions">
                    <button
                      type="button"
                      className="um-btn um-btn--sm um-btn--primary"
                      onClick={() => dispatchScrape(user.id)}
                      title={`Scrape @${user.username}`}
                    >
                      ⚡ Scrape
                    </button>
                  </td>
                </tr>
              );
            })}
            {visibleUsers.length === 0 && (
              <tr>
                <td colSpan={9} className="um-empty-cell">
                  No creators match current search or filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
