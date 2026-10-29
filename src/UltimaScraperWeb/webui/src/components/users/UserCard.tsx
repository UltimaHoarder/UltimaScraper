import { useEffect, useRef, useState } from 'react';

import { PluginSlot } from '../../features/plugins/components/PluginSlot';
import { userIdentityLabel } from '../../features/users/lib/usersUtils';
import { ImageHoverPreview } from '../../shared/ui/ImageHoverPreview';
import { useImageHoverPreview } from '../../shared/ui/useImageHoverPreview';
import { stripHtml } from '../../utils/sanitize';
import './UserCard.css';
import { useCachedUserCard } from '../../features/users/useCachedUserCard';
import { FavouriteButton } from '../../features/favourites/FavouriteButton';

export interface UserCardItem {
  id: number;
  user_id: number;
  username: string | null;
  name?: string | null;
  sex?: number | null;
  gender?: number | null;
  profile_type?: number | null;
  sexual_content?: number | null;
  partner_sex?: number | null;
  partner_gender?: number | null;
  description?: string | null;
  avatar_url?: string | null;
  header_url?: string | null;
  post_count: number;
  image_count: number;
  video_count: number;
  price: number;
  site: string;
  favorite?: boolean;
  is_active: boolean;
  is_subscribed?: boolean;
  is_pending_order?: boolean;
  ai_assisted?: boolean | null;
  verified?: boolean | null;
  last_checked_at?: string | null;
}

export interface UserCardExtraAction {
  key: string;
  label: string;
  title?: string;
  className?: string;
  disabled?: boolean;
  onClick: () => void;
}

interface UserCardProps<T extends UserCardItem> {
  item: T;
  profileUrl: string;
  rootClassName: string;
  inactiveLabel: string;
  isSelected: boolean;
  isCreatingJob: boolean;
  isWatched: boolean;
  isWatchPending: boolean;
  isIgnored: boolean;
  isIgnorePending: boolean;
  onSelect: (item: T) => void;
  onScrape: (item: T) => void;
  onView: (item: T) => void;
  onWatchToggle: (item: T) => void;
  onIgnoreToggle: (item: T) => void;
  formatNumber: (num: number) => string;
  formatPrice: (price: number) => string;
  extraActions?: UserCardExtraAction[];
  extraMenuActions?: UserCardExtraAction[];
  showViewButton?: boolean;
  favouriteDetails?: string;
  onOpenLightbox?: (url: string | null, alt?: string) => void;
}

const PLACEHOLDER_AVATAR = `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='48' height='48' viewBox='0 0 48 48'%3E%3Crect width='48' height='48' rx='24' fill='%23333'/%3E%3Ccircle cx='24' cy='18' r='8' fill='%23555'/%3E%3Cellipse cx='24' cy='38' rx='14' ry='9' fill='%23555'/%3E%3C/svg%3E`;
const PLACEHOLDER_HEADER = `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='400' height='80' viewBox='0 0 400 80'%3E%3Crect width='400' height='80' fill='%231a1a2e'/%3E%3C/svg%3E`;

export function UserCard<T extends UserCardItem>({
  item: cachedItem,
  profileUrl,
  rootClassName,
  inactiveLabel,
  isSelected,
  isCreatingJob,
  isWatched,
  isWatchPending,
  isIgnored,
  isIgnorePending,
  onSelect,
  onScrape,
  onView,
  onWatchToggle,
  onIgnoreToggle,
  formatNumber,
  formatPrice,
  extraActions = [],
  extraMenuActions = [],
  showViewButton = true,
  favouriteDetails,
  onOpenLightbox,
}: UserCardProps<T>) {
  const item = useCachedUserCard(cachedItem, inactiveLabel === 'Expired');
  const description = stripHtml(item.description).trim();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const {
    preview,
    startHover,
    endHover,
    enterPreview,
    leavePreview,
    closeImmediate,
  } = useImageHoverPreview(1000);

  useEffect(() => {
    if (menuOpen) {
      closeImmediate();
    }
  }, [menuOpen, closeImmediate]);

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [menuOpen]);

  const handleCardClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (target.closest('button, [role="button"]') || target.closest('a')) return;
    onSelect(item);
  };
  const identity = userIdentityLabel(item);

  return (
    <div
      className={`${rootClassName} ${item.is_active ? '' : 'inactive'} ${isSelected ? 'selected' : ''}`}
      onClick={handleCardClick}
    >
      {isSelected && (
        <div className="selection-indicator">
          <span className="checkmark">✓</span>
        </div>
      )}

      <div
        className={`card-header-image ${item.header_url && onOpenLightbox ? 'clickable' : ''} ${menuOpen ? 'menu-open' : ''}`}
        style={{ backgroundImage: `url(${item.header_url || PLACEHOLDER_HEADER})` }}
        onMouseEnter={(e) => {
          if (menuOpen) return;
          const target = e.target as HTMLElement;
          if (target.closest('.card-header-overlay, .card-dropdown, .card-menu-btn')) {
            closeImmediate();
            return;
          }
          if (item.header_url) {
            startHover(e.currentTarget, item.header_url, `${item.username || 'User'} header`, 'header');
          }
        }}
        onMouseMove={(e) => {
          if (menuOpen) {
            closeImmediate();
            return;
          }
          const target = e.target as HTMLElement;
          if (target.closest('.card-header-overlay, .card-dropdown, .card-menu-btn')) {
            closeImmediate();
            return;
          }
          if (item.header_url) {
            startHover(e.currentTarget, item.header_url, `${item.username || 'User'} header`, 'header');
          }
        }}
        onMouseLeave={endHover}
        onClick={(e) => {
          closeImmediate();
          if (item.header_url && onOpenLightbox) {
            e.stopPropagation();
            onOpenLightbox(item.header_url, `${item.username || 'User'} header`);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && item.header_url && onOpenLightbox) {
            closeImmediate();
            e.stopPropagation();
            onOpenLightbox(item.header_url, `${item.username || 'User'} header`);
          }
        }}
        role={item.header_url && onOpenLightbox ? 'button' : undefined}
        tabIndex={item.header_url && onOpenLightbox ? 0 : undefined}
        aria-label={item.header_url && onOpenLightbox ? `${item.username || 'User'} header image` : undefined}
      >
        <div
          className="card-header-overlay"
          ref={menuRef}
          onMouseEnter={(e) => {
            e.stopPropagation();
            closeImmediate();
          }}
          onMouseMove={(e) => {
            e.stopPropagation();
            closeImmediate();
          }}
          onMouseOver={(e) => {
            e.stopPropagation();
            closeImmediate();
          }}
        >
          <button
            type="button"
            className="card-menu-btn"
            title="More actions"
            onMouseEnter={(e) => {
              e.stopPropagation();
              closeImmediate();
            }}
            onClick={(e) => {
              e.stopPropagation();
              closeImmediate();
              setMenuOpen((v) => !v);
            }}
          >
            <svg viewBox="0 0 4 16" fill="currentColor" xmlns="http://www.w3.org/2000/svg" width="4" height="16">
              <circle cx="2" cy="2" r="2" />
              <circle cx="2" cy="8" r="2" />
              <circle cx="2" cy="14" r="2" />
            </svg>
          </button>

          {menuOpen && (
            <div
              className="card-dropdown"
              onClick={(e) => e.stopPropagation()}
              onMouseEnter={(e) => {
                e.stopPropagation();
                closeImmediate();
              }}
              onMouseMove={(e) => {
                e.stopPropagation();
                closeImmediate();
              }}
            >
              <button
                className="card-dropdown-item"
                onClick={() => {
                  onScrape(item);
                  setMenuOpen(false);
                }}
                disabled={isCreatingJob}
              >
                <span className="card-dropdown-icon">🚀</span> Download
              </button>
              <button
                className="card-dropdown-item"
                onClick={() => {
                  onWatchToggle(item);
                  setMenuOpen(false);
                }}
                disabled={isWatchPending}
              >
                <span className="card-dropdown-icon">{isWatched ? '🚫' : '👁'}</span>
                {isWatched ? 'Remove from Watch List' : 'Add to Watch List'}
              </button>
              <button
                className="card-dropdown-item"
                onClick={() => {
                  onIgnoreToggle(item);
                  setMenuOpen(false);
                }}
                disabled={isIgnorePending}
              >
                <span className="card-dropdown-icon">{isIgnored ? '✅' : '🚫'}</span>
                {isIgnored ? 'Unignore' : 'Ignore (skip scraping)'}
              </button>
              {extraMenuActions.map((action) => (
                <button
                  key={action.key}
                  className={`card-dropdown-item ${action.className || ''}`.trim()}
                  title={action.title || action.label}
                  onClick={() => {
                    action.onClick();
                    setMenuOpen(false);
                  }}
                  disabled={action.disabled}
                >
                  <span className="card-dropdown-icon">✏️</span> {action.label}
                </button>
              ))}
              <div className="card-dropdown-divider" />
              <button
                className="card-dropdown-item"
                onClick={() => {
                  onView(item);
                  setMenuOpen(false);
                }}
              >
                <span className="card-dropdown-icon">🖼</span> View Content
              </button>
              <button
                className="card-dropdown-item"
                onClick={() => {
                  window.open(profileUrl, '_blank');
                  setMenuOpen(false);
                }}
              >
                <span className="card-dropdown-icon">👤</span> View Profile
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="card-header">
        <div className="user-info">
          <img
            src={item.avatar_url || PLACEHOLDER_AVATAR}
            alt={item.username || 'Avatar'}
            className={`avatar ${item.avatar_url && onOpenLightbox ? 'avatar-clickable' : ''}`}
            onMouseEnter={(e) => {
              if (menuOpen) return;
              if (item.avatar_url) {
                startHover(e.currentTarget, item.avatar_url, `${item.username || 'User'} profile image`, 'avatar');
              }
            }}
            onMouseLeave={endHover}
            onClick={(e) => {
              closeImmediate();
              if (item.avatar_url && onOpenLightbox) {
                e.stopPropagation();
                onOpenLightbox(item.avatar_url, `${item.username || 'User'} profile image`);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && item.avatar_url && onOpenLightbox) {
                closeImmediate();
                e.stopPropagation();
                onOpenLightbox(item.avatar_url, `${item.username || 'User'} profile image`);
              }
            }}
            role={item.avatar_url && onOpenLightbox ? 'button' : undefined}
            tabIndex={item.avatar_url && onOpenLightbox ? 0 : undefined}
            aria-label={item.avatar_url && onOpenLightbox ? `${item.username || 'User'} profile image` : undefined}
          />
          <div className="user-details">
            <a
              href={profileUrl}
              className="username-link"
              title={`@${item.username || 'Unknown'}`}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => {
                e.preventDefault();
                window.open(profileUrl, '_blank');
              }}
            >
              @{item.username || 'Unknown'}
            </a>
            <div className="user-id-label">ID: {item.user_id}</div>
            {item.name && <div className="name">{item.name}</div>}
          </div>
        </div>
        <div className="badges">
          <span className={`badge site ${item.site}`}>{item.site}</span>
          <FavouriteButton entity={{ site: item.site, entity_type: 'user', entity_id: item.user_id }} initialFavorite={item.favorite} details={favouriteDetails} />
          <PluginSlot name="users.card.badges" context={{ item }} />
          {identity && identity !== '—' && <span className="badge sex-badge">{identity}</span>}
          {item.ai_assisted && (
            <span
              className="badge ai-assisted-badge"
              title="AI-Assisted Classification"
              style={{
                fontSize: '10px',
                padding: '1px 5px',
                borderRadius: '4px',
                background: 'rgba(139, 92, 246, 0.2)',
                color: '#c4b5fd',
                border: '1px solid rgba(139, 92, 246, 0.4)',
                fontWeight: 600,
              }}
            >
              🤖 AI
            </span>
          )}
          <span className={`badge status ${item.is_active ? 'active' : 'expired'}`}>
            {item.is_active ? 'Active' : inactiveLabel}
          </span>
          {isWatched && <span className="badge watched-badge">👁 Watching</span>}
          {isIgnored && <span className="badge ignored-badge">🚫 Ignored</span>}
          {item.is_subscribed && <span className="badge subscribed-badge">✓ Subscribed</span>}
          {item.is_pending_order && <span className="badge pending-badge">🕒 Pending Order</span>}
        </div>
      </div>

      {description && (
        <div className="description" title={description}>
          {description}
        </div>
      )}

      <div className="stats">
        <div className="stat">
          <span className="value">{formatNumber(item.post_count)}</span>
          <span className="label">Posts</span>
        </div>
        <div className="stat">
          <span className="value">{formatNumber(item.image_count)}</span>
          <span className="label">Photos</span>
        </div>
        <div className="stat">
          <span className="value">{formatNumber(item.video_count)}</span>
          <span className="label">Videos</span>
        </div>
        <div className="stat price">
          <span className="value">{formatPrice(item.price)}</span>
          <span className="label">Price</span>
        </div>
      </div>

      <div className="card-actions">
        <button
          className="btn-scrape"
          title="Scrape and download content"
          onClick={() => onScrape(item)}
          disabled={isCreatingJob}
        >
          {isCreatingJob ? 'Creating…' : 'Download'}
        </button>
        {extraActions.map((action) => (
          <button
            key={action.key}
            className={action.className || 'btn-action'}
            title={action.title || action.label}
            onClick={action.onClick}
            disabled={action.disabled}
          >
            {action.label}
          </button>
        ))}
        {showViewButton && (
          <button
            className="btn-view"
            title="View downloaded content"
            onClick={() => onView(item)}
          >
            View
          </button>
        )}
        <button
          className={`btn-watch ${isWatched ? 'watched' : ''}`}
          title={isWatched ? 'Remove from watch list' : 'Add to watch list'}
          onClick={() => onWatchToggle(item)}
          disabled={isWatchPending}
        >
          {isWatched ? '🚫 Unwatch' : '+ Watch'}
        </button>
      </div>

      <ImageHoverPreview
        preview={preview}
        onEnter={enterPreview}
        onLeave={leavePreview}
        onClick={(url, alt) => {
          closeImmediate();
          if (onOpenLightbox) {
            onOpenLightbox(url, alt);
          }
        }}
      />
    </div>
  );
}
