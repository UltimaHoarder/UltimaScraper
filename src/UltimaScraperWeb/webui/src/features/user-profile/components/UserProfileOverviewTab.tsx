import type { DetailedUserInfo } from '../../../api/types/users';
import type { UsernameDirectorySearchResponse } from '../../../api/types/users';
import {
  formatBytes,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPrice,
  formatRelativeTime,
  genderLabel,
  profileTypeLabel,
  sexLabel,
  sexualContentLabel,
  type SubscriptionCountdown,
  type UserOverviewVersion,
  type UserOverviewVersionData,
} from '../lib/userProfileUtils';

interface UserProfileOverviewTabProps {
  user: DetailedUserInfo;
  activeOverviewVersion?: UserOverviewVersion;
  activeOverviewData: UserOverviewVersionData | null;
  historySnapshotsLength: number;
  historyLoading: boolean;
  hasOlderOverviewVersion: boolean;
  hasNewerOverviewVersion: boolean;
  onSelectOlderVersion: () => void;
  onSelectNewerVersion: () => void;
  subscriptionCountdown: SubscriptionCountdown;
  onOpenSexModal: () => void;
  updateProfilePending: boolean;
  estimatedProfileSize: number;
  showEstimatedProfileSize: boolean;
  estimatedSizeMeta: string;
  directoryLookup?: UsernameDirectorySearchResponse;
  directoryLookupFetched: boolean;
  directoryLookupLoading: boolean;
  directoryLookupError: boolean;
  onFindDirectory: () => void;
  copiedDirPath: string | null;
  onCopyDir: (path: string) => void;
}

export function UserProfileOverviewTab({
  user,
  activeOverviewVersion,
  activeOverviewData,
  historySnapshotsLength,
  historyLoading,
  hasOlderOverviewVersion,
  hasNewerOverviewVersion,
  onSelectOlderVersion,
  onSelectNewerVersion,
  subscriptionCountdown,
  onOpenSexModal,
  updateProfilePending,
  estimatedProfileSize,
  showEstimatedProfileSize,
  estimatedSizeMeta,
  directoryLookup,
  directoryLookupFetched,
  directoryLookupLoading,
  directoryLookupError,
  onFindDirectory,
  copiedDirPath,
  onCopyDir,
}: UserProfileOverviewTabProps) {
  const showEstimatedContentSize =
    showEstimatedProfileSize && (!activeOverviewVersion || activeOverviewVersion.key === 'current');

  return (
    <div className="overview-tab">
      <div className="overview-version-nav">
        <div className="overview-version-meta">
          <span className="overview-version-label">{activeOverviewVersion?.label || 'Current'}</span>
          <span className="overview-version-date">
            {activeOverviewVersion?.createdAt
              ? formatDateTime(activeOverviewVersion.createdAt)
              : historyLoading
                ? 'Loading history...'
                : 'No timestamp'}
          </span>
        </div>
        <div className="overview-version-actions">
          {hasOlderOverviewVersion && (
            <button type="button" className="btn-secondary" onClick={onSelectOlderVersion}>
              ← Older
            </button>
          )}
          {hasNewerOverviewVersion && (
            <button type="button" className="btn-secondary" onClick={onSelectNewerVersion}>
              Newer →
            </button>
          )}
        </div>
      </div>

      <div className="overview-columns">
        <div className="overview-left">
          {activeOverviewData?.description && (
            <div className="overview-section">
              <h3 className="overview-section-title">Bio / Description</h3>
              <div className="overview-bio">{activeOverviewData.description}</div>
            </div>
          )}

          <div className="overview-section">
            <h3 className="overview-section-title">Financial</h3>
            <div className="overview-detail-list">
              <div className="detail-row">
                <span className="detail-label">Subscription</span>
                <span className="detail-value">
                  {formatPrice(activeOverviewData?.price ?? user.price)}/mo
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Countdown</span>
                <span className={`detail-value subscription-detail ${subscriptionCountdown.tone}`}>
                  {subscriptionCountdown.value}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Expires</span>
                <span className="detail-value">{subscriptionCountdown.detail}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Balance</span>
                <span className="detail-value">${user.balance.toFixed(2)}</span>
              </div>
              {user.promotion && (
                <div className="detail-row">
                  <span className="detail-label">Promotion</span>
                  <span className="detail-value promo">Active</span>
                </div>
              )}
            </div>
          </div>

          <div className="overview-section">
            <h3 className="overview-section-title">Content Stats</h3>
            <div className="overview-detail-list">
              <div className="detail-row">
                <span className="detail-label">Total Media</span>
                <span className="detail-value">
                  {formatNumber(activeOverviewData?.media_count ?? user.media_count)}
                </span>
              </div>
              {showEstimatedContentSize ? (
                <div className="detail-row" title={estimatedSizeMeta}>
                  <span className="detail-label">Estimated Size</span>
                  <span className="detail-value">{formatBytes(estimatedProfileSize)}</span>
                </div>
              ) : null}
              <div className="detail-row">
                <span className="detail-label">Audio</span>
                <span className="detail-value">
                  {formatNumber(activeOverviewData?.audio_count ?? user.audio_count)}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Streams</span>
                <span className="detail-value">
                  {formatNumber(activeOverviewData?.stream_count ?? user.stream_count)}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Archived Posts</span>
                <span className="detail-value">
                  {formatNumber(activeOverviewData?.archived_post_count ?? user.archived_post_count)}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Favourited</span>
                <span className="detail-value">
                  {formatNumber(activeOverviewData?.favourited_count ?? user.favourited_count)}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="overview-right">
          <div className="overview-section">
            <h3 className="overview-section-title">Quick Info</h3>
            <div className="overview-detail-list">
              <div className="detail-row">
                <span className="detail-label">Subscribers</span>
                <span className="detail-value">
                  {formatNumber(activeOverviewData?.subscribers_count ?? user.subscribers_count)}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Location</span>
                <span className="detail-value">{activeOverviewData?.location || '—'}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Website</span>
                <span className="detail-value">
                  {activeOverviewData?.website ? (
                    <a
                      href={
                        activeOverviewData.website.startsWith('http')
                          ? activeOverviewData.website
                          : `https://${activeOverviewData.website}`
                      }
                      target="_blank"
                      rel="noopener noreferrer"
                      className="link"
                    >
                      {activeOverviewData.website} 🔗
                    </a>
                  ) : (
                    '—'
                  )}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Type</span>
                <span className="detail-value">
                  {user.profile_type === null || user.profile_type === undefined ? (
                    <button
                      type="button"
                      className="overview-section-action"
                      onClick={onOpenSexModal}
                      disabled={updateProfilePending}
                    >
                      Set
                    </button>
                  ) : (
                    profileTypeLabel(user.profile_type)
                  )}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Sexual Content</span>
                <span className="detail-value">
                  {user.sexual_content === null || user.sexual_content === undefined ? (
                    <button
                      type="button"
                      className="overview-section-action"
                      onClick={onOpenSexModal}
                      disabled={updateProfilePending}
                    >
                      Set
                    </button>
                  ) : (
                    sexualContentLabel(user.sexual_content)
                  )}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">
                  {user.profile_type === 1 || user.partner_sex !== null ? 'Primary Sex' : 'Sex'}
                </span>
                <span className="detail-value">
                  {user.sex === null ? (
                    <button
                      type="button"
                      className="overview-section-action"
                      onClick={onOpenSexModal}
                      disabled={updateProfilePending}
                    >
                      Set
                    </button>
                  ) : (
                    sexLabel(activeOverviewData?.sex ?? user.sex)
                  )}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">
                  {user.profile_type === 1 || user.partner_gender !== null ? 'Primary Gender' : 'Gender'}
                </span>
                <span className="detail-value">
                  {user.gender === null ? (
                    <button
                      type="button"
                      className="overview-section-action"
                      onClick={onOpenSexModal}
                      disabled={updateProfilePending}
                    >
                      Set
                    </button>
                  ) : (
                    genderLabel(user.gender)
                  )}
                </span>
              </div>
              {(user.profile_type === 1 || user.partner_sex != null || user.partner_gender != null) && (
                <>
                  <div className="detail-row">
                    <span className="detail-label">Partner Sex</span>
                    <span className="detail-value">
                      {user.partner_sex == null ? (
                        <button
                          type="button"
                          className="overview-section-action"
                          onClick={onOpenSexModal}
                          disabled={updateProfilePending}
                        >
                          Set
                        </button>
                      ) : (
                        sexLabel(user.partner_sex)
                      )}
                    </span>
                  </div>
                  <div className="detail-row">
                    <span className="detail-label">Partner Gender</span>
                    <span className="detail-value">
                      {user.partner_gender == null ? (
                        <button
                          type="button"
                          className="overview-section-action"
                          onClick={onOpenSexModal}
                          disabled={updateProfilePending}
                        >
                          Set
                        </button>
                      ) : (
                        genderLabel(user.partner_gender)
                      )}
                    </span>
                  </div>
                </>
              )}
              <div className="detail-row">
                <span className="detail-label">Joined</span>
                <span className="detail-value">
                  {formatDate(activeOverviewData?.join_date ?? user.join_date)}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Directories</span>
                <span className="detail-value directory-lookup-value">
                  {directoryLookupLoading ? (
                    <>
                      <span className="directory-lookup-spinner" aria-hidden="true" />
                      <span>Finding...</span>
                    </>
                  ) : directoryLookupError ? (
                    <>
                      <button
                        type="button"
                        className="overview-section-action"
                        onClick={onFindDirectory}
                      >
                        Retry
                      </button>
                      <span className="directory-lookup-status error">✗ Lookup failed</span>
                    </>
                  ) : directoryLookup && directoryLookup.matches.length > 0 ? (
                    <span className="directory-lookup-list">
                      {directoryLookup.matches.map((match) => {
                        const isCopied = copiedDirPath === match.path;

                        return (
                          <span key={match.path} className="directory-lookup-entry">
                            <button
                              type="button"
                              className="directory-lookup-status success directory-copy-btn"
                              title={isCopied ? 'Copied!' : 'Click to copy'}
                              onClick={() => onCopyDir(match.path)}
                            >
                              {match.path}
                            </button>
                            {isCopied ? (
                              <span className="directory-copy-feedback">Copied</span>
                            ) : null}
                          </span>
                        );
                      })}
                    </span>
                  ) : directoryLookupFetched ? (
                    <>
                      <button
                        type="button"
                        className="overview-section-action"
                        onClick={onFindDirectory}
                      >
                        Find Again
                      </button>
                      <span className="directory-lookup-status error">✗ Not found</span>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="overview-section-action"
                      onClick={onFindDirectory}
                    >
                      Find
                    </button>
                  )}
                </span>
              </div>
            </div>
          </div>

          <div className="overview-section">
            <h3 className="overview-section-title">Activity</h3>
            <div className="overview-detail-list">
              <div className="detail-row">
                <span className="detail-label">
                  {activeOverviewVersion?.key === 'current' ? 'Last Checked' : 'Snapshot Created'}
                </span>
                <span className="detail-value">
                  {formatRelativeTime(activeOverviewData?.last_checked_at ?? user.last_checked_at)}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Downloaded At</span>
                <span className="detail-value">{formatRelativeTime(user.downloaded_at)}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">First Downloaded</span>
                <span className="detail-value">{formatDate(user.first_downloaded_at)}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">DB Record Created</span>
                <span className="detail-value">
                  {formatDate(activeOverviewData?.created_at ?? user.created_at)}
                </span>
              </div>
              {historySnapshotsLength > 0 && (
                <div className="detail-row">
                  <span className="detail-label">History Entries</span>
                  <span className="detail-value">{formatNumber(historySnapshotsLength)}</span>
                </div>
              )}
              {historySnapshotsLength === 0 && !historyLoading && (
                <div className="detail-row">
                  <span className="detail-label">History Entries</span>
                  <span className="detail-value">0</span>
                </div>
              )}
              {historyLoading && (
                <div className="detail-row">
                  <span className="detail-label">History Entries</span>
                  <span className="detail-value">Loading...</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
