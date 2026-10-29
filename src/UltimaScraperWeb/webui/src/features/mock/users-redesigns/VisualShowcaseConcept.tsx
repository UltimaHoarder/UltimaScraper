import { useState } from 'react';
import type { UsersMockModel } from './usersMockModel';
import { getFreshnessStatus } from './usersMockModel';
import { MediaRatioBar } from '../../../components/users/MediaRatioBar';

export function VisualShowcaseConcept({ model }: { model: UsersMockModel }) {
  const { visibleUsers, toggleFavorite, toggleWatch, dispatchScrape, watchedKeys } = model;
  const [density, setDensity] = useState<'standard' | 'compact'>('standard');

  return (
    <div className="um-showcase-layout">
      {/* Sub-toolbar with view density toggle and counts */}
      <div className="um-showcase-toolbar">
        <div className="um-showcase-meta">
          <span>Showing <strong>{visibleUsers.length}</strong> visual dossiers</span>
        </div>
        <div className="um-density-toggle">
          <span>Card Density:</span>
          <button
            type="button"
            className={density === 'standard' ? 'active' : ''}
            onClick={() => setDensity('standard')}
          >
            Standard
          </button>
          <button
            type="button"
            className={density === 'compact' ? 'active' : ''}
            onClick={() => setDensity('compact')}
          >
            Compact
          </button>
        </div>
      </div>

      {/* Grid of Visual Dossier Cards */}
      <div className={`um-card-grid um-card-grid--${density}`}>
        {visibleUsers.map((user) => {
          const freshness = getFreshnessStatus(user);
          const isWatched = watchedKeys.has(user.id);

          return (
            <article key={user.id} className="um-creator-card">
              {/* Header Banner */}
              <div
                className="um-card-header"
                style={{ backgroundImage: `url(${user.header_url})` }}
              >
                <div className="um-card-header-overlay" />
                <div className="um-card-badges">
                  <span className={`um-badge um-badge--${user.site}`}>{user.site}</span>
                  <span className="um-price-tag">
                    {user.price === 0 ? 'FREE' : `$${user.price.toFixed(2)}/mo`}
                  </span>
                </div>
              </div>

              {/* Card Body */}
              <div className="um-card-body">
                <div className="um-card-avatar-row">
                  <div className="um-card-avatar-wrap">
                    <img src={user.avatar_url ?? ''} alt="" className="um-card-avatar" />
                    {user.verified && <span className="um-check-mini">✓</span>}
                  </div>
                  <div className="um-card-quick-actions">
                    <button
                      type="button"
                      className={`um-icon-btn ${user.favorite ? 'active' : ''}`}
                      onClick={() => toggleFavorite(user.id)}
                      title={user.favorite ? 'Favorited' : 'Favorite'}
                      aria-label="Toggle favorite"
                    >
                      ★
                    </button>
                    <button
                      type="button"
                      className={`um-icon-btn ${isWatched ? 'active' : ''}`}
                      onClick={() => toggleWatch(user.id)}
                      title={isWatched ? 'Watched' : 'Watch'}
                      aria-label="Toggle watch"
                    >
                      🔔
                    </button>
                  </div>
                </div>

                <div className="um-card-identity">
                  <h4 className="um-card-name">{user.name || user.username}</h4>
                  <span className="um-card-handle">@{user.username}</span>
                </div>

                {density === 'standard' && user.description && (
                  <p className="um-card-bio">{user.description}</p>
                )}

                {/* Media Balance Bar */}
                <MediaRatioBar
                  imageCount={user.image_count}
                  videoCount={user.video_count}
                  totalMediaCount={user.media_count}
                />

                {/* Card Footer */}
                <div className="um-card-footer">
                  <div className="um-card-freshness">
                    <span className={`um-status-dot um-status-dot--${freshness}`} />
                    <small>
                      {freshness === 'fresh'
                        ? 'Archive up-to-date'
                        : freshness === 'overdue'
                          ? 'Overdue for sync'
                          : 'Not yet archived'}
                    </small>
                  </div>
                  <button
                    type="button"
                    className="um-btn um-btn--sm um-btn--primary"
                    onClick={() => dispatchScrape(user.id)}
                  >
                    ⚡ Scrape
                  </button>
                </div>
              </div>
            </article>
          );
        })}

        {visibleUsers.length === 0 && (
          <div className="um-empty-grid">
            <p>No creators match selected filters.</p>
          </div>
        )}
      </div>
    </div>
  );
}
