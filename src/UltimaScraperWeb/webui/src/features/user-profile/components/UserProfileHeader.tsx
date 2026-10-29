import { FavouriteButton } from '../../favourites/FavouriteButton';
import type { DetailedUserInfo, UserAliasItem } from '../../../api/types/users';
import { ImageLightbox } from '../../../shared/ui/ImageLightbox';
import { ImageHoverPreview } from '../../../shared/ui/ImageHoverPreview';
import { useImageHoverPreview } from '../../../shared/ui/useImageHoverPreview';
import { ToastPortal } from '../../../shared/ui/ToastPortal';
import { ScrapeSplitButton } from './ScrapeSplitButton';
import {
  formatBytes,
  formatNumber,
  formatPrice,
  getSocialUrl,
  type SubscriptionCountdown,
} from '../lib/userProfileUtils';

interface ToastState {
  message: string;
  type: 'success' | 'error';
}

interface UserProfileHeaderProps {
  toast: ToastState | null;
  onDismissToast: () => void;
  user: DetailedUserInfo;
  onBack: () => void;
  profileUrl: string;
  profileDisplayName: string;
  profileDescription: string;
  userAliases: UserAliasItem[];
  onRemoveAlias?: (alias: UserAliasItem) => void;
  onOpenLightbox: (url: string | null) => void;
  lightboxUrl: string | null;
  onCloseLightbox: () => void;
  onScrape: () => void;
  onDelegateScrape: () => void;
  createJobPending: boolean;
  delegateJobPending: boolean;
  authPickerLoading: boolean;
  onViewMedia: () => void;
  onSubscribe: () => void;
  subscribePending: boolean;
  watched: boolean;
  onToggleWatch: () => void;
  watchPending: boolean;
  onToggleFavorite: () => void;
  favoritePending: boolean;
  onOpenEditModal: () => void;
  updateProfilePending: boolean;
  onOpenChat: () => void;
  paidPreviewLoading: boolean;
  paidPreviewTotal: number;
  paidPreviewMediaCount: number;
  onOpenPaidTab: () => void;
  subscriptionCountdown: SubscriptionCountdown;
  resolvedProfileSize: number;
  sizeLabel: string;
  sizeMeta: string;
  activeTab: 'overview' | 'content' | 'paid' | 'subscriptions';
  onTabClick: (tab: 'overview' | 'content' | 'paid' | 'subscriptions') => void;
  paidTabLabel: string;
  hasSubscriptionsTab?: boolean;
  subscriptionsTabLabel?: string;
}

export function UserProfileHeader({
  toast,
  onDismissToast,
  user,
  onBack,
  profileUrl,
  profileDisplayName,
  profileDescription,
  userAliases,
  onRemoveAlias = () => undefined,
  onOpenLightbox,
  lightboxUrl,
  onCloseLightbox,
  onScrape,
  onDelegateScrape,
  createJobPending,
  delegateJobPending,
  authPickerLoading,
  onViewMedia,
  onSubscribe,
  subscribePending,
  watched,
  onToggleWatch,
  watchPending,
  onToggleFavorite,
  favoritePending,
  onOpenEditModal,
  updateProfilePending,
  onOpenChat,
  paidPreviewLoading,
  paidPreviewTotal,
  paidPreviewMediaCount,
  onOpenPaidTab,
  subscriptionCountdown,
  resolvedProfileSize,
  sizeLabel,
  sizeMeta,
  activeTab,
  onTabClick,
  paidTabLabel,
  hasSubscriptionsTab = false,
  subscriptionsTabLabel = 'Subscriptions',
}: UserProfileHeaderProps) {
  const {
    preview,
    startHover,
    endHover,
    enterPreview,
    leavePreview,
    closeImmediate,
  } = useImageHoverPreview(1000);

  const paidPreviewMeta = paidPreviewLoading
    ? 'Loading purchases'
    : paidPreviewTotal === 0
      ? ''
      : `${formatNumber(paidPreviewMediaCount)} media in latest items`;
  const paidPreviewTooltip = paidPreviewLoading
    ? 'Loading purchases'
    : paidPreviewTotal === 0
      ? 'No purchases saved'
      : `${formatNumber(paidPreviewMediaCount)} media in latest items`;

  return (
    <>
      <ToastPortal toast={toast} onDismiss={onDismissToast} />

      <div className="user-profile-header-bar">
        <button className="back-btn" onClick={onBack}>
          ← Back
        </button>
        <a className="external-link" href={profileUrl} target="_blank" rel="noopener noreferrer">
          View on {user.site === 'onlyfans' ? 'OnlyFans' : 'Fansly'} ↗
        </a>
      </div>

      <div className="profile-card">
        {user.header_url ? (
          <div
            className="profile-card-banner"
            style={{ backgroundImage: `url(${user.header_url})` }}
            onMouseEnter={(e) => {
              if (user.header_url) {
                startHover(e.currentTarget, user.header_url, `${user.username} header`, 'header');
              }
            }}
            onMouseLeave={endHover}
            onClick={() => {
              closeImmediate();
              onOpenLightbox(user.header_url);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                closeImmediate();
                onOpenLightbox(user.header_url);
              }
            }}
            role="button"
            tabIndex={0}
          />
        ) : (
          <div className="profile-card-banner profile-card-banner-empty" />
        )}
        <div className="profile-card-body">
          <div className="profile-card-avatar-area">
            {user.avatar_url ? (
              <img
                src={user.avatar_url}
                alt={user.username}
                className="profile-card-avatar"
                onMouseEnter={(e) => {
                  if (user.avatar_url) {
                    startHover(e.currentTarget, user.avatar_url, `${user.username} profile image`, 'avatar');
                  }
                }}
                onMouseLeave={endHover}
                onClick={() => {
                  closeImmediate();
                  onOpenLightbox(user.avatar_url);
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    closeImmediate();
                    onOpenLightbox(user.avatar_url);
                  }
                }}
                role="button"
                tabIndex={0}
              />
            ) : (
              <div className="profile-card-avatar profile-card-avatar-placeholder">
                {user.username.charAt(0).toUpperCase()}
              </div>
            )}
          </div>
          <div className="profile-card-info">
            <div className="profile-card-identity">
              <h1 className="profile-card-name">{profileDisplayName}</h1>
              <span className="profile-card-username">@{user.username}</span>
              <span className="profile-card-user-id">ID: {user.user_id}</span>
            </div>
            {user.socials.length > 0 && (
              <div className="profile-card-socials">
                {user.socials.map((social, index) => {
                  const socialUrl = getSocialUrl(social.site, social.identifier);
                  return (
                    <div key={index} className="social-pill">
                      {socialUrl ? (
                        <a
                          href={socialUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="social-site social-site-link"
                        >
                          {social.site}
                        </a>
                      ) : (
                        <span className="social-site">{social.site}</span>
                      )}
                      <span className="social-id">{social.identifier}</span>
                    </div>
                  );
                })}
              </div>
            )}
            {userAliases.length > 0 && (
              <div className="profile-card-aliases">
                <span className="profile-card-aliases-label">Aliases</span>
                    <div className="profile-card-alias-pills">
                      {userAliases.map((alias) => (
                        <span key={alias.id} className="alias-pill">
                          @{alias.username}
                          <button
                            type="button"
                            className="alias-pill-remove"
                            onClick={() => onRemoveAlias(alias)}
                            aria-label={`Remove alias ${alias.username}`}
                            title="Remove alias"
                          >
                            ×
                          </button>
                        </span>
                  ))}
                </div>
              </div>
            )}
            <div className="profile-card-badges">
              <span className={`badge-status ${user.is_active ? 'active' : 'inactive'}`}>
                {user.is_active ? '● Active' : '● Inactive'}
              </span>
              <span className={`badge-site ${user.site}`}>
                {user.site === 'onlyfans' ? 'OnlyFans' : 'Fansly'}
              </span>
              {user.performer && <span className="badge-performer">Performer</span>}
              {user.favorite && (
                <span className="badge-favorite" title="Favourite" aria-label="Favourite">
                  ★
                </span>
              )}
            </div>
          </div>
          {profileDescription && <p className="profile-card-bio">{profileDescription}</p>}
          <div className="profile-card-actions">
            <ScrapeSplitButton
              primaryLabel={
                authPickerLoading
                  ? 'Checking auths...'
                  : createJobPending
                    ? 'Creating...'
                    : 'Download'
              }
              onPrimaryClick={onScrape}
              onDelegateClick={onDelegateScrape}
              disabled={createJobPending || authPickerLoading || delegateJobPending}
              delegatePending={delegateJobPending}
            />
            <button className="btn-secondary" onClick={onViewMedia}>
              Browse Files
            </button>
            <button className="btn-secondary" onClick={onSubscribe} disabled={subscribePending}>
              {subscribePending ? 'Subscribing...' : 'Subscribe'}
            </button>
            <button
              className={watched ? 'btn-primary btn-watch-toggle' : 'btn-secondary btn-watch-toggle'}
              onClick={onToggleWatch}
              disabled={watchPending}
            >
              {watchPending ? 'Saving...' : watched ? 'Unwatch' : 'Watch'}
            </button>
<FavouriteButton entity={{ site: user.site, entity_type: 'user', entity_id: user.user_id }} initialFavorite={user.favorite} displayLabel="Favourite" className="btn-secondary btn-favorite-toggle" fallback={            <button
              className={
                user.favorite ? 'btn-primary btn-favorite-toggle' : 'btn-secondary btn-favorite-toggle'
              }
              title={user.favorite ? 'Remove favorite' : 'Add favorite'}
              aria-label={user.favorite ? 'Remove favorite' : 'Add favorite'}
              onClick={onToggleFavorite}
              disabled={favoritePending}
            >
              {favoritePending ? '...' : user.favorite ? '★' : '☆'}
            </button>} />
            <button className="btn-secondary" onClick={onOpenEditModal} disabled={updateProfilePending}>
              Edit User
            </button>
            <button className="btn-secondary" onClick={onOpenChat} disabled={!user}>
              Message
            </button>
          </div>
        </div>
      </div>

      <ImageLightbox
        imageUrl={lightboxUrl}
        alt={`${user.username} profile media`}
        onClose={onCloseLightbox}
      />

      <ImageHoverPreview
        preview={preview}
        onEnter={enterPreview}
        onLeave={leavePreview}
        onClick={(url) => {
          closeImmediate();
          onOpenLightbox(url);
        }}
      />

      <div className="stat-pills">
        <div className="stat-pill">
          <span className="stat-pill-icon">📝</span>
          <span className="stat-pill-value">{formatNumber(user.post_count)}</span>
          <span className="stat-pill-label">Posts</span>
        </div>
        <div className="stat-pill">
          <span className="stat-pill-icon">📷</span>
          <span className="stat-pill-value">{formatNumber(user.image_count)}</span>
          <span className="stat-pill-label">Photos</span>
        </div>
        <div className="stat-pill">
          <span className="stat-pill-icon">🎬</span>
          <span className="stat-pill-value">{formatNumber(user.video_count)}</span>
          <span className="stat-pill-label">Videos</span>
        </div>
        <div className="stat-pill">
          <span className="stat-pill-icon">💰</span>
          <span className="stat-pill-value">{formatPrice(user.price)}</span>
          <span className="stat-pill-label">Price</span>
        </div>
        <button
          type="button"
          className="stat-pill stat-pill-button stat-pill-paid"
          onClick={onOpenPaidTab}
          title={paidPreviewTooltip}
        >
          <span className="stat-pill-icon">💎</span>
          <span className="stat-pill-value">
            {paidPreviewLoading ? '…' : formatNumber(paidPreviewTotal)}
          </span>
          <span className="stat-pill-label">Paid Content</span>
          {paidPreviewMeta && <span className="stat-pill-meta">{paidPreviewMeta}</span>}
        </button>
        <div
          className={`stat-pill stat-pill-subscription ${subscriptionCountdown.tone}`}
          title={subscriptionCountdown.detail}
        >
          <span className="stat-pill-icon">⏳</span>
          <span className="stat-pill-value">{subscriptionCountdown.value}</span>
          <span className="stat-pill-label">Subscription</span>
        </div>
        <div className="stat-pill" title={sizeMeta}>
          <span className="stat-pill-icon">📦</span>
          <span className="stat-pill-value">{formatBytes(resolvedProfileSize)}</span>
          <span className="stat-pill-label">{sizeLabel}</span>
        </div>
      </div>

      <div className="profile-tabs">
        <button
          className={`profile-tab ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => onTabClick('overview')}
        >
          Overview
        </button>
        <button
          className={`profile-tab ${activeTab === 'content' ? 'active' : ''}`}
          onClick={() => onTabClick('content')}
        >
          Content
        </button>
        <button
          className={`profile-tab ${activeTab === 'paid' ? 'active' : ''}`}
          onClick={() => onTabClick('paid')}
        >
          {paidTabLabel}
        </button>
        {hasSubscriptionsTab && (
          <button
            className={`profile-tab ${activeTab === 'subscriptions' ? 'active' : ''}`}
            onClick={() => onTabClick('subscriptions')}
          >
            {subscriptionsTabLabel}
          </button>
        )}
      </div>
    </>
  );
}
