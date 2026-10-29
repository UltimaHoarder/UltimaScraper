import { useLocation, type NavigateFunction } from 'react-router-dom';

import { UsersRosterCard } from './UsersRosterCard';
import { OperationsState } from '../../../shared/ui/operations/OperationsChrome';
import { PluginSlot } from '../../plugins/components/PluginSlot';
import type { UserInfo } from '../lib/usersUtils';
import { stripHtml } from '../../../utils/sanitize';
import {
  formatUserNumber,
  formatUserPrice,
  getUserDescription,
  userIdentityLabel,
} from '../lib/usersUtils';
import { appUrl } from '../../../api/http';

interface UsersResultsProps {
  favoriteOnly: boolean;
  error: Error | null;
  allUsers: UserInfo[];
  loadedCount: number;
  totalCount: number | null;
  searchQuery: string;
  viewMode: 'table' | 'grid';
  selectedUsers: Set<string>;
  watchedKeys: Set<string>;
  ignoredKeys: Set<string>;
  isCreatingJob: boolean;
  isAuthPickerLoading: boolean;
  isSubscribePending: boolean;
  isWatchPending: boolean;
  isIgnorePending: boolean;
  isUpdatePending: boolean;
  isLoadingInitialPage: boolean;
  isLoadingNextPage: boolean;
  hasMore: boolean;
  pageSize: number;
  loadMoreSentinelRef: React.RefObject<HTMLDivElement | null>;
  navigate: NavigateFunction;
  onLoadMore: () => void;
  onSelectUser: (user: UserInfo) => void;
  onScrapeUser: (user: UserInfo) => void;
  onSubscribeUser: (user: UserInfo) => void;
  onWatchToggle: (user: UserInfo) => void;
  onIgnoreToggle: (user: UserInfo) => void;
  onEditUser: (user: UserInfo) => void;
  onOpenLightbox?: (url: string | null, alt?: string) => void;
}

export function UsersResults({
  favoriteOnly,
  error,
  allUsers,
  loadedCount,
  totalCount,
  searchQuery,
  viewMode,
  selectedUsers,
  watchedKeys,
  ignoredKeys,
  isCreatingJob,
  isAuthPickerLoading,
  isSubscribePending,
  isWatchPending,
  isIgnorePending,
  isUpdatePending,
  isLoadingInitialPage,
  isLoadingNextPage,
  hasMore,
  pageSize,
  loadMoreSentinelRef,
  navigate,
  onLoadMore,
  onSelectUser,
  onScrapeUser,
  onSubscribeUser,
  onWatchToggle,
  onIgnoreToggle,
  onEditUser,
  onOpenLightbox,
}: UsersResultsProps) {
  const location = useLocation();
  const returnTo = `${location.pathname}${location.search}`;

  return (
    <div className="users-content">
      {isLoadingInitialPage ? (
        <OperationsState
          compact
          variant="loading"
          title="Loading people"
          description="Searching the user index and applying filters."
        />
      ) : error ? (
        <OperationsState
          compact
          variant="error"
          title="Failed to load people"
          description={error.message}
        />
      ) : allUsers.length === 0 ? (
        <OperationsState
          compact
          title={`No ${favoriteOnly ? 'favourites' : 'people'} found`}
          description={
            favoriteOnly
              ? 'Favourite users from the database will appear here.'
              : 'Try adjusting your search terms or filter set.'
          }
        />
      ) : (
        <>
          <div className="users-results-info">
            <span className="users-count">
              Showing {loadedCount.toLocaleString()}{totalCount != null && ` of ${totalCount.toLocaleString()}`}{' '}
              {favoriteOnly ? 'favourite' : 'user'}
              {totalCount !== 1 ? 's' : ''}
            </span>
            {searchQuery && <span className="search-term">matching "{searchQuery}"</span>}
          </div>

          {viewMode === 'table' ? (
            <div className="users-table-container">
              <table className="users-table">
                <thead>
                  <tr>
                    <th className="col-user">User</th>
                    <th className="col-status">Identity</th>
                    <th className="col-bio">Bio</th>
                    <th className="col-stats">Posts</th>
                    <th className="col-stats">Photos</th>
                    <th className="col-stats">Videos</th>
                    <th className="col-price">Price</th>
                    <th className="col-status">Status</th>
                    <th className="col-actions">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {allUsers.map((user) => (
                    <tr key={`${user.site}-${user.id}`} className={user.is_active ? '' : 'inactive'}>
                      <td className="col-user">
                        <div className="user-cell">
                          <a
                            href={appUrl(`/users/${user.id}?site=${encodeURIComponent(user.site)}&return_to=${encodeURIComponent(returnTo)}`)}
                            className="username-link"
                            onClick={(event) => {
                              event.preventDefault();
                              navigate(
                                `/users/${user.id}?site=${encodeURIComponent(user.site)}&return_to=${encodeURIComponent(returnTo)}`
                              );
                            }}
                          >
                            @{user.username}
                          </a>
                          <span className="user-id-label">ID: {user.user_id}</span>
                          {user.name && <span className="display-name">{user.name}</span>}
                          <span className={`site-badge ${user.site}`}>{user.site}</span>
                        </div>
                      </td>
                      <td className="col-status">
                        {(() => {
                          const identityText = userIdentityLabel(user);

                          return (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap' }}>
                              {identityText !== '—' ? <span>{identityText}</span> : null}
                              <PluginSlot
                                name="users.table.identity_extra"
                                context={{ user, onEditUser }}
                                fallback={identityText === '—' ? <span>—</span> : null}
                              />
                              {user.ai_assisted && (
                                <span
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
                              {user.verified && (
                                <span
                                  title="Human Verified"
                                  style={{
                                    fontSize: '10px',
                                    padding: '1px 5px',
                                    borderRadius: '4px',
                                    background: 'rgba(16, 185, 129, 0.2)',
                                    color: '#6ee7b7',
                                    border: '1px solid rgba(16, 185, 129, 0.4)',
                                    fontWeight: 600,
                                  }}
                                >
                                  ✓
                                </span>
                              )}
                            </div>
                          );
                        })()}
                      </td>
                      <td className="col-bio">
                        <span
                          className="bio-text"
                          title={user.description ? stripHtml(user.description) : ''}
                        >
                          {getUserDescription(user) || <span className="no-bio">—</span>}
                        </span>
                      </td>
                      <td className="col-stats">{formatUserNumber(user.post_count)}</td>
                      <td className="col-stats">{formatUserNumber(user.image_count)}</td>
                      <td className="col-stats">{formatUserNumber(user.video_count)}</td>
                      <td className="col-price">
                        <span className={`price ${user.price === 0 ? 'free' : ''}`}>
                          {formatUserPrice(user.price)}
                        </span>
                      </td>
                      <td className="col-status">
                        <span
                          className={`status-badge ${user.is_active ? 'active' : 'inactive'}`}
                        >
                          {user.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="col-actions">
                        <div className="action-buttons">
                          <button
                            className="btn-action btn-scrape"
                            onClick={() => onScrapeUser(user)}
                            disabled={isCreatingJob || isAuthPickerLoading}
                            title="Create job to scrape and download this user"
                          >
                            Scrape + Download
                          </button>
                          <button
                            className="btn-action btn-subscribe"
                            onClick={() => onSubscribeUser(user)}
                            disabled={isSubscribePending}
                            title="Buy subscription using best spender"
                          >
                            Subscribe
                          </button>
                          <button
                            className="btn-action"
                            onClick={() => onEditUser(user)}
                            title="Edit user profile fields"
                          >
                            ✏️ Edit
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="user-card-grid-container">
              <div className="users-grid user-card-grid">
                {allUsers.map((user) => {
                  const userKey = `${user.site}-${user.id}`;

                  return (
                    <UsersRosterCard
                      key={userKey}
                      item={user}
                      profileUrl={`/users/${user.id}?site=${encodeURIComponent(user.site)}&return_to=${encodeURIComponent(returnTo)}`}
                      isSelected={selectedUsers.has(userKey)}
                      isWatched={watchedKeys.has(`${user.site}-${user.user_id}`)}
                      isWatchPending={isWatchPending}
                      isIgnored={ignoredKeys.has(`${user.site}-${user.user_id}`)}
                      isIgnorePending={isIgnorePending}
                      isCreatingJob={isCreatingJob || isAuthPickerLoading}
                      onSelect={onSelectUser}
                      onScrape={onScrapeUser}
                      onView={() => {}}
                      onWatchToggle={onWatchToggle}
                      onIgnoreToggle={onIgnoreToggle}
                      onOpenLightbox={onOpenLightbox}
                      isSubscribePending={isSubscribePending}
                      isUpdatePending={isUpdatePending}
                      onSubscribeUser={onSubscribeUser}
                      onEditUser={onEditUser}
                    />
                  );
                })}
              </div>
            </div>
          )}

          <div ref={loadMoreSentinelRef} className="users-scroll-sentinel" />

          {hasMore && (
            <div className="load-more-container">
              <button
                className="load-more-btn"
                onClick={onLoadMore}
                disabled={isLoadingNextPage}
              >
                {isLoadingNextPage ? 'Loading...' : `Load More (${pageSize})`}
              </button>
            </div>
          )}

          {!hasMore && loadedCount > 0 && (
            <div className="users-end">All users loaded</div>
          )}
        </>
      )}
    </div>
  );
}
